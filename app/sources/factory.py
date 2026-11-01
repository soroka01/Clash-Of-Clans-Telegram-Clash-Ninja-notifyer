from __future__ import annotations

from app.config.settings import Settings
from app.domain.catalog import GameCatalog
from app.sources.base import SnapshotSource
from app.sources.clash_ninja.client import ClashNinjaClient
from app.sources.json_accounts.parser import AccountJsonParser
from app.sources.json_accounts.source import JsonAccountSource
from app.sources.json_accounts.store import AccountStore


class SourceFactory:
    """Builds the configured snapshot source."""

    def __init__(self, settings: Settings, store: AccountStore, catalog: GameCatalog) -> None:
        self._settings = settings
        self._store = store
        self._catalog = catalog

    def build(self) -> SnapshotSource:
        if self._settings.clash_ninja is not None:
            return ClashNinjaClient(self._settings.clash_ninja)
        return JsonAccountSource(self._store, AccountJsonParser(self._catalog))
