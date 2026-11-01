from __future__ import annotations

import json

from app.domain.models import Snapshot
from app.storage.database import Database


class SnapshotRepository:
    """Persists the last known snapshot so a restart does not forget active upgrades."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._last_content: str | None = None

    async def load(self) -> Snapshot | None:
        row = await self._db.fetch_one("SELECT payload FROM snapshots WHERE id = 1")
        if row is None:
            return None
        snapshot = Snapshot.from_dict(json.loads(row["payload"]))
        self._last_content = self._content(snapshot)
        return snapshot

    async def save(self, snapshot: Snapshot) -> bool:
        """Write the snapshot unless nothing but its fetch time changed. Returns True if written."""
        content = self._content(snapshot)
        if content == self._last_content:
            return False
        await self._db.execute(
            "INSERT INTO snapshots(id, payload) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(snapshot.to_dict(), ensure_ascii=False),),
        )
        self._last_content = content
        return True

    @staticmethod
    def _content(snapshot: Snapshot) -> str:
        return json.dumps(snapshot.content_dict(), ensure_ascii=False, sort_keys=True)
