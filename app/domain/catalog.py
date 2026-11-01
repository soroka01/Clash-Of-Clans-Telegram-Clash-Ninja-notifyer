from __future__ import annotations

import logging
from typing import Mapping

from app.domain import game_data

logger = logging.getLogger(__name__)


class GameCatalog:
    """Resolves numeric ids from the game export into display names."""

    def __init__(
        self,
        tables: Mapping[str, Mapping[int, str]] | None = None,
        helpers: Mapping[int, str] | None = None,
    ) -> None:
        self._tables = dict(tables if tables is not None else game_data.TABLES)
        self._helpers = dict(helpers if helpers is not None else game_data.HELPERS)
        self._reported: set[tuple[str, int]] = set()

    def name(self, group: str, identifier: int) -> str:
        """Display name of ``identifier`` in an export list such as "buildings" or "units"."""
        name = self._tables.get(group, {}).get(identifier)
        if name is not None:
            return name
        if (group, identifier) not in self._reported:
            self._reported.add((group, identifier))
            logger.warning("Unknown game id in export: group=%s id=%s", group, identifier)
        return f"ID {identifier}"

    def helper_name(self, identifier: int) -> str | None:
        return self._helpers.get(identifier)
