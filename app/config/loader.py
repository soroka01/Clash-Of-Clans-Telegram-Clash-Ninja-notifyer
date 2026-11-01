from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from app.config.settings import (
    DATA_SOURCE_CLASH_NINJA,
    DATA_SOURCE_JSON,
    ClashNinjaSettings,
    ImportSettings,
    Settings,
)

CookieProvider = Callable[[], "str | None"]

_REQUIRED = ("bot_token", "authorized_user_ids", "notification_chat_ids")
_DEFAULT_TRACKER_URL = "https://www.clash.ninja/upgrade-tracker"


class SettingsLoader:
    """Reads and validates config.json. All problems are reported as RuntimeError in Russian."""

    def __init__(self, path: str | Path = "config.json", cookie_provider: CookieProvider | None = None) -> None:
        self._path = Path(path)
        self._cookie_provider = cookie_provider

    def load(self) -> Settings:
        raw = self._read()
        self._require_fields(raw)
        data_source = str(raw.get("data_source", DATA_SOURCE_CLASH_NINJA)).casefold()
        if data_source not in {DATA_SOURCE_CLASH_NINJA, DATA_SOURCE_JSON}:
            raise RuntimeError("data_source должен быть clash_ninja или json")
        token = str(raw["bot_token"]).strip()
        if not token or token.startswith("PUT_"):
            raise RuntimeError("Укажите bot_token в config.json")
        utc_offset_hours = self._int(raw, "utc_offset_hours", 0)
        if not -12 <= utc_offset_hours <= 14:
            raise RuntimeError("utc_offset_hours должен быть целым числом от -12 до 14")

        return Settings(
            bot_token=token,
            authorized_user_ids=frozenset(self._int_list(raw, "authorized_user_ids")),
            notification_chat_ids=tuple(self._int_list(raw, "notification_chat_ids")),
            poll_interval_seconds=max(30, self._int(raw, "poll_interval_seconds", 60)),
            dashboard_refresh_seconds=max(10, self._int(raw, "dashboard_refresh_seconds", 10)),
            utc_offset_hours=utc_offset_hours,
            database_path=Path(raw.get("database_path", "data/clash_ninja_bot.sqlite3")),
            data_source=data_source,
            json_accounts_directory=Path(raw.get("json_accounts_directory", "accounts")),
            clash_ninja=self._clash_ninja(raw) if data_source == DATA_SOURCE_CLASH_NINJA else None,
            announce_on_timer=bool(raw.get("announce_on_timer", True)),
            announce_max_age_hours=max(1, self._int(raw, "announce_max_age_hours", 24)),
            failure_alert_threshold=max(0, self._int(raw, "failure_alert_threshold", 3)),
            json_import=self._import_settings(raw),
        )

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise RuntimeError(f"Не найден файл настроек: {self._path}") from error
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Некорректный JSON в {self._path}: {error}") from error
        if not isinstance(raw, dict):
            raise RuntimeError(f"{self._path} должен содержать JSON-объект")
        return raw

    def _require_fields(self, raw: dict[str, Any]) -> None:
        missing = [key for key in _REQUIRED if key not in raw]
        if missing:
            raise RuntimeError(f"В {self._path} отсутствуют поля: {', '.join(missing)}")

    @staticmethod
    def _int(raw: dict[str, Any], key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except (TypeError, ValueError) as error:
            raise RuntimeError(f"Поле {key} должно быть целым числом") from error

    @staticmethod
    def _int_list(raw: dict[str, Any], key: str) -> list[int]:
        value = raw[key]
        if not isinstance(value, list):
            raise RuntimeError(f"Поле {key} должно быть списком чисел")
        try:
            return [int(item) for item in value]
        except (TypeError, ValueError) as error:
            raise RuntimeError(f"Поле {key} должно содержать только числа") from error

    def _clash_ninja(self, raw: dict[str, Any]) -> ClashNinjaSettings:
        ninja = raw.get("clash_ninja") or {}
        cookie_header = (ninja.get("cookie_header") or "").strip()
        if not cookie_header or cookie_header.startswith("PUT_"):
            cookie_header = (self._cookie_provider() if self._cookie_provider else None) or ""
            if not cookie_header:
                raise RuntimeError(
                    "Укажите clash_ninja.cookie_header в config.json или войдите в Clash Ninja в браузере, "
                    "чтобы бот смог найти cookie в AppData. Если браузер открыт, закройте его и повторите запуск"
                )
        return ClashNinjaSettings(
            tracker_url=ninja.get("tracker_url", _DEFAULT_TRACKER_URL),
            cookie_header=cookie_header,
            request_timeout_seconds=max(5, int(ninja.get("request_timeout_seconds", 30))),
        )

    def _import_settings(self, raw: dict[str, Any]) -> ImportSettings:
        section = raw.get("json_import") or {}
        # Bot API downloads stop at 20 MB, so a larger limit could never be reached anyway.
        megabytes = min(19, max(1, int(section.get("max_megabytes", 5))))
        idle_seconds = min(30.0, max(1.0, float(section.get("idle_seconds", 3))))
        return ImportSettings(
            max_bytes=megabytes * 1024 * 1024,
            idle_seconds=idle_seconds,
            delete_messages=bool(section.get("delete_messages", True)),
        )
