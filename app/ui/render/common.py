from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain.models import Category, Snapshot, Upgrade
from app.domain.timefmt import format_duration, format_local
from app.services.health import HealthNotice

TRACKER_URL = "https://www.clash.ninja/upgrade-tracker"
OPEN_GAME_URL = "https://link.clashofclans.com/en/"
REPOSITORY_URL = "https://github.com/soroka01/Clash-Of-Clans-Telegram-Clash-Ninja-notifyer"

CATEGORY_META = {
    Category.BUILDER: ("🧱", "Постройки"),
    Category.LAB: ("🔬", "Lab"),
    Category.PET: ("🐾", "Pet House"),
    Category.HELPER: ("🧑‍🔧", "Помощники"),
}
CATEGORY_ORDER = (Category.BUILDER, Category.LAB, Category.PET, Category.HELPER)
HELPER_ICONS = {
    "Lab Assistant": "🧑‍🔬",
    "Builder's Apprentice": "👷",
    "Alchemist": "⚗️",
}
DEFAULT_HELPER_ICON = "🤖"

CALLBACK_LIMIT = 64  # bytes, imposed by Telegram
STALE_AFTER = timedelta(hours=24)  # an export older than this is flagged as outdated


def utf16_len(text: str) -> int:
    """Telegram measures message length in UTF-16 code units (an emoji is usually two)."""
    return len(text.encode("utf-16-le")) // 2


@dataclass(frozen=True, slots=True)
class Screen:
    """A ready-to-send message body."""

    text: str
    markup: InlineKeyboardMarkup | None = None

    @property
    def fingerprint(self) -> int:
        return hash((self.text, self.markup.model_dump_json() if self.markup else ""))


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Everything a renderer needs; built once per render by the ScreenFactory."""

    snapshot: Snapshot
    now: datetime
    utc_offset: int
    notifications_enabled: bool
    health: HealthNotice | None
    link_tracker: bool  # Clash Ninja mode: villages link to the tracker
    import_available: bool
    manage_accounts: bool  # JSON mode: accounts can be uploaded, renamed, removed


def button(text: str, data: str | None = None, url: str | None = None) -> InlineKeyboardButton | None:
    """A button, or None when the callback payload would exceed Telegram's 64-byte limit."""
    if data is not None and len(data.encode("utf-8")) > CALLBACK_LIMIT:
        return None
    return InlineKeyboardButton(text=text[:60], callback_data=data, url=url)


def rows(*buttons: InlineKeyboardButton | None, per_row: int = 1) -> list[list[InlineKeyboardButton]]:
    present = [item for item in buttons if item is not None]
    return [present[start : start + per_row] for start in range(0, len(present), per_row)]


def markup(*groups: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for group in groups for row in group])


def remaining_text(upgrade: Upgrade, now: datetime) -> str:
    seconds = upgrade.seconds_left(now)
    if seconds is None:
        return "время неизвестно"
    if seconds <= 0:
        return "готово ✅"
    return format_duration(seconds)


def finish_text(upgrade: Upgrade, utc_offset: int, pattern: str = "%d.%m · %H:%M") -> str:
    return format_local(upgrade.finish_at, utc_offset, pattern) if upgrade.finish_at else "—"


def format_size(size: int) -> str:
    return f"{size / 1024:.1f} КБ" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} МБ"


def describe_nearest(ctx: RenderContext, village_id: str) -> str | None:
    """"Entity level — time left (finish time)" of the account's nearest upgrade, ready for HTML."""
    timed = [item for item in ctx.snapshot.upgrades_of(village_id) if item.finish_at]
    if not timed:
        return None
    nearest = min(timed, key=lambda item: item.sort_key)
    return (
        f"{escape(nearest.entity)} {escape(nearest.level)} — {remaining_text(nearest, ctx.now)} "
        f"(🏁 {finish_text(nearest, ctx.utc_offset)})"
    )


def paginate(items: list[str], separator: str, budget: int) -> list[str]:
    """Pack ``items`` into pages no longer than ``budget`` UTF-16 units, never splitting an item
    unless a single one is larger than a page (then it is cut at line breaks)."""
    pages: list[str] = []
    current: list[str] = []
    size = 0
    separator_size = utf16_len(separator)

    def flush() -> None:
        nonlocal current, size
        if current:
            pages.append(separator.join(current))
            current, size = [], 0

    for item in items:
        for piece in _split_oversized(item, budget):
            piece_size = utf16_len(piece)
            extra = separator_size if current else 0
            if size + extra + piece_size > budget:
                flush()
                extra = 0
            current.append(piece)
            size += extra + piece_size
    flush()
    return pages or [""]


def _split_oversized(item: str, budget: int) -> list[str]:
    if utf16_len(item) <= budget:
        return [item]
    pieces: list[str] = []
    buffer: list[str] = []
    size = 0
    for line in item.split("\n"):
        line_size = utf16_len(line) + 1
        if buffer and size + line_size > budget:
            pieces.append("\n".join(buffer))
            buffer, size = [], 0
        buffer.append(line[:budget])
        size += line_size
    if buffer:
        pieces.append("\n".join(buffer))
    return pieces
