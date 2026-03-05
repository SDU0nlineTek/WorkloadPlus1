"""工作记录路由"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.models import (
    Department,
    Project,
    SettlementClaim,
    SettlementPeriod,
    User,
    UserDeptLink,
    WorkRecord,
)
from app.routers.deps import CurrentUser, get_user_departments

router = APIRouter(tags=["工作记录"])
settings = get_settings()
templates = Jinja2Templates(directory=settings.base_dir / "templates")


class RecordItem(BaseModel):
    """单条记录"""

    dept_id: int
    project_name: str
    description: str
    hours: int = 0
    minutes: int = 0
    related_content: str | None = None


class BatchRecordRequest(BaseModel):
    """批量记录请求"""

    records: list[RecordItem]


@router.get("/record", response_class=HTMLResponse)
async def record_page(
    request: Request,
    session: Session = Depends(get_session),
):
    """填报主页面"""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    user = session.get(User, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    # 获取用户所属部门
    departments = get_user_departments(user, session)
    user_dept_ids = [
        dept["id"] if isinstance(dept, dict) else dept.id for dept in departments
    ]

    # 首页申报入口：当前用户所属部门的开放结算周期
    claim_entries = []
    if user_dept_ids:
        open_periods = session.exec(
            select(SettlementPeriod)
            .where(SettlementPeriod.is_open == True)
            .where(SettlementPeriod.dept_id.in_(user_dept_ids))
            .order_by(SettlementPeriod.created_at.desc())
        ).all()

        period_ids = [period.id for period in open_periods]
        claimed_period_ids = set()
        if period_ids:
            claimed_period_ids = set(
                session.exec(
                    select(SettlementClaim.period_id)
                    .where(SettlementClaim.user_id == user_id)
                    .where(SettlementClaim.period_id.in_(period_ids))
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
    today_records = session.exec(
        select(WorkRecord)
        .where(WorkRecord.user_id == user_id)
        .where(WorkRecord.created_at >= today_start)
        .order_by(WorkRecord.created_at.desc())
    ).all()

    # 计算今日总时长
    today_minutes = sum(r.duration_minutes for r in today_records)
    today_hours = today_minutes // 60
    today_mins = today_minutes % 60

    return templates.TemplateResponse(
        "record.html",
        {
            "request": request,
            "user": user,
            "departments": departments,
            "today_records": today_records,
            "today_hours": today_hours,
            "today_mins": today_mins,
            "claim_entries": claim_entries,
        },
    )


@router.get("/claim")
async def claim_entry(
    request: Request,
    session: Session = Depends(get_session),
):
    """用户申报快捷入口：跳转到最近开放周期"""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    user = session.get(User, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    departments = get_user_departments(user, session)
    user_dept_ids = [dept["id"] for dept in departments]

    if not user_dept_ids:
        return RedirectResponse(url="/record#settlement-claims", status_code=302)

    period = session.exec(
        select(SettlementPeriod)
        .where(SettlementPeriod.is_open == True)
        .where(SettlementPeriod.dept_id.in_(user_dept_ids))
        .order_by(SettlementPeriod.created_at.desc())
    ).first()

    if not period:
        return RedirectResponse(url="/record#settlement-claims", status_code=302)

    return RedirectResponse(url=f"/admin/claim/{period.id}", status_code=302)


@router.get("/projects/dropdown", response_class=HTMLResponse)
async def get_project_dropdown(
    request: Request,
    dept_id: int = Query(...),
    session: Session = Depends(get_session),
):
    """获取部门项目下拉选项（HTMX端点）"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, "未登录")

    # 获取部门配置的活跃窗口
    dept = session.get(Department, dept_id)
    if not dept:
        return HTMLResponse('<option value="">请选择项目</option>')

    window_months = dept.active_project_window_months
    cutoff_date = datetime.now() - timedelta(days=window_months * 30)

    # 查询活跃项目
    projects = session.exec(
        select(Project)
        .where(Project.dept_id == dept_id)
        .where(Project.last_active_at >= cutoff_date)
        .order_by(Project.last_active_at.desc())
    ).all()

    # 生成HTML选项
    options = ['<option value="">选择或输入新项目</option>']
    for p in projects:
        options.append(f'<option value="{p.name}">{p.name}</option>')

    return HTMLResponse("\n".join(options))


