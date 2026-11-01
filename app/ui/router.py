from __future__ import annotations

from aiogram import Router

from app.ui.access import AccessControl
from app.ui.handlers.accounts import AccountHandlers
from app.ui.handlers.importing import ImportHandlers
from app.ui.handlers.navigation import NavigationHandlers
from app.ui.handlers.settings import SettingsHandlers


def build_router(
    access: AccessControl,
    navigation: NavigationHandlers,
    settings: SettingsHandlers,
    accounts: AccountHandlers,
    importing: ImportHandlers,
) -> Router:
    """Wire the handler classes into one router behind the access check.

    Order matters inside a router: the import view and commands are registered before the generic
    ``view:`` handler, and the catch-all text handler comes last.
    """
    router = Router(name="clash-ninja-notifier")
    router.message.middleware(access)
    router.callback_query.middleware(access)
    importing.register(router)
    accounts.register(router)
    settings.register(router)
    navigation.register(router)
    return router
