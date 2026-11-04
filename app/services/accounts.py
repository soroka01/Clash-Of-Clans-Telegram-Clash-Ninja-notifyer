from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.models import Snapshot
from app.services.monitor import UpgradeMonitor
from app.sources.json_accounts.parser import AccountJsonParser, export_tag, validate_export
from app.sources.json_accounts.store import AccountRecord, AccountStore, AccountStoreError, sanitize_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AccountSummary:
    village_id: str
    name: str
    tag: str | None
    exported_at: datetime | None
    size: int
    upgrades: int
    manageable: bool  # JSON accounts can be replaced, renamed and removed; Clash Ninja ones cannot


@dataclass(frozen=True, slots=True)
class SaveResult:
    summary: AccountSummary
    created: bool
    requested_name_taken: bool  # the wanted name belonged to another account, so a number was added


class AccountService:
    """Account operations shared by the Telegram screens and the JSON importer."""

    def __init__(self, store: AccountStore | None, parser: AccountJsonParser | None, monitor: UpgradeMonitor) -> None:
        self._store = store
        self._parser = parser
        self._monitor = monitor

    @property
    def manageable(self) -> bool:
        return self._store is not None

    # ----- reading -----------------------------------------------------------------

    async def accounts(self) -> list[AccountSummary]:
        snapshot = self._monitor.snapshot
        if self._store is None:
            return [
                AccountSummary(v.id, v.name, None, v.exported_at, 0, len(snapshot.upgrades_of(v.id)), False)
                for v in snapshot.villages
            ]
        records = await asyncio.to_thread(self._store.records)
        return [self._summarize(record, snapshot) for record in records]

    async def get(self, village_id: str) -> AccountSummary | None:
        return next((item for item in await self.accounts() if item.village_id == village_id), None)

    @staticmethod
    def _summarize(record: AccountRecord, snapshot: Snapshot) -> AccountSummary:
        return AccountSummary(
            village_id=record.village_id,
            name=record.name,
            tag=record.tag,
            exported_at=record.exported_at,
            size=record.size,
            upgrades=len(snapshot.upgrades_of(record.village_id)),
            manageable=True,
        )

    async def read_export(self, village_id: str) -> tuple[str, bytes]:
        record = await self._record(village_id)
        data = await asyncio.to_thread(self._store.read_text, record)
        return f"{record.name}.json", data

    # ----- changing ----------------------------------------------------------------

    def validate(self, payload: Any) -> dict[str, Any]:
        """Raise InvalidExport unless the payload is a village export (and the parser accepts it)."""
        validated = validate_export(payload)
        if self._parser is not None:
            self._parser.parse(validated, "check")
        return validated

    async def save_export(
        self, payload: dict[str, Any], preferred_name: str | None, replace_village_id: str | None = None
    ) -> SaveResult:
        """Store an export. The same player tag always updates the existing account in place;
        ``replace_village_id`` additionally lets the user overwrite a chosen account with another tag."""
        store = self._require_store()
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        tag = export_tag(payload)

        def write() -> tuple[AccountRecord, bool, bool]:
            existing = store.find_by_tag(tag)
            if existing is None and replace_village_id:
                existing = store.find_by_village_id(replace_village_id)
            if existing is not None:
                return store.save(existing.name, content), False, False
            wanted = sanitize_name(preferred_name or "") or sanitize_name(tag.lstrip("#") if tag else "") or "Аккаунт"
            name = store.unique_name(wanted)
            return store.save(name, content), True, name != wanted

        record, created, name_taken = await asyncio.to_thread(write)
        await self._monitor.refresh_now()
        logger.info("Account %s: %s (%s bytes)", "added" if created else "updated", record.name, record.size)
        summary = self._summarize(record, self._monitor.snapshot)
        return SaveResult(summary, created, name_taken)

    async def rename(self, village_id: str, new_name: str) -> AccountSummary:
        record = await self._record(village_id)
        renamed = await asyncio.to_thread(self._store.rename, record, new_name)
        await self._monitor.refresh_now()
        logger.info("Account renamed: %s -> %s", record.name, renamed.name)
        return self._summarize(renamed, self._monitor.snapshot)

    async def delete(self, village_id: str) -> str:
        record = await self._record(village_id)
        await asyncio.to_thread(self._store.delete, record)
        await self._monitor.refresh_now()
        logger.info("Account deleted (moved to trash): %s", record.name)
        return record.name

    # ----- helpers -----------------------------------------------------------------

    def _require_store(self) -> AccountStore:
        if self._store is None:
            raise AccountStoreError("Аккаунтами можно управлять только в режиме data_source = json.")
        return self._store

    async def _record(self, village_id: str) -> AccountRecord:
        store = self._require_store()
        record = await asyncio.to_thread(store.find_by_village_id, village_id)
        if record is None:
            raise AccountStoreError("Аккаунт не найден — возможно, он уже удалён.")
        return record
