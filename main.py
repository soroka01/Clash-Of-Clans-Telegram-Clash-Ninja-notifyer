from __future__ import annotations

import asyncio
import logging
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
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(log_directory / "bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    error_handler = RotatingFileHandler(log_directory / "error.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file_handler, error_handler])
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass
