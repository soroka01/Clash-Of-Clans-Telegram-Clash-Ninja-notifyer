from __future__ import annotations

import logging
import time

from app.services.accounts import SaveResult
from app.services.importer import ImportSession
from app.ui import views
from app.ui.gateway import TelegramGateway, TelegramUnavailable
from app.ui.menu_service import MenuService
from app.ui.render.common import Screen
from app.ui.screens import ScreenFactory
from app.ui.views import ViewState

logger = logging.getLogger(__name__)

STATUS_EDIT_INTERVAL = 1.5  # seconds between progress edits (Telegram rate limits edits per chat)


class ImportPresenter:
    """Shows import progress in one status message that is edited as chunks arrive (ImportObserver)."""

    def __init__(
        self,
        gateway: TelegramGateway,
        screens: ScreenFactory,
        menu: MenuService,
        delete_messages: bool,
    ) -> None:
        self._gateway = gateway
        self._screens = screens
        self._menu = menu
        self._delete_messages = delete_messages
        self._renderer = screens.import_renderer

    async def receiving(self, session: ImportSession) -> None:
        await self._show(session, self._renderer.receiving(session), throttle=True)

    async def waiting_for_more(self, session: ImportSession) -> None:
        await self._show(session, self._renderer.waiting_for_more(session))

    async def completed(self, session: ImportSession, result: SaveResult) -> None:
        deleted = await self._delete_user_messages(session)
        ctx = await self._screens.context(session.chat_id)
        await self._show(session, self._renderer.success(ctx, result, session, deleted))
        # The "send me the JSON" prompt is done: bring the menu back to the account list.
        await self._menu.show_in_menu(session.chat_id, ViewState(views.ACCOUNTS), only_if_showing=views.IMPORT)

    async def failed(self, session: ImportSession, reason: str) -> None:
        await self._show(session, self._renderer.failure(reason))

    async def _delete_user_messages(self, session: ImportSession) -> bool:
        if not self._delete_messages or not session.message_ids:
            return False
        return await self._gateway.delete_many(session.chat_id, session.message_ids)

    async def _show(self, session: ImportSession, screen: Screen, *, throttle: bool = False) -> None:
        async with session.ui_lock:
            now = time.monotonic()
            if throttle and session.status_message_id is not None and now - session.status_updated_at < STATUS_EDIT_INTERVAL:
                return
            try:
                if session.status_message_id is None:
                    message_id = await self._gateway.send(session.chat_id, screen.text, screen.markup)
                    session.status_message_id = message_id
                    if message_id is not None:
                        session.bot_message_ids.add(message_id)
                else:
                    await self._gateway.edit(session.chat_id, session.status_message_id, screen.text, screen.markup)
            except TelegramUnavailable as error:
                logger.warning("Could not update the import status in chat %s: %s", session.chat_id, error)
            session.status_updated_at = now
