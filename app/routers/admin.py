"""管理员路由"""

from datetime import datetime
from typing import Optional
from urllib.parse import quote, urlencode
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import col, desc, func, select

from app.config import get_settings
from app.models import (
    Department,
    Project,
    SettlementClaim,
    SettlementPeriod,
    UserDeptLink,
    WorkRecord,
)
from app.routers.deps import AdminSession, DeptAdminSession, UserSession
from app.services.activity_heatmap import build_activity_heatmap
from app.services.excel_exporter import create_export_workbook

router = APIRouter(prefix="/admin", tags=["管理员"])
settings = get_settings()
templates = Jinja2Templates(directory=settings.base_dir / "templates")


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(
    s: AdminSession,
    member_id: Optional[UUID] = Query(None),
    detail_project_id: Optional[UUID] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user_id: Optional[UUID] = Query(None),
    project_id: Optional[UUID] = Query(None),
):
    """管理员统计页面"""
    # 成员统计
    member_links = s.db.exec(
        select(UserDeptLink).where(UserDeptLink.dept_id == s.dept.id)
    ).all()

    members = []
    for link in member_links:
        # 计算该成员的总工时
        total_minutes = (
            s.db.exec(
                select(func.sum(WorkRecord.duration_minutes))
                .where(WorkRecord.user_id == link.user_id)
                .where(WorkRecord.dept_id == s.dept.id)
            ).first()
            or 0
        )

        members.append(
            {
                "id": link.user.id,
                "name": link.user.name,
                "sduid": link.user.sduid,
                "is_admin": link.is_admin,
                "total_hours": total_minutes // 60,
                "total_mins": total_minutes % 60,
            }
        )

    # 项目统计
    projects = s.db.exec(select(Project).where(Project.dept_id == s.dept.id)).all()

    project_stats = []
    for project in projects:
        record_count = (
            s.db.exec(
                select(func.count(col(WorkRecord.id))).where(
                    WorkRecord.project_id == project.id
                )
            ).first()
            or 0
        )

        total_minutes = (
            s.db.exec(
                select(func.sum(WorkRecord.duration_minutes)).where(
                    WorkRecord.project_id == project.id
                )
            ).first()
            or 0
        )

        project_stats.append(
            {
                "id": project.id,
                "name": project.name,
                "record_count": record_count,
                "total_hours": total_minutes // 60,
                "total_mins": total_minutes % 60,
                "last_active": project.last_active_at.strftime("%Y-%m-%d"),
            }
        )

    # 兼容旧参数：统一归并到筛选参数
    if member_id and not user_id:
        user_id = member_id
    if detail_project_id and not project_id:
        project_id = detail_project_id

    parsed_start_dt = None
    parsed_end_dt = None
    if start_date:
        try:
            parsed_start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            start_date = None
    if end_date:
        try:
            parsed_end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
        except ValueError:
            end_date = None

    # 当前部门整体热力图
    department_query = select(WorkRecord).where(WorkRecord.dept_id == s.dept.id)
    if parsed_start_dt:
        department_query = department_query.where(
            WorkRecord.created_at >= parsed_start_dt
        )
    if parsed_end_dt:
        department_query = department_query.where(
            WorkRecord.created_at <= parsed_end_dt
        )

    dept_records = s.db.exec(department_query).all()
    department_heatmap = build_activity_heatmap(
        [r.created_at for r in dept_records], weeks=20
    )

    selected_member = next((m for m in members if user_id and m["id"] == user_id), None)
    selected_project = next(
        (p for p in project_stats if project_id and p["id"] == project_id), None
    )

    # 合并记录查询功能：筛选后的记录列表
    filtered_query = department_query
    if user_id:
        filtered_query = filtered_query.where(WorkRecord.user_id == user_id)
    if project_id:
        filtered_query = filtered_query.where(WorkRecord.project_id == project_id)

    filtered_records = s.db.exec(
        filtered_query.order_by(desc(WorkRecord.created_at))
    ).all()
    filter_heatmap = build_activity_heatmap(
        [r.created_at for r in filtered_records], weeks=20
    )

    return templates.TemplateResponse(
        "admin/stats.html",
        {
            "request": s.request,
            "user": s.user,
            "admin_depts": s.user.admin_dept_list(),
            "current_dept_id": s.dept.id,
            "dept": s.dept,
            "members": members,
            "project_stats": project_stats,
            "selected_member": selected_member,
            "selected_project": selected_project,
            "department_heatmap": department_heatmap,
            "filter_heatmap": filter_heatmap,
            "filter_records": filtered_records,
            "start_date": start_date,
            "end_date": end_date,
            "selected_user_id": user_id,
            "selected_filter_project_id": project_id,
        },
    )


