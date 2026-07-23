from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import HelperStatus, Snapshot, Upgrade


_CATEGORY_META = {
    "builder": ("🧱", "Постройки"),
    "lab": ("🔬", "Lab"),
    "pet": ("🐾", "Pet House"),
    "helper": ("🧑‍🔧", "Помощники"),
}
_TRACKER_URL = "https://www.clash.ninja/upgrade-tracker"
# iOS deep link: opens Clash of Clans itself, without navigating to a settings screen.
_OPEN_GAME_URL = "clashofclans://"


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
        f"{prefix}  ⏳ <b>{_remaining(upgrade)}</b> · 🏁 {finished_at}"
    )


def _village_block(village_id: str, name: str, upgrades: list[Upgrade], utc_offset_hours: int) -> str:
    village_url = f"{_TRACKER_URL}/{escape(village_id, quote=True)}/home"
    village_title = f'🏰 <b>{escape(name)}</b>'
    village_link = f'<a href="{village_url}">🔗 Открыть</a>'
    if not upgrades:
        return f"{village_title} · {village_link}\n└ ✨ <i>Нет текущих улучшений</i>"
    grouped: dict[str, list[Upgrade]] = defaultdict(list)
    for upgrade in upgrades:
        grouped[upgrade.category].append(upgrade)
    lines = [f"{village_title} <i>· {len(upgrades)} в работе</i> · {village_link}"]
    active_categories = [category for category in ("builder", "lab", "pet", "helper") if grouped.get(category)]
    for category in active_categories:
        items = grouped[category]
        icon, title = _CATEGORY_META[category]
        lines.append(f"{icon} <b>{title}</b> <i>({len(items)})</i>")
        prefix = "  "
        lines.extend(
            _upgrade_line(item, prefix, utc_offset_hours)
            for item in sorted(items, key=lambda item: item.finish_at or datetime.max.replace(tzinfo=timezone.utc))
        )
    return "\n".join(lines)


def _helpers_line(helpers: list[HelperStatus], utc_offset_hours: int) -> str:
    if not helpers:
        return ""
    statuses: list[str] = []
    for helper in helpers:
        if helper.state == "available":
            statuses.append(f"🟢 <b>{escape(helper.helper_name)}</b>")
        elif helper.state == "assigned":
            statuses.append(f"🟠 <b>{escape(helper.helper_name)}</b> → {escape(helper.target or 'улучшение')}")
        else:
            until = helper.until.astimezone(_utc_zone(utc_offset_hours)).strftime("%d.%m %H:%M") if helper.until else "—"
            statuses.append(f"🟡 <b>{escape(helper.helper_name)}</b> · КД до {until}")
    return "🤖 " + " · ".join(statuses)


def render_dashboard(snapshot: Snapshot, view: str, utc_offset_hours: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    villages = dict(snapshot.villages)
    selected_id = view.removeprefix("v:") if view.startswith("v:") else None
    by_village: dict[str, list[Upgrade]] = defaultdict(list)
    helpers_by_village: dict[str, list[HelperStatus]] = defaultdict(list)
    for upgrade in snapshot.upgrades:
        by_village[upgrade.village_id].append(upgrade)
    for helper in snapshot.helpers:
        helpers_by_village[helper.village_id].append(helper)

    if selected_id and selected_id in villages:
        body = _village_block(selected_id, villages[selected_id], by_village[selected_id], utc_offset_hours)
        helper_line = _helpers_line(helpers_by_village[selected_id], utc_offset_hours)
        if helper_line:
            body = f"{body}\n{helper_line}"
        title = "⚔️ <b>Текущие улучшения</b>"
        subtitle = f"<i>Аккаунт: {escape(villages[selected_id])}</i>"
    else:
        title = "⚔️ <b>Текущие улучшения</b>"
        subtitle = f"<i>Все аккаунты · {len(villages)}</i>"
        blocks: list[str] = []
        for village_id, name in villages.items():
            block = _village_block(village_id, name, by_village[village_id], utc_offset_hours)
            helper_line = _helpers_line(helpers_by_village[village_id], utc_offset_hours)
            blocks.append(f"{block}\n{helper_line}" if helper_line else block)
        body = "\n\n".join(blocks)
        view = "all"
    if not villages:
        body = "Данные ещё загружаются."

    updated = snapshot.fetched_at.astimezone(_utc_zone(utc_offset_hours)).strftime("%H:%M:%S")
    tracker_link = f'<a href="{_TRACKER_URL}">🌐 Открыть Clash Ninja Upgrade Tracker</a>'
    text = f"{title}\n{tracker_link}\n{subtitle}\n🕒 <code>{updated} {_utc_label(utc_offset_hours)}</code>\n\n{body}"
    # Telegram allows at most 4096 characters. Preserve the keyboard even for large accounts.
    if len(text) > 4096:
        text = text[:4050] + "\n\n<i>Список сокращён: откройте отдельный аккаунт.</i>"

    buttons: list[list[InlineKeyboardButton]] = []
    if view != "all":
        buttons.append([InlineKeyboardButton(text="← 📋 Все аккаунты", callback_data="view:all")])
    else:
        for village_id, name in villages.items():
            buttons.append([InlineKeyboardButton(text=f"🏰 {name}"[:50], callback_data=f"view:v:{village_id}")])
    buttons.append([InlineKeyboardButton(text="🎮 Открыть Clash of Clans", url=_OPEN_GAME_URL)])
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
            [InlineKeyboardButton(text="⚙️ Настройки времени", callback_data="menu:settings")],
            [InlineKeyboardButton(text="🎮 Открыть Clash of Clans", url=_OPEN_GAME_URL)],
            [InlineKeyboardButton(text="🔗 Открыть Clash Ninja", url=_TRACKER_URL)],
        ]
    )
    return text, keyboard


def render_time_settings(utc_offset_hours: int) -> tuple[str, InlineKeyboardMarkup]:
    label = _utc_label(utc_offset_hours)
    text = (
        "⚙️ <b>Настройки времени</b>\n"
        f"Текущий часовой пояс: <b>{label}</b>\n\n"
        "Выберите смещение от UTC. В этом поясе отображаются дата и время завершения улучшений."
    )
    buttons: list[list[InlineKeyboardButton]] = []
    offsets = list(range(-12, 15))
    for start in range(0, len(offsets), 3):
        row: list[InlineKeyboardButton] = []
        for offset in offsets[start : start + 3]:
            prefix = "✅ " if offset == utc_offset_hours else ""
            row.append(InlineKeyboardButton(text=f"{prefix}{_utc_label(offset)}", callback_data=f"tz:{offset}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


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


def render_helper_available_notification(helper: HelperStatus, utc_offset_hours: int = 0) -> str:
    now = datetime.now(_utc_zone(utc_offset_hours)).strftime("%d.%m.%Y · %H:%M")
    return (
        "🟢 <b>Помощник свободен!</b>\n"
        f"🏰 <b>{escape(helper.village_name)}</b>\n"
        f"└ <b>{escape(helper.helper_name)}</b> больше не прикреплён к улучшению.\n"
        f"🕒 <code>{now} {_utc_label(utc_offset_hours)}</code>"
    )
