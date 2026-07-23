from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Snapshot, Upgrade


_CATEGORY_TITLES = {"builder": "Постройки", "lab": "Lab", "pet": "Pet House", "helper": "Помощники"}


def _remaining(upgrade: Upgrade) -> str:
    if not upgrade.finish_at:
        return "время неизвестно"
    seconds = max(0, int((upgrade.finish_at - datetime.now(timezone.utc)).total_seconds()))
    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    minutes = seconds // 60
    parts = ([f"{days}д"] if days else []) + ([f"{hours}ч"] if hours or days else []) + [f"{minutes}м"]
    return " ".join(parts)


def _upgrade_line(upgrade: Upgrade) -> str:
    return f"• {escape(upgrade.entity)} — {escape(upgrade.level)} · <code>{_remaining(upgrade)}</code>"


def _village_block(name: str, upgrades: list[Upgrade]) -> str:
    if not upgrades:
        return f"<b>{escape(name)}</b>\nНет текущих улучшений."
    grouped: dict[str, list[Upgrade]] = defaultdict(list)
    for upgrade in upgrades:
        grouped[upgrade.category].append(upgrade)
    lines = [f"<b>{escape(name)}</b>"]
    for category in ("builder", "lab", "pet", "helper"):
        items = grouped.get(category)
        if not items:
            continue
        lines.append(f"<b>{_CATEGORY_TITLES[category]}</b>")
        lines.extend(_upgrade_line(item) for item in sorted(items, key=lambda item: item.finish_at or datetime.max.replace(tzinfo=timezone.utc)))
    return "\n".join(lines)


def render_dashboard(snapshot: Snapshot, view: str) -> tuple[str, InlineKeyboardMarkup]:
    villages = dict(snapshot.villages)
    selected_id = view.removeprefix("v:") if view.startswith("v:") else None
    by_village: dict[str, list[Upgrade]] = defaultdict(list)
    for upgrade in snapshot.upgrades:
        by_village[upgrade.village_id].append(upgrade)

    if selected_id and selected_id in villages:
        body = _village_block(villages[selected_id], by_village[selected_id])
        title = "<b>Текущие улучшения</b>"
    else:
        title = "<b>Текущие улучшения — все аккаунты</b>"
        body = "\n\n".join(_village_block(name, by_village[village_id]) for village_id, name in villages.items())
        view = "all"
    if not villages:
        body = "Данные ещё загружаются."

    updated = snapshot.fetched_at.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
    text = f"{title}\n<i>Обновление окна каждые 10 секунд · данные: {updated}</i>\n\n{body}"
    # Telegram allows at most 4096 characters. Preserve the keyboard even for large accounts.
    if len(text) > 4096:
        text = text[:4050] + "\n\n<i>Список сокращён: откройте отдельный аккаунт.</i>"

    buttons: list[list[InlineKeyboardButton]] = []
    if view != "all":
        buttons.append([InlineKeyboardButton(text="← Все аккаунты", callback_data="view:all")])
    else:
        for village_id, name in villages.items():
            buttons.append([InlineKeyboardButton(text=name[:50], callback_data=f"view:v:{village_id}")])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def render_notification(upgrade: Upgrade) -> str:
    entity = escape(upgrade.helper_name or upgrade.entity)
    village = escape(upgrade.village_name)
    if upgrade.is_helper:
        return f"🧑‍🔧 <b>{entity} освободился</b>\n{village}: улучшение {entity} ({escape(upgrade.level)}) завершено."
    return f"✅ <b>Улучшение завершено</b>\n{village}: {entity} ({escape(upgrade.level)})."
