from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config.settings import ImportSettings
from app.services.accounts import AccountService, SaveResult
from app.sources.json_accounts.parser import InvalidExport
from app.sources.json_accounts.store import AccountStoreError, sanitize_name

logger = logging.getLogger(__name__)

ARMED_TTL = 600.0  # seconds a "send me the JSON" request stays open
INCOMPLETE_GRACE = 60.0  # how long a JSON that stopped mid-way waits for the rest
NO_START_GRACE = 10.0  # how long text that does not begin with "{" waits for the part that does
ORPHAN_TTL = 10.0  # a long text that arrives before the chunk that starts the JSON is kept this long
ORPHAN_MIN_LENGTH = 1000
MAX_CHUNKS = 2000
EARLY_PARSE_LIMIT = 400_000  # characters; above this only the idle timer concludes a paste
_GENERIC_FILE_NAMES = re.compile(r"(village|export|data|clash.*|coc.*|account|json|file)(\s*\(\d+\))?", re.IGNORECASE)
_STRUCTURE = re.compile(r'["\\{}\[\]]')
# Top-level keys of a village export. A pasted text only *starts* an import when it opens with one of
# them: a later part of the same paste can also begin with "{" (an item inside a list) and must not be
# mistaken for the beginning.
_EXPORT_KEYS = (
    "tag", "timestamp", "village_id", "helpers", "guardians", "buildings", "traps", "decos", "obstacles",
    "units", "siege_machines", "heroes", "spells", "pets", "equipment", "house_parts", "skins", "sceneries",
    "boosts", "buildings2", "traps2", "decos2", "obstacles2", "units2", "heroes2", "skins2", "sceneries2",
)
_EXPORT_START = re.compile(r'\{\s*"(?:' + "|".join(_EXPORT_KEYS) + r')"\s*:')


# ----- looking at a pasted buffer -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Parsed:
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Incomplete:
    """Valid so far, but cut off: more messages are expected."""


@dataclass(frozen=True, slots=True)
class NoStart:
    """The text does not (yet) begin with a JSON object."""


@dataclass(frozen=True, slots=True)
class Invalid:
    message: str


Verdict = Parsed | Incomplete | NoStart | Invalid


def looks_like_export_start(text: str) -> bool:
    """True if ``text`` opens like the beginning of a village export."""
    return _EXPORT_START.match(text.lstrip("﻿​ \t\r\n")) is not None


def scan_structure(text: str) -> tuple[int, bool]:
    """Return (open brackets, inside a string) at the end of ``text``, ignoring JSON syntax errors."""
    depth, in_string, skip_until = 0, False, 0
    for match in _STRUCTURE.finditer(text):
        position, char = match.start(), match.group()
        if position < skip_until:
            continue  # escaped by the preceding backslash
        if in_string:
            if char == "\\":
                skip_until = position + 2
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
    return depth, in_string


def classify_buffer(text: str) -> Verdict:
    """Decide whether ``text`` is a complete JSON object, a cut-off one, or broken. CPU-bound: run in a thread."""
    stripped = text.lstrip("\ufeff\u200b \t\r\n")
    if not stripped.startswith("{"):
        return NoStart()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as error:
        depth, in_string = scan_structure(stripped)
        if depth > 0 or in_string:
            return Incomplete()
        return Invalid(f"синтаксическая ошибка JSON в позиции {error.pos}: {error.msg}")
    except (RecursionError, ValueError) as error:
        return Invalid(f"не удалось разобрать JSON: {type(error).__name__}")
    if not isinstance(payload, dict):
        return Invalid("в JSON ожидался объект с данными деревни")
    return Parsed(payload)


# ----- sessions -----------------------------------------------------------------------


