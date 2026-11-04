from __future__ import annotations

from html import escape

from app.domain.models import HelperState
from app.domain.timefmt import format_local, offset_label
from app.ui import views
from app.ui.render.common import (
    OPEN_GAME_URL,
    REPOSITORY_URL,
    TRACKER_URL,
    RenderContext,
    Screen,
    button,
    markup,
    remaining_text,
    rows,
)
from app.ui.views import ViewState

MIN_OFFSET, MAX_OFFSET = -12, 14


class MainMenuRenderer:
    def render(self, ctx: RenderContext) -> Screen:
        snapshot = ctx.snapshot
        lines = [
            "⚔️ <b>Clash Ninja Notifier</b>",
            "<i>Улучшения, таймеры и уведомления ваших аккаунтов Clash of Clans.</i>",
            "",
        ]
        if snapshot.villages:
            free_helpers = sum(1 for helper in snapshot.helpers if helper.state == HelperState.AVAILABLE)
            summary = f"👥 Аккаунтов: <b>{len(snapshot.villages)}</b> · ⏳ Улучшений: <b>{len(snapshot.upgrades)}</b>"
            if free_helpers:
                summary += f" · 🤖 Свободных помощников: <b>{free_helpers}</b>"
            lines.append(summary)
            nearest = snapshot.nearest_upgrade()
            if nearest:
                lines.append(
                    f"⏰ Ближайшее: <b>{escape(nearest.village_name)}</b> · {escape(nearest.entity)} "
                    f"<code>{escape(nearest.level)}</code> — <b>{remaining_text(nearest, ctx.now)}</b>"
                )
        elif ctx.manage_accounts:
            lines.append("👋 Аккаунтов пока нет. Нажмите «📥 Загрузить JSON» и пришлите экспорт деревни из игры.")
        else:
            lines.append("Данные ещё загружаются.")
        if ctx.health:
            since = format_local(ctx.health.since, ctx.utc_offset, "%H:%M")
            lines.append(f"⚠️ <i>Данные не обновляются с {since}: {escape(ctx.health.reason)}</i>")
        lines += ["", "Выберите действие ниже."]

        keyboard = markup(
            rows(button("📋 Текущие улучшения", ViewState(views.ALL).callback)),
            rows(
                button("👥 Аккаунты", ViewState(views.ACCOUNTS).callback),
                button("📥 Загрузить JSON", ViewState(views.IMPORT).callback) if ctx.import_available else None,
                per_row=2,
            ),
            rows(button("⚙️ Настройки", ViewState(views.SETTINGS).callback)),
            rows(button("🎮 Открыть Clash of Clans", url=OPEN_GAME_URL)),
            rows(
                button("🔗 Clash Ninja", url=TRACKER_URL) if ctx.link_tracker else None,
                button("💻 GitHub", url=REPOSITORY_URL),
                per_row=2,
            ),
        )
        return Screen("\n".join(lines), keyboard)


    def render_help(self, ctx: RenderContext) -> Screen:
        lines = [
            "❓ <b>Справка</b>",
            "",
            "/start, /menu — главное меню",
            "/status — текущие улучшения всех аккаунтов",
            "/accounts — список аккаунтов",
        ]
        if ctx.import_available:
            lines += [
                "/import [имя] — загрузить JSON-экспорт деревни из игры",
                "/cancel — отменить загрузку или переименование",
                "",
                "📥 <b>Как загрузить аккаунт</b>",
                "Вставьте JSON из игры прямо в чат: даже если Telegram разобьёт его на десяток сообщений, "
                "я склею их сам. Можно и отправить файл <code>.json</code>. Тот же аккаунт (по тегу) обновится, "
                "новый добавится. Чтобы задать имя, отправьте <code>/import Имя</code> перед JSON.",
                "",
                "ℹ️ В группах бот видит обычные сообщения только если отключён Privacy Mode; "
                "в личном чате и файлом это работает всегда.",
            ]
        lines += ["", "⏰ Уведомление приходит в момент окончания таймера, а свежий экспорт нужен, чтобы увидеть новые улучшения."]
        keyboard = markup(rows(button("🏠 Главное меню", ViewState(views.MAIN).callback)))
        return Screen("\n".join(lines), keyboard)


class SettingsRenderer:
    def render_hub(self, ctx: RenderContext, chat_receives_alerts: bool) -> Screen:
        lines = [
            "⚙️ <b>Настройки</b>",
            "",
            f"🌍 Часовой пояс: <b>{offset_label(ctx.utc_offset)}</b>",
        ]
        toggle = None
        if chat_receives_alerts:
            state = "включены" if ctx.notifications_enabled else "выключены"
            lines.append(f"🔔 Уведомления в этом чате: <b>{state}</b>")
            toggle = (
                button("🔕 Выключить уведомления", "act:notify:off")
                if ctx.notifications_enabled
                else button("🔔 Включить уведомления", "act:notify:on")
            )
        else:
            lines.append("🔕 Этот чат не указан в <code>notification_chat_ids</code>, поэтому уведомления сюда не приходят.")
        keyboard = markup(
            rows(button("🌍 Часовой пояс", ViewState(views.TIMEZONE).callback)),
            rows(toggle),
            rows(button("🏠 Главное меню", ViewState(views.MAIN).callback)),
        )
        return Screen("\n".join(lines), keyboard)

    def render_timezone(self, ctx: RenderContext) -> Screen:
        text = (
            "🌍 <b>Часовой пояс</b>\n"
            f"Текущий: <b>{offset_label(ctx.utc_offset)}</b>\n\n"
            "Выберите смещение от UTC. В этом поясе отображаются дата и время завершения улучшений."
        )
        offsets = list(range(MIN_OFFSET, MAX_OFFSET + 1))
        buttons = [
            button(f"{'✅ ' if offset == ctx.utc_offset else ''}{offset_label(offset)}", f"tz:{offset}")
            for offset in offsets
        ]
        keyboard = markup(
            rows(*buttons, per_row=3),
            rows(
                button("← Настройки", ViewState(views.SETTINGS).callback),
                button("🏠 Меню", ViewState(views.MAIN).callback),
                per_row=2,
            ),
        )
        return Screen(text, keyboard)