@router.get("/members", response_class=HTMLResponse)
async def members_page(
    s: AdminSession,
):
    """成员管理页面"""
    request = s.request
    dept = s.dept
    dept_id = dept.id
    member_links = s.db.exec(
        select(UserDeptLink).where(UserDeptLink.dept_id == dept_id)
    ).all()

    members = []
    for link in member_links:
        total_minutes = (
            s.db.exec(
                select(func.sum(WorkRecord.duration_minutes))
                .where(WorkRecord.dept_id == dept_id)
                .where(WorkRecord.user_id == link.user_id)
            ).first()
            or 0
        )
        members.append(
            {
                "id": link.user_id,
                "name": link.user.name,
                "sduid": link.user.sduid,
                "is_admin": link.is_admin,
                "total_hours": round(total_minutes / 60, 1),
            }
        )

    join_link = f"{str(s.request.base_url).rstrip('/')}/admin/join/{dept_id}"

    return templates.TemplateResponse(
        "admin/members.html",
        {
            "request": request,
            "admin_depts": s.user.admin_dept_list(),
            "current_dept_id": dept_id,
            "members": members,
            "join_link": join_link,
            "current_user_id": s.user.id,
        },
    )


@router.post("/members/{dept_id}/{member_id}/remove")
async def remove_member(
    s: DeptAdminSession,
    dept_id: UUID,
    member_id: UUID,
):
    """移除部门成员"""

    if s.user.id == member_id:
        raise HTTPException(400, "不能移除自己")

    link = s.db.exec(
        select(UserDeptLink)
        .where(UserDeptLink.dept_id == dept_id)
        .where(UserDeptLink.user_id == member_id)
    ).first()
    if not link:
        raise HTTPException(404, "成员不存在")

    if link.is_admin:
        admin_count = (
            s.db.exec(
                select(func.count())
                .select_from(UserDeptLink)
                .where(UserDeptLink.dept_id == dept_id)
                .where(UserDeptLink.is_admin)
            ).first()
            or 0
        )
        if admin_count <= 1:
            raise HTTPException(400, "不能移除最后一位管理员")

    s.db.delete(link)
    s.db.commit()

    return RedirectResponse(url=f"/admin/members?dept_id={dept_id}", status_code=302)


@router.get("/join/{dept_id}")
async def join_department(
    s: UserSession,
    dept_id: UUID,
):
    """部门注册链接：登录后加入部门"""

    dept = s.db.get(Department, dept_id)
    if not dept:
        raise HTTPException(404, "部门不存在")

    link = s.db.exec(
        select(UserDeptLink)
        .where(UserDeptLink.user_id == s.user.id)
        .where(UserDeptLink.dept_id == dept_id)
    ).first()
    if not link:
        s.db.add(UserDeptLink(user_id=s.user.id, dept_id=dept_id, is_admin=False))
        s.db.commit()

    return RedirectResponse(url="/record", status_code=302)


@router.get("/records", response_class=HTMLResponse)
async def records_page(
    s: AdminSession,
    dept_id: Optional[UUID] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user_id: Optional[UUID] = Query(None),
    project_id: Optional[UUID] = Query(None),
):
    """记录查询已并入统计页，保留重定向兼容。"""
    if not dept_id:
        dept_id = s.dept.id

    params: dict[str, str | UUID] = {}
    if dept_id:
        params["dept_id"] = dept_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if user_id:
        params["user_id"] = user_id
    if project_id:
        params["project_id"] = project_id
    qs = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/admin/stats{qs}#filter-records", status_code=302)


@router.get("/settlement", response_class=HTMLResponse)
async def settlement_page(
    s: AdminSession,
):
    """结算周期管理页面"""
    # 获取结算周期
    periods = s.db.exec(
        select(SettlementPeriod)
        .where(SettlementPeriod.dept_id == s.dept.id)
        .order_by(col(SettlementPeriod.id).desc())
    ).all()

    # 获取每个周期的申报数量
    period_stats = []
    for period in periods:
        claim_count = (
            s.db.exec(
                select(func.count(col(SettlementClaim.id))).where(
                    SettlementClaim.period_id == period.id
                )
            ).first()
            or 0
        )

        period_stats.append(
            {
                "period": period,
                "claim_count": claim_count,
            }
        )

    return templates.TemplateResponse(
        "admin/settlement.html",
        {
            "request": s.request,
            "admin_depts": s.user.admin_dept_list(),
            "current_dept_id": s.dept.id,
            "period_stats": period_stats,
        },
    )


@router.post("/settlement")
async def create_settlement(
    s: UserSession,
    dept_id: UUID = Form(...),
    title: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
):
    """创建结算周期"""
    s.user.require_admin(s.db, dept_id)

    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d")
        ed = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
    except Exception:
        raise HTTPException(400, "日期格式错误")

    period = SettlementPeriod(
        dept_id=dept_id,
        title=title,
        start_date=sd,
        end_date=ed,
        is_open=True,
    )
    s.db.add(period)
    s.db.commit()

    return RedirectResponse(url=f"/admin/settlement?dept_id={dept_id}", status_code=302)


@router.post("/settlement/{period_id}/close")
async def close_settlement(
    s: UserSession,
    period_id: UUID,
):
    """关闭结算周期"""

    period = s.db.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")

    s.user.require_admin(s.db, period.dept_id)

    period.is_open = False
    s.db.commit()

    return {"message": "已关闭"}


