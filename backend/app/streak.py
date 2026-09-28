from datetime import date, timedelta


def advance_streak(count: int, last_day: str | None, today: date) -> tuple[int, str]:
    today_text = today.isoformat()
    if last_day == today_text:
        return count or 0, today_text
    yesterday = (today - timedelta(days=1)).isoformat()
    if last_day == yesterday:
        return (count or 0) + 1, today_text
    return 1, today_text


def visible_streak(count: int, last_day: str | None, today: date) -> int:
    if not last_day:
        return 0
    last = date.fromisoformat(last_day)
    if last == today or last == today - timedelta(days=1):
        return count or 0
    return 0
