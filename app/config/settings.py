from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DATA_SOURCE_CLASH_NINJA = "clash_ninja"
DATA_SOURCE_JSON = "json"


@dataclass(frozen=True, slots=True)
class ClashNinjaSettings:
    tracker_url: str
    cookie_header: str
    request_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class ImportSettings:
    """Limits for receiving game JSON exports through Telegram."""

    max_bytes: int
    idle_seconds: float
    delete_messages: bool  # remove the user's pasted chunks after a successful import


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    authorized_user_ids: frozenset[int]
    notification_chat_ids: tuple[int, ...]
    poll_interval_seconds: int
    dashboard_refresh_seconds: int
    utc_offset_hours: int
    database_path: Path
    data_source: str
    json_accounts_directory: Path
    clash_ninja: ClashNinjaSettings | None
    announce_on_timer: bool
    announce_max_age_hours: int
    failure_alert_threshold: int
    json_import: ImportSettings

    @property
    def uses_json_accounts(self) -> bool:
        return self.data_source == DATA_SOURCE_JSON

    @property
    def import_available(self) -> bool:
        """Importing writes files, so it needs the JSON source and a closed list of users."""
        return self.uses_json_accounts and bool(self.authorized_user_ids)
