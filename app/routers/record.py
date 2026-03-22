"""工作记录路由"""

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import col, select

from app.models import (
    Department,
    Project,
    SettlementClaim,
    SettlementPeriod,
    UserDeptLink,
    WorkRecord,
)
from app.routers.deps import PeriodUserSession, UseridSession, UserSession, templates

router = APIRouter(tags=["工作记录"])


class RecordItem(BaseModel):
    """单条记录"""

    dept_id: UUID
    project_name: str
    description: str
    hours: int = 0
    minutes: int = 0
    related_content: str | None = None


class BatchRecordRequest(BaseModel):
    """批量记录请求"""

    records: list[RecordItem]


def _load_unclaimed_period_records(s: PeriodUserSession) -> list[WorkRecord]:
    """加载当前用户在结算周期内尚未申报的记录"""
    return list(s.db.exec(
        select(WorkRecord)
        .join(Project, col(WorkRecord.project_id) == Project.id)
        .where(WorkRecord.user_id == s.user.id)
        .where(WorkRecord.dept_id == s.period.dept_id)
        # .where(WorkRecord.created_at >= s.period.start_date)
        # .where(WorkRecord.created_at <= s.period.end_date)
        .where(col(WorkRecord.claimed).is_(False))
        .order_by(col(Project.name), col(WorkRecord.created_at).desc())
    ).all())


def _group_records_by_project(records: list[WorkRecord]) -> list[dict]:
    """按项目分组记录，便于模板展示"""
    groups: dict[str, dict] = {}
    for record in records:
        project_name = record.project.name
        if project_name not in groups:
            groups[project_name] = {
                "project_name": project_name,
                "total_minutes": 0,
                "records": [],
            }
        groups[project_name]["records"].append(record)
        groups[project_name]["total_minutes"] += record.duration_minutes
    return list(groups.values())


def _render_claim_form(
    s: PeriodUserSession,
    *,
    existing_claim: SettlementClaim | None,
    form_paid_hours: int | None = None,
    form_paid_minutes: int | None = None,
    form_volunteer_hours: int | None = None,
    error_message: str | None = None,
    selected_record_ids: set[UUID] | None = None,
    status_code: int = 200,
):
    """统一构建申报页面上下文"""
    unclaimed_records = _load_unclaimed_period_records(s)
    project_groups = _group_records_by_project(unclaimed_records)

    if selected_record_ids is None:
        selected_record_ids = {record.id for record in unclaimed_records}

    selected_total_minutes = sum(
        record.duration_minutes
        for record in unclaimed_records
        if record.id in selected_record_ids
    )

    return templates.TemplateResponse(
        "admin/claim_form.html",
        {
            "request": s.request,
            "period": s.period,
            "system_minutes": selected_total_minutes,
            "system_hours": selected_total_minutes / 60,
            "existing_claim": existing_claim,
            "form_paid_hours": form_paid_hours,
            "form_paid_minutes": form_paid_minutes,
            "form_volunteer_hours": form_volunteer_hours,
            "error_message": error_message,
            "project_groups": project_groups,
            "selected_record_ids": selected_record_ids,
        },
        status_code=status_code,
    )


@router.get("/record", response_class=HTMLResponse)
async def record_page(s: UserSession):
    """填报主页面"""
    dept_id = None
    claim_entries = []
    if dept_id := s.request.session.get("current_dept_id"):
        dept_id = UUID(dept_id)
        open_periods = s.db.exec(
            select(SettlementPeriod)
            .where(SettlementPeriod.is_open)
            .where(SettlementPeriod.dept_id == dept_id)
            .order_by(col(SettlementPeriod.id).desc())
        ).all()
        period_ids = [period.id for period in open_periods]
        claimed_period_ids = set()
        if period_ids:
            claimed_period_ids = set(
                s.db.exec(
                    select(SettlementClaim.period_id)
                    .where(SettlementClaim.user_id == s.user.id)
                    .where(col(SettlementClaim.period_id).in_(period_ids))
                ).all()
            )
        for period in open_periods:
            claim_entries.append(
                {
                    "period": period,
                    "claimed": period.id in claimed_period_ids,
                }
            )
    # 获取最近记录
    recent_start = datetime.now()-timedelta(days=1)
    recent_records = s.db.exec(
        select(WorkRecord)
        .where(WorkRecord.user_id == s.user.id)
        .where(WorkRecord.created_at >= recent_start)
        .order_by(col(WorkRecord.created_at).desc())
    ).all()
    # 计算最近总时长
    recent_minutes = sum(r.duration_minutes for r in recent_records)
    recent_hours = recent_minutes // 60
    recent_mins = recent_minutes % 60

    return templates.TemplateResponse(
        "record.html",
        {
            "request": s.request,
            "user": s.user,
            "current_dept_id": dept_id,
            "recent_records": recent_records,
            "recent_hours": recent_hours,
            "recent_mins": recent_mins,
            "claim_entries": claim_entries,
        },
    )


