from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.monitor import UpgradeMonitor
from app.presentation import render_dashboard, render_notification
from app.storage import Storage

logger = logging.getLogger(__name__)


def _actor_label(message: Message | CallbackQuery) -> str:
    user = message.from_user
    if not user:
        return "unknown-user"
    username = f"@{user.username}" if user.username else "without-username"
    return f"id={user.id} {username} name={user.full_name!r}"


class DashboardService:
    def __init__(self, bot: Bot, storage: Storage, monitor: UpgradeMonitor) -> None:
        self._bot = bot
        self._storage = storage
        self._monitor = monitor

    async def _payload(self, view: str) -> tuple[str, object]:
        return render_dashboard(await self._monitor.latest_snapshot(), view)

    async def send_dashboard(self, message: Message, view: str = "all") -> None:
        text, keyboard = await self._payload(view)
        sent = await message.answer(text, reply_markup=keyboard)
        await self._storage.upsert_dashboard(sent.chat.id, sent.message_id, view)
        logger.info("Dashboard sent: chat=%s message=%s view=%s", sent.chat.id, sent.message_id, view)

    async def edit_dashboard(self, chat_id: int, message_id: int, view: str) -> bool:
        text, keyboard = await self._payload(view)
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

    async def handle_callback(self, callback: CallbackQuery, view: str) -> None:
        if not callback.message:
            return
        chat_id = callback.message.chat.id
        message_id = callback.message.message_id
        state = await self._storage.get_dashboard(chat_id)
        # Edit only when the pressed menu is the most recent bot message. If a completion
        # notification appeared after it, create a fresh menu instead of modifying old context.
        can_edit = bool(
            state
            and state.message_id == message_id
            and state.latest_bot_kind == "dashboard"
            and state.latest_bot_message_id == message_id
        )
        if can_edit and await self.edit_dashboard(chat_id, message_id, view):
            logger.info("Menu click edited dashboard: %s view=%s", _actor_label(callback), view)
            return
        logger.info("Menu click created a new dashboard: %s view=%s", _actor_label(callback), view)
        await self.send_dashboard(callback.message, view)

    async def refresh_open_dashboards(self) -> None:
        for state in await self._storage.dashboards():
            ok = await self.edit_dashboard(state.chat_id, state.message_id, state.view)
            if not ok:
                await self._storage.remove_dashboard(state.chat_id)


class NotificationService:
    def __init__(self, bot: Bot, storage: Storage, chat_ids: tuple[int, ...]) -> None:
        self._bot = bot
        self._storage = storage
        self._chat_ids = chat_ids

    async def send(self, upgrade) -> None:  # Upgrade type kept import-free for a narrow delivery layer.
        for chat_id in self._chat_ids:
            try:
                message = await self._bot.send_message(chat_id, render_notification(upgrade))
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
        await dashboard.send_dashboard(message)

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

    return router


async def dashboard_refresh_loop(service: DashboardService, interval_seconds: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            with suppress(Exception):
                await service.refresh_open_dashboards()
