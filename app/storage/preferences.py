from __future__ import annotations

from app.storage.database import Database

MIN_UTC_OFFSET = -12
MAX_UTC_OFFSET = 14


class ChatPreferences:
    """Per-chat settings (time zone, alert switch). Values are cached; writes go through."""

    def __init__(self, database: Database, default_utc_offset: int) -> None:
        self._db = database
        self._default_utc_offset = default_utc_offset
        self._offsets: dict[int, int] = {}
        self._notifications: dict[int, bool] = {}

    async def utc_offset(self, chat_id: int) -> int:
        if chat_id not in self._offsets:
            row = await self._db.fetch_one("SELECT utc_offset_hours FROM chat_settings WHERE chat_id=?", (chat_id,))
            self._offsets[chat_id] = int(row["utc_offset_hours"]) if row else self._default_utc_offset
        return self._offsets[chat_id]

    async def set_utc_offset(self, chat_id: int, utc_offset_hours: int) -> None:
        if not MIN_UTC_OFFSET <= utc_offset_hours <= MAX_UTC_OFFSET:
            raise ValueError("UTC offset must be between -12 and 14")
        await self._db.execute(
            """INSERT INTO chat_settings(chat_id, utc_offset_hours) VALUES (?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET utc_offset_hours=excluded.utc_offset_hours""",
            (chat_id, utc_offset_hours),
        )
        self._offsets[chat_id] = utc_offset_hours

    async def notifications_enabled(self, chat_id: int) -> bool:
        if chat_id not in self._notifications:
            row = await self._db.fetch_one("SELECT enabled FROM chat_notifications WHERE chat_id=?", (chat_id,))
            self._notifications[chat_id] = bool(row["enabled"]) if row else True
        return self._notifications[chat_id]

    async def set_notifications_enabled(self, chat_id: int, enabled: bool) -> None:
        await self._db.execute(
            """INSERT INTO chat_notifications(chat_id, enabled) VALUES (?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled""",
            (chat_id, int(enabled)),
        )
        self._notifications[chat_id] = enabled
