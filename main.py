from __future__ import annotations

import asyncio
import logging
import os
import sys
from ctypes import byref, c_uint, windll
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.clash_ninja.client import ClashNinjaClient
from app.config import load_settings
from app.monitor import UpgradeMonitor
from app.storage import Storage
from app.telegram_ui import (
    DashboardService,
    NotificationService,
    dashboard_refresh_loop,
    make_router,
)


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, *args: object, use_colors: bool = True, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if not self._use_colors:
            return message
        return f"{self.COLORS.get(record.levelno, '')}{message}{self.RESET}"


def _console_supports_colors() -> bool:
    """Enable ANSI on supported Windows consoles; otherwise keep logs clean."""
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    try:
        stdout_handle = windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = c_uint()
        if not windll.kernel32.GetConsoleMode(stdout_handle, byref(mode)):
            return False
        return bool(windll.kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


async def run() -> None:
    settings = load_settings()
    storage = Storage(settings.database_path)
    client = ClashNinjaClient(settings.clash_ninja)
    await client.start()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    notifier = NotificationService(bot, storage, settings.notification_chat_ids, settings.utc_offset_hours)
    monitor = UpgradeMonitor(client, storage, settings.poll_interval_seconds, notifier.send)
    dashboard = DashboardService(bot, storage, monitor, settings.utc_offset_hours)
    dispatcher = Dispatcher()
    dispatcher.include_router(make_router(dashboard, settings.authorized_user_ids))
    refresh_stop = asyncio.Event()
    monitor_task = asyncio.create_task(monitor.run(), name="clash-ninja-monitor")
    dashboard_task = asyncio.create_task(
        dashboard_refresh_loop(dashboard, settings.dashboard_refresh_seconds, refresh_stop),
        name="dashboard-refresh",
    )

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        monitor.stop()
        refresh_stop.set()
        monitor_task.cancel()
        dashboard_task.cancel()
        await asyncio.gather(monitor_task, dashboard_task, return_exceptions=True)
        await client.close()
        await storage.close()
        await bot.session.close()


if __name__ == "__main__":
    log_directory = Path("logs")
    log_directory.mkdir(exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-15s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(
        ColorFormatter(
            formatter._style._fmt,
            datefmt="%Y-%m-%d %H:%M:%S",
            use_colors=_console_supports_colors(),
        )
    )
    file_handler = RotatingFileHandler(log_directory / "bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    error_handler = RotatingFileHandler(log_directory / "error.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file_handler, error_handler])
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass
