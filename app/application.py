from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import Settings, SettingsLoader
from app.domain.catalog import GameCatalog
from app.services.accounts import AccountService
from app.services.detector import EventDetector
from app.services.health import SourceHealth
from app.services.importer import ImportService
from app.services.monitor import UpgradeMonitor
from app.sources.clash_ninja.cookies import CookieDiscoverer
from app.sources.base import SnapshotSource
from app.sources.factory import SourceFactory
from app.sources.json_accounts.parser import AccountJsonParser
from app.sources.json_accounts.store import AccountStore
from app.storage import (
    AlertRepository,
    AnnouncementLedger,
    ChatPreferences,
    Database,
    MenuRepository,
    SnapshotRepository,
)
from app.ui.access import AccessControl
from app.ui.gateway import TelegramGateway
from app.ui.handlers.accounts import AccountHandlers, RenameRequests
from app.ui.handlers.importing import ImportHandlers
from app.ui.handlers.navigation import NavigationHandlers
from app.ui.handlers.settings import SettingsHandlers
from app.ui.import_presenter import ImportPresenter
from app.ui.menu_service import MenuService, refresh_loop
from app.ui.notifier import NotificationService
from app.ui.render.notifications import NotificationRenderer
from app.ui.router import build_router
from app.ui.screens import ScreenFactory

logger = logging.getLogger(__name__)

# The database version that introduced the announcement ledger. A database older than this has no
# record of what was announced, so on its first start everything already finished is muted.
LEDGER_SCHEMA_VERSION = 2
STARTUP_RETRY_SECONDS = (5, 10, 20, 40, 60)  # pauses while Telegram is unreachable at start, then 60 s forever


@dataclass(frozen=True, slots=True)
class _Repositories:
    snapshots: SnapshotRepository
    menus: MenuRepository
    alerts: AlertRepository
    preferences: ChatPreferences
    ledger: AnnouncementLedger


@dataclass(frozen=True, slots=True)
class Runtime:
    """The wired-up object graph; ``Application.run`` drives it, tests can drive it directly."""

    settings: Settings
    bot: Bot
    dispatcher: Dispatcher
    database: Database
    source: SnapshotSource
    monitor: UpgradeMonitor
    menu: MenuService
    accounts: AccountService
    imports: ImportService


class Application:
    """Composition root: builds every component once, runs them, and shuts them down in order."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @classmethod
    def from_config(cls, path: str | Path = "config.json") -> "Application":
        return cls(SettingsLoader(path, cookie_provider=CookieDiscoverer().discover).load())

    def build(self, bot: Bot | None = None) -> Runtime:
        settings = self._settings
        database = Database(settings.database_path)
        bot = bot or Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        repositories = self._build_repositories(database)
        store = AccountStore(settings.json_accounts_directory) if settings.uses_json_accounts else None
        catalog = GameCatalog()
        parser = AccountJsonParser(catalog)
        source = SourceFactory(settings, store, catalog).build()

        gateway = TelegramGateway(bot)
        monitor = self._build_monitor(source, repositories, gateway)
        accounts = AccountService(store, parser if store else None, monitor)
        imports = ImportService(accounts, settings.json_import)
        menu, dispatcher = self._build_telegram(gateway, repositories, monitor, accounts, imports)
        return Runtime(settings, bot, dispatcher, database, source, monitor, menu, accounts, imports)

    def _build_repositories(self, database: Database) -> _Repositories:
        return _Repositories(
            snapshots=SnapshotRepository(database),
            menus=MenuRepository(database),
            alerts=AlertRepository(database),
            preferences=ChatPreferences(database, self._settings.utc_offset_hours),
            ledger=AnnouncementLedger(database),
        )

    def _build_monitor(self, source: SnapshotSource, repositories: _Repositories, gateway: TelegramGateway) -> UpgradeMonitor:
        settings = self._settings
        notifier = NotificationService(
            gateway,
            repositories.preferences,
            repositories.menus,
            repositories.alerts,
            NotificationRenderer(clash_ninja_mode=not settings.uses_json_accounts),
            settings.notification_chat_ids,
        )
        detector = EventDetector(
            settings.poll_interval_seconds,
            settings.announce_on_timer,
            timedelta(hours=settings.announce_max_age_hours),
        )
        return UpgradeMonitor(
            source,
            repositories.snapshots,
            repositories.ledger,
            detector,
            notifier,
            SourceHealth(settings.failure_alert_threshold),
            settings.poll_interval_seconds,
            settings.announce_on_timer,
        )

    def _build_telegram(
        self,
        gateway: TelegramGateway,
        repositories: _Repositories,
        monitor: UpgradeMonitor,
        accounts: AccountService,
        imports: ImportService,
    ) -> tuple[MenuService, Dispatcher]:
        settings = self._settings
        screens = ScreenFactory(settings, monitor, repositories.preferences, accounts)
        menu = MenuService(gateway, screens, repositories.menus, repositories.alerts, settings.notification_chat_ids)
        imports.attach(ImportPresenter(gateway, screens, menu, settings.json_import.delete_messages))
        renames = RenameRequests()
        account_handlers = AccountHandlers(menu, accounts, imports, gateway, renames, settings.import_available)
        router = build_router(
            AccessControl(settings.authorized_user_ids),
            NavigationHandlers(menu, monitor),
            SettingsHandlers(menu, repositories.preferences, settings),
            account_handlers,
            ImportHandlers(
                imports, accounts, account_handlers, menu, screens, gateway, renames, settings.import_available
            ),
        )
        dispatcher = Dispatcher()
        dispatcher.include_router(router)
        return menu, dispatcher

    async def run(self) -> None:
        runtime = self.build()
        settings, bot, monitor, menu, source = runtime.settings, runtime.bot, runtime.monitor, runtime.menu, runtime.source
        await source.start()
        await monitor.start(
            seed_expired=runtime.database.upgraded_from is not None
            and runtime.database.upgraded_from < LEDGER_SCHEMA_VERSION
        )
        refresh_stop = asyncio.Event()
        monitor_task = asyncio.create_task(monitor.run(), name="monitor")
        refresh_task = asyncio.create_task(
            refresh_loop(menu, settings.dashboard_refresh_seconds, refresh_stop), name="menu-refresh"
        )
        dispatcher = runtime.dispatcher
        try:
            await self._retry_while_offline("delete_webhook", lambda: bot.delete_webhook(drop_pending_updates=False))
            await menu.restore_after_restart()
            await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
        finally:
            monitor.stop()
            refresh_stop.set()
            monitor_task.cancel()
            refresh_task.cancel()
            await asyncio.gather(monitor_task, refresh_task, return_exceptions=True)
            with suppress(Exception):
                await source.close()
            await runtime.database.close()
            await bot.session.close()

    @staticmethod
    async def _retry_while_offline(what: str, call) -> None:
        """Run a start-up Bot API call, waiting for the network instead of crashing (e.g. start.bat at login)."""
        attempt = 0
        while True:
            try:
                await call()
                return
            except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter) as error:
                pause = float(getattr(error, "retry_after", 0)) or STARTUP_RETRY_SECONDS[min(attempt, len(STARTUP_RETRY_SECONDS) - 1)]
                attempt += 1
                logger.warning("Telegram is unreachable (%s: %s); retrying in %.0f s", what, error, pause)
                await asyncio.sleep(pause)
