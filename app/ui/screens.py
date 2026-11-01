from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config.settings import Settings
from app.services.accounts import AccountService
from app.services.monitor import UpgradeMonitor
from app.storage.preferences import ChatPreferences
from app.ui import views
from app.ui.render.accounts import AccountsRenderer
from app.ui.render.common import RenderContext, Screen
from app.ui.render.dashboard import DashboardRenderer
from app.ui.render.importing import ImportRenderer
from app.ui.render.menus import MainMenuRenderer, SettingsRenderer
from app.ui.views import ViewState

logger = logging.getLogger(__name__)


class ScreenFactory:
    """Builds the screen for a (chat, view) pair: gathers the data and picks the right renderer."""

    def __init__(
        self,
        settings: Settings,
        monitor: UpgradeMonitor,
        preferences: ChatPreferences,
        accounts: AccountService,
    ) -> None:
        self._settings = settings
        self._monitor = monitor
        self._preferences = preferences
        self._accounts = accounts
        self._dashboard = DashboardRenderer()
        self._main_menu = MainMenuRenderer()
        self._settings_screens = SettingsRenderer()
        self._accounts_screens = AccountsRenderer()
        self._import_screens = ImportRenderer(settings.json_import.max_bytes)

    @property
    def import_renderer(self) -> ImportRenderer:
        return self._import_screens

    async def context(self, chat_id: int) -> RenderContext:
        return RenderContext(
            snapshot=self._monitor.snapshot,
            now=datetime.now(timezone.utc),
            utc_offset=await self._preferences.utc_offset(chat_id),
            notifications_enabled=await self._preferences.notifications_enabled(chat_id),
            health=self._monitor.health.notice(),
            link_tracker=not self._settings.uses_json_accounts,
            import_available=self._settings.import_available,
            manage_accounts=self._accounts.manageable,
        )

    async def build(self, chat_id: int, view: ViewState) -> Screen:
        ctx = await self.context(chat_id)
        kind = view.kind
        if kind == views.MAIN:
            return self._main_menu.render(ctx)
        if kind == views.SETTINGS:
            return self._settings_screens.render_hub(ctx, chat_id in self._settings.notification_chat_ids)
        if kind == views.TIMEZONE:
            return self._settings_screens.render_timezone(ctx)
        if kind == views.ACCOUNTS:
            return self._accounts_screens.render_list(ctx, await self._accounts.accounts())
        if kind == views.ACCOUNT:
            return self._accounts_screens.render_card(ctx, await self._accounts.get(view.argument or ""))
        if kind == views.CONFIRM_DELETE:
            return self._accounts_screens.render_delete_confirm(ctx, await self._accounts.get(view.argument or ""))
        if kind == views.IMPORT:
            return await self._import_screen(view)
        if kind == views.HELP:
            return self._main_menu.render_help(ctx)
        return self._dashboard.render(ctx, view)

    async def _import_screen(self, view: ViewState) -> Screen:
        if not self._settings.uses_json_accounts:
            return self._import_screens.render_unavailable("Загрузка JSON работает только при <code>data_source = json</code>.")
        if not self._settings.authorized_user_ids:
            return self._import_screens.render_unavailable(
                "Она записывает файлы на диск, поэтому нужен непустой список <code>authorized_user_ids</code> в config.json."
            )
        replacing = await self._accounts.get(view.argument) if view.argument else None
        return self._import_screens.render_prompt(replacing)
