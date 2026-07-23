from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ClashNinjaSettings:
    tracker_url: str
    cookie_header: str
    request_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    authorized_user_ids: frozenset[int]
    notification_chat_ids: tuple[int, ...]
    poll_interval_seconds: int
    dashboard_refresh_seconds: int
    database_path: Path
    clash_ninja: ClashNinjaSettings


def load_settings(path: str | Path = "config.json") -> Settings:
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"Не найден файл настроек: {config_path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Некорректный JSON в {config_path}: {error}") from error

    required = ("bot_token", "authorized_user_ids", "notification_chat_ids", "clash_ninja")
    missing = [key for key in required if key not in raw]
    if missing:
        raise RuntimeError(f"В {config_path} отсутствуют поля: {', '.join(missing)}")

    ninja = raw["clash_ninja"]
    if not raw["bot_token"] or raw["bot_token"].startswith("PUT_"):
        raise RuntimeError("Укажите bot_token в config.json")
    if not ninja.get("cookie_header") or ninja["cookie_header"].startswith("PUT_"):
        raise RuntimeError("Укажите clash_ninja.cookie_header в config.json")

    return Settings(
        bot_token=raw["bot_token"],
        authorized_user_ids=frozenset(map(int, raw["authorized_user_ids"])),
        notification_chat_ids=tuple(map(int, raw["notification_chat_ids"])),
        poll_interval_seconds=max(30, int(raw.get("poll_interval_seconds", 60))),
        dashboard_refresh_seconds=max(10, int(raw.get("dashboard_refresh_seconds", 10))),
        database_path=Path(raw.get("database_path", "data/clash_ninja_bot.sqlite3")),
        clash_ninja=ClashNinjaSettings(
            tracker_url=ninja.get("tracker_url", "https://www.clash.ninja/upgrade-tracker"),
            cookie_header=ninja["cookie_header"],
            request_timeout_seconds=max(5, int(ninja.get("request_timeout_seconds", 30))),
        ),
    )
