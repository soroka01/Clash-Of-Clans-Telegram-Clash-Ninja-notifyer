from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.monitor import UpgradeMonitor
from app.presentation import render_dashboard, render_main_menu, render_notification, render_time_settings
from app.storage import Storage

logger = logging.getLogger(__name__)


def _actor_label(message: Message | CallbackQuery) -> str:
    user = message.from_user
    if not user:
        return "unknown-user"
    username = f"@{user.username}" if user.username else "without-username"
    return f"id={user.id} {username} name={user.full_name!r}"


class DashboardService:
    def __init__(self, bot: Bot, storage: Storage, monitor: UpgradeMonitor, utc_offset_hours: int) -> None:
        self._bot = bot
        self._storage = storage
        self._monitor = monitor
        self._utc_offset_hours = utc_offset_hours

    async def _payload(self, chat_id: int, view: str) -> tuple[str, object]:
        offset = await self._storage.get_utc_offset(chat_id, self._utc_offset_hours)
        return render_dashboard(await self._monitor.latest_snapshot(), view, offset)

    async def send_dashboard(self, message: Message, view: str = "all") -> None:
        text, keyboard = await self._payload(message.chat.id, view)
        sent = await message.answer(text, reply_markup=keyboard)
        await self._storage.upsert_dashboard(sent.chat.id, sent.message_id, view)
        logger.info("Dashboard sent: chat=%s message=%s view=%s", sent.chat.id, sent.message_id, view)

    async def send_main_menu(self, message: Message) -> None:
        text, keyboard = render_main_menu()
        sent = await message.answer(text, reply_markup=keyboard)
        await self._storage.upsert_dashboard(sent.chat.id, sent.message_id, "main")
        logger.info("Main menu sent: chat=%s message=%s", sent.chat.id, sent.message_id)

    async def edit_dashboard(self, chat_id: int, message_id: int, view: str) -> bool:
        text, keyboard = await self._payload(chat_id, view)
        try:
            await self._bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
            )
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).lower():
                logger.warning("Could not edit dashboard %s/%s: %s", chat_id, message_id, error)
                return False
        except TelegramForbiddenError:
            return False
        await self._storage.update_dashboard_view(chat_id, view)
        logger.debug("Dashboard edited: chat=%s message=%s view=%s", chat_id, message_id, view)
        return True

    async def edit_main_menu(self, chat_id: int, message_id: int) -> bool:
        text, keyboard = render_main_menu()
        try:
            await self._bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).lower():
                logger.warning("Could not edit main menu %s/%s: %s", chat_id, message_id, error)
                return False
        except TelegramForbiddenError:
            return False
        await self._storage.update_dashboard_view(chat_id, "main")
        logger.debug("Main menu edited: chat=%s message=%s", chat_id, message_id)
        return True

    async def send_time_settings(self, message: Message) -> None:
        offset = await self._storage.get_utc_offset(message.chat.id, self._utc_offset_hours)
        text, keyboard = render_time_settings(offset)
        sent = await message.answer(text, reply_markup=keyboard)
        await self._storage.upsert_dashboard(sent.chat.id, sent.message_id, "settings")
        logger.info("Time settings sent: chat=%s offset=%s", sent.chat.id, offset)

    async def edit_time_settings(self, chat_id: int, message_id: int) -> bool:
        offset = await self._storage.get_utc_offset(chat_id, self._utc_offset_hours)
        text, keyboard = render_time_settings(offset)
        try:
            await self._bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).lower():
                logger.warning("Could not edit time settings %s/%s: %s", chat_id, message_id, error)
                return False
        except TelegramForbiddenError:
            return False
        await self._storage.update_dashboard_view(chat_id, "settings")
        return True

    @staticmethod
    def _can_edit(state, message_id: int) -> bool:
        return bool(
            state
            and state.message_id == message_id
            and state.latest_bot_kind == "dashboard"
            and state.latest_bot_message_id == message_id
        )

    async def handle_callback(self, callback: CallbackQuery, view: str) -> None:
        if not callback.message:
            return
        chat_id = callback.message.chat.id
        message_id = callback.message.message_id
        state = await self._storage.get_dashboard(chat_id)
        # Edit only when the pressed menu is the most recent bot message. If a completion
        # notification appeared after it, create a fresh menu instead of modifying old context.
        can_edit = self._can_edit(state, message_id)
        if can_edit and await self.edit_dashboard(chat_id, message_id, view):
            logger.info("Menu click edited dashboard: %s view=%s", _actor_label(callback), view)
            return
        logger.info("Menu click created a new dashboard: %s view=%s", _actor_label(callback), view)
        await self.send_dashboard(callback.message, view)

    async def handle_main_menu(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        state = await self._storage.get_dashboard(callback.message.chat.id)
        message_id = callback.message.message_id
        if self._can_edit(state, message_id) and await self.edit_main_menu(callback.message.chat.id, message_id):
            logger.info("Menu click returned to main menu: %s", _actor_label(callback))
            return
        logger.info("Menu click created a new main menu: %s", _actor_label(callback))
        await self.send_main_menu(callback.message)

    async def handle_time_settings(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        state = await self._storage.get_dashboard(callback.message.chat.id)
        message_id = callback.message.message_id
        if self._can_edit(state, message_id) and await self.edit_time_settings(callback.message.chat.id, message_id):
            logger.info("Menu click opened time settings: %s", _actor_label(callback))
            return
        logger.info("Menu click created time settings: %s", _actor_label(callback))
        await self.send_time_settings(callback.message)

    async def set_time_zone(self, callback: CallbackQuery, utc_offset_hours: int) -> None:
        if not callback.message:
            return
        chat_id = callback.message.chat.id
        await self._storage.set_utc_offset(chat_id, utc_offset_hours)
        logger.info("Timezone changed: %s chat=%s offset=UTC%+d", _actor_label(callback), chat_id, utc_offset_hours)
        state = await self._storage.get_dashboard(chat_id)
        if self._can_edit(state, callback.message.message_id) and await self.edit_time_settings(chat_id, callback.message.message_id):
            return
        await self.send_time_settings(callback.message)

    async def refresh_open_dashboards(self) -> None:
        for state in await self._storage.dashboards():
            if state.view in {"main", "settings"}:
                continue
            ok = await self.edit_dashboard(state.chat_id, state.message_id, state.view)
            if not ok:
                await self._storage.remove_dashboard(state.chat_id)


class NotificationService:
    def __init__(self, bot: Bot, storage: Storage, chat_ids: tuple[int, ...], utc_offset_hours: int) -> None:
        self._bot = bot
        self._storage = storage
        self._chat_ids = chat_ids
        self._default_utc_offset_hours = utc_offset_hours

    async def send(self, upgrade) -> None:  # Upgrade type kept import-free for a narrow delivery layer.
        for chat_id in self._chat_ids:
            try:
                offset = await self._storage.get_utc_offset(chat_id, self._default_utc_offset_hours)
                message = await self._bot.send_message(chat_id, render_notification(upgrade, offset))
                await self._storage.mark_notification(chat_id, message.message_id)
                logger.info("Notification sent: chat=%s message=%s entity=%s", chat_id, message.message_id, upgrade.entity)
            except TelegramForbiddenError:
                logger.warning("Bot is blocked in notification chat %s", chat_id)
            except TelegramBadRequest:
                logger.exception("Could not send notification to %s", chat_id)


def make_router(dashboard: DashboardService, authorized_user_ids: frozenset[int]) -> Router:
    router = Router()

    def allowed(message: Message | CallbackQuery) -> bool:
        user = message.from_user
        return bool(user and (not authorized_user_ids or user.id in authorized_user_ids))

    @router.message(Command("start", "menu", "status"))
    async def command_menu(message: Message) -> None:
        if not allowed(message):
            logger.warning("Unauthorized command ignored: %s chat=%s", _actor_label(message), message.chat.id)
            return
        logger.info("Menu command received: %s chat=%s command=%r", _actor_label(message), message.chat.id, message.text)
        if message.text and message.text.startswith("/status"):
            await dashboard.send_dashboard(message)
        else:
            await dashboard.send_main_menu(message)

    @router.callback_query(lambda query: query.data and query.data.startswith("view:"))
    async def choose_view(callback: CallbackQuery) -> None:
        if not allowed(callback):
            logger.warning("Unauthorized callback ignored: %s chat=%s data=%s", _actor_label(callback), callback.message.chat.id if callback.message else "?", callback.data)
            await callback.answer("Нет доступа", show_alert=True)
            return
        view = callback.data.removeprefix("view:")
        logger.info("Menu callback received: %s view=%s", _actor_label(callback), view)
        await callback.answer()
        await dashboard.handle_callback(callback, view)

    @router.callback_query(lambda query: query.data and query.data.startswith("menu:"))
    async def choose_menu(callback: CallbackQuery) -> None:
        if not allowed(callback):
            logger.warning("Unauthorized menu callback ignored: %s", _actor_label(callback))
            await callback.answer("Нет доступа", show_alert=True)
            return
        action = callback.data.removeprefix("menu:")
        logger.info("Main menu callback received: %s action=%s", _actor_label(callback), action)
        await callback.answer()
        if action == "upgrades":
            await dashboard.handle_callback(callback, "all")
        elif action == "settings":
            await dashboard.handle_time_settings(callback)
        elif action == "main":
            await dashboard.handle_main_menu(callback)

    @router.callback_query(lambda query: query.data and query.data.startswith("tz:"))
    async def choose_time_zone(callback: CallbackQuery) -> None:
        if not allowed(callback):
            logger.warning("Unauthorized timezone callback ignored: %s", _actor_label(callback))
            await callback.answer("Нет доступа", show_alert=True)
            return
        try:
            offset = int(callback.data.removeprefix("tz:"))
            if not -12 <= offset <= 14:
                raise ValueError
        except ValueError:
            await callback.answer("Некорректный часовой пояс", show_alert=True)
            return
        await callback.answer(f"Установлен UTC{offset:+d}")
        await dashboard.set_time_zone(callback, offset)

    return router


async def dashboard_refresh_loop(service: DashboardService, interval_seconds: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            with suppress(Exception):
                await service.refresh_open_dashboards()
