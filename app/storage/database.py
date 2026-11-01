from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# Each entry upgrades the schema by one version (PRAGMA user_version). Never edit a released
# entry: append a new one. Entry 1 is the schema of the original releases, so a database created
# before versioning existed is adopted as-is.
MIGRATIONS: tuple[str, ...] = (
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
    CREATE TABLE IF NOT EXISTS chat_settings (
        chat_id INTEGER PRIMARY KEY,
        utc_offset_hours INTEGER NOT NULL CHECK (utc_offset_hours BETWEEN -12 AND 14)
    );
    CREATE TABLE IF NOT EXISTS menu_messages (
        chat_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        PRIMARY KEY (chat_id, message_id)
    );
    CREATE TABLE IF NOT EXISTS alert_messages (
        chat_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        PRIMARY KEY (chat_id, message_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS announcements (
        key TEXT PRIMARY KEY,
        finish_at TEXT,
        announced_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS chat_notifications (
        chat_id INTEGER PRIMARY KEY,
        enabled INTEGER NOT NULL
    );
    """,
)


class Database:
    """One SQLite connection shared by the repositories.

    Statements run in a worker thread so disk syncs never stall the event loop, and a lock keeps
    them strictly serialized (one connection is not safe for concurrent use).
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self.upgraded_from: int | None = None  # schema version found on disk, set only if it was migrated
        self._migrate()
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")

    def _migrate(self) -> None:
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current >= len(MIGRATIONS):
            return
        self.upgraded_from = current
        self._backup_before_migration(current)
        for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
            self._connection.executescript(script)
            self._connection.execute(f"PRAGMA user_version = {version}")
            self._connection.commit()
            logger.info("Database migrated to version %s", version)

    def _backup_before_migration(self, current_version: int) -> None:
        """Keep a copy of a pre-existing database before touching its schema."""
        has_data = self._connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is not None
        if not has_data:
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = self._path.with_name(f"{self._path.name}.v{current_version}-{stamp}.bak")
        try:
            target = sqlite3.connect(backup_path)
            try:
                self._connection.backup(target)
            finally:
                target.close()
            logger.info("Database backup created before migration: %s", backup_path.name)
        except (OSError, sqlite3.Error) as error:
            logger.warning("Could not back up the database before migration: %s", error)

    @property
    def schema_version(self) -> int:
        return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        await self.run(((sql, params),))

    async def run(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> None:
        """Execute several statements in one transaction."""
        async with self._lock:
            await asyncio.to_thread(self._run, statements)

    def _run(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> None:
        try:
            for sql, params in statements:
                self._connection.execute(sql, params)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        async with self._lock:
            return await asyncio.to_thread(lambda: self._connection.execute(sql, params).fetchone())

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        async with self._lock:
            return await asyncio.to_thread(lambda: self._connection.execute(sql, params).fetchall())

    async def close(self) -> None:
        async with self._lock:
            self._connection.close()
