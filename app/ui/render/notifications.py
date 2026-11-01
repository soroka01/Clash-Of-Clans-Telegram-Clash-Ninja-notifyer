from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from aiogram.types import InlineKeyboardMarkup

from app.domain.events import DomainEvent, HelperReleased, SourceDown, SourceRecovered, UpgradeCompleted
from app.domain.models import HelperStatus
from app.domain.timefmt import format_duration, format_local, offset_label
from app.ui.render.common import CATEGORY_META, HELPER_ICONS, DEFAULT_HELPER_ICON, button, markup, rows

_FULL_DATE = "%d.%m.%Y · %H:%M"


class NotificationRenderer:
    """Texts of the messages the bot sends on its own."""

    def __init__(self, clash_ninja_mode: bool) -> None:
        self._clash_ninja_mode = clash_ninja_mode

    def render(self, event: DomainEvent, utc_offset: int) -> str:
        if isinstance(event, UpgradeCompleted):
            return self._completed(event, utc_offset)
        if isinstance(event, HelperReleased):
            return self._helper_released(event.helper, utc_offset)
        if isinstance(event, SourceDown):
            return self._source_down(event, utc_offset)
        if isinstance(event, SourceRecovered):
            return self._source_recovered(event)
        raise TypeError(f"Unsupported event: {type(event).__name__}")

    @staticmethod
    def keyboard() -> InlineKeyboardMarkup:
        return markup(rows(button("📋 Обновить меню", "alert:menu")))

    # ----- upgrades ----------------------------------------------------------------

    def _completed(self, event: UpgradeCompleted, utc_offset: int) -> str:
        upgrade = event.upgrade
        village = escape(upgrade.village_name)
        finished_at = (
            format_local(upgrade.finish_at, utc_offset, _FULL_DATE) if upgrade.finish_at else "—"
        )
        timing = f"\n🕒 <code>{finished_at} {offset_label(utc_offset)}</code>"
        if upgrade.is_helper:
            entity = escape(upgrade.helper_name or upgrade.entity)
            return (
                "🧑‍🔧 <b>Помощник свободен!</b>\n"
                f"🏰 <b>{village}</b>\n"
                f"└ {entity} <code>{escape(upgrade.level)}</code> завершил своё улучшение.{timing}"
            )
        icon, title = CATEGORY_META.get(upgrade.category, ("✅", "Улучшение"))
        text = (
            "✅ <b>Улучшение завершено!</b>\n"
            f"🏰 <b>{village}</b>\n"
            f"└ {icon} <b>{escape(upgrade.entity)}</b> <code>{escape(upgrade.level)}</code> · {title}{timing}"
        )
        for helper in event.freed_helpers:
            text += f"\n🟢 <b>{escape(helper.helper_name)}</b> свободен"
        return text

    def _helper_released(self, helper: HelperStatus, utc_offset: int) -> str:
        now = format_local(datetime.now(timezone.utc), utc_offset, _FULL_DATE)
        icon = HELPER_ICONS.get(helper.helper_name, DEFAULT_HELPER_ICON)
        return (
            "🟢 <b>Помощник свободен!</b>\n"
            f"🏰 <b>{escape(helper.village_name)}</b>\n"
            f"└ {icon} <b>{escape(helper.helper_name)}</b> больше не прикреплён к улучшению.\n"
            f"🕒 <code>{now} {offset_label(utc_offset)}</code>"
        )

    # ----- data source -------------------------------------------------------------

    def _source_down(self, event: SourceDown, utc_offset: int) -> str:
        since = format_local(event.since, utc_offset, _FULL_DATE)
        hint = (
            "Скорее всего, истекла сессия Clash Ninja: войдите на сайт в браузере и перезапустите бота "
            "(или обновите <code>cookie_header</code> в config.json)."
            if self._clash_ninja_mode
            else "Проверьте папку с JSON-аккаунтами и <code>logs/error.log</code>."
        )
        return (
            "⚠️ <b>Бот не получает свежие данные</b>\n"
            f"Неудачных попыток подряд: {event.failures} (с {since} {offset_label(utc_offset)}).\n"
            f"<i>{escape(event.reason)}</i>\n\n"
            f"{hint}\n"
            "Бот продолжит попытки и сообщит, когда всё заработает."
        )

    @staticmethod
    def _source_recovered(event: SourceRecovered) -> str:
        downtime = int((datetime.now(timezone.utc) - event.down_since).total_seconds())
        return f"✅ <b>Данные снова обновляются</b>\nПерерыв: {format_duration(downtime)}."
