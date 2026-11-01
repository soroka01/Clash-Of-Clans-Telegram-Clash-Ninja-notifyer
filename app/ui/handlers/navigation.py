from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.services.monitor import UpgradeMonitor
from app.ui import views
from app.ui.menu_service import MenuService, describe_actor
from app.ui.views import ViewState

logger = logging.getLogger(__name__)

REFRESH_COOLDOWN = 5.0  # seconds between forced source refreshes per chat
REFRESH_TIMEOUT = 15.0

# Buttons of menus that were sent by older versions of the bot keep their original callback data.
_LEGACY_MENU_ACTIONS = {"upgrades": views.ALL, "settings": views.SETTINGS, "main": views.MAIN}


class NavigationHandlers:
    """Commands and buttons that move between screens."""

    def __init__(self, menu: MenuService, monitor: UpgradeMonitor) -> None:
        self._menu = menu
        self._monitor = monitor
        self._last_refresh: dict[int, float] = {}

    def register(self, router: Router) -> None:
        router.message.register(self.on_start, Command("start", "menu"))
        router.message.register(self.on_status, Command("status"))
        router.message.register(self.on_accounts, Command("accounts"))
        router.message.register(self.on_help, Command("help"))
        router.callback_query.register(self.on_view, F.data.startswith("view:"))
        router.callback_query.register(self.on_legacy_menu, F.data.startswith("menu:"))
        router.callback_query.register(self.on_alert_menu, F.data == "alert:menu")
        router.callback_query.register(self.on_refresh, F.data == "act:refresh")
        router.callback_query.register(self.on_noop, F.data == "noop")

    # ----- commands ----------------------------------------------------------------

    async def on_start(self, message: Message) -> None:
        await self._send(message, ViewState(views.MAIN))

    async def on_status(self, message: Message) -> None:
        await self._send(message, ViewState(views.ALL))

    async def on_accounts(self, message: Message) -> None:
        await self._send(message, ViewState(views.ACCOUNTS))

    async def on_help(self, message: Message) -> None:
        await self._send(message, ViewState(views.HELP))

    async def _send(self, message: Message, view: ViewState) -> None:
        logger.info("Command received: %s chat=%s command=%r", describe_actor(message), message.chat.id, message.text)
        await self._menu.send(message.chat.id, view)

    # ----- buttons -----------------------------------------------------------------

    async def on_view(self, callback: CallbackQuery) -> None:
        view = ViewState.parse(callback.data.removeprefix("view:"))
        logger.debug("View callback: %s view=%s", describe_actor(callback), view.serialize())
        await callback.answer()
        await self._menu.open_from_callback(callback, view)

    async def on_legacy_menu(self, callback: CallbackQuery) -> None:
        kind = _LEGACY_MENU_ACTIONS.get(callback.data.removeprefix("menu:"))
        await callback.answer()
        if kind:
            await self._menu.open_from_callback(callback, ViewState(kind))

    async def on_alert_menu(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        await callback.answer()
        logger.info("Alert menu refresh requested: %s chat=%s", describe_actor(callback), callback.message.chat.id)
        await self._menu.replace_menus(callback.message.chat.id)

    async def on_refresh(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        chat_id, message_id = callback.message.chat.id, callback.message.message_id
        now = time.monotonic()
        if now - self._last_refresh.get(chat_id, 0.0) >= REFRESH_COOLDOWN:
            self._last_refresh[chat_id] = now
            await callback.answer("Обновляю данные…")
            await self._monitor.refresh_now(timeout=REFRESH_TIMEOUT)
        else:
            await callback.answer("Данные только что обновлены")
        await self._menu.open_from_callback(callback, await self._menu.current_view(chat_id, message_id))

    @staticmethod
    async def on_noop(callback: CallbackQuery) -> None:
        await callback.answer()
