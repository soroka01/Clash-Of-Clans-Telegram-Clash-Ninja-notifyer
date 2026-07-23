from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup, Tag

from app.models import HELPER_NAMES, Snapshot, Upgrade


class TrackerParseError(ValueError):
    pass


_COMPLETE_DATE = re.compile(r"Complete:\s*(.+)$")
_ORDINAL = re.compile(r"(\d{1,2})(?:st|nd|rd|th)")


def _clean(value: str) -> str:
    return " ".join(value.split())


def _village_name(village: Tag) -> str:
    heading = village.find("h2", recursive=False)
    if not heading:
        return village.get("id", "Unknown village")
    link = heading.find("a")
    if link:
        text = " ".join(str(part).strip() for part in link.contents if isinstance(part, str) and part.strip())
        if text:
            return _clean(text)
    return _clean(heading.get_text(" ", strip=True)).split("  ")[0]


def _category_for(table: Tag, entity: str) -> str | None:
    if entity.casefold() in HELPER_NAMES:
        # A Helper must be inside a real upgrade row. Availability/cooldown counters are
        # deliberately ignored because they do not have the Entity/Level/Remaining table.
        return "helper"
    heading = table.find_previous(["h4", "h3"])
    label = _clean(heading.get_text(" ", strip=True)).casefold() if heading else ""
    if "laboratory" in label or label.startswith("lab "):
        return "lab"
    if "pet" in label:
        return "pet"
    if "builder" in label and "upgrade" in label:
        return "builder"
    return None


def _finish_at(row: Tag, feed_finish_at: datetime | None = None) -> datetime | None:
    if feed_finish_at:
        return feed_finish_at
    progress = row.select_one("[role='progressbar'][title]")
    if progress:
        raw = progress.get("title", "").strip()
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)

    remaining = row.select_one("td:nth-of-type(3) [title]")
    title = remaining.get("title", "") if remaining else ""
    match = _COMPLETE_DATE.search(title)
    if not match:
        return None
    source = _ORDINAL.sub(r"\1", match.group(1))
    try:
        # Clash Ninja currently renders e.g. "Tue 28th Jul 2026 @ 10:41".
        return datetime.strptime(source, "%a %d %b %Y @ %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _rows_from_village(
    village: Tag,
    village_id: str,
    village_name: str,
    feed_finishes: dict[str, datetime],
) -> list[Upgrade]:
    upgrades: list[Upgrade] = []
    for table in village.find_all("table"):
        headers = [_clean(cell.get_text(" ", strip=True)).casefold() for cell in table.find_all("th")]
        if "entity" not in headers or "remaining" not in headers:
            continue
        for row in table.find_all("tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 3:
                continue
            entity = _clean(cells[0].get_text(" ", strip=True))
            level = _clean(cells[1].get_text(" ", strip=True))
            if not entity or not level:
                continue
            category = _category_for(table, entity)
            if not category:
                continue
            timer = cells[2].find(id=True)
            timer_id = timer.get("id") if timer else None
            finish_at = _finish_at(row, feed_finishes.get(timer_id or ""))
            # Current Clash Ninja markup leaves timer cells blank and fills them
            # client-side from /feed/villages.json. Do not present a phantom
            # "active upgrade" if its live feed record is absent.
            if not finish_at:
                continue
            upgrades.append(
                Upgrade(
                    village_id=village_id,
                    village_name=village_name,
                    category=category,
                    entity=entity,
                    level=level,
                    finish_at=finish_at,
                )
            )
    return upgrades


def _feed_finishes(feed: list[dict] | None) -> dict[str, datetime]:
    """Map DOM timer IDs (tag-eid-index-rem) to completion timestamps."""
    finishes: dict[str, datetime] = {}
    for village in feed or []:
        village_id = village.get("tws")
        if not village_id:
            continue
        for village_type in ("hb", "bb"):
            upgrades = village.get(village_type, {})
            for kind in ("b", "l", "p"):
                entries = upgrades.get(kind)
                if isinstance(entries, dict):
                    entries = [entries]
                for entry in entries or []:
                    try:
                        key = f"{village_id}-{int(entry['eid'])}-{int(entry.get('i', 0))}-rem"
                        finishes[key] = datetime.fromtimestamp(int(entry["cd"]) / 1000, tz=timezone.utc)
                    except (KeyError, TypeError, ValueError, OSError):
                        continue
    return finishes


def parse_tracker_html(html: str, feed: list[dict] | None = None, now: datetime | None = None) -> Snapshot:
    """Parse the logged-in Upgrade Tracker overview without relying on fragile IDs."""
    soup = BeautifulSoup(html, "html.parser")
    villages: list[tuple[str, str]] = []
    upgrades: list[Upgrade] = []
    feed_finishes = _feed_finishes(feed)
    for village in soup.select("div.village-overview[id]"):
        village_id = village.get("id", "")
        if not village_id or village_id == "overall-timers":
            continue
        name = _village_name(village)
        villages.append((village_id, name))
        upgrades.extend(_rows_from_village(village, village_id, name, feed_finishes))
    if not villages:
        raise TrackerParseError("На странице не найдены деревни. Возможно, изменилась разметка или истекла сессия.")
    return Snapshot(
        villages=tuple(villages),
        upgrades=tuple(upgrades),
        fetched_at=now or datetime.now(timezone.utc),
    )
