from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.clash_ninja.game_data import BUILDINGS, HEROES, HELPERS, PETS, SPELLS, TRAPS, TROOPS
from app.models import HelperStatus, Snapshot, Upgrade

logger = logging.getLogger(__name__)


def _name(identifier: int, mapping: dict[int, str]) -> str:
    return mapping.get(identifier, f"ID {identifier}")


def _finish(timestamp: int, timer: Any) -> datetime | None:
    try:
        seconds = int(timer)
        if seconds <= 0:
            return None
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc) + timedelta(seconds=seconds)
    except (TypeError, ValueError, OSError):
        return None


def parse_account_json(payload: dict[str, Any], filename: str, now: datetime | None = None) -> Snapshot:
    fetched_at = now or datetime.now(timezone.utc)
    timestamp = int(payload.get("timestamp", int(fetched_at.timestamp())))
    village_id = str(payload.get("village_id") or payload.get("tag") or Path(filename).stem)
    village_name = str(payload.get("name") or payload.get("village_name") or Path(filename).stem)
    upgrades: list[Upgrade] = []
    counters: dict[tuple[str, int], int] = {}
    lab_assistant_target: str | None = None

    groups = (("buildings", "builder", BUILDINGS), ("traps", "builder", TRAPS),
              ("heroes", "builder", HEROES), ("units", "lab", TROOPS),
              ("spells", "lab", SPELLS), ("pets", "pet", PETS))
    for field, category, mapping in groups:
        for item in payload.get(field, []) or []:
            if not isinstance(item, dict) or "timer" not in item:
                continue
            try:
                identifier = int(item["data"])
                level = int(item.get("lvl", 0))
            except (TypeError, ValueError):
                continue
            finish_at = _finish(timestamp, item.get("timer"))
            if not finish_at:
                continue
            key = (category, identifier)
            counters[key] = counters.get(key, 0) + 1
            label = _name(identifier, mapping)
            if counters[key] > 1 or sum(1 for x in payload.get(field, []) or [] if isinstance(x, dict) and x.get("data") == identifier) > 1:
                label = f"{label} #{counters[key]}"
            level_text = f"{level} → {level + 1}"
            upgrades.append(Upgrade(village_id, village_name, category, label, level_text, finish_at, f"json:{field}:{identifier}:{counters[key]}"))
            if item.get("helper_recurrent") and category == "lab":
                lab_assistant_target = f"{label} {level_text}"

    helpers: list[HelperStatus] = []
    for item in payload.get("helpers", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            helper_id = int(item["data"])
        except (KeyError, TypeError, ValueError):
            continue
        helper_name = HELPERS.get(helper_id)
        if not helper_name:
            continue
        until = _finish(timestamp, item.get("helper_cooldown"))
        state = "cooldown" if until and until > fetched_at else "available"
        target = None
        if helper_name == "Lab Assistant" and lab_assistant_target:
            state = "assigned"
            target = lab_assistant_target
        helpers.append(HelperStatus(village_id, village_name, helper_name, state, target, until))

    return Snapshot(((village_id, village_name),), tuple(upgrades), tuple(helpers), fetched_at)


class JsonAccountSource:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def fetch_snapshot(self) -> Snapshot:
        if not self._directory.exists():
            raise RuntimeError(f"Папка JSON-аккаунтов не найдена: {self._directory}")
        snapshots: list[Snapshot] = []
        for path in sorted(self._directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                snapshots.append(parse_account_json(payload, path.name))
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
                logger.error("Не удалось прочитать JSON аккаунта %s: %s", path.name, error)
        if not snapshots:
            raise RuntimeError(f"В папке {self._directory} нет корректных JSON-файлов аккаунтов")
        fetched_at = max(snapshot.fetched_at for snapshot in snapshots)
        return Snapshot(tuple(v for snapshot in snapshots for v in snapshot.villages),
                        tuple(u for snapshot in snapshots for u in snapshot.upgrades),
                        tuple(h for snapshot in snapshots for h in snapshot.helpers), fetched_at)
