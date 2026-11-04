from __future__ import annotations

from html import escape

from app.domain.timefmt import format_age, format_local
from app.services.accounts import AccountSummary
from app.ui import views
from app.ui.render.common import STALE_AFTER, RenderContext, Screen, button, describe_nearest, format_size, markup, rows
from app.ui.views import ViewState


class AccountsRenderer:
    """Account list, account card and the delete confirmation."""

    def render_list(self, ctx: RenderContext, accounts: list[AccountSummary]) -> Screen:
        lines = ["👥 <b>Аккаунты</b>"]
        if not accounts:
            lines.append("")
            lines.append(
                "Аккаунтов пока нет. Нажмите «📥 Добавить JSON» и пришлите экспорт деревни из игры."
                if ctx.manage_accounts
                else "Данные ещё загружаются."
            )
        else:
            lines.append(f"<i>Всего: {len(accounts)}</i>")
            lines.append("")
            lines.extend(self._list_line(ctx, account) for account in accounts)
        entries = [
            button(
                f"🏰 {account.name}",
                (ViewState.account(account.village_id) if account.manageable else ViewState.village(account.village_id)).callback,
            )
            for account in accounts
        ]
        keyboard = markup(
            rows(*entries, per_row=2),
            rows(button("📥 Добавить JSON", ViewState(views.IMPORT).callback) if ctx.import_available else None),
            rows(button("🏠 Главное меню", ViewState(views.MAIN).callback)),
        )
        return Screen("\n".join(lines), keyboard)

    def _list_line(self, ctx: RenderContext, account: AccountSummary) -> str:
        parts = [f"🏰 <b>{escape(account.name)}</b>", f"⏳ {account.upgrades}"]
        if account.exported_at:
            age = format_age(int((ctx.now - account.exported_at).total_seconds()))
            stale = "⚠️ " if ctx.now - account.exported_at >= STALE_AFTER else ""
            parts.append(f"{stale}данные {age}")
        return " · ".join(parts)

    def render_card(self, ctx: RenderContext, account: AccountSummary | None) -> Screen:
        if account is None:
            return Screen(
                "🤷 Аккаунт не найден — возможно, он уже удалён.",
                markup(rows(button("← Аккаунты", ViewState(views.ACCOUNTS).callback))),
            )
        lines = [f"🏰 <b>{escape(account.name)}</b>"]
        if account.tag:
            lines.append(f"🏷 Тег: <code>{escape(account.tag)}</code>")
        if account.exported_at:
            age = format_age(int((ctx.now - account.exported_at).total_seconds()))
            lines.append(f"📅 Данные от {format_local(account.exported_at, ctx.utc_offset)} ({age})")
            if ctx.now - account.exported_at >= STALE_AFTER:
                lines.append("⚠️ <i>Данные устарели: пришлите свежий JSON.</i>")
        if account.size:
            lines.append(f"📦 Размер файла: {format_size(account.size)}")
        lines.append(f"⏳ Улучшений: <b>{account.upgrades}</b>")
        nearest = describe_nearest(ctx, account.village_id)
        if nearest:
            lines.append(f"⏰ Ближайшее: {nearest}")

        keyboard = markup(
            rows(button("📋 Улучшения аккаунта", ViewState.village(account.village_id).callback)),
            rows(
                button("🔄 Заменить JSON", f"act:replace:{account.village_id}") if ctx.import_available else None,
                button("✏️ Переименовать", f"act:rename:{account.village_id}"),
                per_row=2,
            ),
            rows(
                button("📤 Скачать JSON", f"act:download:{account.village_id}"),
                button("🗑 Удалить", ViewState.confirm_delete(account.village_id).callback),
                per_row=2,
            ),
            rows(button("← Аккаунты", ViewState(views.ACCOUNTS).callback)),
        )
        return Screen("\n".join(lines), keyboard)

    def render_delete_confirm(self, ctx: RenderContext, account: AccountSummary | None) -> Screen:
        if account is None:
            return self.render_card(ctx, None)
        text = (
            f"🗑 <b>Удалить аккаунт «{escape(account.name)}»?</b>\n\n"
            "Он пропадёт из бота и уведомления по нему прекратятся. Файл не стирается, "
            "а переносится в <code>accounts/_trash</code> — его можно вернуть вручную."
        )
        keyboard = markup(
            rows(button("✅ Да, удалить", f"act:delete:{account.village_id}")),
            rows(button("← Отмена", ViewState.account(account.village_id).callback)),
        )
        return Screen(text, keyboard)
