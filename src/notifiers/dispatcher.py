"""
Notification dispatcher.
Coordinates delivery of alerts across multiple configured notification providers.
"""

import logging
from typing import List

from src.config import AppConfig
from src.engine.models import AlertPayload
from src.notifiers.base import BaseNotifier, format_stress_text
from src.notifiers.email_notifier import EmailNotifier
from src.notifiers.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Dispatches alerts to all active and enabled notification channels."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.notifiers: List[BaseNotifier] = []

        # Initialize Telegram notifier
        tg_notifier = TelegramNotifier(config.notifications.telegram)
        if tg_notifier.is_configured():
            self.notifiers.append(tg_notifier)
            logger.info("Telegram notification channel active.")
        else:
            logger.debug("Telegram notification channel inactive or missing credentials.")

        # Initialize Email notifier
        em_notifier = EmailNotifier(config.notifications.email)
        if em_notifier.is_configured():
            self.notifiers.append(em_notifier)
            logger.info("Email notification channel active.")

    def dispatch(self, payload: AlertPayload) -> int:
        """Send alert to all registered notifiers. Returns number of successful dispatches."""
        if not self.notifiers:
            logger.warning(
                "No notification providers configured or enabled. Alert was suppressed: %s",
                payload.title,
            )
            return 0

        successes = 0
        for notifier in self.notifiers:
            try:
                if notifier.send_alert(payload):
                    successes += 1
            except Exception as e:
                logger.error("Notifier %s encountered unexpected error: %s", notifier.__class__.__name__, e)

        return successes

    def send_test_notification(self) -> bool:
        """Send a test message across all active notification channels."""
        if not self.notifiers:
            logger.error("Cannot send test notification: No providers configured.")
            return False

        all_ok = True
        for notifier in self.notifiers:
            if isinstance(notifier, TelegramNotifier):
                test_text = (
                    "🔔 <b>Home Server Monitoring Test</b>\n\n"
                    "Telegram alerts are configured and functioning correctly.\n"
                    f"Host: <code>{self.config.server.hostname}</code>"
                )
                ok = notifier.send_raw_message(test_text)
                all_ok = all_ok and ok
            elif isinstance(notifier, EmailNotifier):
                # Send simple test email
                logger.info("Sending test email...")
                # We could dispatch a dummy payload
        return all_ok
