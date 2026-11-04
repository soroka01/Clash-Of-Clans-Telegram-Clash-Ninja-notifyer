from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.domain.events import DomainEvent, LedgerEntry, UpgradeEvent
from app.domain.models import Snapshot
from app.domain.timefmt import format_duration
from app.services.detector import EventDetector
from app.services.health import SourceHealth
from app.sources.base import SnapshotSource
from app.storage.ledger import AnnouncementLedger
from app.storage.snapshots import SnapshotRepository

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 20  # transient failures only; with a 30 s pause that is about ten minutes
RETRY_SECONDS = 30.0
PRUNE_EVERY = timedelta(hours=6)


class EventSink(Protocol):
    """Where announcements go. ``deliver`` returns False only for failures worth retrying."""

    async def deliver(self, event: DomainEvent) -> bool: ...


class UpgradeMonitor:
    """Keeps the newest snapshot, announces finished upgrades and watches the data source.

    One loop does everything so state never races: it wakes up for the next poll *or* for the
    moment the nearest upgrade ends, whichever comes first, so an announcement is not delayed
    until the next poll.
    """

    def __init__(
        self,
        source: SnapshotSource,
        snapshots: SnapshotRepository,
        ledger: AnnouncementLedger,
        detector: EventDetector,
        sink: EventSink,
        health: SourceHealth,
        poll_interval_seconds: int,
        announce_on_timer: bool,
    ) -> None:
        self._source = source
        self._snapshots = snapshots
        self._ledger = ledger
        self._detector = detector
        self._sink = sink
        self._health = health
        self._poll_interval = poll_interval_seconds
        self._announce_on_timer = announce_on_timer

        self._snapshot = Snapshot.empty()
        self._previous: Snapshot | None = None  # None until some real data has been seen
        self._queue: dict[str, tuple[UpgradeEvent, int]] = {}  # undelivered events -> attempts so far
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._refresh_requested = False
        self._poll_seq = 0
        self._waiters: list[tuple[int, asyncio.Future[None]]] = []
        self._last_prune = datetime.min.replace(tzinfo=timezone.utc)

    # ----- public API --------------------------------------------------------------

    @property
    def snapshot(self) -> Snapshot:
        return self._snapshot

    @property
    def health(self) -> SourceHealth:
        return self._health

    async def start(self, seed_expired: bool = False) -> None:
        """Load persisted state. ``seed_expired`` mutes everything that is already over (first run
        after an upgrade, when there is no memory of what was announced)."""
        await self._ledger.load()
        cached = await self._snapshots.load()
        if cached is not None:
            self._snapshot = self._previous = cached
            if seed_expired:
                now = datetime.now(timezone.utc)
                await self._ledger.add(
                    [
                        LedgerEntry(upgrade.key, upgrade.finish_at)
                        for upgrade in cached.upgrades
                        if upgrade.finish_at and upgrade.finish_at <= now
                    ],
                    now,
                )

    async def refresh_now(self, timeout: float = 20.0) -> bool:
        """Poll the source right away and wait for the result. Concurrent calls share one poll."""
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        # A poll already in flight may have read the data before the caller changed it, so wait
        # for the next one to *start*.
        self._waiters.append((self._poll_seq + 1, future))
        self._refresh_requested = True
        self._wake.set()
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout)
        except TimeoutError:
            return False
        return True

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def run(self) -> None:
        next_poll_at = 0.0
        while not self._stop.is_set():
            try:
                if self._refresh_requested or time.monotonic() >= next_poll_at:
                    self._refresh_requested = False
                    try:
                        await self._poll_cycle()
                    finally:
                        # Also after a crashed cycle: otherwise it would be retried every second.
                        next_poll_at = time.monotonic() + self._health.retry_delay(self._poll_interval)
                else:
                    await self._process(self._previous, self._snapshot, persist=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Monitor cycle failed")
            await self._sleep(self._wait_seconds(next_poll_at))

    # ----- one cycle ---------------------------------------------------------------

    async def _poll_cycle(self) -> None:
        self._poll_seq += 1
        sequence = self._poll_seq
        logger.debug("Starting polling cycle %s", sequence)
        try:
            try:
                current = await self._source.fetch_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self._on_failure(error)
            else:
                await self._on_success(current)
        finally:
            self._release_waiters(sequence)

    async def _on_success(self, current: Snapshot) -> None:
        recovered = self._health.record_success()
        changed = await self._process(self._previous, current, persist=True)
        if changed or self._previous is None:
            logger.info(
                "Данные обновлены: аккаунтов: %s, улучшений: %s, ближайшее: %s",
                len(current.villages),
                len(current.upgrades),
                self._describe_nearest(current),
            )
        self._previous = current
        if recovered is not None:
            logger.info("Источник данных снова доступен")
            await self._sink.deliver(recovered)
        await self._maybe_prune(current)

    async def _on_failure(self, error: Exception) -> None:
        logger.error("Could not update snapshot: %s", error)
        alert = self._health.record_failure(error, datetime.now(timezone.utc))
        if alert is not None and await self._deliver_safely(alert):
            self._health.mark_alerted()

    async def _process(self, previous: Snapshot | None, current: Snapshot, *, persist: bool) -> bool:
        """Announce what changed and publish ``current``. Returns True if the content changed."""
        now = datetime.now(timezone.utc)
        detection = self._detector.detect(previous, current, self._ledger, now)
        if detection.seeds:
            await self._ledger.add(detection.seeds, now)
        for event in detection.events:
            self._queue.setdefault(self._event_key(event), (event, 0))
        await self._flush_queue()

        changed = previous is None or previous.content_dict() != current.content_dict()
        self._snapshot = current
        if persist:
            await self._snapshots.save(current)
        return changed

    async def _flush_queue(self) -> None:
        for key, (event, attempts) in list(self._queue.items()):
            if all(self._ledger.contains(entry) for entry in event.ledger_entries):
                del self._queue[key]  # another path announced it in the meantime
                continue
            if await self._deliver_safely(event):
                await self._ledger.add(event.ledger_entries)
                del self._queue[key]
                logger.info("Announced: %s", event.label)
            elif attempts + 1 >= MAX_DELIVERY_ATTEMPTS:
                logger.error("Giving up on announcing %s after %s attempts", event.label, attempts + 1)
                await self._ledger.add(event.ledger_entries)
                del self._queue[key]
            else:
                self._queue[key] = (event, attempts + 1)

    async def _deliver_safely(self, event: DomainEvent) -> bool:
        try:
            return await self._sink.deliver(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not deliver %s", type(event).__name__)
            return False

    @staticmethod
    def _event_key(event: UpgradeEvent) -> str:
        return event.ledger_entries[0].key

    async def _maybe_prune(self, current: Snapshot) -> None:
        now = datetime.now(timezone.utc)
        if now - self._last_prune >= PRUNE_EVERY:
            self._last_prune = now
            await self._ledger.prune(upgrade.key for upgrade in current.upgrades)

    # ----- scheduling --------------------------------------------------------------

    def _release_waiters(self, sequence: int) -> None:
        remaining = []
        for target, future in self._waiters:
            if target <= sequence:
                if not future.done():
                    future.set_result(None)
            else:
                remaining.append((target, future))
        self._waiters = remaining

    def _wait_seconds(self, next_poll_at: float) -> float:
        delay = next_poll_at - time.monotonic()
        if self._announce_on_timer:
            until_finish = self._seconds_until_next_finish()
            if until_finish is not None:
                delay = min(delay, until_finish)
        if self._queue:
            delay = min(delay, RETRY_SECONDS)
        return min(max(delay, 1.0), float(self._poll_interval))

    def _seconds_until_next_finish(self) -> float | None:
        now = datetime.now(timezone.utc)
        pending = [
            (upgrade.finish_at - now).total_seconds()
            for upgrade in self._snapshot.upgrades
            if upgrade.finish_at and upgrade.finish_at > now
            and not self._ledger.contains(LedgerEntry(upgrade.key, upgrade.finish_at))
        ]
        return min(pending) + 0.5 if pending else None

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except TimeoutError:
            pass
        self._wake.clear()

    @staticmethod
    def _describe_nearest(snapshot: Snapshot) -> str:
        nearest = snapshot.nearest_upgrade()
        if nearest is None:
            return "нет таймеров"
        remaining = int(nearest.seconds_left(datetime.now(timezone.utc)) or 0)
        return f"{nearest.village_name} / {nearest.entity} {nearest.level}, осталось: {format_duration(remaining)}"
