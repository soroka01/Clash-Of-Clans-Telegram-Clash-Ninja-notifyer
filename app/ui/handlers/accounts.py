from __future__ import annotations

import logging
import time
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.services.accounts import AccountService
from app.services.importer import ImportService
from app.sources.json_accounts.store import MAX_NAME_LENGTH, AccountStoreError
from app.ui import views
from app.ui.gateway import TelegramGateway, TelegramUnavailable
from app.ui.menu_service import MenuService, describe_actor
from app.ui.views import ViewState

logger = logging.getLogger(__name__)

RENAME_TTL = 300.0


class RenameRequests:
    """Remembers who is expected to type a new account name next."""

    def __init__(self) -> None:
        self._pending: dict[tuple[int, int], tuple[str, float]] = {}

    def expect(self, chat_id: int, user_id: int, village_id: str) -> None:
        self._pending[(chat_id, user_id)] = (village_id, time.monotonic() + RENAME_TTL)

    def pending(self, chat_id: int, user_id: int) -> str | None:
        entry = self._pending.get((chat_id, user_id))
        if entry and entry[1] < time.monotonic():
            del self._pending[(chat_id, user_id)]
            return None
        return entry[0] if entry else None

    def cancel(self, chat_id: int, user_id: int) -> bool:
        return self._pending.pop((chat_id, user_id), None) is not None


class AccountHandlers:
    """Per-account actions: replace the JSON, rename, download, delete."""

    def __init__(
        self,
        menu: MenuService,
        accounts: AccountService,
        imports: ImportService,
        gateway: TelegramGateway,
        renames: RenameRequests,
        import_available: bool,
    ) -> None:
        self._menu = menu
        self._accounts = accounts
        self._imports = imports
        self._gateway = gateway
        self._renames = renames
        self._import_available = import_available

    def register(self, router: Router) -> None:
        router.callback_query.register(self.on_replace, F.data.startswith("act:replace:"))
        router.callback_query.register(self.on_rename, F.data.startswith("act:rename:"))
        router.callback_query.register(self.on_download, F.data.startswith("act:download:"))
        router.callback_query.register(self.on_delete, F.data.startswith("act:delete:"))

    async def on_replace(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        village_id = callback.data.removeprefix("act:replace:")
        account = await self._accounts.get(village_id)
        if account is None or not self._import_available:
            await callback.answer("Аккаунт не найден", show_alert=True)
            return
        self._imports.arm(callback.message.chat.id, callback.from_user.id, account.name, replace_village_id=village_id)
        await callback.answer()
        await self._menu.open_from_callback(callback, ViewState.import_for(village_id))

    async def on_rename(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        account = await self._accounts.get(callback.data.removeprefix("act:rename:"))
        if account is None or not account.manageable:
            await callback.answer("Аккаунт не найден", show_alert=True)
            return
        chat_id = callback.message.chat.id
        self._renames.expect(chat_id, callback.from_user.id, account.village_id)
        await callback.answer()
        await self._say(
            chat_id,
            f"✏️ Отправьте новое имя для <b>«{escape(account.name)}»</b> (до {MAX_NAME_LENGTH} символов) "
            "или /cancel.",
        )

    async def on_download(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        try:
            filename, data = await self._accounts.read_export(callback.data.removeprefix("act:download:"))
        except AccountStoreError as error:
            await callback.answer(str(error), show_alert=True)
            return
        await callback.answer("Отправляю файл…")
        try:
            await self._gateway.send_document(callback.message.chat.id, data, filename, caption=f"📤 {filename}")
        except TelegramUnavailable as error:
            logger.warning("Could not send the export file: %s", error)

    async def on_delete(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        try:
            name = await self._accounts.delete(callback.data.removeprefix("act:delete:"))
        except AccountStoreError as error:
            await callback.answer(str(error), show_alert=True)
            return
        logger.info("Account deleted by %s: %s", describe_actor(callback), name)
        await callback.answer(f"Удалён: {name}")
        await self._menu.open_from_callback(callback, ViewState(views.ACCOUNTS))

    # ----- called by the text handler ----------------------------------------------

    async def finish_rename(self, message: Message, village_id: str) -> None:
        """Apply the name the user typed after pressing "Rename"."""
        chat_id = message.chat.id
        try:
            summary = await self._accounts.rename(village_id, message.text or "")
        except AccountStoreError as error:
            await self._say(chat_id, f"❌ {escape(str(error))} Попробуйте другое имя или отправьте /cancel.")
            return
        self._renames.cancel(chat_id, message.from_user.id)
        logger.info("Account renamed by %s: -> %s", describe_actor(message), summary.name)
        await self._menu.send(chat_id, ViewState.account(summary.village_id))

    async def _say(self, chat_id: int, text: str) -> None:
        try:
            await self._gateway.send(chat_id, text)
        except TelegramUnavailable as error:
            logger.warning("Could not send a message to chat %s: %s", chat_id, error)

