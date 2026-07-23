from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.models import Snapshot


@dataclass(frozen=True, slots=True)
class DashboardState:
    chat_id: int
    message_id: int
    view: str
    latest_bot_message_id: int
    latest_bot_kind: str


class Storage:
    """Small SQLite repository. All DB calls are serialized for sqlite safety."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dashboards (
                chat_id INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                view TEXT NOT NULL,
                latest_bot_message_id INTEGER NOT NULL,
                latest_bot_kind TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    async def close(self) -> None:
        async with self._lock:
            self._connection.close()

    async def load_snapshot(self) -> Snapshot | None:
        async with self._lock:
            row = self._connection.execute("SELECT payload FROM snapshots WHERE id = 1").fetchone()
        return Snapshot.from_dict(json.loads(row["payload"])) if row else None

    async def save_snapshot(self, snapshot: Snapshot) -> None:
        payload = json.dumps(snapshot.to_dict(), ensure_ascii=False)
        async with self._lock:
            self._connection.execute(
                "INSERT INTO snapshots(id, payload) VALUES(1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (payload,),
            )
            self._connection.commit()

    async def upsert_dashboard(self, chat_id: int, message_id: int, view: str) -> None:
        async with self._lock:
            self._connection.execute(
                """INSERT INTO dashboards(chat_id, message_id, view, latest_bot_message_id, latest_bot_kind)
                   VALUES (?, ?, ?, ?, 'dashboard')
                   ON CONFLICT(chat_id) DO UPDATE SET
                     message_id=excluded.message_id, view=excluded.view,
                     latest_bot_message_id=excluded.latest_bot_message_id,
                     latest_bot_kind='dashboard'""",
                (chat_id, message_id, view, message_id),
            )
            self._connection.commit()

    async def update_dashboard_view(self, chat_id: int, view: str) -> None:
        async with self._lock:
            self._connection.execute("UPDATE dashboards SET view=? WHERE chat_id=?", (view, chat_id))
            self._connection.commit()

    async def mark_notification(self, chat_id: int, message_id: int) -> None:
        async with self._lock:
            self._connection.execute(
                "UPDATE dashboards SET latest_bot_message_id=?, latest_bot_kind='notification' WHERE chat_id=?",
                (message_id, chat_id),
            )
            self._connection.commit()

    async def get_dashboard(self, chat_id: int) -> DashboardState | None:
        async with self._lock:
            row = self._connection.execute("SELECT * FROM dashboards WHERE chat_id=?", (chat_id,)).fetchone()
        return DashboardState(**dict(row)) if row else None

    async def dashboards(self) -> list[DashboardState]:
        async with self._lock:
            rows = self._connection.execute("SELECT * FROM dashboards").fetchall()
        return [DashboardState(**dict(row)) for row in rows]

    async def remove_dashboard(self, chat_id: int) -> None:
        async with self._lock:
            self._connection.execute("DELETE FROM dashboards WHERE chat_id=?", (chat_id,))
            self._connection.commit()
