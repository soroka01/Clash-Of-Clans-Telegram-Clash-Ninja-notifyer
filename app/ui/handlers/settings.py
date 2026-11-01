from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config.settings import Settings
from app.storage.preferences import MAX_UTC_OFFSET, MIN_UTC_OFFSET, ChatPreferences
from app.ui import views
from app.ui.menu_service import MenuService, describe_actor
from app.ui.views import ViewState

logger = logging.getLogger(__name__)


class SettingsHandlers:
    """Time zone and alert switch."""

    def __init__(self, menu: MenuService, preferences: ChatPreferences, settings: Settings) -> None:
        self._menu = menu
        self._preferences = preferences
        self._notification_chats = frozenset(settings.notification_chat_ids)

    def register(self, router: Router) -> None:
        router.callback_query.register(self.on_time_zone, F.data.startswith("tz:"))
        router.callback_query.register(self.on_notifications, F.data.startswith("act:notify:"))

    async def on_time_zone(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        try:
            offset = int(callback.data.removeprefix("tz:"))
            if not MIN_UTC_OFFSET <= offset <= MAX_UTC_OFFSET:
                raise ValueError
        except ValueError:
            await callback.answer("Некорректный часовой пояс", show_alert=True)
            return
        chat_id = callback.message.chat.id
        await self._preferences.set_utc_offset(chat_id, offset)
        logger.info("Timezone changed: %s chat=%s offset=UTC%+d", describe_actor(callback), chat_id, offset)
        await callback.answer(f"Установлен UTC{offset:+d}")
        await self._menu.open_from_callback(callback, ViewState(views.TIMEZONE))

    async def on_notifications(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        chat_id = callback.message.chat.id
        if chat_id not in self._notification_chats:
            await callback.answer("Этот чат не получает уведомления (notification_chat_ids)", show_alert=True)
            return
        enabled = callback.data.removeprefix("act:notify:") == "on"
        await self._preferences.set_notifications_enabled(chat_id, enabled)
        logger.info("Notifications %s: %s chat=%s", "enabled" if enabled else "muted", describe_actor(callback), chat_id)
        await callback.answer("Уведомления включены" if enabled else "Уведомления выключены")
        await self._menu.open_from_callback(callback, ViewState(views.SETTINGS))
