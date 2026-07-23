from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Snapshot, Upgrade


_CATEGORY_META = {
    "builder": ("🧱", "Постройки"),
    "lab": ("🔬", "Lab"),
    "pet": ("🐾", "Pet House"),
    "helper": ("🧑‍🔧", "Помощники"),
}
_TRACKER_URL = "https://www.clash.ninja/upgrade-tracker"


def _remaining(upgrade: Upgrade) -> str:
    if not upgrade.finish_at:
        return "время неизвестно"
    seconds = int((upgrade.finish_at - datetime.now(timezone.utc)).total_seconds())
    if seconds <= 0:
        return "готово"
    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    minutes = seconds // 60
    parts = ([f"{days}д"] if days else []) + ([f"{hours}ч"] if hours or days else []) + [f"{minutes}м"]
    return " ".join(parts)


def _upgrade_line(upgrade: Upgrade, prefix: str) -> str:
    return f"{prefix}◦ <b>{escape(upgrade.entity)}</b> <code>{escape(upgrade.level)}</code> · ⏳ <b>{_remaining(upgrade)}</b>"


def _village_block(village_id: str, name: str, upgrades: list[Upgrade]) -> str:
    village_url = f"{_TRACKER_URL}/{escape(village_id, quote=True)}/home"
    village_title = f'<a href="{village_url}">🏰 <b>{escape(name)}</b></a>'
    if not upgrades:
        return f"{village_title}\n└ ✨ <i>Нет текущих улучшений</i>"
    grouped: dict[str, list[Upgrade]] = defaultdict(list)
    for upgrade in upgrades:
        grouped[upgrade.category].append(upgrade)
    lines = [f"{village_title} <i>· {len(upgrades)} в работе</i>"]
    active_categories = [category for category in ("builder", "lab", "pet", "helper") if grouped.get(category)]
    for index, category in enumerate(active_categories):
        items = grouped[category]
        icon, title = _CATEGORY_META[category]
        is_last = index == len(active_categories) - 1
        lines.append(f"{'└' if is_last else '├'} {icon} <b>{title}</b> <i>({len(items)})</i>")
        prefix = "   " if is_last else "│  "
        lines.extend(_upgrade_line(item, prefix) for item in sorted(items, key=lambda item: item.finish_at or datetime.max.replace(tzinfo=timezone.utc)))
    return "\n".join(lines)


def render_dashboard(snapshot: Snapshot, view: str) -> tuple[str, InlineKeyboardMarkup]:
    villages = dict(snapshot.villages)
    selected_id = view.removeprefix("v:") if view.startswith("v:") else None
    by_village: dict[str, list[Upgrade]] = defaultdict(list)
    for upgrade in snapshot.upgrades:
        by_village[upgrade.village_id].append(upgrade)

    if selected_id and selected_id in villages:
        body = _village_block(selected_id, villages[selected_id], by_village[selected_id])
        title = f'⚔️ <a href="{_TRACKER_URL}"><b>Текущие улучшения</b></a>'
        subtitle = f"<i>Аккаунт: {escape(villages[selected_id])}</i>"
    else:
        title = f'⚔️ <a href="{_TRACKER_URL}"><b>Текущие улучшения</b></a>'
        subtitle = f"<i>Все аккаунты · {len(villages)}</i>"
        body = "\n\n".join(_village_block(village_id, name, by_village[village_id]) for village_id, name in villages.items())
        view = "all"
    if not villages:
        body = "Данные ещё загружаются."

    updated = snapshot.fetched_at.astimezone(timezone.utc).strftime("%H:%M:%S")
    text = f"{title}\n{subtitle}\n🕒 <code>{updated} UTC</code>\n\n{body}"
    # Telegram allows at most 4096 characters. Preserve the keyboard even for large accounts.
    if len(text) > 4096:
        text = text[:4050] + "\n\n<i>Список сокращён: откройте отдельный аккаунт.</i>"

    buttons: list[list[InlineKeyboardButton]] = []
    if view != "all":
        buttons.append([InlineKeyboardButton(text="← 📋 Все аккаунты", callback_data="view:all")])
    else:
        for village_id, name in villages.items():
            buttons.append([InlineKeyboardButton(text=f"🏰 {name}"[:50], callback_data=f"view:v:{village_id}")])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def render_notification(upgrade: Upgrade) -> str:
    entity = escape(upgrade.helper_name or upgrade.entity)
    village = escape(upgrade.village_name)
    if upgrade.is_helper:
        return (
            "🧑‍🔧 <b>Помощник свободен!</b>\n"
            f"🏰 <b>{village}</b>\n"
            f"└ {entity} <code>{escape(upgrade.level)}</code> завершил своё улучшение."
        )
    icon, title = _CATEGORY_META.get(upgrade.category, ("✅", "Улучшение"))
    return (
        "✅ <b>Улучшение завершено!</b>\n"
        f"🏰 <b>{village}</b>\n"
        f"└ {icon} <b>{entity}</b> <code>{escape(upgrade.level)}</code> · {title}"
    )
