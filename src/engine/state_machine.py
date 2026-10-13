"""
State machine and hysteresis engine.
Maintains state across evaluation cycles, handles alert cooldowns,
requires sustained durations before firing, and tracks recovery.
"""

import logging
import time
from typing import List, Optional

from src.collectors.base import SystemSnapshot
from src.config import AppConfig
from src.engine.models import AlertPayload, EvaluationResult, HealthState, StressFactor

logger = logging.getLogger(__name__)


def format_duration(seconds: float) -> str:
    """Format duration in seconds into human-readable format like '2m 15s' or '1h 4m'."""
    sec = int(seconds)
    if sec < 60:
        return f"{sec}s"
    minutes = sec // 60
    rem_sec = sec % 60
    if minutes < 60:
        return f"{minutes}m {rem_sec:02d}s"
    hours = minutes // 60
    rem_min = minutes % 60
    return f"{hours}h {rem_min:02d}m"


class MonitoringStateMachine:
    """Tracks state over time, enforces sustained threshold durations, and manages alert hysteresis."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.current_state: HealthState = HealthState.HEALTHY

        # Stress episode tracking
        self.stress_candidate_start: Optional[float] = None
        self.stress_episode_start: Optional[float] = None
        self.initial_trigger_snapshot: Optional[SystemSnapshot] = None
        self.last_alert_time: Optional[float] = None
        self.last_alert_severity: Optional[HealthState] = None
        self.alerted_in_current_episode: bool = False
        self.active_stress_factors: List[StressFactor] = []

        # Recovery tracking
        self.recovery_candidate_start: Optional[float] = None

    def process(self, eval_result: EvaluationResult) -> Optional[AlertPayload]:
        """Process an evaluation result and return an AlertPayload if a notification should be sent."""
        now = time.time()
        snapshot = eval_result.snapshot or SystemSnapshot()
        state = eval_result.state

        # ==========================================
        # Case 1: System is currently evaluated as UNHEALTHY (WARNING or CRITICAL)
        # ==========================================
        if state in (HealthState.WARNING, HealthState.CRITICAL):
            # Reset any pending recovery candidate
            self.recovery_candidate_start = None

            # Track stress candidate
            if self.stress_candidate_start is None:
                self.stress_candidate_start = now
                self.initial_trigger_snapshot = snapshot

            duration_stressed = now - self.stress_candidate_start
            required_duration = self.config.monitoring.stress_duration_seconds

            # Has the stress been sustained long enough?
            if duration_stressed >= required_duration:
                # If entering a new alerted episode
                if not self.alerted_in_current_episode:
                    self.current_state = state
                    self.alerted_in_current_episode = True
                    self.stress_episode_start = self.stress_candidate_start
                    self.last_alert_time = now
                    self.last_alert_severity = state
                    self.active_stress_factors = list(eval_result.active_factors)

                    dur_str = format_duration(now - self.stress_episode_start)
                    icon = "🔴" if state == HealthState.CRITICAL else "⚠️"
                    title = f"{icon} Home Server Stress Detected"

                    logger.warning(
                        "Stress detected and sustained (%s). Primary bottleneck: %s",
                        dur_str,
                        eval_result.primary_bottleneck,
                    )

                    return AlertPayload(
                        alert_type="STRESS",
                        title=title,
                        severity=state,
                        duration_str=dur_str,
                        primary_bottleneck=eval_result.primary_bottleneck or "Unknown",
                        trigger_reasons=eval_result.reasons,
                        snapshot=snapshot,
                        initial_trigger_snapshot=self.initial_trigger_snapshot,
                        stress_factors=self.active_stress_factors,
                    )

                # Already alerted: Check for Escalation (WARNING -> CRITICAL)
                if self.last_alert_severity == HealthState.WARNING and state == HealthState.CRITICAL:
                    self.current_state = state
                    self.last_alert_severity = state
                    self.last_alert_time = now
                    # Add newly triggered factors
                    for f in eval_result.active_factors:
                        if f not in self.active_stress_factors:
                            self.active_stress_factors.append(f)

                    dur_str = format_duration(now - (self.stress_episode_start or now))
                    logger.critical(
                        "Stress escalated to CRITICAL (%s). Bottleneck: %s",
                        dur_str,
                        eval_result.primary_bottleneck,
                    )

                    return AlertPayload(
                        alert_type="STRESS",
                        title="🔴 Home Server Stress ESCALATED to CRITICAL",
                        severity=HealthState.CRITICAL,
                        duration_str=dur_str,
                        primary_bottleneck=eval_result.primary_bottleneck or "Unknown",
                        trigger_reasons=eval_result.reasons,
                        snapshot=snapshot,
                        initial_trigger_snapshot=self.initial_trigger_snapshot,
                        stress_factors=self.active_stress_factors,
                    )

                # Check for Alert Cooldown reminder if still stressed
                cooldown = self.config.monitoring.alert_cooldown_seconds
                if self.last_alert_time and (now - self.last_alert_time >= cooldown):
                    self.last_alert_time = now
                    dur_str = format_duration(now - (self.stress_episode_start or now))
                    logger.warning("Periodic stress reminder sent after %s cooldown", cooldown)

                    return AlertPayload(
                        alert_type="STRESS",
                        title="⚠️ Home Server Stress Ongoing (Reminder)",
                        severity=state,
                        duration_str=dur_str,
                        primary_bottleneck=eval_result.primary_bottleneck or "Unknown",
                        trigger_reasons=eval_result.reasons,
                        snapshot=snapshot,
                        initial_trigger_snapshot=self.initial_trigger_snapshot,
                        stress_factors=self.active_stress_factors,
                    )

            return None

        # ==========================================
        # Case 2: System is currently evaluated as HEALTHY
        # ==========================================
        # If stress was only transient and never reached the required sustained duration
        if not self.alerted_in_current_episode:
            self.stress_candidate_start = None
            self.initial_trigger_snapshot = None
            return None

        # If we ARE in an alerted stress episode, check if recovery criteria are satisfied
        # Check if all previously triggering stress factors meet recovery thresholds (hysteresis)
        all_recovered = True
        for factor in self.active_stress_factors:
            factor_eval = eval_result.factor_evaluations.get(factor)
            if factor_eval and not factor_eval.is_recovery_satisfied:
                all_recovered = False
                break

        if not all_recovered:
            # Still in recovery hysteresis band (e.g. CPU at 74% when trigger was 85% and recovery is 70%)
            self.recovery_candidate_start = None
            return None

        # Recovery thresholds are met; require sustained recovery duration to prevent flapping
        if self.recovery_candidate_start is None:
            self.recovery_candidate_start = now

        recovery_duration = now - self.recovery_candidate_start
        required_recovery = self.config.monitoring.recovery_duration_seconds

        if recovery_duration >= required_recovery:
            # Confirmed recovery!
            total_stress_duration = now - (self.stress_episode_start or self.stress_candidate_start or now)
            dur_str = format_duration(total_stress_duration)

            logger.info("Server recovered after %s of stress", dur_str)

            recovery_payload = AlertPayload(
                alert_type="RECOVERY",
                title="🟢 Home Server Recovered",
                severity=HealthState.HEALTHY,
                duration_str=dur_str,
                primary_bottleneck="Normal",
                trigger_reasons=[
                    f"{f.value} returned to normal levels" for f in self.active_stress_factors
                ] or ["System resources have returned to normal"],
                snapshot=snapshot,
                initial_trigger_snapshot=self.initial_trigger_snapshot,
                stress_factors=list(self.active_stress_factors),
            )

            # Reset state machine
            self.current_state = HealthState.HEALTHY
            self.stress_candidate_start = None
            self.stress_episode_start = None
            self.initial_trigger_snapshot = None
            self.alerted_in_current_episode = False
            self.active_stress_factors = []
            self.recovery_candidate_start = None
            self.last_alert_time = None
            self.last_alert_severity = None

            return recovery_payload

        return None
