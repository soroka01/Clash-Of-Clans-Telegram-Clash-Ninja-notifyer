from __future__ import annotations

import aiohttp

from app.config import ClashNinjaSettings


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
        async with self._session.get(
            self._settings.tracker_url,
            headers={"Cookie": self._settings.cookie_header},
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            html = await response.text()
        if ">Login<" in html or "Not logged in" in html:
            raise RuntimeError("Clash Ninja отклонил сессию: обновите cookie_header в config.json")
        return html
