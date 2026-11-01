from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.models import HelperStatus, Upgrade


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """Identity of something that must be announced at most once."""

    key: str
    finish_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UpgradeCompleted:
    """An upgrade finished; ``freed_helpers`` stopped working on it at the same moment."""

    upgrade: Upgrade
    freed_helpers: tuple[HelperStatus, ...] = ()

    @property
    def ledger_entries(self) -> tuple[LedgerEntry, ...]:
        entries = [LedgerEntry(self.upgrade.key, self.upgrade.finish_at)]
        entries.extend(LedgerEntry(helper.release_key(self.upgrade.target_label)) for helper in self.freed_helpers)
        return tuple(entries)

    @property
    def label(self) -> str:
        return self.upgrade.entity


@dataclass(frozen=True, slots=True)
class HelperReleased:
    """A helper stopped working on ``target`` without a matching completed upgrade."""

    helper: HelperStatus
    target: str | None = None

    @property
    def ledger_entries(self) -> tuple[LedgerEntry, ...]:
        return (LedgerEntry(self.helper.release_key(self.target)),)

    @property
    def label(self) -> str:
        return self.helper.helper_name


@dataclass(frozen=True, slots=True)
class SourceDown:
    """The data source has been failing for a while."""

    reason: str
    since: datetime
    failures: int


@dataclass(frozen=True, slots=True)
class SourceRecovered:
    down_since: datetime


UpgradeEvent = UpgradeCompleted | HelperReleased
DomainEvent = UpgradeEvent | SourceDown | SourceRecovered
