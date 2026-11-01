from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable


class Category(StrEnum):
    """Upgrade categories. Values are persisted in SQLite, so they must stay stable."""

    BUILDER = "builder"
    LAB = "lab"
    PET = "pet"
    HELPER = "helper"


class HelperState(StrEnum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    COOLDOWN = "cooldown"


HELPER_NAMES = {
    "lab assistant": "Lab Assistant",
    "builder's apprentice": "Builder's Apprentice",
    "builders apprentice": "Builder's Apprentice",
    "builder apprentice": "Builder's Apprentice",
    "builder's app": "Builder's Apprentice",
    "alchemist": "Alchemist",
}

_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True, slots=True)
class Upgrade:
    """One real, currently active upgrade."""

    village_id: str
    village_name: str
    category: str  # a Category value
    entity: str
    level: str
    finish_at: datetime | None
    source_id: str | None = None

    @property
    def key(self) -> str:
        # The level is intentional: starting the next level of the same item is a new upgrade.
        return "|".join((self.village_id, self.category, self.entity.casefold(), self.level))

    @property
    def target_label(self) -> str:
        """The text helpers use to point at this upgrade (see HelperStatus.target)."""
        return f"{self.entity} {self.level}"

    @property
    def is_helper(self) -> bool:
        return self.category == Category.HELPER or self.entity.casefold() in HELPER_NAMES

    @property
    def helper_name(self) -> str | None:
        return HELPER_NAMES.get(self.entity.casefold()) if self.is_helper else None

    @property
    def sort_key(self) -> datetime:
        return self.finish_at or _FAR_FUTURE

    def seconds_left(self, now: datetime) -> int | None:
        if self.finish_at is None:
            return None
        return int((self.finish_at - now).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["category"] = str(self.category)
        result["finish_at"] = self.finish_at.isoformat() if self.finish_at else None
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Upgrade":
        return cls(
            village_id=data["village_id"],
            village_name=data["village_name"],
            category=data["category"],
            entity=data["entity"],
            level=data["level"],
            finish_at=_parse_time(data.get("finish_at")),
            source_id=data.get("source_id"),
        )


@dataclass(frozen=True, slots=True)
class HelperStatus:
    village_id: str
    village_name: str
    helper_name: str
    state: str  # a HelperState value
    target: str | None = None
    until: datetime | None = None

    @property
    def key(self) -> str:
        return f"{self.village_id}|{self.helper_name}"

    def release_key(self, target: str | None = None) -> str:
        """Ledger key of "this helper stopped working on <target>"."""
        return f"helper|{self.key}|{target if target is not None else self.target or ''}"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state"] = str(self.state)
        result["until"] = self.until.isoformat() if self.until else None
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HelperStatus":
        return cls(
            village_id=data["village_id"],
            village_name=data["village_name"],
            helper_name=data["helper_name"],
            state=data["state"],
            target=data.get("target"),
            until=_parse_time(data.get("until")),
        )


@dataclass(frozen=True, slots=True)
class Village:
    """One tracked account. ``exported_at`` is when its data was captured (JSON exports only)."""

    id: str
    name: str
    exported_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "exported_at": self.exported_at.isoformat() if self.exported_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | list[Any] | tuple[Any, ...]) -> "Village":
        if isinstance(data, dict):
            return cls(str(data["id"]), str(data["name"]), _parse_time(data.get("exported_at")))
        village_id, name = data  # legacy snapshots stored [id, name] pairs
        return cls(str(village_id), str(name))


@dataclass(frozen=True, slots=True)
class Snapshot:
    villages: tuple[Village, ...]
    upgrades: tuple[Upgrade, ...]
    helpers: tuple[HelperStatus, ...]
    fetched_at: datetime

    @classmethod
    def empty(cls) -> "Snapshot":
        return cls((), (), (), datetime.now(timezone.utc))

    @classmethod
    def merge(cls, parts: Iterable["Snapshot"], fetched_at: datetime | None = None) -> "Snapshot":
        """Combine per-account snapshots; the first occurrence of a village id wins."""
        villages: dict[str, Village] = {}
        upgrades: list[Upgrade] = []
        helpers: list[HelperStatus] = []
        latest = fetched_at
        for part in parts:
            for village in part.villages:
                if village.id in villages:
                    continue
                villages[village.id] = village
                upgrades.extend(item for item in part.upgrades if item.village_id == village.id)
                helpers.extend(item for item in part.helpers if item.village_id == village.id)
            if fetched_at is None and (latest is None or part.fetched_at > latest):
                latest = part.fetched_at
        return cls(tuple(villages.values()), tuple(upgrades), tuple(helpers), latest or datetime.now(timezone.utc))

    @property
    def village_ids(self) -> frozenset[str]:
        return frozenset(village.id for village in self.villages)

    def village(self, village_id: str) -> Village | None:
        return next((village for village in self.villages if village.id == village_id), None)

    def upgrades_of(self, village_id: str) -> list[Upgrade]:
        return [item for item in self.upgrades if item.village_id == village_id]

    def helpers_of(self, village_id: str) -> list[HelperStatus]:
        return [item for item in self.helpers if item.village_id == village_id]

    def nearest_upgrade(self) -> Upgrade | None:
        timed = [item for item in self.upgrades if item.finish_at is not None]
        return min(timed, key=lambda item: item.sort_key) if timed else None

    def content_dict(self) -> dict[str, Any]:
        """Everything except the fetch time: equal dicts mean "nothing changed"."""
        return {
            "villages": [village.to_dict() for village in self.villages],
            "upgrades": [upgrade.to_dict() for upgrade in self.upgrades],
            "helpers": [helper.to_dict() for helper in self.helpers],
        }

    def to_dict(self) -> dict[str, Any]:
        return {"fetched_at": self.fetched_at.isoformat(), **self.content_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snapshot":
        return cls(
            villages=tuple(Village.from_dict(item) for item in data.get("villages", [])),
            upgrades=tuple(Upgrade.from_dict(item) for item in data["upgrades"]),
            helpers=tuple(HelperStatus.from_dict(item) for item in data.get("helpers", [])),
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
        )
