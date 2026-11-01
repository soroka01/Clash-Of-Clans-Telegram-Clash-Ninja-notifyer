from __future__ import annotations

from dataclasses import dataclass

from app.storage.database import Database


@dataclass(frozen=True, slots=True)
class MenuState:
    """The single live menu message of a chat plus what the bot sent after it."""

    chat_id: int
    message_id: int
    view: str
    latest_bot_message_id: int
    latest_bot_kind: str

    def is_editable_from(self, message_id: int) -> bool:
        """True while the pressed menu is still the newest thing the bot said in the chat."""
        return (
            self.message_id == message_id
            and self.latest_bot_kind == "dashboard"
            and self.latest_bot_message_id == message_id
        )


class MenuRepository:
    """Tracks menu messages per chat so they can be edited, restored and cleaned up."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def upsert(self, chat_id: int, message_id: int, view: str) -> None:
        await self._db.run(
            (
                (
                    """INSERT INTO dashboards(chat_id, message_id, view, latest_bot_message_id, latest_bot_kind)
                       VALUES (?, ?, ?, ?, 'dashboard')
                       ON CONFLICT(chat_id) DO UPDATE SET
                         message_id=excluded.message_id, view=excluded.view,
                         latest_bot_message_id=excluded.latest_bot_message_id,
                         latest_bot_kind='dashboard'""",
                    (chat_id, message_id, view, message_id),
                ),
                ("INSERT OR IGNORE INTO menu_messages(chat_id, message_id) VALUES (?, ?)", (chat_id, message_id)),
            )
        )

    async def update_view(self, chat_id: int, view: str) -> None:
        await self._db.execute("UPDATE dashboards SET view=? WHERE chat_id=?", (view, chat_id))

    async def mark_notification(self, chat_id: int, message_id: int) -> None:
        await self._db.execute(
            "UPDATE dashboards SET latest_bot_message_id=?, latest_bot_kind='notification' WHERE chat_id=?",
            (message_id, chat_id),
        )

    async def get(self, chat_id: int) -> MenuState | None:
        row = await self._db.fetch_one("SELECT * FROM dashboards WHERE chat_id=?", (chat_id,))
        return MenuState(**dict(row)) if row else None

    async def all(self) -> list[MenuState]:
        return [MenuState(**dict(row)) for row in await self._db.fetch_all("SELECT * FROM dashboards")]

    async def remove(self, chat_id: int) -> None:
        await self._db.execute("DELETE FROM dashboards WHERE chat_id=?", (chat_id,))

    async def remember_message(self, chat_id: int, message_id: int) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO menu_messages(chat_id, message_id) VALUES (?, ?)", (chat_id, message_id)
        )

    async def message_ids(self, chat_id: int) -> list[int]:
        rows = await self._db.fetch_all(
            "SELECT message_id FROM menu_messages WHERE chat_id=? ORDER BY message_id", (chat_id,)
        )
        return [int(row["message_id"]) for row in rows]

    async def forget_message(self, chat_id: int, message_id: int) -> None:
        await self._db.execute("DELETE FROM menu_messages WHERE chat_id=? AND message_id=?", (chat_id, message_id))


class AlertRepository:
    """Tracks alert messages that still carry the "refresh menu" button."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def remember(self, chat_id: int, message_id: int) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO alert_messages(chat_id, message_id) VALUES (?, ?)", (chat_id, message_id)
        )

    async def message_ids(self, chat_id: int) -> list[int]:
        rows = await self._db.fetch_all(
            "SELECT message_id FROM alert_messages WHERE chat_id=? ORDER BY message_id", (chat_id,)
        )
        return [int(row["message_id"]) for row in rows]

    async def forget(self, chat_id: int, message_id: int) -> None:
        await self._db.execute("DELETE FROM alert_messages WHERE chat_id=? AND message_id=?", (chat_id, message_id))
