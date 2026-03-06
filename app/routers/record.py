"""工作记录路由"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import col, func, select

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
    # 获取今日记录
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_records = s.db.exec(
        select(WorkRecord)
        .where(WorkRecord.user_id == s.user.id)
        .where(WorkRecord.created_at >= today_start)
        .order_by(col(WorkRecord.created_at).desc())
    ).all()
    # 计算今日总时长
    today_minutes = sum(r.duration_minutes for r in today_records)
    today_hours = today_minutes // 60
    today_mins = today_minutes % 60

    return templates.TemplateResponse(
        "record.html",
        {
            "request": s.request,
            "user": s.user,
            "current_dept_id": dept_id,
            "today_records": today_records,
            "today_hours": today_hours,
            "today_mins": today_mins,
            "claim_entries": claim_entries,
        },
    )


@router.get("/claim/{period_id}", response_class=HTMLResponse)
async def claim_page(s: PeriodUserSession):
    """用户申报页面"""
    if not s.period.is_open:
        raise HTTPException(400, "该结算周期已关闭")
    # 计算系统工时
    system_minutes = (
        s.db.exec(
            select(func.sum(WorkRecord.duration_minutes))
            .where(WorkRecord.user_id == s.user.id)
            .where(WorkRecord.dept_id == s.period.dept_id)
            .where(WorkRecord.created_at >= s.period.start_date)
            .where(WorkRecord.created_at <= s.period.end_date)
        ).first()
        or 0
    )
    # 查找已有申报
    existing_claim = s.db.exec(
        select(SettlementClaim)
        .where(SettlementClaim.period_id == s.period.id)
        .where(SettlementClaim.user_id == s.user.id)
    ).first()

    return templates.TemplateResponse(
        "admin/claim_form.html",
        {
            "request": s.request,
            "period": s.period,
            "system_hours": system_minutes / 60,
            "existing_claim": existing_claim,
        },
    )


@router.post("/claim/{period_id}")
async def submit_claim(
    s: PeriodUserSession,
    paid_hours: float = Form(...),
    volunteer_hours: float = Form(...),
):
    """提交申报"""
    if not s.period.is_open:
        raise HTTPException(400, "该结算周期已关闭")

    # 计算该周期系统总工时（小时）
    system_minutes = (
        s.db.exec(
            select(func.sum(WorkRecord.duration_minutes))
            .where(WorkRecord.user_id == s.user.id)
            .where(WorkRecord.dept_id == s.period.dept_id)
            .where(WorkRecord.created_at >= s.period.start_date)
            .where(WorkRecord.created_at <= s.period.end_date)
        ).first()
        or 0
    )
    system_hours = round(system_minutes / 60, 2)

    # 查找或更新申报
    claim = s.db.exec(
        select(SettlementClaim)
        .where(SettlementClaim.period_id == s.period.id)
        .where(SettlementClaim.user_id == s.user.id)
    ).first()

    total_hours = round(paid_hours + volunteer_hours, 2)
    # 业务规则：工资时长 + 志愿时长 必须等于该周期系统总工时
    if abs(total_hours - system_hours) > 1e-6:
        return templates.TemplateResponse(
            "admin/claim_form.html",
            {
                "request": s.request,
                "period": s.period,
                "system_hours": system_hours,
                "existing_claim": claim,
                "form_paid_hours": paid_hours,
                "form_volunteer_hours": volunteer_hours,
                "error_message": f"工资时长 + 志愿时长 必须等于本段总工时 {system_hours:.2f} 小时",
            },
            status_code=400,
        )

    if claim:
        claim.paid_hours = paid_hours
        claim.volunteer_hours = volunteer_hours
        claim.total_hours = total_hours
        claim.submitted_at = datetime.now()
    else:
        claim = SettlementClaim(
            period_id=s.period.id,
            user_id=s.user.id,
            paid_hours=paid_hours,
            volunteer_hours=volunteer_hours,
            total_hours=total_hours,
        )
        s.db.add(claim)

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
