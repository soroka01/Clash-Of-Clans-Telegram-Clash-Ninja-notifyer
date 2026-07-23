from __future__ import annotations

import logging
from urllib.parse import urljoin

import aiohttp

from app.config import ClashNinjaSettings

logger = logging.getLogger(__name__)


class ClashNinjaClient:
    def __init__(self, settings: ClashNinjaSettings) -> None:
        self._settings = settings
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        timeout = aiohttp.ClientTimeout(total=self._settings.request_timeout_seconds)
        self._session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "ClashNinjaTelegramBot/1.0"})

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    async def fetch_tracker_html(self) -> str:
        if not self._session:
            raise RuntimeError("ClashNinjaClient не запущен")
        logger.debug("→ Запрос страницы Clash Ninja")
        async with self._session.get(
            self._settings.tracker_url,
            headers={"Cookie": self._settings.cookie_header},
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            html = await response.text()
            final_url = response.url
            logger.debug("← Страница Clash Ninja: status=%s path=%s", response.status, final_url.path)
        # The authenticated tracker HTML itself includes a hidden login modal. Checking
        # text such as "Not logged in" therefore produces a false failure. A redirect
        # to /login is the reliable indication that the session cookie was rejected.
        if final_url.path.rstrip("/").casefold() == "/login":
            raise RuntimeError("Clash Ninja отклонил сессию: обновите cookie_header в config.json")
        return html

    async def fetch_tracker_data(self) -> tuple[str, list[dict]]:
        """Get the static tracker markup and its live timer feed in one session."""
        html = await self.fetch_tracker_html()
        if not self._session:
            raise RuntimeError("ClashNinjaClient не запущен")
        feed_url = urljoin(self._settings.tracker_url, "/feed/villages.json")
        logger.debug("→ Запрос live-таймеров Clash Ninja")
        async with self._session.get(feed_url, headers={"Cookie": self._settings.cookie_header}) as response:
            response.raise_for_status()
            if response.url.path.rstrip("/").casefold() == "/login":
                raise RuntimeError("Clash Ninja отклонил сессию при загрузке таймеров")
            feed = await response.json(content_type=None)
            logger.debug("← Live-таймеры: status=%s аккаунтов=%s", response.status, len(feed))
        if not isinstance(feed, list):
            raise RuntimeError("Clash Ninja вернул неожиданный формат таймеров")
        return html, feed
