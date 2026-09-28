from datetime import date, timedelta


def can_change_position(current: str | None, new: str, changed_on: str | None, today: date, tier: str) -> tuple[bool, str | None]:
    if current == new or current is None or tier == "pro":
        return True, None
    if not changed_on:
        return True, None
    opened = date.fromisoformat(changed_on) + timedelta(days=30)
    if today >= opened:
        return True, None
    return False, opened.isoformat()