@dataclass(slots=True)
class ImportSession:
    """Messages of one user that together make one JSON export."""

    chat_id: int
    user_id: int
    explicit: bool  # the user asked for an import (button or /import) rather than just pasting
    preferred_name: str | None
    source: str = "text"  # "text" or "file"
    replace_village_id: str | None = None  # account this export replaces regardless of its tag
    chunks: dict[int, str] = field(default_factory=dict)  # Telegram message id -> text
    bot_message_ids: set[int] = field(default_factory=set)  # the bot's own messages between the chunks
    status_message_id: int | None = None  # owned by the UI
    status_updated_at: float = 0.0  # monotonic time of the last status edit (UI throttling)
    generation: int = 0  # bumped by every new chunk so stale parse results can be discarded
    waiting_for_more: bool = False
    closed: bool = False
    total_chars: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ui_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    timer: asyncio.Task | None = None

    @property
    def message_ids(self) -> list[int]:
        return sorted(self.chunks)

    def assemble(self) -> str:
        """Join the chunks in message order, with nothing in between: Telegram only trims whitespace
        at its split points and JSON does not need any there."""
        return "".join(self.chunks[message_id] for message_id in sorted(self.chunks))

    def is_contiguous(self) -> bool:
        if not self.chunks:
            return False
        ids = sorted(self.chunks)
        return all(number in self.chunks or number in self.bot_message_ids for number in range(ids[0], ids[-1] + 1))


class ImportObserver(Protocol):
    """Implemented by the Telegram layer to show what the importer is doing."""

    async def receiving(self, session: ImportSession) -> None: ...

    async def waiting_for_more(self, session: ImportSession) -> None: ...

    async def completed(self, session: ImportSession, result: SaveResult) -> None: ...

    async def failed(self, session: ImportSession, reason: str) -> None: ...


@dataclass(slots=True)
class _Armed:
    preferred_name: str | None
    expires_at: float
    replace_village_id: str | None = None


