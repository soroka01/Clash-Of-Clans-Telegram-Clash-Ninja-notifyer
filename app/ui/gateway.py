from __future__ import annotations

import asyncio
import io
import logging
import time
from enum import StrEnum

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import BufferedInputFile, Document, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

MAX_FLOOD_WAIT = 20.0  # longest pause worth blocking a sender for


class TelegramUnavailable(Exception):
    """A temporary failure (network, server, flood limit): the same call may succeed later."""


class Edit(StrEnum):
    DONE = "done"
    UNCHANGED = "unchanged"  # the message already looks exactly like this
    MISSING = "missing"  # deleted, too old or otherwise not editable: send a new one
    REJECTED = "rejected"  # Telegram refuses this content or the chat: sending a new one is the only option
    UNAVAILABLE = "unavailable"  # temporary failure: leave things as they are and try later

    @property
    def needs_replacement(self) -> bool:
        return self in (Edit.MISSING, Edit.REJECTED)

    @property
    def shown(self) -> bool:
        return self in (Edit.DONE, Edit.UNCHANGED)


_NOT_EDITABLE_MARKERS = ("message to edit not found", "message can't be edited", "message_id_invalid")


class TelegramGateway:
    """The only place that talks to the Telegram Bot API for sending, editing and deleting.

    It turns the zoo of aiogram exceptions into three outcomes that callers can reason about:
    success, a permanent refusal (logged, never retried) and a temporary failure.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._flood_until = 0.0

    @property
    def bot(self) -> Bot:
        return self._bot

    def _flooded(self) -> bool:
        return time.monotonic() < self._flood_until

    def _note_flood(self, error: TelegramRetryAfter) -> None:
        self._flood_until = time.monotonic() + float(error.retry_after)
        logger.warning("Telegram flood control: pausing for %s s", error.retry_after)

    # ----- sending -----------------------------------------------------------------

    async def send(self, chat_id: int, text: str, markup: InlineKeyboardMarkup | None = None) -> int | None:
        """Send a message. Returns its id, or None if Telegram permanently refused it.

        Raises TelegramUnavailable when the failure is temporary.
        """
        return await self._send(lambda: self._bot.send_message(chat_id, text, reply_markup=markup), chat_id, "message")

    async def send_document(self, chat_id: int, data: bytes, filename: str, caption: str | None = None) -> int | None:
        document = BufferedInputFile(data, filename=filename)
        return await self._send(lambda: self._bot.send_document(chat_id, document, caption=caption), chat_id, "document")

    async def _send(self, call, chat_id: int, what: str) -> int | None:
        for attempt in (1, 2):
            if self._flooded():
                await self._wait_out_flood()
            try:
                message = await call()
                return message.message_id
            except TelegramRetryAfter as error:
                self._note_flood(error)
                if attempt == 2 or error.retry_after > MAX_FLOOD_WAIT:
                    raise TelegramUnavailable(f"flood control: retry after {error.retry_after}s") from error
            except TelegramForbiddenError as error:
                logger.warning("Telegram refused the %s for chat %s: %s", what, chat_id, error)
                return None
            except TelegramBadRequest as error:
                logger.warning("Could not send %s to chat %s: %s", what, chat_id, error)
                return None
            except (TelegramNetworkError, TelegramServerError) as error:
                raise TelegramUnavailable(str(error)) from error
        raise TelegramUnavailable("unreachable")  # pragma: no cover

    async def _wait_out_flood(self) -> None:
        remaining = self._flood_until - time.monotonic()
        if remaining > MAX_FLOOD_WAIT:
            raise TelegramUnavailable(f"flood control for another {remaining:.0f}s")
        await asyncio.sleep(max(0.0, remaining) + 0.2)

    # ----- editing -----------------------------------------------------------------

    async def edit(self, chat_id: int, message_id: int, text: str, markup: InlineKeyboardMarkup | None) -> Edit:
        if self._flooded():
            return Edit.UNAVAILABLE
        try:
            await self._bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
        except TelegramBadRequest as error:
            reason = str(error).lower()
            if "message is not modified" in reason:
                return Edit.UNCHANGED
            if any(marker in reason for marker in _NOT_EDITABLE_MARKERS):
                logger.debug("Message %s/%s cannot be edited: %s", chat_id, message_id, error)
                return Edit.MISSING
            logger.warning("Could not edit message %s/%s: %s", chat_id, message_id, error)
            return Edit.REJECTED
        except TelegramForbiddenError as error:
            logger.warning("Telegram refused to edit message %s/%s: %s", chat_id, message_id, error)
            return Edit.REJECTED
        except TelegramRetryAfter as error:
            self._note_flood(error)
            return Edit.UNAVAILABLE
        except (TelegramNetworkError, TelegramServerError) as error:
            logger.warning("Telegram unavailable while editing %s/%s: %s", chat_id, message_id, error)
            return Edit.UNAVAILABLE
        return Edit.DONE

    async def clear_markup(self, chat_id: int, message_id: int) -> None:
        """Remove the buttons from a message; any failure only matters for the log."""
        try:
            await self._bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).lower():
                logger.debug("Could not clear buttons %s/%s: %s", chat_id, message_id, error)
        except (TelegramForbiddenError, TelegramNetworkError, TelegramServerError, TelegramRetryAfter) as error:
            logger.debug("Could not clear buttons %s/%s: %s", chat_id, message_id, error)

    async def delete(self, chat_id: int, message_id: int) -> bool:
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramServerError, TelegramRetryAfter) as error:
            logger.debug("Could not delete message %s/%s: %s", chat_id, message_id, error)
            return False
        return True

    async def delete_many(self, chat_id: int, message_ids: list[int]) -> bool:
        """Delete messages in batches of 100 (the Bot API limit). True only if every batch succeeded."""
        everything = True
        for start in range(0, len(message_ids), 100):
            batch = message_ids[start : start + 100]
            try:
                await self._bot.delete_messages(chat_id=chat_id, message_ids=batch)
            except (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramServerError, TelegramRetryAfter) as error:
                logger.debug("Could not delete %s messages in chat %s: %s", len(batch), chat_id, error)
                everything = False
        return everything

    # ----- files -------------------------------------------------------------------

    async def download(self, document: Document) -> bytes:
        """Download a file the user sent. Raises TelegramUnavailable on temporary failures."""
        buffer = io.BytesIO()
        try:
            await self._bot.download(document, destination=buffer)
        except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter, TelegramBadRequest) as error:
            raise TelegramUnavailable(str(error)) from error  # BadRequest here means "file is too big" and the like
        return buffer.getvalue()
