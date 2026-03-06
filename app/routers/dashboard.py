"""个人时间线路由"""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlmodel import col, select

from app.models import (
    WorkRecord,
)
from app.routers.deps import UseridSession, UserSession, templates
from app.utils.activity_heatmap import build_activity_heatmap

router = APIRouter(tags=["时间线"])


@router.get("/timeline", response_class=HTMLResponse)
async def timeline_page(
    s: UserSession,
    month: Optional[str] = Query(None),  # 格式: 2024-01
    dept_id: Optional[UUID] = Query(None),
    day: Optional[str] = Query(None),  # 格式: 2024-01-31
):
    """个人时间线页面"""
    # 解析当前部门（来自侧边栏选择），并兼容旧参数。
    user_dept_ids = {link.dept_id for link in s.user.dept_links}
    selected_dept_id = dept_id
    if not selected_dept_id:
        selected_raw = s.request.session.get("current_dept_id")
        if selected_raw:
            try:
                selected_dept_id = UUID(selected_raw)
            except TypeError, ValueError:
                selected_dept_id = None

    if selected_dept_id and selected_dept_id not in user_dept_ids:
        selected_dept_id = None

    # 构建查询
    query = select(WorkRecord).where(WorkRecord.user_id == s.user.id)

    # 按月份筛选
    if month:
        try:
            year, mon = map(int, month.split("-"))
            start_date = datetime(year, mon, 1)
            if mon == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, mon + 1, 1)
            query = query.where(WorkRecord.created_at >= start_date)
            query = query.where(WorkRecord.created_at < end_date)
        except Exception:
            pass

    # 按部门筛选
    if selected_dept_id:
        query = query.where(WorkRecord.dept_id == selected_dept_id)

    # 热力图保持按月份/部门口径，不跟随按天筛选缩小范围。
    heatmap_query = query

    # 按日期筛选
    if day:
        try:
            day_start = datetime.strptime(day, "%Y-%m-%d")
            day_end = day_start + timedelta(days=1)
            query = query.where(WorkRecord.created_at >= day_start)
            query = query.where(WorkRecord.created_at < day_end)
        except ValueError:
            pass

    # 获取记录
    records = s.db.exec(query.order_by(col(WorkRecord.created_at).desc())).all()
    heatmap_records = s.db.exec(
        heatmap_query.order_by(col(WorkRecord.created_at).desc())
    ).all()

    # 按日期分组
    grouped_records = {}
    for record in records:
        date_key = record.created_at.strftime("%Y-%m-%d")
        if date_key not in grouped_records:
            grouped_records[date_key] = {
                "date": record.created_at.strftime("%m月%d日"),
                "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
                    record.created_at.weekday()
                ],
                "records": [],
                "total_minutes": 0,
            }
        grouped_records[date_key]["records"].append(record)
        grouped_records[date_key]["total_minutes"] += record.duration_minutes

    # 生成月份选项（最近12个月）
    months = []
    now = datetime.now()
    for i in range(12):
        d = now - timedelta(days=i * 30)
        months.append(
            {
                "value": d.strftime("%Y-%m"),
                "label": d.strftime("%Y年%m月"),
            }
        )

    # 计算总工时
    total_minutes = sum(r.duration_minutes for r in records)
    total_hours = total_minutes // 60
    total_mins = total_minutes % 60

    heatmap_timestamps = [r.created_at for r in heatmap_records]
    activity_heatmap = build_activity_heatmap(heatmap_timestamps)

    return templates.TemplateResponse(
        "timeline.html",
        {
            "request": s.request,
            "user": s.user,
            "grouped_records": grouped_records,
            "months": months,
            "current_month": month,
            "current_day": day,
            "total_hours": total_hours,
            "total_mins": total_mins,
            "record_count": len(records),
            "activity_heatmap": activity_heatmap,
        },
    )


@router.get("/timeline/filter", response_class=HTMLResponse)
async def timeline_filter(s: UseridSession, month: Optional[str] = Query(None)):
    """HTMX 筛选端点"""
    # 构建查询
    query = (
        select(WorkRecord)
        .where(WorkRecord.user_id == s.user_id)
        .where(WorkRecord.dept_id == UUID(s.request.session.get("current_dept_id")))
    )
    if month:
        try:
            year, mon = map(int, month.split("-"))
            start_date = datetime(year, mon, 1)
            if mon == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, mon + 1, 1)
            query = query.where(WorkRecord.created_at >= start_date)
            query = query.where(WorkRecord.created_at < end_date)
        except Exception:
            pass
    records = s.db.exec(query.order_by(col(WorkRecord.created_at).desc())).all()
    # 按日期分组
    grouped_records = {}
    for record in records:
        date_key = record.created_at.strftime("%Y-%m-%d")
        if date_key not in grouped_records:
            grouped_records[date_key] = {
                "date": record.created_at.strftime("%m月%d日"),
                "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
                    record.created_at.weekday()
                ],
                "records": [],
                "total_minutes": 0,
            }
        grouped_records[date_key]["records"].append(record)
        grouped_records[date_key]["total_minutes"] += record.duration_minutes
    # 返回记录列表HTML片段
    html_parts = []
    if not grouped_records:
        html_parts.append('<p class="text-gray-400 text-center py-12">暂无记录</p>')
    else:
        for date_key, group in grouped_records.items():
            html_parts.append(f"""
            <div class="mb-6">
                <div class="flex items-center mb-3">
                    <div class="w-3 h-3 bg-blue-600 rounded-full"></div>
                    <span class="ml-3 font-medium text-gray-800">{group["date"]} {group["weekday"]}</span>
                    <span class="ml-auto text-sm text-gray-500">{group["total_minutes"] / 60:.1f} 小时</span>
                </div>
                <div class="ml-6 border-l-2 border-gray-200 pl-4 space-y-3">
            """)
            for record in group["records"]:
                html_parts.append(f"""
                    <div class="p-3 bg-white rounded-lg shadow-sm">
                        <div class="flex justify-between items-start">
                            <div>
                                <p class="font-medium text-gray-800">{record.project.name}</p>
                                <p class="text-sm text-gray-600 mt-1">{record.description}</p>
                                <p class="text-xs text-gray-400 mt-1">{record.department.name}</p>
                            </div>
                            <span class="text-blue-600 font-medium">{record.duration_minutes / 60:.1f} 小时</span>
                        </div>
                    </div>
                """)
            html_parts.append("</div></div>")
    return HTMLResponse("\n".join(html_parts))
