from __future__ import annotations

import logging

from app.domain.events import DomainEvent, HelperReleased, SourceDown, SourceRecovered, UpgradeCompleted
from app.storage.menus import AlertRepository, MenuRepository
from app.storage.preferences import ChatPreferences
from app.ui.gateway import TelegramGateway, TelegramUnavailable
from app.ui.render.notifications import NotificationRenderer

logger = logging.getLogger(__name__)


class NotificationService:
    """Delivers the monitor's announcements to the configured chats (it is the monitor's EventSink)."""

    def __init__(
        self,
        gateway: TelegramGateway,
        preferences: ChatPreferences,
        menus: MenuRepository,
        alerts: AlertRepository,
        renderer: NotificationRenderer,
        chat_ids: tuple[int, ...],
    ) -> None:
        self._gateway = gateway
        self._preferences = preferences
        self._menus = menus
        self._alerts = alerts
        self._renderer = renderer
        self._chat_ids = chat_ids

    async def deliver(self, event: DomainEvent) -> bool:
        """Send ``event`` to every chat that wants it.

        Returns False only if nobody could be reached because of a temporary failure, i.e. when
        trying again later makes sense. Blocked chats and muted chats count as handled.
        """
        reached, deferred = False, False
        for chat_id in self._chat_ids:
            if not await self._preferences.notifications_enabled(chat_id):
                continue
            text = self._renderer.render(event, await self._preferences.utc_offset(chat_id))
            try:
                message_id = await self._gateway.send(chat_id, text, self._renderer.keyboard())
            except TelegramUnavailable as error:
                logger.warning("Notification to chat %s postponed: %s", chat_id, error)
                deferred = True
                continue
            if message_id is None:
                continue
            reached = True
            await self._menus.mark_notification(chat_id, message_id)
            await self._alerts.remember(chat_id, message_id)
            logger.info("Notification sent: chat=%s message=%s item=%s", chat_id, message_id, self._label(event))
        return reached or not deferred

    @staticmethod
    def _label(event: DomainEvent) -> str:
        if isinstance(event, (UpgradeCompleted, HelperReleased)):
            return event.label
        return "source-down" if isinstance(event, SourceDown) else "source-recovered" if isinstance(event, SourceRecovered) else "?"
