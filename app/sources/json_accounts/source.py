from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.domain.models import Snapshot
from app.sources.json_accounts.parser import AccountJsonParser
from app.sources.json_accounts.store import AccountStore

logger = logging.getLogger(__name__)
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


class JsonAccountSource:
    """Snapshot source backed by the game exports stored in the accounts folder."""

    def __init__(self, store: AccountStore, parser: AccountJsonParser) -> None:
        self._store = store
        self._parser = parser
        self._reported_duplicates: set[str] = set()

    async def start(self) -> None:
        if self._store.ensure_directory():
            logger.info("Папка JSON-аккаунтов создана: %s", self._store.directory)

    async def close(self) -> None:
        return None

    async def fetch_snapshot(self) -> Snapshot:
        return await asyncio.to_thread(self._build)

    def _build(self) -> Snapshot:
        # One account per village id. When two files hold the same account, the newest export wins.
        newest: dict[str, tuple] = {}
        for record, payload in self._store.load_all():
            current = newest.get(record.village_id)
            if current is None or (record.exported_at or _EPOCH) > (current[0].exported_at or _EPOCH):
                if current is not None:
                    self._warn_duplicate(record.village_id, current[0].name, record.name)
                newest[record.village_id] = (record, payload)
            else:
                self._warn_duplicate(record.village_id, record.name, current[0].name)
        parts = [self._parser.parse(payload, record.name) for record, payload in newest.values()]
        parts.sort(key=lambda part: part.villages[0].name.casefold())
        return Snapshot.merge(parts)

    def _warn_duplicate(self, village_id: str, ignored: str, kept: str) -> None:
        marker = f"{village_id}|{ignored}|{kept}"
        if marker not in self._reported_duplicates:
            self._reported_duplicates.add(marker)
            logger.warning("Файлы «%s» и «%s» содержат один аккаунт; используется «%s»", ignored, kept, kept)
