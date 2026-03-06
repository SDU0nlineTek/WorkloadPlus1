"""Activity heatmap data builder."""

from datetime import date, datetime, timedelta
from math import ceil


def build_activity_heatmap(
    timestamps: list[datetime],
    total_days: int = 365,
    end_date: date | None = None,
) -> dict:
    """Build GitHub-like weekly heatmap data from record timestamps."""
    if end_date is None:
        end_date = date.today()

    start_date = end_date - timedelta(days=total_days - 1)

    # Align the rendered grid to full weeks (Sunday -> Saturday).
    start_offset = (start_date.weekday() + 1) % 7
    display_start = start_date - timedelta(days=start_offset)
    end_offset = 6 - ((end_date.weekday() + 1) % 7)
    display_end = end_date + timedelta(days=end_offset)

    counts: dict[date, int] = {}
    for ts in timestamps:
        day = ts.date()
        if start_date <= day <= end_date:
            counts[day] = counts.get(day, 0) + 1

    max_count = max(counts.values(), default=0)

    def level_for(count: int) -> int:
        if count <= 0 or max_count <= 0:
            return 0
        return max(1, min(4, ceil((count / max_count) * 4)))

    days: list[dict] = []
    total_display_days = (display_end - display_start).days + 1
    for offset in range(total_display_days):
        current_day = display_start + timedelta(days=offset)
        count = counts.get(current_day, 0)
        sun_first_weekday = (current_day.weekday() + 1) % 7
        in_range = start_date <= current_day <= end_date
        days.append(
            {
                "date": current_day.strftime("%Y-%m-%d"),
                "count": count,
                "level": level_for(count),
                "weekday": current_day.weekday(),
                "weekday_sun_first": sun_first_weekday,
                "day_of_month": current_day.day,
                "month": current_day.month,
                "year": current_day.year,
                "in_range": in_range,
            }
        )

    week_columns: list[list[dict]] = []
    for i in range(0, len(days), 7):
        week_columns.append(days[i : i + 7])

    month_labels: list[str] = []
    for week_index, week in enumerate(week_columns):
        label = ""
        for day in week:
            if day["in_range"] and day["day_of_month"] == 1:
                label = f"{day['month']}月"
                break

        if not label and week_index == 0:
            first_in_range = next((d for d in week if d["in_range"]), None)
            if first_in_range:
                label = f"{first_in_range['month']}月"

        month_labels.append(label)

    active_days = sum(1 for d in days if d["count"] > 0)

    return {
        "weeks": week_columns,
        "weekday_labels": ["周日", "周一", "周二", "周三", "周四", "周五", "周六"],
        "month_labels": month_labels,
        "max_count": max_count,
        "active_days": active_days,
        "total_days": total_days,
    }
