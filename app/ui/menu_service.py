from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from aiogram.types import CallbackQuery

from app.storage.menus import AlertRepository, MenuRepository, MenuState
from app.ui import views
from app.ui.gateway import Edit, TelegramGateway, TelegramUnavailable
from app.ui.screens import ScreenFactory
from app.ui.views import ViewState

logger = logging.getLogger(__name__)


def describe_actor(event: object) -> str:
    user = getattr(event, "from_user", None)
    if not user:
        return "unknown-user"
    username = f"@{user.username}" if user.username else "without-username"
    return f"id={user.id} {username} name={user.full_name!r}"


class MenuService:
    """Owns the one live menu message per chat: sends, edits, refreshes and restores it.

    Everything that changes a chat's menu goes through a per-chat lock, so a button press and the
    background refresh can never edit the same message at the same time.
    """

    def __init__(
        self,
        gateway: TelegramGateway,
        screens: ScreenFactory,
        menus: MenuRepository,
        alerts: AlertRepository,
        startup_chat_ids: tuple[int, ...],
    ) -> None:
        self._gateway = gateway
        self._screens = screens
        self._menus = menus
        self._alerts = alerts
        self._startup_chat_ids = startup_chat_ids
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._shown: dict[int, tuple[int, int]] = {}  # chat -> (message id, fingerprint of what it shows)

    # ----- sending and editing -----------------------------------------------------

    async def send(self, chat_id: int, view: ViewState) -> bool:
        async with self._locks[chat_id]:
            return await self._send(chat_id, view)

    async def _send(self, chat_id: int, view: ViewState) -> bool:
        await self._clear_alert_buttons(chat_id)
        screen = await self._screens.build(chat_id, view)
        try:
            message_id = await self._gateway.send(chat_id, screen.text, screen.markup)
        except TelegramUnavailable as error:
            logger.warning("Could not send the %s screen to chat %s: %s", view.kind, chat_id, error)
            return False
        if message_id is None:
            return False
        await self._menus.upsert(chat_id, message_id, view.serialize())
        self._shown[chat_id] = (message_id, screen.fingerprint)
        logger.info("Menu sent: chat=%s message=%s view=%s", chat_id, message_id, view.serialize())
        return True

    async def edit(self, chat_id: int, message_id: int, view: ViewState) -> Edit:
        async with self._locks[chat_id]:
            return await self._edit(chat_id, message_id, view)

    async def _edit(self, chat_id: int, message_id: int, view: ViewState, *, skip_if_same: bool = False) -> Edit:
        screen = await self._screens.build(chat_id, view)
        if skip_if_same and self._shown.get(chat_id) == (message_id, screen.fingerprint):
            return Edit.UNCHANGED
        result = await self._gateway.edit(chat_id, message_id, screen.text, screen.markup)
        if result.shown:
            await self._menus.update_view(chat_id, view.serialize())
            await self._menus.remember_message(chat_id, message_id)
            self._shown[chat_id] = (message_id, screen.fingerprint)
            logger.debug("Menu edited: chat=%s message=%s view=%s", chat_id, message_id, view.serialize())
        return result

    async def _clear_alert_buttons(self, chat_id: int) -> None:
        """Remove the obsolete "refresh menu" button from every tracked alert in a chat."""
        for message_id in await self._alerts.message_ids(chat_id):
            await self._gateway.clear_markup(chat_id, message_id)
            await self._alerts.forget(chat_id, message_id)

    # ----- reacting to the user ----------------------------------------------------

    async def current_view(self, chat_id: int, message_id: int) -> ViewState:
        """The view a menu message is showing (the all-accounts list for anything else)."""
        state = await self._menus.get(chat_id)
        if state and state.message_id == message_id:
            return ViewState.parse(state.view)
        return ViewState(views.ALL)

    async def is_menu_message(self, chat_id: int, message_id: int) -> bool:
        state = await self._menus.get(chat_id)
        return bool(state and state.message_id == message_id)

    async def open_from_callback(self, callback: CallbackQuery, view: ViewState) -> None:
        """Show ``view`` by editing the pressed menu, or send a fresh message when that menu is stale."""
        if not callback.message:
            return
        chat_id, message_id = callback.message.chat.id, callback.message.message_id
        async with self._locks[chat_id]:
            state = await self._menus.get(chat_id)
            # A notification posted after the menu makes it stale: do not rewrite old context.
            if state and state.is_editable_from(message_id):
                result = await self._edit(chat_id, message_id, view)
                if result.shown:
                    logger.info("Menu click edited message (%s): %s", view.serialize(), describe_actor(callback))
                    return
                if result is Edit.UNAVAILABLE:
                    return
            logger.info("Menu click created a new message (%s): %s", view.serialize(), describe_actor(callback))
            await self._send(chat_id, view)

    async def replace_menus(self, chat_id: int) -> bool:
        """Delete tracked menu messages, then send one fresh main menu."""
        async with self._locks[chat_id]:
            for message_id in await self._menus.message_ids(chat_id):
                if await self._gateway.delete(chat_id, message_id):
                    await self._menus.forget_message(chat_id, message_id)
            await self._menus.remove(chat_id)
            self._shown.pop(chat_id, None)
            return await self._send(chat_id, ViewState(views.MAIN))

    async def show_in_menu(self, chat_id: int, view: ViewState, only_if_showing: str | None = None) -> None:
        """Switch a chat's existing menu to ``view`` (optionally only while it shows a given kind)."""
        async with self._locks[chat_id]:
            state = await self._menus.get(chat_id)
            if state is None:
                return
            if only_if_showing and ViewState.parse(state.view).kind != only_if_showing:
                return
            await self._edit(chat_id, state.message_id, view)

    # ----- background work ---------------------------------------------------------

    async def refresh_all(self) -> None:
        """Re-render every live menu; only messages whose content really changed are edited."""
        for state in await self._menus.all():
            try:
                await self._refresh_one(state)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Could not refresh the menu of chat %s", state.chat_id)

    async def _refresh_one(self, state: MenuState) -> None:
        async with self._locks[state.chat_id]:
            view = ViewState.parse(state.view)
            result = await self._edit(state.chat_id, state.message_id, view, skip_if_same=True)
            if result.needs_replacement and not await self._send(state.chat_id, view):
                await self._menus.remove(state.chat_id)

    async def restore_after_restart(self) -> None:
        """Re-attach to each saved menu, replacing a deleted or uneditable message."""
        states = await self._menus.all()
        known = {state.chat_id for state in states}
        for state in states:
            async with self._locks[state.chat_id]:
                view = ViewState.parse(state.view)
                result = await self._edit(state.chat_id, state.message_id, view)
                if result.shown:
                    logger.info("Saved menu restored: chat=%s message=%s view=%s", state.chat_id, state.message_id, state.view)
                elif result.needs_replacement:
                    logger.info("Saved menu is unavailable; sending a replacement: chat=%s view=%s", state.chat_id, state.view)
                    if not await self._send(state.chat_id, view):
                        await self._menus.remove(state.chat_id)
        for chat_id in self._startup_chat_ids:
            if chat_id not in known:
                logger.info("No saved menu found; sending main menu: chat=%s", chat_id)
                await self.send(chat_id, ViewState(views.MAIN))


async def refresh_loop(menu: MenuService, interval_seconds: int, stop: asyncio.Event) -> None:
    """Redraw the live menus every ``interval_seconds`` until ``stop`` is set."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            await menu.refresh_all()
