from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


HELPER_NAMES = {
    "lab assistant": "Lab Assistant",
    "builder's apprentice": "Builder's Apprentice",
    "builders apprentice": "Builder's Apprentice",
    "builder apprentice": "Builder's Apprentice",
    "builder's app": "Builder's Apprentice",
    "alchemist": "Alchemist",
}


@dataclass(frozen=True, slots=True)
class Upgrade:
    """One real, currently active upgrade from the tracker page."""

    village_id: str
    village_name: str
    category: str  # builder | lab | pet | helper
    entity: str
    level: str
    finish_at: datetime | None
    source_id: str | None = None

    @property
    def key(self) -> str:
        # The level is intentional: starting the next level of the same item is a new upgrade.
        return "|".join((self.village_id, self.category, self.entity.casefold(), self.level))

    @property
    def is_helper(self) -> bool:
        return self.category == "helper" or self.entity.casefold() in HELPER_NAMES

    @property
    def helper_name(self) -> str | None:
        return HELPER_NAMES.get(self.entity.casefold()) if self.is_helper else None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["finish_at"] = self.finish_at.isoformat() if self.finish_at else None
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Upgrade":
        finish_at = data.get("finish_at")
        return cls(
            village_id=data["village_id"],
            village_name=data["village_name"],
            category=data["category"],
            entity=data["entity"],
            level=data["level"],
            finish_at=datetime.fromisoformat(finish_at) if finish_at else None,
            source_id=data.get("source_id"),
        )


@dataclass(frozen=True, slots=True)
class HelperStatus:
    village_id: str
    village_name: str
    helper_name: str
    state: str  # available | assigned | cooldown
    target: str | None = None
    until: datetime | None = None

    @property
    def key(self) -> str:
        return f"{self.village_id}|{self.helper_name}"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["until"] = self.until.isoformat() if self.until else None
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HelperStatus":
        until = data.get("until")
        return cls(
            village_id=data["village_id"],
            village_name=data["village_name"],
            helper_name=data["helper_name"],
            state=data["state"],
            target=data.get("target"),
            until=datetime.fromisoformat(until) if until else None,
        )


@dataclass(frozen=True, slots=True)
class Snapshot:
    villages: tuple[tuple[str, str], ...]
    upgrades: tuple[Upgrade, ...]
    helpers: tuple[HelperStatus, ...]
    fetched_at: datetime

    @classmethod
    def empty(cls) -> "Snapshot":
        return cls((), (), (), datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at.isoformat(),
            "villages": list(self.villages),
            "upgrades": [upgrade.to_dict() for upgrade in self.upgrades],
            "helpers": [helper.to_dict() for helper in self.helpers],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snapshot":
        return cls(
            villages=tuple(tuple(item) for item in data.get("villages", [])),
            upgrades=tuple(Upgrade.from_dict(item) for item in data["upgrades"]),
            helpers=tuple(HelperStatus.from_dict(item) for item in data.get("helpers", [])),
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
        )
