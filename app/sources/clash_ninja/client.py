from __future__ import annotations

import logging
from urllib.parse import urljoin

import aiohttp

from app.config.settings import ClashNinjaSettings
from app.domain.models import Snapshot
from app.sources.clash_ninja.parser import TrackerParser

logger = logging.getLogger(__name__)


class SessionRejected(RuntimeError):
    """Clash Ninja redirected to /login: the cookie is no longer valid."""


class ClashNinjaClient:
    """Downloads the Upgrade Tracker page and its live feed with the user's session cookie."""

    def __init__(self, settings: ClashNinjaSettings, parser: TrackerParser | None = None) -> None:
        self._settings = settings
        self._parser = parser or TrackerParser()
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        timeout = aiohttp.ClientTimeout(total=self._settings.request_timeout_seconds)
        self._session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "ClashNinjaTelegramBot/1.0"})

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    def _require_session(self) -> aiohttp.ClientSession:
        if not self._session:
            raise RuntimeError("ClashNinjaClient не запущен")
        return self._session

    @staticmethod
    def _is_login_redirect(response: aiohttp.ClientResponse) -> bool:
        # The authenticated tracker HTML itself includes a hidden login modal. Checking
        # text such as "Not logged in" therefore produces a false failure. A redirect
        # to /login is the reliable indication that the session cookie was rejected.
        return response.url.path.rstrip("/").casefold() == "/login"

    async def fetch_tracker_html(self) -> str:
        session = self._require_session()
        logger.debug("→ Запрос страницы Clash Ninja")
        async with session.get(
            self._settings.tracker_url,
            headers={"Cookie": self._settings.cookie_header},
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            html = await response.text()
            rejected = self._is_login_redirect(response)
            logger.debug("← Страница Clash Ninja: status=%s path=%s", response.status, response.url.path)
        if rejected:
            raise SessionRejected("Clash Ninja отклонил сессию: обновите cookie_header в config.json")
        return html

    async def fetch_tracker_data(self) -> tuple[str, list[dict]]:
        """Get the static tracker markup and its live timer feed in one session."""
        html = await self.fetch_tracker_html()
        session = self._require_session()
        feed_url = urljoin(self._settings.tracker_url, "/feed/villages.json")
        logger.debug("→ Запрос live-таймеров Clash Ninja")
        async with session.get(feed_url, headers={"Cookie": self._settings.cookie_header}) as response:
            response.raise_for_status()
            if self._is_login_redirect(response):
                raise SessionRejected("Clash Ninja отклонил сессию при загрузке таймеров")
            feed = await response.json(content_type=None)
            logger.debug("← Live-таймеры: status=%s аккаунтов=%s", response.status, len(feed))
        if not isinstance(feed, list):
            raise RuntimeError("Clash Ninja вернул неожиданный формат таймеров")
        return html, feed

    async def fetch_snapshot(self) -> Snapshot:
        html, feed = await self.fetch_tracker_data()
        return self._parser.parse(html, feed)