@router.post("/record")
async def create_record(
    request: Request,
    session: Session = Depends(get_session),
    dept_id: int = Form(...),
    project_name: str = Form(...),
    description: str = Form(...),
    hours: int = Form(0),
    minutes: int = Form(0),
    related_content: str | None = Form(None),
):
    """创建单条记录"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, "未登录")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(401, "用户不存在")

    # 验证部门
    dept = session.get(Department, dept_id)
    if not dept:
        raise HTTPException(400, "部门不存在")

    if hours < 0 or minutes < 0:
        raise HTTPException(400, "时长不能为负数")

    # 计算总分钟数
    duration_minutes = hours * 60 + minutes
    if duration_minutes <= 0:
        raise HTTPException(400, "时长必须大于0")

    # 查找或创建项目
    project = session.exec(
        select(Project)
        .where(Project.dept_id == dept_id)
        .where(Project.name == project_name)
    ).first()

    if not project:
        project = Project(dept_id=dept_id, name=project_name)
        session.add(project)
        session.commit()
        session.refresh(project)
    else:
        # 更新活跃时间
        project.last_active_at = datetime.now()
        session.add(project)

    # 创建记录
    record = WorkRecord(
        user_id=user_id,
        dept_id=dept_id,
        project_id=project.id,
        description=description,
        duration_minutes=duration_minutes,
        related_content=related_content if related_content else None,
    )
    session.add(record)

    # 确保用户与部门关联
    link = session.exec(
        select(UserDeptLink)
        .where(UserDeptLink.user_id == user_id)
        .where(UserDeptLink.dept_id == dept_id)
    ).first()
    if not link:
        link = UserDeptLink(user_id=user_id, dept_id=dept_id, is_admin=False)
        session.add(link)

    session.commit()

    # 返回重定向
    return RedirectResponse(url="/record", status_code=302)


@router.post("/record/batch")
async def create_batch_records(
    request: Request,
    data: BatchRecordRequest,
    session: Session = Depends(get_session),
):
    """批量创建记录"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, "未登录")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(401, "用户不存在")

    if not data.records:
        raise HTTPException(400, "至少需要一条记录")

    created_count = 0

    for item in data.records:
        # 验证部门
        dept = session.get(Department, item.dept_id)
        if not dept:
            continue

        if item.hours < 0 or item.minutes < 0:
            continue

        # 计算总分钟数
        duration_minutes = item.hours * 60 + item.minutes
        if duration_minutes <= 0:
            continue

        # 查找或创建项目
        project = session.exec(
            select(Project)
            .where(Project.dept_id == item.dept_id)
            .where(Project.name == item.project_name)
        ).first()

        if not project:
            project = Project(dept_id=item.dept_id, name=item.project_name)
            session.add(project)
            session.commit()
            session.refresh(project)
        else:
            project.last_active_at = datetime.now()
            session.add(project)

        # 创建记录
        record = WorkRecord(
            user_id=user_id,
            dept_id=item.dept_id,
            project_id=project.id,
            description=item.description,
            duration_minutes=duration_minutes,
            related_content=item.related_content,
        )
        session.add(record)

        # 确保用户与部门关联
        link = session.exec(
            select(UserDeptLink)
            .where(UserDeptLink.user_id == user_id)
            .where(UserDeptLink.dept_id == item.dept_id)
        ).first()
        if not link:
            link = UserDeptLink(user_id=user_id, dept_id=item.dept_id, is_admin=False)
            session.add(link)

        created_count += 1

    session.commit()

    return {"message": f"成功创建 {created_count} 条记录", "count": created_count}


@router.delete("/record/{record_id}")
async def delete_record(
    request: Request,
    record_id: int,
    session: Session = Depends(get_session),
):
    """删除记录"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, "未登录")

    record = session.get(WorkRecord, record_id)
    if not record:
        raise HTTPException(404, "记录不存在")

    if record.user_id != user_id:
        raise HTTPException(403, "无权删除他人记录")

    session.delete(record)
    session.commit()

    return {"message": "删除成功"}
