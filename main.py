from __future__ import annotations

import asyncio
import logging

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
    notifier = NotificationService(bot, storage, settings.notification_chat_ids)
    monitor = UpgradeMonitor(client, storage, settings.poll_interval_seconds, notifier.send)
    dashboard = DashboardService(bot, storage, monitor)
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass
