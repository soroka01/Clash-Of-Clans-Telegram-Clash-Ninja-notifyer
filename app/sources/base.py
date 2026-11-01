from __future__ import annotations

from typing import Protocol

from app.domain.models import Snapshot


class SnapshotSource(Protocol):
    """Anything that can report the currently running upgrades."""

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def fetch_snapshot(self) -> Snapshot: ...
