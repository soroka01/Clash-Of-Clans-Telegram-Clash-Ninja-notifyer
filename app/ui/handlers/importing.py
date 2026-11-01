from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.services.accounts import AccountService
from app.services.importer import ImportService, looks_like_export_start
from app.ui import views
from app.ui.gateway import TelegramGateway, TelegramUnavailable
from app.ui.handlers.accounts import AccountHandlers, RenameRequests
from app.ui.menu_service import MenuService, describe_actor
from app.ui.screens import ScreenFactory
from app.ui.views import ViewState

logger = logging.getLogger(__name__)

_JSON_MIME_TYPES = {"application/json", "text/json"}


class ImportHandlers:
    """Receives game exports sent as text (usually several messages) or as a .json file."""

    def __init__(
        self,
        imports: ImportService,
        accounts: AccountService,
        account_handlers: AccountHandlers,
        menu: MenuService,
        screens: ScreenFactory,
        gateway: TelegramGateway,
        renames: RenameRequests,
        import_available: bool,
    ) -> None:
        self._imports = imports
        self._accounts = accounts
        self._account_handlers = account_handlers
        self._menu = menu
        self._screens = screens
        self._gateway = gateway
        self._renames = renames
        self._import_available = import_available

    def register(self, router: Router) -> None:
        router.message.register(self.on_import_command, Command("import"))
        router.message.register(self.on_cancel_command, Command("cancel"))
        router.callback_query.register(self.on_import_view, F.data.startswith("view:import"))
        router.callback_query.register(self.on_cancel_button, F.data == "act:import_cancel")
        router.message.register(self.on_document, F.document)
        # Registered last: plain text that is not a command is either a rename, part of a JSON, or noise.
        router.message.register(self.on_text, F.text, ~F.text.startswith("/"))

    # ----- commands and buttons ----------------------------------------------------

    async def on_import_command(self, message: Message, command: CommandObject) -> None:
        if self._import_available and message.from_user:
            self._imports.arm(message.chat.id, message.from_user.id, command.args)
        logger.info("Import requested: %s chat=%s", describe_actor(message), message.chat.id)
        await self._menu.send(message.chat.id, ViewState(views.IMPORT))

    async def on_cancel_command(self, message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        cancelled = await self._imports.cancel(message.chat.id, user_id)
        cancelled = self._renames.cancel(message.chat.id, user_id) or cancelled
        await self._say(message.chat.id, "🚫 Отменено." if cancelled else "Сейчас нечего отменять.")

    async def on_import_view(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        view = ViewState.parse(callback.data.removeprefix("view:"))
        if self._import_available:
            self._imports.arm(callback.message.chat.id, callback.from_user.id)
        await callback.answer()
        await self._menu.open_from_callback(callback, view)

    async def on_cancel_button(self, callback: CallbackQuery) -> None:
        if not callback.message:
            return
        chat_id = callback.message.chat.id
        await self._imports.cancel(chat_id, callback.from_user.id)
        await callback.answer("Загрузка отменена")
        if await self._menu.is_menu_message(chat_id, callback.message.message_id):
            await self._menu.open_from_callback(callback, ViewState(views.ACCOUNTS))
        else:
            screen = self._screens.import_renderer.cancelled()
            await self._gateway.edit(chat_id, callback.message.message_id, screen.text, screen.markup)

    # ----- incoming data -----------------------------------------------------------

    async def on_text(self, message: Message) -> None:
        user = message.from_user
        if user is None or not message.text:
            return
        # No awaits before the chunk is registered: updates are handled concurrently and the
        # first part of a long JSON must claim its session before the later parts look for it.
        village_id = self._renames.pending(message.chat.id, user.id)
        if village_id:
            if len(message.text) > 100 or looks_like_export_start(message.text):
                self._renames.cancel(message.chat.id, user.id)  # this is a JSON, not a name: forget the rename
            else:
                await self._account_handlers.finish_rename(message, village_id)
                return
        private = message.chat.type == ChatType.PRIVATE
        if not self._import_available:
            if private and looks_like_export_start(message.text):
                await self._say(
                    message.chat.id,
                    "📥 Загрузка JSON выключена: нужен <code>data_source = json</code> и непустой "
                    "<code>authorized_user_ids</code> в config.json.",
                )
            return
        await self._imports.add_text(message.chat.id, user.id, message.message_id, message.text, private)

    async def on_document(self, message: Message) -> None:
        document, user = message.document, message.from_user
        if document is None or user is None:
            return
        name = document.file_name or "export.json"
        is_json = name.lower().endswith(".json") or (document.mime_type or "") in _JSON_MIME_TYPES
        armed = self._imports.is_armed(message.chat.id, user.id)
        if not is_json and not armed:
            return  # some other file the user shared with the bot: not ours
        if not self._import_available:
            await self._say(message.chat.id, "📥 Загрузка JSON выключена в настройках бота.")
            return
        if not is_json:
            await self._say(message.chat.id, "📎 Нужен файл с расширением <code>.json</code>.")
            return
        if document.file_size and document.file_size > self._imports.max_bytes:
            limit = self._imports.max_bytes // (1024 * 1024)
            await self._say(message.chat.id, f"❌ Файл больше {limit} МБ — это точно экспорт одной деревни?")
            return
        try:
            data = await self._gateway.download(document)
        except TelegramUnavailable as error:
            logger.warning("Could not download %s: %s", name, error)
            await self._say(message.chat.id, "⚠️ Не получилось скачать файл из Telegram. Отправьте его ещё раз.")
            return
        logger.info("Import file received: %s chat=%s name=%r bytes=%s", describe_actor(message), message.chat.id, name, len(data))
        await self._imports.import_file(message.chat.id, user.id, message.message_id, name, data)

    async def _say(self, chat_id: int, text: str) -> None:
        try:
            await self._gateway.send(chat_id, text)
        except TelegramUnavailable as error:
            logger.warning("Could not send a message to chat %s: %s", chat_id, error)
