"""
Email notification provider.
Sends alerts via SMTP with STARTTLS or SSL support.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.config import EmailConfig
from src.engine.models import AlertPayload
from src.notifiers.base import BaseNotifier, format_recovery_text, format_stress_text

logger = logging.getLogger(__name__)


class EmailNotifier(BaseNotifier):
    """Sends email notifications via SMTP."""

    def __init__(self, config: EmailConfig):
        self.config = config

    def is_configured(self) -> bool:
        """Check if email notifications are enabled and configured."""
        return bool(
            self.config.enabled
            and self.config.smtp_server
            and self.config.sender_email
            and self.config.recipient_emails
        )

    def send_alert(self, payload: AlertPayload) -> bool:
        """Format and send alert via SMTP."""
        if not self.is_configured():
            logger.debug("Email notifier is not configured or disabled.")
            return False

        subject = f"[{payload.severity.value}] {payload.title} - {payload.snapshot.hostname}"
        body_text = format_recovery_text(payload) if payload.alert_type == "RECOVERY" else format_stress_text(payload)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.sender_email
        msg["To"] = ", ".join(self.config.recipient_emails)
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        try:
            if self.config.smtp_port == 465:
                server = smtplib.SMTP_SSL(self.config.smtp_server, self.config.smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=15)
                if self.config.use_tls:
                    server.starttls()

            if self.config.username and self.config.password:
                server.login(self.config.username, self.config.password)

            server.sendmail(
                self.config.sender_email,
                self.config.recipient_emails,
                msg.as_string(),
            )
            server.quit()
            logger.info("Email alert successfully sent to %s", self.config.recipient_emails)
            return True
        except Exception as e:
            logger.error("Failed to send email alert: %s", e)
            return False
