from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from app.clash_ninja.client import ClashNinjaClient
from app.clash_ninja.parser import parse_tracker_html
from app.models import Snapshot, Upgrade
from app.storage import Storage

logger = logging.getLogger(__name__)
NotificationCallback = Callable[[Upgrade], Awaitable[None]]


class UpgradeMonitor:
    def __init__(
        self,
        client: ClashNinjaClient,
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

    async def poll_once(self) -> None:
        html = await self._client.fetch_tracker_html()
        current = parse_tracker_html(html)
        previous = await self._storage.load_snapshot()

        if previous:
            for finished in self._completed(previous, current):
                await self._notify(finished)
        await self._storage.save_snapshot(current)
        async with self._snapshot_lock:
            self._latest = current
        logger.info("Tracker updated: %s villages, %s active upgrades", len(current.villages), len(current.upgrades))

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

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Could not update Clash Ninja tracker")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
