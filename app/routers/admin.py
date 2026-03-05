"""管理员路由"""

from datetime import datetime
from typing import Optional
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlmodel import Session, desc, func, select

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
from app.routers.deps import check_dept_admin
from app.services.activity_heatmap import build_activity_heatmap

router = APIRouter(prefix="/admin", tags=["管理员"])
settings = get_settings()
templates = Jinja2Templates(directory=settings.base_dir / "templates")


def require_admin(request: Request, session: Session, dept_id: int) -> User:
    """验证管理员权限"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, "未登录")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(401, "用户不存在")

    if not check_dept_admin(user, dept_id, session):
        raise HTTPException(403, "无管理员权限")

    return user


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    dept_id: Optional[int] = Query(None),
    member_id: Optional[int] = Query(None),
    detail_project_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """管理员统计页面"""
    current_user_id = request.session.get("user_id")
    if not current_user_id:
        return RedirectResponse(url="/login", status_code=302)

    user = session.get(User, current_user_id)
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    # 获取用户管理的部门
    admin_links = session.exec(
        select(UserDeptLink)
        .where(UserDeptLink.user_id == current_user_id)
        .where(UserDeptLink.is_admin == True)
    ).all()

    if not admin_links:
        return templates.TemplateResponse(
            "admin/no_permission.html",
            {
                "request": request,
            },
        )

    admin_depts = [
        {"id": link.dept_id, "name": link.department.name} for link in admin_links
    ]

    # 默认选择第一个部门
    if not dept_id:
        dept_id = admin_depts[0]["id"]

    # 验证权限
    if not any(d["id"] == dept_id for d in admin_depts):
        dept_id = admin_depts[0]["id"]

    # 获取部门统计
    dept = session.get(Department, dept_id)

    # 成员统计
    member_links = session.exec(
        select(UserDeptLink).where(UserDeptLink.dept_id == dept_id)
    ).all()

    members = []
    for link in member_links:
        # 计算该成员的总工时
        total_minutes = (
            session.exec(
                select(func.sum(WorkRecord.duration_minutes))
                .where(WorkRecord.user_id == link.user_id)
                .where(WorkRecord.dept_id == dept_id)
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
    projects = session.exec(select(Project).where(Project.dept_id == dept_id)).all()

    project_stats = []
    for project in projects:
        record_count = (
            session.exec(
                select(func.count(WorkRecord.id)).where(
                    WorkRecord.project_id == project.id
                )
            ).first()
            or 0
        )

        total_minutes = (
            session.exec(
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
    department_query = select(WorkRecord).where(WorkRecord.dept_id == dept_id)
    if parsed_start_dt:
        department_query = department_query.where(
            WorkRecord.created_at >= parsed_start_dt
        )
    if parsed_end_dt:
        department_query = department_query.where(
            WorkRecord.created_at <= parsed_end_dt
        )

    dept_records = session.exec(department_query).all()
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

    filtered_records = session.exec(
        filtered_query.order_by(desc(WorkRecord.created_at))
    ).all()
    filter_heatmap = build_activity_heatmap(
        [r.created_at for r in filtered_records], weeks=20
    )

    return templates.TemplateResponse(
        "admin/stats.html",
        {
            "request": request,
            "user": user,
            "admin_depts": admin_depts,
            "current_dept_id": dept_id,
            "dept": dept,
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
    request: Request,
    dept_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """成员管理页面"""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    user = session.get(User, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    admin_links = session.exec(
        select(UserDeptLink)
        .where(UserDeptLink.user_id == user_id)
        .where(UserDeptLink.is_admin == True)
    ).all()
    if not admin_links:
        return templates.TemplateResponse(
            "admin/no_permission.html", {"request": request}
        )

    admin_depts = [
        {"id": link.dept_id, "name": link.department.name} for link in admin_links
    ]
    if not dept_id:
        dept_id = admin_depts[0]["id"]

    if not any(d["id"] == dept_id for d in admin_depts):
        dept_id = admin_depts[0]["id"]

    member_links = session.exec(
        select(UserDeptLink).where(UserDeptLink.dept_id == dept_id)
    ).all()

    members = []
    for link in member_links:
        total_minutes = (
            session.exec(
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

    join_link = f"{str(request.base_url).rstrip('/')}/admin/join/{dept_id}"

    return templates.TemplateResponse(
        "admin/members.html",
        {
            "request": request,
            "admin_depts": admin_depts,
            "current_dept_id": dept_id,
            "members": members,
            "join_link": join_link,
            "current_user_id": user_id,
        },
    )


@router.post("/members/{dept_id}/{member_id}/remove")
async def remove_member(
    request: Request,
    dept_id: int,
    member_id: int,
    session: Session = Depends(get_session),
):
    """移除部门成员"""
    current_user = require_admin(request, session, dept_id)

    if current_user.id == member_id:
        raise HTTPException(400, "不能移除自己")

    link = session.exec(
        select(UserDeptLink)
        .where(UserDeptLink.dept_id == dept_id)
        .where(UserDeptLink.user_id == member_id)
    ).first()
    if not link:
        raise HTTPException(404, "成员不存在")

    if link.is_admin:
        admin_count = (
            session.exec(
                select(func.count())
                .select_from(UserDeptLink)
                .where(UserDeptLink.dept_id == dept_id)
                .where(UserDeptLink.is_admin == True)
            ).first()
            or 0
        )
        if admin_count <= 1:
            raise HTTPException(400, "不能移除最后一位管理员")

    session.delete(link)
    session.commit()

    return RedirectResponse(url=f"/admin/members?dept_id={dept_id}", status_code=302)


@router.get("/join/{dept_id}")
async def join_department(
    request: Request,
    dept_id: int,
    session: Session = Depends(get_session),
):
    """部门注册链接：登录后加入部门"""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    dept = session.get(Department, dept_id)
    if not dept:
        raise HTTPException(404, "部门不存在")

    link = session.exec(
        select(UserDeptLink)
        .where(UserDeptLink.user_id == user_id)
        .where(UserDeptLink.dept_id == dept_id)
    ).first()
    if not link:
        session.add(UserDeptLink(user_id=user_id, dept_id=dept_id, is_admin=False))
        session.commit()

    return RedirectResponse(url="/record", status_code=302)


@router.get("/records", response_class=HTMLResponse)
async def records_page(
    request: Request,
    dept_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """记录查询已并入统计页，保留重定向兼容。"""
    params: dict[str, str | int] = {}
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
    request: Request,
    dept_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """结算周期管理页面"""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    user = session.get(User, user_id)

    # 获取管理的部门
    admin_links = session.exec(
        select(UserDeptLink)
        .where(UserDeptLink.user_id == user_id)
        .where(UserDeptLink.is_admin == True)
    ).all()

    if not admin_links:
        return templates.TemplateResponse(
            "admin/no_permission.html", {"request": request}
        )

    admin_depts = [
        {"id": link.dept_id, "name": link.department.name} for link in admin_links
    ]

    if not dept_id:
        dept_id = admin_depts[0]["id"]

    # 获取结算周期
    periods = session.exec(
        select(SettlementPeriod)
        .where(SettlementPeriod.dept_id == dept_id)
        .order_by(SettlementPeriod.created_at.desc())
    ).all()

    # 获取每个周期的申报数量
    period_stats = []
    for period in periods:
        claim_count = (
            session.exec(
                select(func.count(SettlementClaim.id)).where(
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
            "request": request,
            "admin_depts": admin_depts,
            "current_dept_id": dept_id,
            "period_stats": period_stats,
        },
    )


@router.post("/settlement")
async def create_settlement(
    request: Request,
    dept_id: int = Form(...),
    title: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    session: Session = Depends(get_session),
):
    """创建结算周期"""
    user = require_admin(request, session, dept_id)

    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d")
        ed = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
    except:
        raise HTTPException(400, "日期格式错误")

    period = SettlementPeriod(
        dept_id=dept_id,
        title=title,
        start_date=sd,
        end_date=ed,
        is_open=True,
    )
    session.add(period)
    session.commit()

    return RedirectResponse(url=f"/admin/settlement?dept_id={dept_id}", status_code=302)


@router.post("/settlement/{period_id}/close")
async def close_settlement(
    request: Request,
    period_id: int,
    session: Session = Depends(get_session),
):
    """关闭结算周期"""
    period = session.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")

    user = require_admin(request, session, period.dept_id)

    period.is_open = False
    session.commit()

    return {"message": "已关闭"}


@router.get("/settlement/{period_id}/claims", response_class=HTMLResponse)
async def settlement_claims(
    request: Request,
    period_id: int,
    session: Session = Depends(get_session),
):
    """查看结算周期申报情况"""
    period = session.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")

    user_id = request.session.get("user_id")
    user = session.get(User, user_id)

    if not check_dept_admin(user, period.dept_id, session):
        raise HTTPException(403, "无管理员权限")

    # 获取所有申报
    claims = session.exec(
        select(SettlementClaim).where(SettlementClaim.period_id == period_id)
    ).all()

    # 获取部门所有成员
    members = session.exec(
        select(UserDeptLink).where(UserDeptLink.dept_id == period.dept_id)
    ).all()

    # 计算每个成员的系统工时和申报状态
    member_data = []
    for link in members:
        # 系统记录工时
        system_minutes = (
            session.exec(
                select(func.sum(WorkRecord.duration_minutes))
                .where(WorkRecord.user_id == link.user_id)
                .where(WorkRecord.dept_id == period.dept_id)
                .where(WorkRecord.created_at >= period.start_date)
                .where(WorkRecord.created_at <= period.end_date)
            ).first()
            or 0
        )

        # 查找申报
        claim = next((c for c in claims if c.user_id == link.user_id), None)

        member_data.append(
            {
                "user": link.user,
                "system_hours": system_minutes / 60,
                "claim": claim,
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
    request: Request,
    period_id: int,
    session: Session = Depends(get_session),
):
    """用户申报页面"""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    period = session.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")

    if not period.is_open:
        raise HTTPException(400, "该结算周期已关闭")

    user = session.get(User, user_id)

    # 计算系统工时
    system_minutes = (
        session.exec(
            select(func.sum(WorkRecord.duration_minutes))
            .where(WorkRecord.user_id == user_id)
            .where(WorkRecord.dept_id == period.dept_id)
            .where(WorkRecord.created_at >= period.start_date)
            .where(WorkRecord.created_at <= period.end_date)
        ).first()
        or 0
    )

    # 查找已有申报
    existing_claim = session.exec(
        select(SettlementClaim)
        .where(SettlementClaim.period_id == period_id)
        .where(SettlementClaim.user_id == user_id)
    ).first()

    return templates.TemplateResponse(
        "admin/claim_form.html",
        {
            "request": request,
            "period": period,
            "system_hours": system_minutes / 60,
            "existing_claim": existing_claim,
        },
    )


@router.post("/claim/{period_id}")
async def submit_claim(
    request: Request,
    period_id: int,
    paid_hours: float = Form(...),
    volunteer_hours: float = Form(...),
    session: Session = Depends(get_session),
):
    """提交申报"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, "未登录")

    period = session.get(SettlementPeriod, period_id)
    if not period:
        raise HTTPException(404, "结算周期不存在")

    if not period.is_open:
        raise HTTPException(400, "该结算周期已关闭")

    # 计算该周期系统总工时（小时）
    system_minutes = (
        session.exec(
            select(func.sum(WorkRecord.duration_minutes))
            .where(WorkRecord.user_id == user_id)
            .where(WorkRecord.dept_id == period.dept_id)
            .where(WorkRecord.created_at >= period.start_date)
            .where(WorkRecord.created_at <= period.end_date)
        ).first()
        or 0
    )
    system_hours = round(system_minutes / 60, 2)

    # 查找或更新申报
    claim = session.exec(
        select(SettlementClaim)
        .where(SettlementClaim.period_id == period_id)
        .where(SettlementClaim.user_id == user_id)
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
            user_id=user_id,
            paid_hours=paid_hours,
            volunteer_hours=volunteer_hours,
            total_hours=total_hours,
        )
        session.add(claim)

    session.commit()

    return RedirectResponse(url="/timeline", status_code=302)


