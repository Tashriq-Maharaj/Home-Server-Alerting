import time
import unittest
from unittest.mock import patch

from src.collectors.base import SystemSnapshot
from src.config import AppConfig
from src.engine.evaluator import StressEvaluator
from src.engine.models import EvaluationResult, HealthState, MetricFactorEvaluation, StressFactor
from src.engine.state_machine import MonitoringStateMachine


class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        # Set short sustained windows for unit tests: 60s
        self.config.monitoring.stress_duration_seconds = 60
        self.config.monitoring.recovery_duration_seconds = 60
        self.config.monitoring.alert_cooldown_seconds = 1800
        self.sm = MonitoringStateMachine(self.config)

    def _make_eval(self, state: HealthState, factor: StressFactor = StressFactor.CPU_LOAD, rec_satisfied: bool = False) -> EvaluationResult:
        eval_factor = MetricFactorEvaluation(
            factor=factor,
            state=state,
            score=0.9 if state != HealthState.HEALTHY else 0.1,
            summary="test summary",
            is_recovery_satisfied=rec_satisfied,
        )
        return EvaluationResult(
            state=state,
            primary_bottleneck=factor.value if state != HealthState.HEALTHY else "Normal",
            active_factors=[factor] if state != HealthState.HEALTHY else [],
            factor_evaluations={factor: eval_factor},
            reasons=["test reason"] if state != HealthState.HEALTHY else [],
            snapshot=SystemSnapshot(),
        )

    def test_transient_spike_suppressed(self):
        """A single spike or short burst should NOT trigger an alert."""
        t0 = 1000.0
        with patch("time.time", return_value=t0):
            # First spike sample
            alert = self.sm.process(self._make_eval(HealthState.CRITICAL))
            self.assertIsNone(alert, "Should not alert on initial spike sample")

        with patch("time.time", return_value=t0 + 20.0):
            # 20 seconds later, still spiked
            alert = self.sm.process(self._make_eval(HealthState.CRITICAL))
            self.assertIsNone(alert, "Should not alert before stress_duration_seconds (60s)")

        with patch("time.time", return_value=t0 + 30.0):
            # System recovers back to healthy at 30 seconds
            alert = self.sm.process(self._make_eval(HealthState.HEALTHY, rec_satisfied=True))
            self.assertIsNone(alert, "Transient spike resolved without alert")
            self.assertEqual(self.sm.current_state, HealthState.HEALTHY)
            self.assertFalse(self.sm.alerted_in_current_episode)

    def test_sustained_stress_triggers_single_alert_and_no_spam(self):
        """Sustained stress >= 60s triggers exactly ONE alert without continuous spam."""
        t0 = 1000.0

        with patch("time.time", return_value=t0):
            alert = self.sm.process(self._make_eval(HealthState.CRITICAL))
            self.assertIsNone(alert)

        with patch("time.time", return_value=t0 + 60.0):
            # Reached 60s of sustained stress
            alert = self.sm.process(self._make_eval(HealthState.CRITICAL))
            self.assertIsNotNone(alert, "Should alert after sustained duration")
            self.assertEqual(alert.alert_type, "STRESS")
            self.assertEqual(alert.severity, HealthState.CRITICAL)
            self.assertTrue(self.sm.alerted_in_current_episode)

        # Subsequent samples while still in stress should NOT spam alerts
        with patch("time.time", return_value=t0 + 70.0):
            alert = self.sm.process(self._make_eval(HealthState.CRITICAL))
            self.assertIsNone(alert, "Must not spam alerts during ongoing stress")

        with patch("time.time", return_value=t0 + 120.0):
            alert = self.sm.process(self._make_eval(HealthState.CRITICAL))
            self.assertIsNone(alert, "Must not spam alerts before cooldown")

    def test_escalation_from_warning_to_critical(self):
        """When sustained warning escalates to critical, send an escalation alert."""
        t0 = 1000.0

        with patch("time.time", return_value=t0):
            self.sm.process(self._make_eval(HealthState.WARNING))

        with patch("time.time", return_value=t0 + 60.0):
            alert = self.sm.process(self._make_eval(HealthState.WARNING))
            self.assertIsNotNone(alert)
            self.assertEqual(alert.severity, HealthState.WARNING)

        with patch("time.time", return_value=t0 + 90.0):
            # Escalates to CRITICAL
            alert = self.sm.process(self._make_eval(HealthState.CRITICAL))
            self.assertIsNotNone(alert, "Escalation should trigger notification")
            self.assertEqual(alert.severity, HealthState.CRITICAL)
            self.assertIn("ESCALATED", alert.title)

    def test_recovery_hysteresis_and_notification(self):
        """Recovery requires meeting recovery criteria for sustained recovery duration."""
        t0 = 1000.0

        # 1. Trigger sustained stress
        with patch("time.time", return_value=t0):
            self.sm.process(self._make_eval(HealthState.CRITICAL))
        with patch("time.time", return_value=t0 + 60.0):
            alert = self.sm.process(self._make_eval(HealthState.CRITICAL))
            self.assertIsNotNone(alert)

        # 2. Server evaluates as HEALTHY, but recovery hysteresis not satisfied (e.g. CPU in recovery gap)
        with patch("time.time", return_value=t0 + 100.0):
            alert = self.sm.process(self._make_eval(HealthState.HEALTHY, rec_satisfied=False))
            self.assertIsNone(alert, "Must not recover if recovery threshold not satisfied")

        # 3. Server satisfies recovery threshold, but not sustained yet
        with patch("time.time", return_value=t0 + 120.0):
            alert = self.sm.process(self._make_eval(HealthState.HEALTHY, rec_satisfied=True))
            self.assertIsNone(alert, "Must sustain recovery duration before alerting")

        # 4. Sustained recovery for 60s
        with patch("time.time", return_value=t0 + 180.0):
            alert = self.sm.process(self._make_eval(HealthState.HEALTHY, rec_satisfied=True))
            self.assertIsNotNone(alert, "Should emit recovery alert after sustained recovery")
            self.assertEqual(alert.alert_type, "RECOVERY")
            self.assertEqual(self.sm.current_state, HealthState.HEALTHY)
            self.assertFalse(self.sm.alerted_in_current_episode)


if __name__ == "__main__":
    unittest.main()
