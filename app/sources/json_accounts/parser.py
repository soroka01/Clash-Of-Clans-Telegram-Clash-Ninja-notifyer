from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.catalog import GameCatalog
from app.domain.models import Category, HelperState, HelperStatus, Snapshot, Upgrade, Village

logger = logging.getLogger(__name__)

# (export list, category). Builder Base lists carry a "2" suffix (buildings2, units2, ...) and are
# deliberately not listed here: the bot tracks the home village only.
UPGRADE_GROUPS: tuple[tuple[str, Category], ...] = (
    ("buildings", Category.BUILDER),
    ("traps", Category.BUILDER),
    ("heroes", Category.BUILDER),
    ("units", Category.LAB),
    ("siege_machines", Category.LAB),
    ("spells", Category.LAB),
    ("pets", Category.PET),
)
_LAB_ASSISTANT = "Lab Assistant"


class InvalidExport(ValueError):
    """The payload is not a Clash of Clans village export. The message is shown to the user."""


_TAG = re.compile(r"#?[0-9A-Za-z]{3,20}")


def export_tag(payload: dict[str, Any]) -> str | None:
    """The player tag, if the export has one in the expected shape (it becomes the account identity)."""
    tag = payload.get("tag")
    if not isinstance(tag, str):
        return None
    tag = tag.strip()
    return tag if _TAG.fullmatch(tag) else None


def export_village_id(payload: dict[str, Any], account_name: str) -> str:
    """Stable account identity: explicit village_id, else the player tag, else the file name."""
    return str(payload.get("village_id") or export_tag(payload) or account_name)


def export_time(payload: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(payload["timestamp"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None


def validate_export(payload: Any) -> dict[str, Any]:
    """Raise InvalidExport unless ``payload`` looks like a village export; return it as a dict."""
    if not isinstance(payload, dict):
        raise InvalidExport("Ожидался JSON-объект экспорта деревни, а получен другой тип данных.")
    if not isinstance(payload.get("buildings"), list):
        raise InvalidExport("Это не экспорт деревни Clash of Clans: в JSON нет списка buildings.")
    if export_tag(payload) is None and export_time(payload) is None:
        raise InvalidExport("Это не экспорт деревни Clash of Clans: в JSON нет ни tag, ни timestamp.")
    return payload


def _finish(timestamp: int, timer: Any) -> datetime | None:
    try:
        seconds = int(timer)
        if seconds <= 0:
            return None
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc) + timedelta(seconds=seconds)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class AccountJsonParser:
    """Turns one in-game village export into a Snapshot of its active timers."""

    def __init__(self, catalog: GameCatalog) -> None:
        self._catalog = catalog

    def parse(self, payload: dict[str, Any], account_name: str, now: datetime | None = None) -> Snapshot:
        fetched_at = now or datetime.now(timezone.utc)
        exported_at = export_time(payload)
        timestamp = int(exported_at.timestamp()) if exported_at else int(fetched_at.timestamp())
        village_id = export_village_id(payload, account_name)

        upgrades, lab_assistant_target = self._upgrades(payload, village_id, account_name, timestamp)
        helpers = self._helpers(payload, village_id, account_name, timestamp, fetched_at, lab_assistant_target)
        return Snapshot((Village(village_id, account_name, exported_at),), tuple(upgrades), tuple(helpers), fetched_at)

    def _upgrades(
        self, payload: dict[str, Any], village_id: str, account_name: str, timestamp: int
    ) -> tuple[list[Upgrade], str | None]:
        upgrades: list[Upgrade] = []
        lab_assistant_target: str | None = None
        for field, category in UPGRADE_GROUPS:
            # Ordered by finish time so the "#n" numbering does not swap between exports.
            timed = sorted(self._timed_items(payload.get(field), timestamp), key=lambda entry: (entry[0], entry[2]))
            # Same item upgrading more than once at a time (e.g. two Wizard Towers) needs numbering.
            copies = Counter(identifier for identifier, *_ in timed)
            seen: Counter[int] = Counter()
            for identifier, level, finish_at, item in timed:
                seen[identifier] += 1
                label = self._catalog.name(field, identifier)
                if copies[identifier] > 1:
                    label = f"{label} #{seen[identifier]}"
                level_text = f"{level} → {level + 1}"
                upgrades.append(
                    Upgrade(
                        village_id,
                        account_name,
                        category,
                        label,
                        level_text,
                        finish_at,
                        f"json:{field}:{identifier}:{seen[identifier]}",
                    )
                )
                if item.get("helper_recurrent") and category == Category.LAB:
                    lab_assistant_target = f"{label} {level_text}"
        return upgrades, lab_assistant_target

    @staticmethod
    def _timed_items(items: Any, timestamp: int):
        """Yield (id, level, finish_at, raw item) for every entry that has a running timer."""
        for item in items or []:
            if not isinstance(item, dict) or "timer" not in item:
                continue
            try:
                identifier = int(item["data"])
                level = int(item.get("lvl", 0))
            except (KeyError, TypeError, ValueError):
                continue
            finish_at = _finish(timestamp, item.get("timer"))
            if finish_at:
                yield identifier, level, finish_at, item

    def _helpers(
        self,
        payload: dict[str, Any],
        village_id: str,
        account_name: str,
        timestamp: int,
        fetched_at: datetime,
        lab_assistant_target: str | None,
    ) -> list[HelperStatus]:
        helpers: list[HelperStatus] = []
        for item in payload.get("helpers") or []:
            if not isinstance(item, dict):
                continue
            try:
                helper_id = int(item["data"])
            except (KeyError, TypeError, ValueError):
                continue
            helper_name = self._catalog.helper_name(helper_id)
            if not helper_name:
                continue
            until = _finish(timestamp, item.get("helper_cooldown"))
            state = HelperState.COOLDOWN if until and until > fetched_at else HelperState.AVAILABLE
            target = None
            if helper_name == _LAB_ASSISTANT and lab_assistant_target:
                state, target = HelperState.ASSIGNED, lab_assistant_target
            helpers.append(HelperStatus(village_id, account_name, helper_name, state, target, until))
        return helpers
