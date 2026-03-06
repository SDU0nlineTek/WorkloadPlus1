"""管理员路由"""

import re
from datetime import datetime
from enum import StrEnum
from typing import Optional
from urllib.parse import quote, urlencode
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import col, desc, func, select

from app.config import settings
from app.models import (
    Department,
    Project,
    SettlementClaim,
    SettlementPeriod,
    SettlementProjectSummary,
    User,
    UserDeptLink,
    WorkRecord,
)
from app.routers.deps import AdminSession, DeptAdminSession, UserSession
from app.services.activity_heatmap import build_activity_heatmap
from app.services.excel_exporter import create_export_workbook

router = APIRouter(prefix="/admin", tags=["管理员"])

templates = Jinja2Templates(directory=settings.base_dir / "templates")


class PROJECT_STATUS_OPTIONS(StrEnum):
    IN_PROGRESS = "进行中"
    PENDING_LAUNCH = "待上线"
    DONE = "已完工"


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
    department_heatmap = build_activity_heatmap([r.created_at for r in dept_records])

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
    filter_heatmap = build_activity_heatmap([r.created_at for r in filtered_records])

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


@router.get("/department", response_class=HTMLResponse)
async def department_page(
    s: AdminSession,
):
    """部门管理页面（成员与项目可见性）"""
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

    projects = s.db.exec(
        select(Project)
        .where(Project.dept_id == dept_id)
        .order_by(col(Project.last_active_at).desc())
    ).all()

    project_items = []
    for project in projects:
        project_record_count = (
            s.db.exec(
                select(func.count(col(WorkRecord.id))).where(
                    WorkRecord.project_id == project.id
                )
            ).first()
            or 0
        )
        project_items.append(
            {
                "id": project.id,
                "name": project.name,
                "is_visible": project.is_visible,
                "last_active": project.last_active_at,
                "record_count": project_record_count,
            }
        )

    join_link = f"{str(s.request.base_url).rstrip('/')}/admin/join/{dept_id}"

    return templates.TemplateResponse(
        "admin/department.html",
        {
            "request": request,
            "admin_depts": s.user.admin_dept_list(),
            "current_dept_id": dept_id,
            "current_dept_name": dept.name,
            "members": members,
            "projects": project_items,
            "join_link": join_link,
            "current_user_id": s.user.id,
        },
    )


@router.post("/department/projects/{project_id}/visibility")
async def update_project_visibility(
    s: AdminSession,
    project_id: UUID,
    is_visible: bool = Form(...),
):
    """更新项目可见性。"""
    project = s.db.get(Project, project_id)
    if not project or project.dept_id != s.dept.id:
        raise HTTPException(404, "项目不存在")

    project.is_visible = is_visible
    s.db.add(project)
    s.db.commit()

    return RedirectResponse(url="/admin/department", status_code=302)


@router.post("/department/{dept_id}/{member_id}/remove")
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

    return RedirectResponse(url=f"/admin/department?dept_id={dept_id}", status_code=302)


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
            "current_dept_name": s.dept.name,
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
    saved: bool = Query(False),
):
    """查看结算周期申报情况"""
    request = s.request

    period = s.db.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")
    if not s.user.is_dept_admin(s.db, period.dept_id):
        raise HTTPException(403, "无管理员权限")

    period_records = s.db.exec(
        select(WorkRecord)
        .where(WorkRecord.dept_id == period.dept_id)
        .where(WorkRecord.created_at >= period.start_date)
        .where(WorkRecord.created_at <= period.end_date)
        .order_by(col(WorkRecord.created_at).asc())
    ).all()

    involved_project_ids = []
    seen_ids: set[UUID] = set()
    for record in period_records:
        if record.project_id in seen_ids:
            continue
        seen_ids.add(record.project_id)
        involved_project_ids.append(record.project_id)

    involved_projects = []
    if involved_project_ids:
        involved_projects = s.db.exec(
            select(Project)
            .where(col(Project.id).in_(involved_project_ids))
            .order_by(col(Project.name).asc())
        ).all()

    existing_summaries = s.db.exec(
        select(SettlementProjectSummary).where(
            SettlementProjectSummary.period_id == period_id
        )
    ).all()
    summary_by_project_id = {item.project_id: item for item in existing_summaries}

    project_stats: dict[UUID, dict[str, float | int]] = {}
    for record in period_records:
        stats = project_stats.setdefault(
            record.project_id,
            {
                "record_count": 0,
                "total_hours": 0.0,
            },
        )
        stats["record_count"] = int(stats["record_count"]) + 1
        stats["total_hours"] = float(stats["total_hours"]) + (
            record.duration_minutes / 60
        )

    project_summary_rows = []
    for project in involved_projects:
        saved_summary = summary_by_project_id.get(project.id)
        stats = project_stats.get(project.id, {"record_count": 0, "total_hours": 0.0})
        project_summary_rows.append(
            {
                "project": project,
                "status": (
                    saved_summary.status
                    if saved_summary
                    else PROJECT_STATUS_OPTIONS.IN_PROGRESS.value
                ),
                "summary": saved_summary.summary if saved_summary else "",
                "record_count": int(stats["record_count"]),
                "total_hours": round(float(stats["total_hours"]), 2),
            }
        )

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
            "project_summary_rows": project_summary_rows,
            "project_status_options": [item.value for item in PROJECT_STATUS_OPTIONS],
            "saved": saved,
        },
    )