@router.get("/claim/{period_id}", response_class=HTMLResponse)
async def claim_page(s: PeriodUserSession):
    """用户申报页面"""
    if not s.period.is_open:
        raise HTTPException(400, "该结算周期已关闭")
    # 查找已有申报
    existing_claim = s.db.exec(
        select(SettlementClaim)
        .where(SettlementClaim.period_id == s.period.id)
        .where(SettlementClaim.user_id == s.user.id)
    ).first()
    return _render_claim_form(s, existing_claim=existing_claim)


@router.post("/claim/{period_id}")
async def submit_claim(
    s: PeriodUserSession,
    paid_hours: int = Form(...),
    paid_minutes: int = Form(...),
    volunteer_hours: int = Form(...),
    selected_record_ids: list[str] = Form(default=[]),
):
    """提交申报"""
    if not s.period.is_open:
        raise HTTPException(400, "该结算周期已关闭")

    if paid_hours < 0 or paid_minutes < 0 or volunteer_hours < 0:
        raise HTTPException(400, "申报时长不能为负数")
    if paid_minutes >= 60:
        raise HTTPException(400, "工资时长分钟必须在0到59之间")

    parsed_record_ids: set[UUID] = set()
    for record_id in selected_record_ids:
        try:
            parsed_record_ids.add(UUID(record_id))
        except ValueError:
            raise HTTPException(400, "存在无效的记录ID")

    if not parsed_record_ids:
        claim = s.db.exec(
            select(SettlementClaim)
            .where(SettlementClaim.period_id == s.period.id)
            .where(SettlementClaim.user_id == s.user.id)
        ).first()
        return _render_claim_form(
            s,
            existing_claim=claim,
            form_paid_hours=paid_hours,
            form_paid_minutes=paid_minutes,
            form_volunteer_hours=volunteer_hours,
            error_message="请至少选择一条工作记录进行申报",
            selected_record_ids=parsed_record_ids,
            status_code=400,
        )

    selected_records = s.db.exec(
        select(WorkRecord)
        .where(col(WorkRecord.id).in_(parsed_record_ids))
        .where(WorkRecord.user_id == s.user.id)
        .where(WorkRecord.dept_id == s.period.dept_id)
        # .where(WorkRecord.created_at >= s.period.start_date)
        # .where(WorkRecord.created_at <= s.period.end_date)
        .where(col(WorkRecord.claimed).is_(False))
    ).all()

    if len(selected_records) != len(parsed_record_ids):
        claim = s.db.exec(
            select(SettlementClaim)
            .where(SettlementClaim.period_id == s.period.id)
            .where(SettlementClaim.user_id == s.user.id)
        ).first()
        return _render_claim_form(
            s,
            existing_claim=claim,
            form_paid_hours=paid_hours,
            form_paid_minutes=paid_minutes,
            form_volunteer_hours=volunteer_hours,
            error_message="所选记录中包含不可申报项，请刷新后重试",
            selected_record_ids=parsed_record_ids,
            status_code=400,
        )

    system_minutes = sum(record.duration_minutes for record in selected_records)

    # 查找或更新申报
    claim = s.db.exec(
        select(SettlementClaim)
        .where(SettlementClaim.period_id == s.period.id)
        .where(SettlementClaim.user_id == s.user.id)
    ).first()

    paid_total_minutes = paid_hours * 60 + paid_minutes
    volunteer_total_minutes = volunteer_hours * 60
    total_minutes = paid_total_minutes + volunteer_total_minutes

    total_hours = round(total_minutes / 60, 2)
    expected_hours = round(system_minutes / 60, 2)
    # 业务规则：工资时长 + 志愿时长 必须等于该周期系统总工时
    if total_minutes != system_minutes:
        return _render_claim_form(
            s,
            existing_claim=claim,
            form_paid_hours=paid_hours,
            form_paid_minutes=paid_minutes,
            form_volunteer_hours=volunteer_hours,
            error_message=f"工资时长 + 志愿时长 必须等于已选工时 {expected_hours:.2f} 小时",
            selected_record_ids=parsed_record_ids,
            status_code=400,
        )

    if claim:
        claim.paid_minutes = paid_total_minutes
        claim.volunteer_minutes = volunteer_total_minutes
        claim.total_minutes = total_minutes
        claim.submitted_at = datetime.now()
    else:
        claim = SettlementClaim(
            period_id=s.period.id,
            user_id=s.user.id,
            paid_minutes=paid_total_minutes,
            volunteer_minutes=volunteer_total_minutes,
            total_minutes=total_minutes,
        )
        s.db.add(claim)

    for record in selected_records:
        record.claimed = True
        s.db.add(record)

    s.db.commit()
    return RedirectResponse(url="/timeline", status_code=302)


