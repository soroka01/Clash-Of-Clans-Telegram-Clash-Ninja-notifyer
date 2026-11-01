from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, User

from app.ui.menu_service import describe_actor

logger = logging.getLogger(__name__)

Handler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


class AccessControl(BaseMiddleware):
    """Lets only authorized users through. An empty allow-list means "everyone" (see the README warning)."""

    def __init__(self, authorized_user_ids: frozenset[int]) -> None:
        self._authorized = authorized_user_ids

    def allows(self, user: User | None) -> bool:
        return bool(user and (not self._authorized or user.id in self._authorized))

    async def __call__(self, handler: Handler, event: Message | CallbackQuery, data: dict[str, Any]) -> Any:
        if self.allows(event.from_user):
            return await handler(event, data)
        self._log_rejected(event)
        if isinstance(event, CallbackQuery):
            await event.answer("Нет доступа", show_alert=True)  # otherwise the button keeps spinning
        return None

    @staticmethod
    def _log_rejected(event: Message | CallbackQuery) -> None:
        # Plain chatter in a group is none of our business; commands, buttons and files are.
        chatter = (
            isinstance(event, Message)
            and event.chat.type != ChatType.PRIVATE
            and not (event.text or "").startswith("/")
            and event.document is None
        )
        log = logger.debug if chatter else logger.warning
        log("Unauthorized %s ignored: %s", type(event).__name__, describe_actor(event))
