from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.domain.events import LedgerEntry
from app.storage.database import Database

logger = logging.getLogger(__name__)

# A re-created upgrade with the same key but a different finish time (cancelled and restarted) is
# a new upgrade; finish times closer than this are the same one seen through a different export.
SAME_FINISH_TOLERANCE = timedelta(seconds=120)
RETENTION = timedelta(days=7)


class AnnouncementLedger:
    """Remembers what was already announced so a notification is sent at most once.

    The whole table lives in memory (it is tiny and pruned) and every change is written through.
    """

    def __init__(self, database: Database) -> None:
        self._db = database
        self._entries: dict[str, tuple[datetime | None, datetime]] = {}

    async def load(self) -> None:
        rows = await self._db.fetch_all("SELECT key, finish_at, announced_at FROM announcements")
        self._entries = {
            row["key"]: (
                datetime.fromisoformat(row["finish_at"]) if row["finish_at"] else None,
                datetime.fromisoformat(row["announced_at"]),
            )
            for row in rows
        }
        logger.debug("Announcement ledger loaded: %s entries", len(self._entries))

    def contains(self, entry: LedgerEntry) -> bool:
        known = self._entries.get(entry.key)
        if known is None:
            return False
        known_finish, _ = known
        if entry.finish_at is None or known_finish is None:
            return True
        return abs(entry.finish_at - known_finish) <= SAME_FINISH_TOLERANCE

    async def add(self, entries: Iterable[LedgerEntry], now: datetime | None = None) -> None:
        moment = now or datetime.now(timezone.utc)
        fresh = [entry for entry in entries if not self.contains(entry)]
        if not fresh:
            return
        for entry in fresh:
            self._entries[entry.key] = (entry.finish_at, moment)
        await self._db.run(
            tuple(
                (
                    """INSERT INTO announcements(key, finish_at, announced_at) VALUES (?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET finish_at=excluded.finish_at,
                                                      announced_at=excluded.announced_at""",
                    (entry.key, entry.finish_at.isoformat() if entry.finish_at else None, moment.isoformat()),
                )
                for entry in fresh
            )
        )

    async def prune(self, active_keys: Iterable[str] = (), now: datetime | None = None) -> None:
        """Forget old entries, but never one whose upgrade is still listed (it would be announced again)."""
        threshold = (now or datetime.now(timezone.utc)) - RETENTION
        active = set(active_keys)
        stale = [
            key
            for key, (_, announced_at) in self._entries.items()
            if announced_at < threshold and key not in active
        ]
        if not stale:
            return
        for key in stale:
            del self._entries[key]
        await self._db.run(tuple(("DELETE FROM announcements WHERE key=?", (key,)) for key in stale))
        logger.debug("Announcement ledger pruned: %s entries removed", len(stale))
