"""
Telegram Bot notification provider.
Sends formatted alerts via the official Telegram Bot API using standard library urllib.
"""

import html
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from src.config import TelegramConfig
from src.engine.models import AlertPayload
from src.notifiers.base import BaseNotifier, format_recovery_text, format_stress_text

logger = logging.getLogger(__name__)


class TelegramNotifier(BaseNotifier):
    """Sends notifications to a Telegram chat via Bot API."""

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.bot_token = config.bot_token
        self.chat_id = config.chat_id

    def is_configured(self) -> bool:
        """Check if Telegram is enabled and credentials are set."""
        return bool(self.config.enabled and self.bot_token and self.chat_id)

    def _format_html(self, payload: AlertPayload) -> str:
        """Format the alert payload using HTML for reliable Telegram rendering."""
        snap = payload.snapshot
        load = snap.load
        cpu = snap.cpu
        mem = snap.memory
        disk = snap.disk
        psi = snap.psi
        temp = snap.thermal

        if payload.alert_type == "RECOVERY":
            io_psi_str = f"{psi.io.some_avg10:.1f}%" if (psi.available and psi.io) else "Normal"
            text = f"""<b>{html.escape(payload.title)}</b>

⏱ <b>Stress duration:</b> {html.escape(payload.duration_str)}
🖥 <b>Host:</b> {html.escape(snap.hostname)}

<b>Current state:</b>
• <b>CPU:</b> {cpu.overall_percent:.1f}%
• <b>Load (1m):</b> {load.load_1m:.2f} (Capacity: {load.cpu_count} CPUs)
• <b>RAM Available:</b> {mem.available_mb / 1024.0:.1f} GB ({mem.available_percent:.1f}%)
• <b>Swap:</b> {mem.swap_percent:.1f}%
• <b>I/O Pressure:</b> {html.escape(io_psi_str)}

<i>System resources have returned to normal operating thresholds.</i>"""
            return text.strip()

        # STRESS alert HTML
        mount_lines = []
        for m_pt, m_data in disk.mounts.items():
            mount_lines.append(f"{html.escape(m_pt)}: {m_data.percent_used:.1f}% ({m_data.free_gb:.1f} GB free)")
        mounts_str = ", ".join(mount_lines) if mount_lines else "N/A"

        cpu_psi_str = f"{psi.cpu.some_avg10:.1f}%" if (psi.available and psi.cpu) else "N/A"
        io_psi_str = f"{psi.io.some_avg10:.1f}%" if (psi.available and psi.io) else "N/A"
        mem_psi_str = f"{psi.memory.some_avg10:.1f}%" if (psi.available and psi.memory) else "N/A"
        temp_str = f"{temp.cpu_temp_c:.1f}°C" if (temp.available and temp.cpu_temp_c is not None) else "N/A"

        reasons = "\n".join(f"• {html.escape(r)}" for r in payload.trigger_reasons)

        text = f"""<b>{html.escape(payload.title)}</b>

⏱ <b>Duration:</b> {html.escape(payload.duration_str)}
🚨 <b>Severity:</b> {payload.severity.value}
🖥 <b>Host:</b> {html.escape(snap.hostname)}

📊 <b>Load Average:</b>
1m: <code>{load.load_1m:.2f}</code> | 5m: <code>{load.load_5m:.2f}</code> | 15m: <code>{load.load_15m:.2f}</code>
<i>(Logical CPUs: {load.cpu_count})</i>

⚡ <b>CPU:</b> {cpu.overall_percent:.1f}% (Idle: {cpu.idle_percent:.1f}%)
💨 <b>CPU Pressure:</b> {html.escape(cpu_psi_str)}
🌡 <b>Temperature:</b> {html.escape(temp_str)}

💾 <b>RAM:</b> {mem.used_percent:.1f}% used
📦 <b>Available RAM:</b> {mem.available_mb / 1024.0:.1f} GB ({mem.available_percent:.1f}%)
🔄 <b>Swap:</b> {mem.swap_percent:.1f}% | <b>Mem Pressure:</b> {html.escape(mem_psi_str)}

💽 <b>Disk (/):</b> {mounts_str}
⏳ <b>I/O Wait:</b> {disk.iowait_percent:.1f}% | <b>I/O Pressure:</b> {html.escape(io_psi_str)}

🎯 <b>Top suspected resource:</b>
<b>{html.escape(payload.primary_bottleneck)}</b>

⚠️ <b>Contributing factors:</b>
{reasons}

<i>Monitoring continues...</i>"""
        return text.strip()

    def send_raw_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send raw text message to Telegram chat."""
        if not self.is_configured():
            logger.debug("Telegram notifier is not configured or disabled.")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if resp.status == 200:
                    logger.info("Telegram notification successfully sent.")
                    return True
                else:
                    logger.error("Telegram API returned non-200 status: %s", resp.status)
                    return False
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error("Telegram API HTTP error (%s): %s", e.code, err_body)
            # If HTML parsing fails for any reason, retry with plain text
            if parse_mode == "HTML":
                logger.info("Retrying Telegram message with plain text fallback...")
                return self.send_raw_message(text, parse_mode="")
            return False
        except Exception as e:
            logger.error("Failed to send Telegram notification: %s", e)
            return False

    def send_alert(self, payload: AlertPayload) -> bool:
        """Format and send alert payload to Telegram."""
        html_msg = self._format_html(payload)
        return self.send_raw_message(html_msg, parse_mode="HTML")
