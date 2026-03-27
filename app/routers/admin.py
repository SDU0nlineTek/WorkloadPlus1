"""管理员路由"""

import re
from contextlib import suppress
from datetime import datetime
from enum import StrEnum
from urllib.parse import quote, urlencode
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlmodel import col, desc, func, select

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
from app.routers.deps import (
    AdminSession,
    PeriodAdminSession,
    UserSession,
    templates,
)
from app.utils.activity_heatmap import build_activity_heatmap
from app.utils.excel_exporter import create_export_workbook

router = APIRouter(prefix="/admin", tags=["管理员"])


class PROJECT_STATUS_OPTIONS(StrEnum):
    IN_PROGRESS = "进行中"
    PENDING_LAUNCH = "待上线"
    DONE = "已完工"


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(
    s: AdminSession,
    start_date: str = Query(""),
    end_date: str = Query(""),
    user_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
):
    """管理员统计页面"""
    parsed_start_dt = None
    parsed_end_dt = None
    with suppress(ValueError):
        parsed_start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    with suppress(ValueError):
        parsed_end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
    members = []
    time_query = select(func.sum(WorkRecord.duration_minutes)).where(
        WorkRecord.dept_id == s.dept.id
    )
    record_query = select(func.count(col(WorkRecord.id)))
    if parsed_start_dt:
        time_query = time_query.where(WorkRecord.created_at >= parsed_start_dt)
        record_query = record_query.where(WorkRecord.created_at >= parsed_start_dt)
    if parsed_end_dt:
        time_query = time_query.where(WorkRecord.created_at <= parsed_end_dt)
        record_query = record_query.where(WorkRecord.created_at <= parsed_end_dt)
    for link in s.dept.user_links:
        # 计算该成员的总工时
        total_minutes = (
            s.db.exec(time_query.where(WorkRecord.user_id == link.user_id)).first() or 0
        )
        record_count = (
            s.db.exec(record_query.where(WorkRecord.user_id == link.user_id)).first()
            or 0
        )
        members.append(
            {
                "id": link.user.id,
                "name": link.user.name,
                "record_count": record_count,
                "is_admin": link.is_admin,
                "total_hours": total_minutes // 60,
                "total_mins": total_minutes % 60,
            }
        )
    # 项目统计
    record_query = select(func.count(col(WorkRecord.id)))
    time_query = select(func.sum(WorkRecord.duration_minutes))
    if parsed_start_dt:
        record_query = record_query.where(WorkRecord.created_at >= parsed_start_dt)
        time_query = time_query.where(WorkRecord.created_at >= parsed_start_dt)
    if parsed_end_dt:
        record_query = record_query.where(WorkRecord.created_at <= parsed_end_dt)
        time_query = time_query.where(WorkRecord.created_at <= parsed_end_dt)
    project_stats = []
    for project in s.dept.projects:
        record_count = (
            s.db.exec(record_query.where(WorkRecord.project_id == project.id)).first()
            or 0
        )
        total_minutes = (
            s.db.exec(time_query.where(WorkRecord.project_id == project.id)).first()
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
        s.request,
        "admin/stats.jinja2",
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
async def department_page(s: AdminSession):
    """部门管理页面"""
    members = []
    for link in s.dept.user_links:
        total_minutes = (
            s.db.exec(
                select(func.sum(WorkRecord.duration_minutes))
                .where(WorkRecord.dept_id == s.dept.id)
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
        .where(Project.dept_id == s.dept.id)
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
    join_link = f"{str(s.request.base_url).rstrip('/')}/admin/join/{s.dept.id}"
    return templates.TemplateResponse(
        s.request,
        "admin/department.jinja2",
        {
            "request": s.request,
            "admin_depts": s.user.admin_dept_list(),
            "current_dept_id": s.dept.id,
            "current_dept_name": s.dept.name,
            "members": members,
            "projects": project_items,
            "join_link": join_link,
            "current_user_id": s.user.id,
        },
    )


@router.post("/department/{dept_id}/projects/{project_id}/visibility")
async def update_project_visibility(
    s: AdminSession, project_id: UUID, is_visible: bool = Form(...)
):
    """更新项目可见性。"""
    project = s.db.get(Project, project_id)
    if not project or project.dept_id != s.dept.id:
        raise HTTPException(404, "项目不存在")
    project.is_visible = is_visible
    s.db.add(project)
    s.db.commit()
    return RedirectResponse(url="/admin/department", status_code=302)


@router.post("/department/{dept_id}/projects/{project_id}/rename")
async def rename_project(s: AdminSession, project_id: UUID, new_name: str = Form(...)):
    """重命名项目。"""
    project = s.db.get(Project, project_id)
    if not project or project.dept_id != s.dept.id:
        raise HTTPException(404, "项目不存在")

    normalized_name = new_name.strip()
    if not normalized_name:
        raise HTTPException(400, "项目名称不能为空")

    same_name_project = s.db.exec(
        select(Project)
        .where(Project.dept_id == s.dept.id)
        .where(Project.name == normalized_name)
    ).first()
    if same_name_project and same_name_project.id != project.id:
        # 同名项目合并：迁移记录与结算总结到已存在项目，再删除当前项目。
        records_to_move = s.db.exec(
            select(WorkRecord).where(WorkRecord.project_id == project.id)
        ).all()
        for record in records_to_move:
            record.project_id = same_name_project.id
            s.db.add(record)

        summaries_to_move = s.db.exec(
            select(SettlementProjectSummary).where(
                SettlementProjectSummary.project_id == project.id
            )
        ).all()
        for source_summary in summaries_to_move:
            target_summary = s.db.exec(
                select(SettlementProjectSummary)
                .where(SettlementProjectSummary.period_id == source_summary.period_id)
                .where(SettlementProjectSummary.project_id == same_name_project.id)
            ).first()

            if target_summary:
                source_text = source_summary.summary.strip()
                target_text = target_summary.summary.strip()
                if source_text and source_text != target_text:
                    target_summary.summary = f"{target_text}\n\n---\n\n{source_text}"
                target_summary.updated_at = max(
                    target_summary.updated_at, source_summary.updated_at
                )
                s.db.add(target_summary)
                s.db.delete(source_summary)
                continue

            source_summary.project_id = same_name_project.id
            s.db.add(source_summary)

        same_name_project.is_visible = (
            same_name_project.is_visible or project.is_visible
        )
        same_name_project.last_active_at = max(
            same_name_project.last_active_at, project.last_active_at
        )
        s.db.add(same_name_project)
        s.db.delete(project)
        s.db.commit()
        return RedirectResponse(url="/admin/department", status_code=302)

    project.name = normalized_name
    s.db.add(project)
    s.db.commit()
    return RedirectResponse(url="/admin/department", status_code=302)


@router.post("/department/{dept_id}/{member_id}/remove")
async def remove_member(s: AdminSession, dept_id: UUID, member_id: UUID):
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
        raise HTTPException(400, "管理员不能被移除")
    s.db.delete(link)
    s.db.commit()
    return RedirectResponse(url=f"/admin/department?dept_id={dept_id}", status_code=302)


@router.get("/join/{dept_id}")
async def join_department(s: UserSession, dept_id: UUID):
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
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    user_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
):
    """记录查询已并入统计页，保留重定向兼容。"""
    params: dict[str, str | UUID] = {}
    params["dept_id"] = s.dept.id
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
async def settlement_page(s: AdminSession):
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
        s.request,
        "admin/settlement.jinja2",
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
    s: AdminSession,
    title: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
):
    """创建结算周期"""
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d")
        ed = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
    except Exception:
        raise HTTPException(400, "日期格式错误")
    period = SettlementPeriod(
        dept_id=s.dept.id,
        title=title,
        start_date=sd,
        end_date=ed,
        is_open=True,
    )
    s.db.add(period)
    s.db.commit()
    return RedirectResponse(
        url=f"/admin/settlement?dept_id={s.dept.id}", status_code=302
    )


@router.post("/settlement/{period_id}/close")
async def close_settlement(s: PeriodAdminSession):
    """关闭结算周期"""
    s.period.is_open = False
    s.db.commit()
    return {"message": "已关闭"}


@router.post("/settlement/{period_id}/delete")
async def delete_settlement(s: PeriodAdminSession):
    """删除结算周期，并清理关联申报。"""
    claim_ids = s.db.exec(
        select(SettlementClaim.id).where(SettlementClaim.period_id == s.period.id)
    ).all()

    if claim_ids:
        related_records = s.db.exec(
            select(WorkRecord).where(col(WorkRecord.claim_id).in_(claim_ids))
        ).all()
        for record in related_records:
            record.claim_id = None
            s.db.add(record)

    summaries = s.db.exec(
        select(SettlementProjectSummary).where(
            SettlementProjectSummary.period_id == s.period.id
        )
    ).all()
    for summary in summaries:
        s.db.delete(summary)

    claims = s.db.exec(
        select(SettlementClaim).where(SettlementClaim.period_id == s.period.id)
    ).all()
    for claim in claims:
        s.db.delete(claim)

    s.db.delete(s.period)
    s.db.commit()
    return {"message": "已删除"}


@router.get("/settlement/{period_id}/claims", response_class=HTMLResponse)
async def settlement_claims(
    s: PeriodAdminSession,
    saved: bool = Query(False),
    user_id: UUID | None = Query(None),
):
    """查看结算周期申报情况"""
    period_records = s.db.exec(
        select(WorkRecord)
        .where(WorkRecord.dept_id == s.period.dept_id)
        .where(WorkRecord.created_at >= s.period.start_date)
        .where(WorkRecord.created_at <= s.period.end_date)
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
            SettlementProjectSummary.period_id == s.period.id
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

    claim_by_user_id = {claim.user_id: claim for claim in s.period.claims}
    member_data = []
    for u in s.dept.users:
        # 系统记录工时
        system_minutes = (
            s.db.exec(
                select(func.sum(WorkRecord.duration_minutes))
                .where(WorkRecord.user_id == u.id)
                .where(WorkRecord.dept_id == s.period.dept_id)
                .where(WorkRecord.created_at >= s.period.start_date)
                .where(WorkRecord.created_at <= s.period.end_date)
            ).first()
            or 0
        )
        member_data.append(
            {
                "user": u,
                "system_hours": system_minutes / 60,  # 查找申报
                "claim": claim_by_user_id.get(u.id),
            }
        )

    selected_member_detail = None
    selected_member_records: list[WorkRecord] = []
    if user_id:
        selected_member_detail = next(
            (item for item in member_data if item["user"].id == user_id), None
        )
        if selected_member_detail:
            selected_member_records = list(
                s.db.exec(
                    select(WorkRecord)
                    .join(Project, col(WorkRecord.project_id) == Project.id)
                    .where(WorkRecord.user_id == user_id)
                    .where(WorkRecord.dept_id == s.period.dept_id)
                    .where(WorkRecord.created_at >= s.period.start_date)
                    .where(WorkRecord.created_at <= s.period.end_date)
                    .order_by(col(WorkRecord.created_at).desc())
                ).all()
            )

    return templates.TemplateResponse(
        s.request,
        "admin/settlement_claims.jinja2",
        {
            "request": s.request,
            "period": s.period,
            "member_data": member_data,
            "selected_user_id": user_id,
            "selected_member_detail": selected_member_detail,
            "selected_member_records": selected_member_records,
            "project_summary_rows": project_summary_rows,
            "project_status_options": [item.value for item in PROJECT_STATUS_OPTIONS],
            "saved": saved,
        },
    )


@router.post("/settlement/{period_id}/project-summaries")
async def save_settlement_project_summaries(
    s: PeriodAdminSession,
    project_id: list[UUID] = Form(...),
    status: list[str] = Form(...),
    summary: list[str] = Form(...),
):
    """保存结算周期项目状态与总结"""
    if not (len(project_id) == len(status) == len(summary)):
        raise HTTPException(400, "提交数据格式错误")

    allowed_projects = s.db.exec(
        select(Project.id).where(Project.dept_id == s.period.dept_id)
    ).all()
    allowed_project_ids = set(allowed_projects)

    existing_rows = s.db.exec(
        select(SettlementProjectSummary).where(
            SettlementProjectSummary.period_id == s.period.id
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
                period_id=s.period.id,
                project_id=pid,
                status=current_status,
                summary=current_summary,
            )
        )

    s.db.commit()
    return RedirectResponse(
        url=f"/admin/settlement/{s.period.id}/claims?saved=1", status_code=302
    )


@router.post("/export/download")
async def download_export(
    s: AdminSession,
    period_id: UUID | None = Form(None),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    user_id: UUID | None = Form(None),
    project_id: UUID | None = Form(None),
):
    """下载 Excel 导出"""
    # 解析日期
    sd = None
    ed = None
    if start_date:
        with suppress(Exception):
            sd = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        with suppress(Exception):
            ed = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )

    # 生成 Excel
    output = create_export_workbook(
        session=s.db,
        dept_id=s.dept.id,
        start_date=sd,
        end_date=ed,
        period_id=period_id,
        user_id=user_id,
        project_id=project_id,
    )

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
    safe_dept_name = re.sub(r'[\\/:*?"<>|]', "_", s.dept.name).strip() or "部门"
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
