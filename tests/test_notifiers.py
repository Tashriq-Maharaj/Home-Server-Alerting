import unittest

from src.collectors.base import (
    CpuMetrics,
    DiskMetrics,
    DiskMountMetrics,
    LoadMetrics,
    MemoryMetrics,
    PsiMetrics,
    PsiResourceMetrics,
    SystemSnapshot,
    ThermalMetrics,
)
from src.config import TelegramConfig
from src.engine.models import AlertPayload, HealthState, StressFactor
from src.notifiers.base import format_recovery_text, format_stress_text
from src.notifiers.telegram import TelegramNotifier


class TestNotifiers(unittest.TestCase):
    def _create_sample_payload(self, alert_type="STRESS") -> AlertPayload:
        snap = SystemSnapshot(
            hostname="homeserver",
            load=LoadMetrics(load_1m=6.21, load_5m=5.14, load_15m=2.91, cpu_count=4),
            cpu=CpuMetrics(overall_percent=94.0, idle_percent=6.0, iowait_percent=4.2),
            memory=MemoryMetrics(total_mb=16000, available_mb=2100, available_percent=13.1, used_percent=86.9, swap_percent=4.0),
            disk=DiskMetrics(
                mounts={"/": DiskMountMetrics(mount_point="/", total_gb=500, used_gb=310, free_gb=190, percent_used=62.0)},
                iowait_percent=4.2,
            ),
            psi=PsiMetrics(
                available=True,
                cpu=PsiResourceMetrics(some_avg10=38.2),
                io=PsiResourceMetrics(some_avg10=31.0),
            ),
            thermal=ThermalMetrics(available=True, cpu_temp_c=74.5),
        )

        return AlertPayload(
            alert_type=alert_type,
            title="🔴 Home Server Stress Detected" if alert_type == "STRESS" else "🟢 Home Server Recovered",
            severity=HealthState.CRITICAL if alert_type == "STRESS" else HealthState.HEALTHY,
            duration_str="2m 15s" if alert_type == "STRESS" else "7m 42s",
            primary_bottleneck="CPU / system load",
            trigger_reasons=["Load 1m critically high: 6.21", "Severe CPU stall pressure: 38.2%"],
            snapshot=snap,
            stress_factors=[StressFactor.CPU_LOAD],
        )

    def test_format_stress_text(self):
        payload = self._create_sample_payload("STRESS")
        text = format_stress_text(payload)
        self.assertIn("Home Server Stress Detected", text)
        self.assertIn("6.21", text)
        self.assertIn("94.0%", text)
        self.assertIn("CPU / system load", text)
        self.assertIn("38.2%", text)

    def test_format_recovery_text(self):
        payload = self._create_sample_payload("RECOVERY")
        text = format_recovery_text(payload)
        self.assertIn("Home Server Recovered", text)
        self.assertIn("7m 42s", text)
        self.assertIn("returned to normal operating thresholds", text)

    def test_telegram_html_formatting(self):
        cfg = TelegramConfig(enabled=True, bot_token="123:dummy", chat_id="999")
        notifier = TelegramNotifier(cfg)
        self.assertTrue(notifier.is_configured())

        payload = self._create_sample_payload("STRESS")
        html_msg = notifier._format_html(payload)
        self.assertIn("<b>🔴 Home Server Stress Detected</b>", html_msg)
        self.assertIn("<code>6.21</code>", html_msg)
        self.assertIn("<b>CPU / system load</b>", html_msg)

        rec_payload = self._create_sample_payload("RECOVERY")
        rec_html = notifier._format_html(rec_payload)
        self.assertIn("<b>🟢 Home Server Recovered</b>", rec_html)
        self.assertIn("7m 42s", rec_html)


if __name__ == "__main__":
    unittest.main()
