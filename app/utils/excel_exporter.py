"""Excel 导出服务"""

from datetime import datetime
from io import BytesIO
from typing import Optional
from uuid import UUID

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlmodel import Session, col, select

from app.core import settings
from app.models import (
    Project,
    SettlementClaim,
    SettlementPeriod,
    SettlementProjectSummary,
    UserDeptLink,
    WorkRecord,
)


def create_export_workbook(
    session: Session,
    dept_id: UUID,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    period_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
) -> BytesIO:
    """
    创建导出 Excel 工作簿

    Args:
        session: 数据库会话
        dept_id: 部门ID
        start_date: 开始日期 (可选)
        end_date: 结束日期 (可选)
        period_id: 结算周期ID (可选，如果提供则从结算周期获取日期范围)
        user_id: 成员筛选 (可选)
        project_id: 项目筛选 (可选)

    Returns:
        BytesIO: Excel 文件流
    """
    wb = Workbook()
    wb.properties.creator += f"; {settings.app_name}"
    wb.properties.lastModifiedBy = settings.app_name

    # 样式定义
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(
        start_color="4472C4", end_color="4472C4", fill_type="solid"
    )
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    def merge_adjacent_same_values(
        worksheet,
        column_index: int,
        start_row: int,
        end_row: int,
    ) -> None:
        """Merge adjacent identical values in one column within a row range."""
        if end_row <= start_row:
            return

        merge_start = start_row
        prev_value = worksheet.cell(row=start_row, column=column_index).value

        for r in range(start_row + 1, end_row + 1):
            current_value = worksheet.cell(row=r, column=column_index).value
            if current_value != prev_value:
                if merge_start < r - 1 and prev_value not in (None, "", "-"):
                    worksheet.merge_cells(
                        start_row=merge_start,
                        start_column=column_index,
                        end_row=r - 1,
                        end_column=column_index,
                    )
                    worksheet.cell(
                        row=merge_start, column=column_index
                    ).alignment = header_alignment
                merge_start = r
                prev_value = current_value

        if merge_start < end_row and prev_value not in (None, "", "-"):
            worksheet.merge_cells(
                start_row=merge_start,
                start_column=column_index,
                end_row=end_row,
                end_column=column_index,
            )
            worksheet.cell(
                row=merge_start, column=column_index
            ).alignment = header_alignment

    # 如果提供了结算周期ID，获取日期范围
    if period_id:
        period = session.get(SettlementPeriod, period_id)
        if period:
            start_date = period.start_date
            end_date = period.end_date

    # ==================== Sheet 1: 个人 ====================
    ws1 = wb.active
    assert ws1
    ws1.title = "个人"

    # 表头
    headers1 = [
        "姓名",
        "学号",
        "项目",
        "工作时间",
        "工作内容",
        "详细信息",
        "时长(h)",
        "总时长(h)",
        "工资时长(h)",
        "志愿时长(h)",
    ]
    for c, header in enumerate(headers1, 1):
        cell = ws1.cell(row=1, column=c, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # 获取部门成员
    member_links = session.exec(
        select(UserDeptLink).where(UserDeptLink.dept_id == dept_id)
    ).all()
    if user_id:
        member_links = [link for link in member_links if link.user_id == user_id]

    row = 2
    user_row_blocks: list[tuple[int, int]] = []
    for link in member_links:
        user = link.user
        user_start_row = row

        # 构建工作记录查询
        record_query = (
            select(WorkRecord)
            .where(WorkRecord.user_id == user.id)
            .where(WorkRecord.dept_id == dept_id)
        )

        if start_date:
            record_query = record_query.where(WorkRecord.created_at >= start_date)
        if end_date:
            record_query = record_query.where(WorkRecord.created_at <= end_date)
        if project_id:
            record_query = record_query.where(WorkRecord.project_id == project_id)

        records = session.exec(
            record_query.order_by(col(WorkRecord.created_at).asc())
        ).all()

        # 获取申报信息（仅按结算周期导出时有值）
        paid_hours = 0.0
        volunteer_hours = 0.0

        if period_id:
            claim = session.exec(
                select(SettlementClaim)
                .where(SettlementClaim.period_id == period_id)
                .where(SettlementClaim.user_id == user.id)
            ).first()
            if claim:
                paid_hours = claim.paid_hours
                volunteer_hours = claim.volunteer_hours

        # 写入明细（每条记录一行）
        if records:
            for r in records:
                ws1.cell(row=row, column=1, value=user.name).border = thin_border
                ws1.cell(row=row, column=2, value=user.sduid).border = thin_border
                ws1.cell(row=row, column=3, value=r.project.name).border = thin_border
                ws1.cell(
                    row=row, column=4, value=r.created_at.strftime("%Y-%m-%d %H:%M")
                ).border = thin_border
                ws1.cell(row=row, column=5, value=r.description).border = thin_border
                ws1.cell(
                    row=row, column=6, value=r.related_content or "-"
                ).border = thin_border
                ws1.cell(
                    row=row, column=7, value=round(r.duration_minutes / 60, 2)
                ).border = thin_border
                ws1.cell(row=row, column=8, value=None).border = thin_border
                ws1.cell(
                    row=row, column=9, value=round(paid_hours, 2)
                ).border = thin_border
                ws1.cell(
                    row=row, column=10, value=round(volunteer_hours, 2)
                ).border = thin_border
                row += 1
        else:
            # 没有明细时保留人员汇总行
            ws1.cell(row=row, column=1, value=user.name).border = thin_border
            ws1.cell(row=row, column=2, value=user.sduid).border = thin_border
            ws1.cell(row=row, column=3, value="-").border = thin_border
            ws1.cell(row=row, column=4, value="-").border = thin_border
            ws1.cell(row=row, column=5, value="-").border = thin_border
            ws1.cell(row=row, column=6, value="-").border = thin_border
            ws1.cell(row=row, column=7, value=0).border = thin_border
            ws1.cell(row=row, column=8, value=None).border = thin_border
            ws1.cell(row=row, column=9, value=round(paid_hours, 2)).border = thin_border
            ws1.cell(
                row=row, column=10, value=round(volunteer_hours, 2)
            ).border = thin_border
            row += 1

        user_end_row = row - 1
        user_row_blocks.append((user_start_row, user_end_row))

        total_formula = f"=SUM($G${user_start_row}:$G${user_end_row})"
        for r in range(user_start_row, user_end_row + 1):
            ws1.cell(row=r, column=8, value=total_formula).border = thin_border

    sheet1_last_row = row - 1

    # 小时列与申报列统一数值格式
    for r in range(2, sheet1_last_row + 1):
        ws1.cell(row=r, column=7).number_format = "0.00"
        ws1.cell(row=r, column=8).number_format = "0.00"
        ws1.cell(row=r, column=9).number_format = "0.00"
        ws1.cell(row=r, column=10).number_format = "0.00"

    # 成员维度字段按成员分块合并，项目列也仅在成员分块内合并。
    for start_row, end_row in user_row_blocks:
        merge_adjacent_same_values(ws1, 3, start_row, end_row)
        if start_row >= end_row:
            continue
        for col_idx in (1, 2, 8, 9, 10):
            ws1.merge_cells(
                start_row=start_row,
                start_column=col_idx,
                end_row=end_row,
                end_column=col_idx,
            )
            ws1.cell(row=start_row, column=col_idx).alignment = header_alignment

    # 调整列宽
    ws1.column_dimensions["A"].width = 12
    ws1.column_dimensions["B"].width = 14
    ws1.column_dimensions["C"].width = 16
    ws1.column_dimensions["D"].width = 18
    ws1.column_dimensions["E"].width = 36
    ws1.column_dimensions["F"].width = 28
    ws1.column_dimensions["G"].width = 10
    ws1.column_dimensions["H"].width = 10
    ws1.column_dimensions["I"].width = 12
    ws1.column_dimensions["J"].width = 12

    # ==================== Sheet 2: 项目 ====================
    ws2 = wb.create_sheet(title="项目")

    # 表头
    headers2 = [
        "项目名",
        "姓名",
        "工作时间",
        "工作内容",
        "详细信息",
        "时长(h)",
        "总时长(h)",
    ]
    for c, header in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=c, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # 获取项目
    projects = session.exec(select(Project).where(Project.dept_id == dept_id)).all()
    if project_id:
        projects = [p for p in projects if p.id == project_id]

    row = 2
    project_row_blocks: list[tuple[int, int]] = []
    for project in projects:
        project_start_row = row
        # 构建查询
        record_query = select(WorkRecord).where(WorkRecord.project_id == project.id)

        if start_date:
            record_query = record_query.where(WorkRecord.created_at >= start_date)
        if end_date:
            record_query = record_query.where(WorkRecord.created_at <= end_date)
        if user_id:
            record_query = record_query.where(WorkRecord.user_id == user_id)

        records = session.exec(record_query).all()

        if not records:
            continue

        # 每条记录一行，并用公式计算项目总时长
        for r in records:
            ws2.cell(row=row, column=1, value=project.name).border = thin_border
            ws2.cell(row=row, column=2, value=r.user.name).border = thin_border
            ws2.cell(
                row=row, column=3, value=r.created_at.strftime("%Y-%m-%d %H:%M")
            ).border = thin_border
            ws2.cell(row=row, column=4, value=r.description).border = thin_border
            ws2.cell(
                row=row, column=5, value=r.related_content or "-"
            ).border = thin_border
            ws2.cell(
                row=row, column=6, value=round(r.duration_minutes / 60, 2)
            ).border = thin_border
            ws2.cell(row=row, column=7, value=None).border = thin_border
            row += 1

        project_end_row = row - 1
        project_row_blocks.append((project_start_row, project_end_row))

        total_formula = f"=SUM($F${project_start_row}:$F${project_end_row})"
        for r in range(project_start_row, project_end_row + 1):
            ws2.cell(row=r, column=7, value=total_formula).border = thin_border

    sheet2_last_row = row - 1

    for r in range(2, sheet2_last_row + 1):
        ws2.cell(row=r, column=6).number_format = "0.00"
        ws2.cell(row=r, column=7).number_format = "0.00"

    # 姓名按相邻相同值合并
    merge_adjacent_same_values(ws2, 2, 2, sheet2_last_row)

    # 项目维度字段按项目分块合并
    for start_row, end_row in project_row_blocks:
        if start_row >= end_row:
            continue
        for col_idx in (1, 7):
            ws2.merge_cells(
                start_row=start_row,
                start_column=col_idx,
                end_row=end_row,
                end_column=col_idx,
            )
            ws2.cell(row=start_row, column=col_idx).alignment = header_alignment

    # 调整列宽
    ws2.column_dimensions["A"].width = 18
    ws2.column_dimensions["B"].width = 12
    ws2.column_dimensions["C"].width = 18
    ws2.column_dimensions["D"].width = 36
    ws2.column_dimensions["E"].width = 28
    ws2.column_dimensions["F"].width = 10
    ws2.column_dimensions["G"].width = 12

    # ==================== Sheet 3: 统计 ====================
    ws3 = wb.create_sheet(title="统计")

    # 项目统计块
    ws3.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
    ws3.cell(row=1, column=1, value="项目统计").font = Font(bold=True, size=13)
    ws3.cell(row=1, column=1).alignment = Alignment(
        horizontal="left", vertical="center"
    )

    project_headers = ["项目名", "完工状态", "项目总结", "时长(h)"]
    for c, header in enumerate(project_headers, 1):
        cell = ws3.cell(row=2, column=c, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    project_rows_start = 3
    stats_project_query = select(WorkRecord).where(WorkRecord.dept_id == dept_id)
    if start_date:
        stats_project_query = stats_project_query.where(
            WorkRecord.created_at >= start_date
        )
    if end_date:
        stats_project_query = stats_project_query.where(
            WorkRecord.created_at <= end_date
        )
    if user_id:
        stats_project_query = stats_project_query.where(WorkRecord.user_id == user_id)
    if project_id:
        stats_project_query = stats_project_query.where(
            WorkRecord.project_id == project_id
        )

    stats_records = session.exec(stats_project_query).all()

    project_hours: dict[UUID, float] = {}
    for record in stats_records:
        project_hours[record.project_id] = project_hours.get(record.project_id, 0.0) + (
            record.duration_minutes / 60
        )

    stats_projects = []
    if project_hours:
        stats_projects = session.exec(
            select(Project)
            .where(col(Project.id).in_(list(project_hours.keys())))
            .order_by(col(Project.name).asc())
        ).all()

    summary_by_project_id: dict[UUID, SettlementProjectSummary] = {}
    if period_id:
        period_summaries = session.exec(
            select(SettlementProjectSummary).where(
                SettlementProjectSummary.period_id == period_id
            )
        ).all()
        summary_by_project_id = {item.project_id: item for item in period_summaries}

    project_row = project_rows_start
    for project in stats_projects:
        summary_row = summary_by_project_id.get(project.id)
        ws3.cell(row=project_row, column=1, value=project.name).border = thin_border
        ws3.cell(
            row=project_row,
            column=2,
            value=summary_row.status if summary_row else "-",
        ).border = thin_border
        ws3.cell(
            row=project_row,
            column=3,
            value=summary_row.summary if summary_row else "-",
        ).border = thin_border
        ws3.cell(
            row=project_row,
            column=4,
            value=(f"=IFERROR(SUMIFS('项目'!$F:$F,'项目'!$A:$A,$A{project_row}),0)"),
        ).border = thin_border
        ws3.cell(row=project_row, column=4).number_format = "0.00"
        project_row += 1

    if project_row == project_rows_start:
        for c in range(1, 5):
            ws3.cell(row=project_row, column=c, value="-").border = thin_border
        project_row += 1

    # 个人统计块（右侧并列）
    people_title_row = 1
    people_start_col = 6
    ws3.merge_cells(
        start_row=people_title_row,
        start_column=people_start_col,
        end_row=people_title_row,
        end_column=people_start_col + 4,
    )
    ws3.cell(
        row=people_title_row, column=people_start_col, value="个人统计"
    ).font = Font(bold=True, size=13)
    ws3.cell(row=people_title_row, column=people_start_col).alignment = Alignment(
        horizontal="left", vertical="center"
    )

    people_header_row = 2
    people_headers = ["姓名", "学号", "总时长(h)", "工资时长(h)", "志愿时长(h)"]
    for offset, header in enumerate(people_headers):
        cell = ws3.cell(
            row=people_header_row, column=people_start_col + offset, value=header
        )
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    people_row = 3
    for link in member_links:
        ws3.cell(
            row=people_row, column=people_start_col, value=link.user.name
        ).border = thin_border
        ws3.cell(
            row=people_row, column=people_start_col + 1, value=link.user.sduid
        ).border = thin_border

        ws3.cell(
            row=people_row,
            column=people_start_col + 2,
            value=(
                f"=IFERROR(SUMIFS('个人'!$H:$H,'个人'!$A:$A,$F{people_row},'个人'!$B:$B,$G{people_row}),0)"
            ),
        ).border = thin_border
        ws3.cell(
            row=people_row,
            column=people_start_col + 3,
            value=(
                f"=IFERROR(SUMIFS('个人'!$I:$I,'个人'!$A:$A,$F{people_row},'个人'!$B:$B,$G{people_row}),0)"
            ),
        ).border = thin_border
        ws3.cell(
            row=people_row,
            column=people_start_col + 4,
            value=(
                f"=IFERROR(SUMIFS('个人'!$J:$J,'个人'!$A:$A,$F{people_row},'个人'!$B:$B,$G{people_row}),0)"
            ),
        ).border = thin_border

        ws3.cell(row=people_row, column=people_start_col + 2).number_format = "0.00"
        ws3.cell(row=people_row, column=people_start_col + 3).number_format = "0.00"
        ws3.cell(row=people_row, column=people_start_col + 4).number_format = "0.00"
        people_row += 1

    if people_row == 3:
        for offset in range(5):
            ws3.cell(
                row=people_row, column=people_start_col + offset, value="-"
            ).border = thin_border

    ws3.column_dimensions["A"].width = 18
    ws3.column_dimensions["B"].width = 12
    ws3.column_dimensions["C"].width = 46
    ws3.column_dimensions["D"].width = 12
    ws3.column_dimensions["E"].width = 4
    ws3.column_dimensions["F"].width = 12
    ws3.column_dimensions["G"].width = 14
    ws3.column_dimensions["H"].width = 12
    ws3.column_dimensions["I"].width = 12
    ws3.column_dimensions["J"].width = 12

    # 保存到 BytesIO
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return output
