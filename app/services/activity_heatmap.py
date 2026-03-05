"""Activity heatmap data builder."""

from datetime import date, datetime, timedelta
from math import ceil


def build_activity_heatmap(
    timestamps: list[datetime],
    weeks: int = 20,
    end_date: date | None = None,
) -> dict:
    """Build GitHub-like weekly heatmap data from record timestamps."""
    if end_date is None:
        end_date = date.today()

    total_days = weeks * 7
    start_date = end_date - timedelta(days=total_days - 1)

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
    for offset in range(total_days):
        current_day = start_date + timedelta(days=offset)
        count = counts.get(current_day, 0)
        days.append(
            {
                "date": current_day.strftime("%Y-%m-%d"),
                "count": count,
                "level": level_for(count),
                "weekday": current_day.weekday(),
            }
        )

    week_columns: list[list[dict]] = []
    for i in range(0, len(days), 7):
        week_columns.append(days[i : i + 7])

    active_days = sum(1 for d in days if d["count"] > 0)

    return {
        "weeks": week_columns,
        "max_count": max_count,
        "active_days": active_days,
        "total_days": total_days,
    }