class ImportService:
    """Collects a game export that arrives as text messages (usually split by Telegram) or a file."""

    def __init__(self, accounts: AccountService, settings: ImportSettings) -> None:
        self._accounts = accounts
        self._settings = settings
        self._observer: ImportObserver | None = None
        self._sessions: dict[tuple[int, int], ImportSession] = {}
        self._armed: dict[tuple[int, int], _Armed] = {}
        self._orphans: dict[tuple[int, int], list[tuple[int, str, float]]] = {}

    def attach(self, observer: ImportObserver) -> None:
        self._observer = observer

    @property
    def max_bytes(self) -> int:
        return self._settings.max_bytes

    # ----- arming ------------------------------------------------------------------

    def arm(
        self,
        chat_id: int,
        user_id: int,
        preferred_name: str | None = None,
        replace_village_id: str | None = None,
    ) -> None:
        """Treat the next text of this user as part of an export, whatever it looks like.

        ``replace_village_id`` names the account that the export is meant to replace even if the
        player tag differs from the stored one."""
        name = sanitize_name(preferred_name or "") if preferred_name else None
        self._armed[(chat_id, user_id)] = _Armed(name, time.monotonic() + ARMED_TTL, replace_village_id)

    def is_armed(self, chat_id: int, user_id: int) -> bool:
        armed = self._armed.get((chat_id, user_id))
        if armed and armed.expires_at < time.monotonic():
            del self._armed[(chat_id, user_id)]
            return False
        return armed is not None

    async def cancel(self, chat_id: int, user_id: int) -> bool:
        key = (chat_id, user_id)
        was_active = self._armed.pop(key, None) is not None
        session = self._sessions.get(key)
        if session is not None:
            await self._close(session)
            was_active = True
        self._orphans.pop(key, None)
        return was_active

    def has_session(self, chat_id: int, user_id: int) -> bool:
        return (chat_id, user_id) in self._sessions

    # ----- text intake -------------------------------------------------------------

    def wants_text(self, chat_id: int, user_id: int, text: str, private_chat: bool) -> bool:
        """True if this text belongs to the importer, so no other handler should treat it."""
        key = (chat_id, user_id)
        if key in self._sessions or self.is_armed(chat_id, user_id):
            return True
        return private_chat and looks_like_export_start(text)

    def remember_orphan(self, chat_id: int, user_id: int, message_id: int, text: str) -> None:
        """A long text with no import in progress may be a continuation that overtook its first part."""
        if len(text) < ORPHAN_MIN_LENGTH:
            return
        now = time.monotonic()
        items = [item for item in self._orphans.get((chat_id, user_id), []) if now - item[2] < ORPHAN_TTL]
        items.append((message_id, text, now))
        # Bounded by the same size limit as a whole import, dropping the oldest first.
        while len(items) > 1 and sum(len(item[1]) for item in items) > self._settings.max_bytes:
            items.pop(0)
        self._orphans[(chat_id, user_id)] = items

    async def add_text(self, chat_id: int, user_id: int, message_id: int, text: str, private_chat: bool) -> None:
        """Register one message. The registration itself is synchronous (no await before the chunk is
        stored) so that concurrently handled updates cannot lose their place."""
        key = (chat_id, user_id)
        session = self._sessions.get(key)
        if session is None:
            if not self.wants_text(chat_id, user_id, text, private_chat):
                self.remember_orphan(chat_id, user_id, message_id, text)
                return
            session = self._open_session(chat_id, user_id, message_id)
        if session.closed:
            return
        if len(session.chunks) >= MAX_CHUNKS or session.total_chars + len(text) > self._settings.max_bytes:
            await self._fail(session, self._too_large_message())
            return
        if message_id not in session.chunks:
            session.chunks[message_id] = text
            session.total_chars += len(text)
        session.generation += 1
        session.waiting_for_more = False
        self._schedule_idle(session, self._settings.idle_seconds)
        await self._notify("receiving", session)
        await self._try_finish(session, early=True)

    def _open_session(self, chat_id: int, user_id: int, first_message_id: int) -> ImportSession:
        key = (chat_id, user_id)
        armed = self._armed.pop(key, None)
        session = ImportSession(
            chat_id,
            user_id,
            explicit=armed is not None,
            preferred_name=armed.preferred_name if armed else None,
            replace_village_id=armed.replace_village_id if armed else None,
        )
        self._sessions[key] = session
        now = time.monotonic()
        kept: list[tuple[int, str, float]] = []
        for orphan in self._orphans.pop(key, []):
            message_id, text, seen = orphan
            if now - seen >= ORPHAN_TTL:
                continue
            if message_id > first_message_id:
                session.chunks[message_id] = text
                session.total_chars += len(text)
            else:
                kept.append(orphan)  # sent before the opener: not part of this paste
        if kept:
            self._orphans[key] = kept
        return session

    # ----- file intake -------------------------------------------------------------

    async def import_file(self, chat_id: int, user_id: int, message_id: int, filename: str, data: bytes) -> None:
        key = (chat_id, user_id)
        armed = self._armed.pop(key, None)
        preferred = armed.preferred_name if armed and armed.preferred_name else self._name_from_file(filename)
        session = ImportSession(
            chat_id,
            user_id,
            explicit=True,
            preferred_name=preferred,
            source="file",
            replace_village_id=armed.replace_village_id if armed else None,
        )
        session.chunks[message_id] = ""
        previous = self._sessions.get(key)
        if previous is not None:
            await self._close(previous)
        self._sessions[key] = session
        if len(data) > self._settings.max_bytes:  # Telegram may omit file_size, so check what arrived
            await self._fail(session, self._too_large_message())
            return
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            await self._fail(session, "файл не в кодировке UTF-8 — пришлите оригинальный экспорт из игры")
            return
        session.chunks[message_id] = text
        session.total_chars = len(text)
        await self._notify("receiving", session)
        async with session.lock:
            verdict = await asyncio.to_thread(classify_buffer, text)
            await self._conclude(session, verdict, final=True)

    @staticmethod
    def _name_from_file(filename: str) -> str | None:
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        name = sanitize_name(stem)
        return None if name is None or _GENERIC_FILE_NAMES.fullmatch(name) else name

    # ----- finishing ---------------------------------------------------------------

    def _schedule_idle(self, session: ImportSession, delay: float) -> None:
        if session.timer is not None:
            session.timer.cancel()
        session.timer = asyncio.create_task(self._idle(session, session.generation, delay))

    async def _idle(self, session: ImportSession, generation: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if session.closed or session.generation != generation:
            return
        await self._try_finish(session, early=False)

    async def _try_finish(self, session: ImportSession, *, early: bool) -> None:
        async with session.lock:
            if session.closed:
                return
            if early and session.total_chars > EARLY_PARSE_LIMIT:
                return  # big pastes are parsed once, after the pause, instead of after every part
            text = session.assemble()
            if early and not text.rstrip().endswith("}"):
                return
            generation = session.generation
            verdict = await asyncio.to_thread(classify_buffer, text)
            if session.closed or generation != session.generation:
                return  # a newer chunk arrived while parsing; its own attempt will follow
            if early:
                # Only ever short-circuit on success, and only when no chunk can be missing.
                if isinstance(verdict, Parsed) and session.is_contiguous():
                    await self._conclude(session, verdict, final=False)
                return
            await self._conclude(session, verdict, final=True)

    async def _conclude(self, session: ImportSession, verdict: Verdict, *, final: bool) -> None:
        if isinstance(verdict, Parsed):
            await self._complete(session, verdict.payload)
        elif isinstance(verdict, Invalid):
            await self._fail(session, verdict.message)
        elif session.source == "file":
            await self._fail(
                session,
                "файл не похож на экспорт: он должен начинаться с «{»"
                if isinstance(verdict, NoStart)
                else "JSON в файле обрывается — похоже, файл скопирован не полностью",
            )
        elif not session.waiting_for_more:
            # Not an error yet: the missing part may simply still be on its way.
            session.waiting_for_more = True
            if isinstance(verdict, Incomplete):
                self._schedule_idle(session, INCOMPLETE_GRACE)
                await self._notify("waiting_for_more", session)
            else:
                self._schedule_idle(session, NO_START_GRACE)
        else:
            await self._fail(
                session,
                "не вижу начала JSON — он должен начинаться с «{»"
                if isinstance(verdict, NoStart)
                else "JSON так и не закончился — пришлите экспорт целиком",
            )

    async def _complete(self, session: ImportSession, payload: dict[str, Any]) -> None:
        try:
            validated = self._accounts.validate(payload)
            result = await self._accounts.save_export(validated, session.preferred_name, session.replace_village_id)
        except InvalidExport as error:
            await self._fail(session, str(error))
            return
        except AccountStoreError as error:
            await self._fail(session, str(error))
            return
        except Exception:
            logger.exception("Import failed while saving")
            await self._fail(session, "внутренняя ошибка при сохранении — подробности в logs/error.log")
            return
        await self._close(session)
        logger.info(
            "Import finished: chat=%s source=%s chunks=%s chars=%s account=%s",
            session.chat_id,
            session.source,
            len(session.chunks),
            session.total_chars,
            result.summary.name,
        )
        await self._notify("completed", session, result)

    async def _fail(self, session: ImportSession, reason: str) -> None:
        if session.closed:
            return
        await self._close(session)
        logger.info("Import rejected: chat=%s reason=%s", session.chat_id, reason)
        await self._notify("failed", session, reason)

    async def _close(self, session: ImportSession) -> None:
        session.closed = True
        current = asyncio.current_task()
        if session.timer is not None and session.timer is not current:
            session.timer.cancel()
        if self._sessions.get((session.chat_id, session.user_id)) is session:
            del self._sessions[(session.chat_id, session.user_id)]

    async def _notify(self, what: str, session: ImportSession, extra: Any = None) -> None:
        if self._observer is None:
            return
        try:
            handler = getattr(self._observer, what)
            await (handler(session, extra) if extra is not None else handler(session))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Import observer failed in %s", what)

    def _too_large_message(self) -> str:
        return f"JSON больше допустимых {self._settings.max_bytes // (1024 * 1024)} МБ или состоит из слишком многих сообщений"
