from __future__ import annotations


def format_duration(total_seconds: int) -> str:
    """Format seconds as a compact '3д 4ч 5м' string (minutes are always shown)."""
    days, remainder = divmod(max(0, total_seconds), 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes = remainder // 60
    parts = ([f"{days}д"] if days else []) + ([f"{hours}ч"] if hours or days else []) + [f"{minutes}м"]
    return " ".join(parts)
