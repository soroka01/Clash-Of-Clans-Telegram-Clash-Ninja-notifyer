from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.events import SourceDown, SourceRecovered

DEGRADED_AFTER_FAILURES = 2
_REASON_LIMIT = 200


@dataclass(frozen=True, slots=True)
class HealthNotice:
    """What the UI shows when the data stopped updating."""

    since: datetime
    reason: str
    failures: int


class SourceHealth:
    """Counts consecutive source failures and decides when the owner has to be told.

    One failed poll is noise (a timeout, a restart of the site); a streak is a real problem such as
    an expired Clash Ninja cookie. An alert is sent once per streak, followed by a recovery message.
    """

    def __init__(self, alert_threshold: int) -> None:
        self._alert_threshold = alert_threshold
        self._failures = 0
        self._since: datetime | None = None
        self._reason = ""
        self._alerted = False

    @property
    def failures(self) -> int:
        return self._failures

    @property
    def alerted(self) -> bool:
        return self._alerted

    def notice(self) -> HealthNotice | None:
        """Set once the problem is persistent enough to show in the menus."""
        if self._failures >= DEGRADED_AFTER_FAILURES and self._since is not None:
            return HealthNotice(self._since, self._reason, self._failures)
        return None

    def record_success(self) -> SourceRecovered | None:
        recovered = SourceRecovered(self._since) if self._alerted and self._since else None
        self._failures, self._since, self._reason, self._alerted = 0, None, "", False
        return recovered

    def record_failure(self, error: BaseException, now: datetime) -> SourceDown | None:
        self._failures += 1
        self._since = self._since or now
        self._reason = (str(error).strip() or type(error).__name__)[:_REASON_LIMIT]
        if self._alert_threshold and not self._alerted and self._failures >= self._alert_threshold:
            return SourceDown(self._reason, self._since, self._failures)
        return None

    def mark_alerted(self) -> None:
        self._alerted = True

    def retry_delay(self, base_seconds: int) -> int:
        """Back off while the source keeps failing: 1x, 2x, 4x, then 5x the normal interval."""
        return base_seconds * min(2 ** max(0, self._failures - 1), 5)