@router.get("/projects/dropdown", response_class=HTMLResponse)
async def get_project_dropdown(s: UseridSession, dept_id: UUID = Query(...)):
    """获取部门项目下拉选项（HTMX端点）"""
    # 验证部门
    dept = s.db.get(Department, dept_id)
    if not dept:
        return HTMLResponse('<option value="">请选择项目</option>')
    # 查询管理员设为可见的项目
    projects = s.db.exec(
        select(Project)
        .where(Project.dept_id == dept_id)
        .where(Project.is_visible)
        .order_by(col(Project.last_active_at).desc())
    ).all()
    # 生成HTML选项
    options = ['<option value="">选择或输入新项目</option>']
    for p in projects:
        options.append(f'<option value="{p.name}">{p.name}</option>')

    return HTMLResponse("\n".join(options))


@router.post("/record")
async def create_record(
    s: UserSession,
    dept_id: UUID = Form(...),
    project_name: str = Form(...),
    description: str = Form(...),
    hours: int = Form(0),
    minutes: int = Form(0),
    related_content: str | None = Form(None),
):
    """创建单条记录"""
    # 验证部门
    dept = s.db.get(Department, dept_id)
    if not dept:
        raise HTTPException(400, "部门不存在")
    if hours < 0 or minutes < 0:
        raise HTTPException(400, "时长不能为负数")
    # 计算总分钟数
    duration_minutes = hours * 60 + minutes
    if duration_minutes <= 0:
        raise HTTPException(400, "时长必须大于0")
    # 查找或创建项目
    project = s.db.exec(
        select(Project)
        .where(Project.dept_id == dept_id)
        .where(Project.name == project_name)
    ).first()
    if not project:
        project = Project(dept_id=dept_id, name=project_name)
        s.db.add(project)
        s.db.commit()
        s.db.refresh(project)
    else:
        # 更新活跃时间
        project.last_active_at = datetime.now()
        s.db.add(project)
    # 创建记录
    record = WorkRecord(
        user_id=s.user.id,
        dept_id=dept_id,
        project_id=project.id,
        description=description,
        duration_minutes=duration_minutes,
        related_content=related_content if related_content else None,
    )
    s.db.add(record)
    # 确保用户与部门关联
    link = s.db.exec(
        select(UserDeptLink)
        .where(UserDeptLink.user_id == s.user.id)
        .where(UserDeptLink.dept_id == dept_id)
    ).first()
    if not link:
        link = UserDeptLink(user_id=s.user.id, dept_id=dept_id, is_admin=False)
        s.db.add(link)
    s.db.commit()
    # 返回重定向
    return RedirectResponse(url="/record", status_code=302)


@router.post("/record/batch")
async def create_batch_records(s: UserSession, data: BatchRecordRequest):
    """批量创建记录"""
    if not data.records:
        raise HTTPException(400, "至少需要一条记录")
    created_count = 0
    for item in data.records:
        # 验证部门
        dept = s.db.get(Department, item.dept_id)
        if not dept:
            continue
        if item.hours < 0 or item.minutes < 0:
            continue
        # 计算总分钟数
        duration_minutes = item.hours * 60 + item.minutes
        if duration_minutes <= 0:
            continue
        # 查找或创建项目
        project = s.db.exec(
            select(Project)
            .where(Project.dept_id == item.dept_id)
            .where(Project.name == item.project_name)
        ).first()
        if not project:
            project = Project(dept_id=item.dept_id, name=item.project_name)
            s.db.add(project)
            s.db.commit()
            s.db.refresh(project)
        else:
            project.last_active_at = datetime.now()
            s.db.add(project)
        # 创建记录
        record = WorkRecord(
            user_id=s.user.id,
            dept_id=item.dept_id,
            project_id=project.id,
            description=item.description,
            duration_minutes=duration_minutes,
            related_content=item.related_content,
        )
        s.db.add(record)
        # 确保用户与部门关联
        link = s.db.exec(
            select(UserDeptLink)
            .where(UserDeptLink.user_id == s.user.id)
            .where(UserDeptLink.dept_id == item.dept_id)
        ).first()
        if not link:
            link = UserDeptLink(user_id=s.user.id, dept_id=item.dept_id, is_admin=False)
            s.db.add(link)
        created_count += 1
    s.db.commit()
    return {"message": f"成功创建 {created_count} 条记录", "count": created_count}


@router.delete("/record/{record_id}")
async def delete_record(s: UserSession, record_id: UUID):
    """删除记录"""
    record = s.db.get(WorkRecord, record_id)
    if not record:
        raise HTTPException(404, "记录不存在")
    if record.user_id != s.user.id:
        raise HTTPException(403, "无权删除他人记录")
    s.db.delete(record)
    s.db.commit()
    return {"message": "删除成功"}
