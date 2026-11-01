from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.domain.events import HelperReleased, LedgerEntry, UpgradeCompleted, UpgradeEvent
from app.domain.models import HelperState, HelperStatus, Snapshot, Upgrade
from app.storage.ledger import AnnouncementLedger


@dataclass(slots=True)
class Detection:
    events: list[UpgradeEvent] = field(default_factory=list)
    # Things that already happened before we started watching: remembered silently, never announced.
    seeds: list[LedgerEntry] = field(default_factory=list)


class EventDetector:
    """Works out what has to be announced. Pure: all state comes in through the arguments.

    An upgrade counts as completed when either
      * its finish time has passed (``announce_on_timer``), which also covers sources that only
        change when the user re-exports their data, or
      * it vanished from the newest data shortly before / after its finish time (this also catches
        completions sped up with gems, books or hammers).
    The ledger keeps both paths from announcing the same upgrade twice.
    """

    def __init__(
        self,
        poll_interval_seconds: int,
        announce_on_timer: bool,
        max_age: timedelta = timedelta(hours=24),
    ) -> None:
        self._tolerance = timedelta(seconds=max(poll_interval_seconds * 2, 120))
        self._announce_on_timer = announce_on_timer
        self._max_age = max_age

    def detect(
        self,
        previous: Snapshot | None,
        current: Snapshot,
        ledger: AnnouncementLedger,
        now: datetime,
    ) -> Detection:
        detection = Detection()
        completed = self._completed(previous, current, ledger, now, detection)
        releases = self._released_helpers(previous, current, ledger)

        attached: set[str] = set()
        for upgrade in sorted(completed, key=lambda item: item.sort_key):
            freed = tuple(
                helper
                for helper, target in releases
                if helper.village_id == upgrade.village_id and target == upgrade.target_label
            )
            attached.update(helper.release_key(upgrade.target_label) for helper in freed)
            detection.events.append(UpgradeCompleted(upgrade, freed))
        for helper, target in releases:
            if helper.release_key(target) not in attached:
                detection.events.append(HelperReleased(helper, target))
        return detection

    def _completed(
        self,
        previous: Snapshot | None,
        current: Snapshot,
        ledger: AnnouncementLedger,
        now: datetime,
        detection: Detection,
    ) -> list[Upgrade]:
        completed: list[Upgrade] = []
        known_villages = previous.village_ids if previous else frozenset()

        if self._announce_on_timer:
            for upgrade in current.upgrades:
                if upgrade.finish_at is None or upgrade.finish_at > now:
                    continue
                entry = LedgerEntry(upgrade.key, upgrade.finish_at)
                if ledger.contains(entry):
                    continue
                if upgrade.village_id in known_villages and now - upgrade.finish_at <= self._max_age:
                    completed.append(upgrade)
                else:
                    # A fresh start, a newly added account or an export that was never refreshed:
                    # timers that ended long ago are history, not news.
                    detection.seeds.append(entry)

        if previous:
            active_now = {upgrade.key for upgrade in current.upgrades}
            present_villages = current.village_ids
            for upgrade in previous.upgrades:
                if upgrade.key in active_now or upgrade.village_id not in present_villages:
                    continue
                if upgrade.finish_at is None or upgrade.finish_at > now + self._tolerance:
                    continue  # gone long before its finish time: cancelled, not completed
                if ledger.contains(LedgerEntry(upgrade.key, upgrade.finish_at)):
                    continue
                completed.append(upgrade)
        return completed

    @staticmethod
    def _released_helpers(
        previous: Snapshot | None, current: Snapshot, ledger: AnnouncementLedger
    ) -> list[tuple[HelperStatus, str | None]]:
        """Helpers that went from working on something to idle, with what they were working on."""
        if previous is None:
            return []
        before = {helper.key: helper for helper in previous.helpers}
        released: list[tuple[HelperStatus, str | None]] = []
        for helper in current.helpers:
            old = before.get(helper.key)
            if helper.state != HelperState.AVAILABLE or old is None or old.state != HelperState.ASSIGNED:
                continue
            if ledger.contains(LedgerEntry(helper.release_key(old.target))):
                continue
            released.append((helper, old.target))
        return released
