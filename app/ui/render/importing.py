from __future__ import annotations

from html import escape

from app.domain.timefmt import format_local
from app.services.accounts import AccountSummary, SaveResult
from app.services.importer import ImportSession
from app.ui import views
from app.ui.render.common import RenderContext, Screen, button, describe_nearest, format_size, markup, rows
from app.ui.views import ViewState


class ImportRenderer:
    """Texts of the "send me your game JSON" flow."""

    def __init__(self, max_bytes: int) -> None:
        self._max_megabytes = max_bytes // (1024 * 1024)

    def render_prompt(self, replacing: AccountSummary | None = None) -> Screen:
        lines = ["📥 <b>Загрузка JSON</b>", ""]
        if replacing:
            lines.append(f"Заменяю данные аккаунта <b>«{escape(replacing.name)}»</b>: пришлите его свежий экспорт.")
        else:
            lines.append("Пришлите экспорт деревни из игры одним из способов:")
        lines += [
            "• <b>текстом</b> — вставьте JSON целиком. Telegram сам разобьёт длинный текст на несколько сообщений, "
            "я соберу их вместе;",
            "• <b>файлом</b> <code>.json</code>.",
            "",
            "Тот же аккаунт (по тегу игрока) обновится, новый — добавится. "
            "Чтобы задать имя, заранее отправьте <code>/import Имя</code>.",
            f"<i>Лимит: {self._max_megabytes} МБ · отмена: /cancel</i>",
        ]
        keyboard = markup(
            rows(button("❌ Отмена", "act:import_cancel")),
            rows(button("🏠 Главное меню", ViewState(views.MAIN).callback)),
        )
        return Screen("\n".join(lines), keyboard)

    def render_unavailable(self, reason: str) -> Screen:
        keyboard = markup(rows(button("🏠 Главное меню", ViewState(views.MAIN).callback)))
        return Screen(f"📥 <b>Загрузка JSON недоступна</b>\n{reason}", keyboard)

    def receiving(self, session: ImportSession) -> Screen:
        what = "файл" if session.source == "file" else f"сообщений: {len(session.chunks)}"
        text = (
            "📥 <b>Принимаю JSON…</b>\n"
            f"Получено: {what} · {format_size(session.total_chars)}\n"
            "<i>Если это не всё, присылайте остальное — соберу автоматически.</i>"
        )
        return Screen(text, markup(rows(button("❌ Отмена", "act:import_cancel"))))

    def waiting_for_more(self, session: ImportSession) -> Screen:
        text = (
            "⏳ <b>JSON ещё не закончился</b>\n"
            f"Получено: сообщений {len(session.chunks)} · {format_size(session.total_chars)}\n"
            "Пришлите продолжение — я подожду минуту. Если вы вставили всё, а сообщений не хватает, "
            "отправьте экспорт заново."
        )
        return Screen(text, markup(rows(button("❌ Отмена", "act:import_cancel"))))

    def success(
        self, ctx: RenderContext, result: SaveResult, session: ImportSession, messages_deleted: bool
    ) -> Screen:
        account = result.summary
        title = "✅ <b>Аккаунт добавлен</b>" if result.created else "✅ <b>Данные аккаунта обновлены</b>"
        lines = [title, f"🏰 <b>{escape(account.name)}</b>"]
        if account.tag:
            lines[-1] += f" · <code>{escape(account.tag)}</code>"
        if account.exported_at:
            lines.append(f"📅 Экспорт от {format_local(account.exported_at, ctx.utc_offset)}")
        lines.append(f"⏳ Активных улучшений: <b>{account.upgrades}</b>")
        nearest = describe_nearest(ctx, account.village_id)
        if nearest:
            lines.append(f"⏰ Ближайшее: {nearest}")
        if result.requested_name_taken:
            lines.append("ℹ️ <i>Выбранное имя занято другим аккаунтом, к нему добавлен номер.</i>")
        source = "файл" if session.source == "file" else f"{len(session.chunks)} сообщ."
        lines.append(f"<i>Принято: {source} · {format_size(session.total_chars)}"
                     f"{' · сообщения с JSON удалены' if messages_deleted else ''}</i>")
        keyboard = markup(
            rows(button("📋 Улучшения аккаунта", ViewState.village(account.village_id).callback)),
            rows(
                button("✏️ Переименовать", f"act:rename:{account.village_id}"),
                button("👥 Аккаунты", ViewState(views.ACCOUNTS).callback),
                per_row=2,
            ),
        )
        return Screen("\n".join(lines), keyboard)

    def failure(self, reason: str) -> Screen:
        text = (
            "❌ <b>Не удалось импортировать JSON</b>\n"
            f"{escape((reason[0].upper() + reason[1:] if reason else 'Неизвестная ошибка').rstrip('.'))}.\n\n"
            "Пришлите экспорт целиком ещё раз (текстом или файлом <code>.json</code>)."
        )
        keyboard = markup(
            rows(button("📥 Повторить", ViewState(views.IMPORT).callback)),
            rows(button("🏠 Главное меню", ViewState(views.MAIN).callback)),
        )
        return Screen(text, keyboard)

    def cancelled(self) -> Screen:
        return Screen(
            "🚫 Загрузка JSON отменена.",
            markup(rows(button("🏠 Главное меню", ViewState(views.MAIN).callback))),
        )