@router.post("/settlement/{period_id}/project-summaries")
async def save_settlement_project_summaries(
    s: UserSession,
    period_id: UUID,
    project_id: list[UUID] = Form(...),
    status: list[str] = Form(...),
    summary: list[str] = Form(...),
):
    """保存结算周期项目状态与总结"""
    period = s.db.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")
    s.user.require_admin(s.db, period.dept_id)

    if not (len(project_id) == len(status) == len(summary)):
        raise HTTPException(400, "提交数据格式错误")

    allowed_projects = s.db.exec(
        select(Project.id).where(Project.dept_id == period.dept_id)
    ).all()
    allowed_project_ids = set(allowed_projects)

    existing_rows = s.db.exec(
        select(SettlementProjectSummary).where(
            SettlementProjectSummary.period_id == period_id
        )
    ).all()
    existing_map = {row.project_id: row for row in existing_rows}

    for idx, pid in enumerate(project_id):
        if pid not in allowed_project_ids:
            raise HTTPException(400, "包含非法项目")

        current_status = status[idx].strip()
        current_summary = summary[idx].strip()

        try:
            current_status = PROJECT_STATUS_OPTIONS(current_status).value
        except ValueError:
            raise HTTPException(400, "项目状态不合法")
        if not current_summary:
            raise HTTPException(400, "项目总结不能为空")

        existing = existing_map.get(pid)
        if existing:
            existing.status = current_status
            existing.summary = current_summary
            existing.updated_at = datetime.now()
            continue

        s.db.add(
            SettlementProjectSummary(
                period_id=period_id,
                project_id=pid,
                status=current_status,
                summary=current_summary,
            )
        )

    s.db.commit()
    return RedirectResponse(
        url=f"/admin/settlement/{period_id}/claims?saved=1", status_code=302
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

    period = s.db.get(SettlementPeriod, period_id) if period_id else None
    if period:
        filter_label = period.title
    else:
        custom_parts: list[str] = []

        if user_id:
            selected_user = s.db.get(User, user_id)
            if selected_user:
                custom_parts.append(f"成员-{selected_user.name}")

        if project_id:
            selected_project = s.db.get(Project, project_id)
            if selected_project:
                custom_parts.append(f"项目-{selected_project.name}")

        if not custom_parts:
            custom_parts.append("全部成员项目")

        if start_date or end_date:
            custom_parts.append(f"{start_date or '起始'}~{end_date or '结束'}")

        filter_label = "_".join(custom_parts)

    # Windows/macOS/Linux 保守文件名清洗
    safe_dept_name = re.sub(r'[\\/:*?"<>|]', "_", dept.name).strip() or "部门"
    safe_filter_label = re.sub(r'[\\/:*?"<>|]', "_", filter_label).strip() or "筛选"
    export_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = f"{export_time}_{safe_dept_name}_{safe_filter_label}_工作量.xlsx"
    encoded_filename = quote(filename)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        },
    )
