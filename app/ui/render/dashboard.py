from __future__ import annotations

from collections import defaultdict
from html import escape

from aiogram.types import InlineKeyboardMarkup

from app.domain.models import HelperState, HelperStatus, Upgrade, Village
from app.domain.timefmt import format_age, format_local, offset_label
from app.ui import views
from app.ui.render.common import (
    CATEGORY_META,
    CATEGORY_ORDER,
    DEFAULT_HELPER_ICON,
    HELPER_ICONS,
    OPEN_GAME_URL,
    STALE_AFTER,
    TRACKER_URL,
    RenderContext,
    Screen,
    button,
    finish_text,
    markup,
    paginate,
    remaining_text,
    rows,
    utf16_len,
)
from app.ui.views import ViewState

PAGE_BUDGET = 3900  # UTF-16 units of raw HTML; Telegram allows 4096 and HTML tags count against us here
EMPTY_BODY_LOADING = "Данные ещё загружаются."


class DashboardRenderer:
    """The "current upgrades" screens: all accounts, nearest first, or one account. Long ones paginate."""

    def render(self, ctx: RenderContext, view: ViewState) -> Screen:
        snapshot = ctx.snapshot
        villages = {village.id: village for village in snapshot.villages}
        selected = villages.get(view.argument or "") if view.kind == views.VILLAGE else None
        kind = views.VILLAGE if selected else (views.SORTED if view.kind == views.SORTED else views.ALL)

        helper_icons = self._assigned_icons(ctx)
        if not villages:
            subtitle, items, separator = "", [self._empty_hint(ctx)], "\n"
        elif kind == views.VILLAGE:
            subtitle = f"<i>Аккаунт: {escape(selected.name)}</i>"
            items, separator = self._village_items(ctx, selected, helper_icons), "\n"
        elif kind == views.SORTED:
            subtitle = f"<i>Все аккаунты · {len(villages)} · ближайшие первыми</i>"
            items, separator = self._sorted_items(ctx, helper_icons), "\n"
        else:
            subtitle = f"<i>Все аккаунты · {len(villages)}</i>"
            items = [self._village_block(ctx, village, helper_icons) for village in snapshot.villages]
            separator = "\n\n"

        header = self._header(ctx, subtitle)
        pages = paginate(items, separator, max(500, PAGE_BUDGET - utf16_len(header) - 40))
        page = min(max(view.page, 0), len(pages) - 1)
        page_note = f" · стр. {page + 1}/{len(pages)}" if len(pages) > 1 else ""
        text = f"{header}{page_note}\n\n{pages[page]}" if page_note else f"{header}\n\n{pages[page]}"
        current = ViewState(kind, selected.id if selected else None, page)
        return Screen(text, self._keyboard(ctx, current, len(pages)))

    # ----- header ------------------------------------------------------------------

    def _header(self, ctx: RenderContext, subtitle: str) -> str:
        updated = format_local(ctx.snapshot.fetched_at, ctx.utc_offset, "%H:%M")
        lines = ["⚔️ <b>Текущие улучшения</b>"]
        if ctx.link_tracker:
            lines.append(f'<a href="{TRACKER_URL}">🌐 Открыть Clash Ninja Upgrade Tracker</a>')
        if subtitle:
            lines.append(subtitle)
        lines.append(f"🕒 <code>{updated} {offset_label(ctx.utc_offset)}</code>")
        if ctx.health:
            since = format_local(ctx.health.since, ctx.utc_offset, "%H:%M")
            lines.append(f"⚠️ <i>Данные не обновляются с {since}: {escape(ctx.health.reason)}</i>")
        return "\n".join(lines)

    @staticmethod
    def _empty_hint(ctx: RenderContext) -> str:
        if ctx.manage_accounts:
            return "Пока нет аккаунтов. Откройте «👥 Аккаунты» и пришлите JSON-экспорт деревни из игры."
        return EMPTY_BODY_LOADING

    # ----- building blocks ---------------------------------------------------------

    @staticmethod
    def _assigned_icons(ctx: RenderContext) -> dict[tuple[str, str], list[str]]:
        icons: dict[tuple[str, str], list[str]] = defaultdict(list)
        for helper in ctx.snapshot.helpers:
            if helper.state == HelperState.ASSIGNED and helper.target:
                icons[(helper.village_id, helper.target)].append(HELPER_ICONS.get(helper.helper_name, DEFAULT_HELPER_ICON))
        return icons

    def _upgrade_lines(self, ctx: RenderContext, upgrade: Upgrade, icons: dict, prefix: str = "  ") -> list[str]:
        helper_icons = " ".join(icons.get((upgrade.village_id, upgrade.target_label), []))
        helper_prefix = f"{helper_icons} " if helper_icons else ""
        return [
            f"{prefix}◦ {helper_prefix}<b>{escape(upgrade.entity)}</b> <code>{escape(upgrade.level)}</code>",
            f"{prefix}  ⏳ <b>{remaining_text(upgrade, ctx.now)}</b> · 🏁 {finish_text(upgrade, ctx.utc_offset)}",
        ]

    @staticmethod
    def _village_title(ctx: RenderContext, village: Village) -> str:
        if ctx.link_tracker:
            url = f"{TRACKER_URL}/{escape(village.id, quote=True)}/home"
            return f'🏰 <a href="{url}">{escape(village.name)}</a>'
        return f"🏰 <b>{escape(village.name)}</b>"

    @staticmethod
    def _stale_note(ctx: RenderContext, village: Village) -> str | None:
        if village.exported_at is None or ctx.now - village.exported_at < STALE_AFTER:
            return None
        age = format_age(int((ctx.now - village.exported_at).total_seconds()))
        taken = format_local(village.exported_at, ctx.utc_offset)
        return f"⚠️ <i>Данные от {taken} ({age}). Пришлите свежий JSON, чтобы видеть новые улучшения.</i>"

    @staticmethod
    def _helpers_line(helpers: list[HelperStatus]) -> str:
        available = [helper for helper in helpers if helper.state == HelperState.AVAILABLE]
        if not available:
            return ""
        lines = [
            f"  • {HELPER_ICONS.get(helper.helper_name, DEFAULT_HELPER_ICON)} <b>{escape(helper.helper_name)}</b>"
            for helper in available
        ]
        return "🤖 <b>Свободные помощники</b>\n" + "\n".join(lines)

    def _village_items(self, ctx: RenderContext, village: Village, icons: dict) -> list[str]:
        """One account as a list of lines (so a very long account can still be split across pages)."""
        upgrades = ctx.snapshot.upgrades_of(village.id)
        items = [self._village_title(ctx, village)]
        stale = self._stale_note(ctx, village)
        if stale:
            items.append(stale)
        if not upgrades:
            items.append("✨ <i>Нет текущих улучшений</i>")
        grouped: dict[str, list[Upgrade]] = defaultdict(list)
        for upgrade in upgrades:
            grouped[upgrade.category].append(upgrade)
        for category in CATEGORY_ORDER:
            members = sorted(grouped.get(category, []), key=lambda item: item.sort_key)
            if not members:
                continue
            icon, title = CATEGORY_META[category]
            items.append(f"{icon} <b>{title}</b> <i>({len(members)})</i>")
            items.extend("\n".join(self._upgrade_lines(ctx, member, icons)) for member in members)
        helpers_line = self._helpers_line(ctx.snapshot.helpers_of(village.id))
        if helpers_line:
            items.append(helpers_line)
        return items

    def _village_block(self, ctx: RenderContext, village: Village, icons: dict) -> str:
        return "\n".join(self._village_items(ctx, village, icons))

    def _sorted_items(self, ctx: RenderContext, icons: dict) -> list[str]:
        """Every account's upgrades in one nearest-first timeline."""
        names = {village.id: village.name for village in ctx.snapshot.villages}
        items: list[str] = []
        for upgrade in sorted(ctx.snapshot.upgrades, key=lambda item: item.sort_key):
            icon = CATEGORY_META.get(upgrade.category, ("•", ""))[0]
            helper_icons = " ".join(icons.get((upgrade.village_id, upgrade.target_label), []))
            helper_prefix = f"{helper_icons} " if helper_icons else ""
            village_name = escape(names.get(upgrade.village_id, upgrade.village_name))
            items.append(
                f"🏰 <b>{village_name}</b> · {icon} {helper_prefix}<b>{escape(upgrade.entity)}</b> "
                f"<code>{escape(upgrade.level)}</code>\n"
                f"  ⏳ <b>{remaining_text(upgrade, ctx.now)}</b> · 🏁 {finish_text(upgrade, ctx.utc_offset)}"
            )
        for village in ctx.snapshot.villages:
            helpers_line = self._helpers_line(ctx.snapshot.helpers_of(village.id))
            if helpers_line:
                items.append(f"\n🏰 <b>{escape(village.name)}</b>\n{helpers_line}")
        return items or ["✨ <i>Нет текущих улучшений</i>"]

    # ----- keyboard ----------------------------------------------------------------

    def _keyboard(self, ctx: RenderContext, current: ViewState, page_count: int) -> InlineKeyboardMarkup:
        villages = ctx.snapshot.villages
        navigation = []
        if page_count > 1:
            previous = button("◀", current.with_page(current.page - 1).callback) if current.page > 0 else None
            following = button("▶", current.with_page(current.page + 1).callback) if current.page < page_count - 1 else None
            navigation = [
                [
                    item
                    for item in (
                        previous or button("·", "noop"),
                        button(f"{current.page + 1}/{page_count}", "noop"),
                        following or button("·", "noop"),
                    )
                    if item
                ]
            ]

        accounts = []
        if current.kind == views.VILLAGE:
            accounts = rows(button("← 📋 Все аккаунты", ViewState(views.ALL).callback))
            if ctx.manage_accounts:
                accounts += rows(button("⚙️ Управление аккаунтом", ViewState.account(current.argument).callback))
        elif len(villages) > 1:
            accounts = rows(
                *(button(f"🏰 {village.name}", ViewState.village(village.id).callback) for village in villages),
                per_row=2,
            )

        if current.kind == views.SORTED:
            ordering = rows(button("↩ Обычная сортировка", ViewState(views.ALL).callback))
        elif current.kind == views.ALL:
            ordering = rows(button("⏱ Сначала ближайшие", ViewState(views.SORTED).callback))
        else:
            ordering = []

        actions = rows(
            button("🔄 Обновить", "act:refresh"),
            button("🏠 Меню", ViewState(views.MAIN).callback),
            per_row=2,
        )
        game = rows(button("🎮 Открыть Clash of Clans", url=OPEN_GAME_URL))
        return markup(navigation, accounts, ordering, actions, game)
