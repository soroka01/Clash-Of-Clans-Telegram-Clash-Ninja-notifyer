from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Protocol

from app.models import HelperStatus, Snapshot, Upgrade
from app.storage import Storage
from app.timefmt import format_duration

logger = logging.getLogger(__name__)
NotificationEvent = Upgrade | HelperStatus
NotificationCallback = Callable[[NotificationEvent], Awaitable[None]]


class SnapshotSource(Protocol):
    async def fetch_snapshot(self) -> Snapshot: ...


class UpgradeMonitor:
    def __init__(
        self,
        client: SnapshotSource,
        storage: Storage,
        poll_interval_seconds: int,
        notify: NotificationCallback,
    ) -> None:
        self._client = client
        self._storage = storage
        self._poll_interval = poll_interval_seconds
        self._notify = notify
        self._latest = Snapshot.empty()
        self._stop = asyncio.Event()
        self._snapshot_lock = asyncio.Lock()

    async def latest_snapshot(self) -> Snapshot:
        async with self._snapshot_lock:
            return self._latest

    async def restore_cached_snapshot(self) -> None:
        """Make the last known data available while the first network poll is running."""
        snapshot = await self._storage.load_snapshot()
        if snapshot is None:
            return
        async with self._snapshot_lock:
            self._latest = snapshot

    async def poll_once(self) -> None:
        logger.debug("Starting polling cycle")
        current = await self._client.fetch_snapshot()
        previous = await self._storage.load_snapshot()

        if previous:
            for finished in self._completed(previous, current):
                logger.info(
                    "Completion detected: village=%s entity=%s level=%s helper=%s",
                    finished.village_name,
                    finished.entity,
                    finished.level,
                    finished.is_helper,
                )
                await self._notify(finished)
            for helper in self._released_helpers(previous, current):
                logger.info("Helper became available: village=%s helper=%s", helper.village_name, helper.helper_name)
                await self._notify(helper)
        await self._storage.save_snapshot(current)
        async with self._snapshot_lock:
            self._latest = current
        logger.info(
            "Clash Ninja обновлён: аккаунтов: %s, улучшений: %s, ближайшее: %s",
            len(current.villages),
            len(current.upgrades),
            self._nearest_upgrade(current.upgrades),
        )

    @staticmethod
    def _nearest_upgrade(upgrades: tuple[Upgrade, ...]) -> str:
        timed = [(upgrade.finish_at, upgrade) for upgrade in upgrades if upgrade.finish_at is not None]
        if not timed:
            return "нет таймеров"
        finish_at, nearest = min(timed, key=lambda pair: pair[0])
        remaining = int((finish_at - datetime.now(timezone.utc)).total_seconds())
        return f"{nearest.village_name} / {nearest.entity} {nearest.level}, осталось: {format_duration(remaining)}"

    def _completed(self, previous: Snapshot, current: Snapshot) -> list[Upgrade]:
        active_now = {upgrade.key for upgrade in current.upgrades}
        present_villages = {village_id for village_id, _ in current.villages}
        now = datetime.now(timezone.utc)
        tolerance = timedelta(seconds=max(self._poll_interval * 2, 120))
        return [
            upgrade
            for upgrade in previous.upgrades
            if upgrade.key not in active_now
            and upgrade.village_id in present_villages
            and upgrade.finish_at is not None
            and upgrade.finish_at <= now + tolerance
        ]

    @staticmethod
    def _released_helpers(previous: Snapshot, current: Snapshot) -> list[HelperStatus]:
        before = {helper.key: helper for helper in previous.helpers}
        return [
            helper
            for helper in current.helpers
            if helper.state == "available"
            and helper.key in before
            and before[helper.key].state == "assigned"
        ]

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("Could not update Clash Ninja tracker: %s", error)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
