from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
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


def _utc_zone(utc_offset_hours: int) -> timezone:
    return timezone(timedelta(hours=utc_offset_hours))


def _utc_label(utc_offset_hours: int) -> str:
    return f"UTC{utc_offset_hours:+d}"


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


def _upgrade_line(upgrade: Upgrade, prefix: str, utc_offset_hours: int) -> str:
    finished_at = upgrade.finish_at.astimezone(_utc_zone(utc_offset_hours)).strftime("%d.%m · %H:%M")
    return (
        f"{prefix}◦ <b>{escape(upgrade.entity)}</b> <code>{escape(upgrade.level)}</code>\n"
        f"{prefix}  ⏳ <b>{_remaining(upgrade)}</b> · 🏁 <code>{finished_at}</code>"
    )


def _village_block(village_id: str, name: str, upgrades: list[Upgrade], utc_offset_hours: int) -> str:
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
        lines.extend(
            _upgrade_line(item, prefix, utc_offset_hours)
            for item in sorted(items, key=lambda item: item.finish_at or datetime.max.replace(tzinfo=timezone.utc))
        )
    return "\n".join(lines)


def render_dashboard(snapshot: Snapshot, view: str, utc_offset_hours: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    villages = dict(snapshot.villages)
    selected_id = view.removeprefix("v:") if view.startswith("v:") else None
    by_village: dict[str, list[Upgrade]] = defaultdict(list)
    for upgrade in snapshot.upgrades:
        by_village[upgrade.village_id].append(upgrade)

    if selected_id and selected_id in villages:
        body = _village_block(selected_id, villages[selected_id], by_village[selected_id], utc_offset_hours)
        title = f'⚔️ <a href="{_TRACKER_URL}"><b>Текущие улучшения</b></a>'
        subtitle = f"<i>Аккаунт: {escape(villages[selected_id])}</i>"
    else:
        title = f'⚔️ <a href="{_TRACKER_URL}"><b>Текущие улучшения</b></a>'
        subtitle = f"<i>Все аккаунты · {len(villages)}</i>"
        body = "\n\n".join(
            _village_block(village_id, name, by_village[village_id], utc_offset_hours)
            for village_id, name in villages.items()
        )
        view = "all"
    if not villages:
        body = "Данные ещё загружаются."

    updated = snapshot.fetched_at.astimezone(_utc_zone(utc_offset_hours)).strftime("%H:%M:%S")
    text = f"{title}\n{subtitle}\n🕒 <code>{updated} {_utc_label(utc_offset_hours)}</code>\n\n{body}"
    # Telegram allows at most 4096 characters. Preserve the keyboard even for large accounts.
    if len(text) > 4096:
        text = text[:4050] + "\n\n<i>Список сокращён: откройте отдельный аккаунт.</i>"

    buttons: list[list[InlineKeyboardButton]] = []
    if view != "all":
        buttons.append([InlineKeyboardButton(text="← 📋 Все аккаунты", callback_data="view:all")])
    else:
        for village_id, name in villages.items():
            buttons.append([InlineKeyboardButton(text=f"🏰 {name}"[:50], callback_data=f"view:v:{village_id}")])
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def render_main_menu() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "⚔️ <b>Clash Ninja Notifier</b>\n"
        "<i>Улучшения, таймеры и уведомления ваших аккаунтов Clash of Clans.</i>\n\n"
        "Выберите действие ниже."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Текущие улучшения", callback_data="menu:upgrades")],
            [InlineKeyboardButton(text="🔗 Открыть Clash Ninja", url=_TRACKER_URL)],
        ]
    )
    return text, keyboard


def render_notification(upgrade: Upgrade, utc_offset_hours: int = 0) -> str:
    entity = escape(upgrade.helper_name or upgrade.entity)
    village = escape(upgrade.village_name)
    finished_at = upgrade.finish_at.astimezone(_utc_zone(utc_offset_hours)).strftime("%d.%m.%Y · %H:%M") if upgrade.finish_at else "—"
    timing = f"\n🕒 <code>{finished_at} {_utc_label(utc_offset_hours)}</code>"
    if upgrade.is_helper:
        return (
            "🧑‍🔧 <b>Помощник свободен!</b>\n"
            f"🏰 <b>{village}</b>\n"
            f"└ {entity} <code>{escape(upgrade.level)}</code> завершил своё улучшение.{timing}"
        )
    icon, title = _CATEGORY_META.get(upgrade.category, ("✅", "Улучшение"))
    return (
        "✅ <b>Улучшение завершено!</b>\n"
        f"🏰 <b>{village}</b>\n"
        f"└ {icon} <b>{entity}</b> <code>{escape(upgrade.level)}</code> · {title}{timing}"
    )