@router.get("/export", response_class=HTMLResponse)
async def export_page(
    request: Request,
    dept_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """导出已下沉到申报详情和筛选结果，保留重定向兼容。"""
    target = (
        f"/admin/stats?dept_id={dept_id}#filter-records"
        if dept_id
        else "/admin/stats#filter-records"
    )
    return RedirectResponse(url=target, status_code=302)


@router.post("/export/download")
async def download_export(
    request: Request,
    dept_id: int = Form(...),
    period_id: Optional[int] = Form(None),
    start_date: Optional[str] = Form(None),
    end_date: Optional[str] = Form(None),
    user_id: Optional[int] = Form(None),
    project_id: Optional[int] = Form(None),
    session: Session = Depends(get_session),
):
    """下载 Excel 导出"""
    user = require_admin(request, session, dept_id)

    from app.services.excel_exporter import create_export_workbook

    # 解析日期
    sd = None
    ed = None
    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d")
        except:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
        except:
            pass

    # 生成 Excel
    output = create_export_workbook(
        session=session,
        dept_id=dept_id,
        start_date=sd,
        end_date=ed,
        period_id=period_id if period_id and period_id > 0 else None,
        user_id=user_id,
        project_id=project_id,
    )

    # 获取部门名称
    dept = session.get(Department, dept_id)
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
