from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo


def format_duration(total_seconds: int) -> str:
    """Format seconds as a compact '3д 4ч 5м' string (minutes are always shown)."""
    days, remainder = divmod(max(0, total_seconds), 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes = remainder // 60
    parts = ([f"{days}д"] if days else []) + ([f"{hours}ч"] if hours or days else []) + [f"{minutes}м"]
    return " ".join(parts)


def format_age(total_seconds: int) -> str:
    """Format how long ago something happened: 'только что', '5 мин назад', '3 ч назад', '2 дн назад'."""
    seconds = max(0, total_seconds)
    if seconds < 60:
        return "только что"
    if seconds < 3_600:
        return f"{seconds // 60} мин назад"
    if seconds < 86_400:
        return f"{seconds // 3_600} ч назад"
    return f"{seconds // 86_400} дн назад"


def offset_zone(utc_offset_hours: int) -> tzinfo:
    return timezone(timedelta(hours=utc_offset_hours))


def offset_label(utc_offset_hours: int) -> str:
    return f"UTC{utc_offset_hours:+d}"


def format_local(moment: datetime, utc_offset_hours: int, pattern: str = "%d.%m · %H:%M") -> str:
    return moment.astimezone(offset_zone(utc_offset_hours)).strftime(pattern)