@router.get("/settlement/{period_id}/claims", response_class=HTMLResponse)
async def settlement_claims(
    s: UserSession,
    period_id: UUID,
):
    """查看结算周期申报情况"""
    request = s.request

    period = s.db.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")
    if not s.user.is_dept_admin(s.db, period.dept_id):
        raise HTTPException(403, "无管理员权限")
    member_data = []
    for u in period.department.users:
        # 系统记录工时
        system_minutes = (
            s.db.exec(
                select(func.sum(WorkRecord.duration_minutes))
                .where(WorkRecord.user_id == u.id)
                .where(WorkRecord.dept_id == period.dept_id)
                .where(WorkRecord.created_at >= period.start_date)
                .where(WorkRecord.created_at <= period.end_date)
            ).first()
            or 0
        )
        member_data.append(
            {
                "user": u,
                "system_hours": system_minutes / 60,  # 查找申报
                "claim": next((c for c in period.claims if c.user_id == u.id), None),
            }
        )
    return templates.TemplateResponse(
        "admin/settlement_claims.html",
        {
            "request": request,
            "period": period,
            "member_data": member_data,
        },
    )


# 用户申报端点
@router.get("/claim/{period_id}", response_class=HTMLResponse)
async def claim_page(
    s: UserSession,
    period_id: UUID,
):
    """用户申报页面"""

    period = s.db.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")
    if not period.is_open:
        raise HTTPException(400, "该结算周期已关闭")
    # 计算系统工时
    system_minutes = (
        s.db.exec(
            select(func.sum(WorkRecord.duration_minutes))
            .where(WorkRecord.user_id == s.user.id)
            .where(WorkRecord.dept_id == period.dept_id)
            .where(WorkRecord.created_at >= period.start_date)
            .where(WorkRecord.created_at <= period.end_date)
        ).first()
        or 0
    )
    # 查找已有申报
    existing_claim = s.db.exec(
        select(SettlementClaim)
        .where(SettlementClaim.period_id == period_id)
        .where(SettlementClaim.user_id == s.user.id)
    ).first()

    return templates.TemplateResponse(
        "admin/claim_form.html",
        {
            "request": s.request,
            "period": period,
            "system_hours": system_minutes / 60,
            "existing_claim": existing_claim,
        },
    )


@router.post("/claim/{period_id}")
async def submit_claim(
    s: UserSession,
    period_id: UUID,
    paid_hours: float = Form(...),
    volunteer_hours: float = Form(...),
):
    """提交申报"""
    request = s.request

    period = s.db.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")
    if not period.is_open:
        raise HTTPException(400, "该结算周期已关闭")
    # 计算该周期系统总工时（小时）
    system_minutes = (
        s.db.exec(
            select(func.sum(WorkRecord.duration_minutes))
            .where(WorkRecord.user_id == s.user.id)
            .where(WorkRecord.dept_id == period.dept_id)
            .where(WorkRecord.created_at >= period.start_date)
            .where(WorkRecord.created_at <= period.end_date)
        ).first()
        or 0
    )
    system_hours = round(system_minutes / 60, 2)

    # 查找或更新申报
    claim = s.db.exec(
        select(SettlementClaim)
        .where(SettlementClaim.period_id == period_id)
        .where(SettlementClaim.user_id == s.user.id)
    ).first()

    total_hours = round(paid_hours + volunteer_hours, 2)
    # 业务规则：工资时长 + 志愿时长 必须等于该周期系统总工时
    if abs(total_hours - system_hours) > 1e-6:
        return templates.TemplateResponse(
            "admin/claim_form.html",
            {
                "request": request,
                "period": period,
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
            period_id=period_id,
            user_id=s.user.id,
            paid_hours=paid_hours,
            volunteer_hours=volunteer_hours,
            total_hours=total_hours,
        )
        s.db.add(claim)
    s.db.commit()
    return RedirectResponse(url="/timeline", status_code=302)


@router.post("/export/download")
async def download_export(
    s: UserSession,
    dept_id: UUID = Form(...),
    period_id: Optional[UUID] = Form(None),
    start_date: Optional[str] = Form(None),
    end_date: Optional[str] = Form(None),
    user_id: Optional[UUID] = Form(None),
    project_id: Optional[UUID] = Form(None),
):
    """下载 Excel 导出"""
    s.user.require_admin(s.db, dept_id)

    # 解析日期
    sd = None
    ed = None
    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d")
        except Exception:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
        except Exception:
            pass

    # 生成 Excel
    output = create_export_workbook(
        session=s.db,
        dept_id=dept_id,
        start_date=sd,
        end_date=ed,
        period_id=period_id,
        user_id=user_id,
        project_id=project_id,
    )

    # 获取部门名称
    dept = s.db.get(Department, dept_id)
    if not dept:
        raise HTTPException(404, "部门不存在")

    filename = f"工作量导出_{dept.name}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    encoded_filename = quote(filename)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        },
    )
