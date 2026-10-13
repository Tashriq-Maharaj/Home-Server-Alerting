"""
Health and stress evaluation engine.
Correlates multiple system metrics to evaluate server stress without false positives.
"""

from typing import Dict, List, Optional

from src.collectors.base import SystemSnapshot
from src.config import AppConfig
from src.engine.models import (
    EvaluationResult,
    HealthState,
    MetricFactorEvaluation,
    StressFactor,
)


class StressEvaluator:
    """Evaluates SystemSnapshot against configured thresholds and correlates signals."""

    def __init__(self, config: AppConfig):
        self.config = config

    def _eval_cpu_load(self, snapshot: SystemSnapshot) -> MetricFactorEvaluation:
        """Evaluate CPU utilization, system load (4-core aware), and CPU PSI."""
        t_cpu = self.config.thresholds.cpu
        t_load = self.config.thresholds.load
        t_psi = self.config.thresholds.psi

        cpu = snapshot.cpu
        load = snapshot.load
        psi_cpu = snapshot.psi.cpu if (snapshot.psi and snapshot.psi.available) else None

        cpu_val = cpu.overall_percent
        load_1m = load.load_1m
        psi_avg10 = psi_cpu.some_avg10 if psi_cpu else None

        # Check critical
        is_crit = False
        reasons = []

        if load_1m >= t_load.critical_1m:
            is_crit = True
            reasons.append(f"Load 1m critically high: {load_1m:.2f} (capacity: {load.cpu_count} CPUs)")
        if cpu_val >= t_cpu.critical_percent and load_1m >= t_load.warning_1m:
            is_crit = True
            reasons.append(f"CPU sustained at {cpu_val:.1f}% with elevated load ({load_1m:.2f})")
        if psi_avg10 is not None and psi_avg10 >= t_psi.cpu_avg10_crit and load_1m >= t_load.warning_1m:
            is_crit = True
            reasons.append(f"Severe CPU stall pressure: {psi_avg10:.1f}% PSI avg10")

        # Check warning
        is_warn = False
        if not is_crit:
            if load_1m >= t_load.warning_1m:
                is_warn = True
                reasons.append(f"Load 1m elevated: {load_1m:.2f} (capacity: {load.cpu_count} CPUs)")
            if cpu_val >= t_cpu.warning_percent:
                is_warn = True
                reasons.append(f"High CPU utilization: {cpu_val:.1f}%")
            if psi_avg10 is not None and psi_avg10 >= t_psi.cpu_avg10_warn:
                is_warn = True
                reasons.append(f"Elevated CPU stall pressure: {psi_avg10:.1f}% PSI avg10")

        state = HealthState.CRITICAL if is_crit else (HealthState.WARNING if is_warn else HealthState.HEALTHY)

        # Recovery criteria (hysteresis)
        recovery_satisfied = (
            cpu_val <= t_cpu.recovery_percent
            and load_1m <= t_load.recovery_1m
            and (psi_avg10 is None or psi_avg10 <= t_psi.cpu_avg10_recovery)
        )

        score = min(1.0, max(cpu_val / 100.0, load.normalized_1m / 2.0))
        summary = "; ".join(reasons) if reasons else "CPU and load normal"

        return MetricFactorEvaluation(
            factor=StressFactor.CPU_LOAD,
            state=state,
            score=score,
            summary=summary,
            details={
                "cpu_percent": f"{cpu_val:.1f}%",
                "load_1m": f"{load_1m:.2f}",
                "load_5m": f"{load.load_5m:.2f}",
                "psi_cpu_avg10": f"{psi_avg10:.1f}%" if psi_avg10 is not None else "N/A",
            },
            is_recovery_satisfied=recovery_satisfied,
        )

    def _eval_memory(self, snapshot: SystemSnapshot) -> MetricFactorEvaluation:
        """Evaluate RAM, available memory (Linux cache-aware), swap, and Memory PSI."""
        t_mem = self.config.thresholds.memory
        t_psi = self.config.thresholds.psi

        mem = snapshot.memory
        psi_mem = snapshot.psi.memory if (snapshot.psi and snapshot.psi.available) else None
        psi_avg10 = psi_mem.some_avg10 if psi_mem else None

        avail_pct = mem.available_percent
        avail_mb = mem.available_mb
        swap_pct = mem.swap_percent

        is_crit = False
        is_warn = False
        reasons = []

        if avail_mb <= t_mem.min_available_mb_crit or avail_pct <= t_mem.min_available_percent_crit:
            is_crit = True
            reasons.append(f"Available RAM critically low: {avail_mb:.0f} MB ({avail_pct:.1f}%)")
        elif avail_mb <= t_mem.min_available_mb_warn or avail_pct <= t_mem.min_available_percent_warn:
            is_warn = True
            reasons.append(f"Available RAM low: {avail_mb:.0f} MB ({avail_pct:.1f}%)")

        if psi_avg10 is not None:
            if psi_avg10 >= t_psi.memory_avg10_crit:
                is_crit = True
                reasons.append(f"Severe memory stall pressure: {psi_avg10:.1f}% PSI avg10")
            elif psi_avg10 >= t_psi.memory_avg10_warn:
                is_warn = True
                reasons.append(f"Elevated memory stall pressure: {psi_avg10:.1f}% PSI avg10")

        if swap_pct >= t_mem.swap_percent_crit:
            is_crit = True
            reasons.append(f"Critical swap usage: {swap_pct:.1f}%")
        elif swap_pct >= t_mem.swap_percent_warn:
            is_warn = True
            reasons.append(f"Elevated swap usage: {swap_pct:.1f}%")

        state = HealthState.CRITICAL if is_crit else (HealthState.WARNING if is_warn else HealthState.HEALTHY)

        recovery_satisfied = (
            avail_pct >= t_mem.recovery_available_percent
            and swap_pct <= t_mem.recovery_swap_percent
            and (psi_avg10 is None or psi_avg10 <= t_psi.memory_avg10_recovery)
        )

        score = min(1.0, max(1.0 - (avail_pct / 100.0), swap_pct / 100.0))
        summary = "; ".join(reasons) if reasons else "Memory capacity normal"

        return MetricFactorEvaluation(
            factor=StressFactor.MEMORY_PRESSURE,
            state=state,
            score=score,
            summary=summary,
            details={
                "available_ram_mb": f"{avail_mb:.0f} MB",
                "available_percent": f"{avail_pct:.1f}%",
                "swap_percent": f"{swap_pct:.1f}%",
                "psi_mem_avg10": f"{psi_avg10:.1f}%" if psi_avg10 is not None else "N/A",
            },
            is_recovery_satisfied=recovery_satisfied,
        )

    def _eval_disk_capacity(self, snapshot: SystemSnapshot) -> MetricFactorEvaluation:
        """Evaluate filesystem capacity for monitored mounts."""
        t_disk = self.config.thresholds.disk
        is_crit = False
        is_warn = False
        reasons = []
        max_used_pct = 0.0

        for mount_pt, m_stats in snapshot.disk.mounts.items():
            used_pct = m_stats.percent_used
            if used_pct > max_used_pct:
                max_used_pct = used_pct

            if used_pct >= t_disk.critical_percent:
                is_crit = True
                reasons.append(f"Mount '{mount_pt}' critically full: {used_pct:.1f}% ({m_stats.free_gb:.1f} GB free)")
            elif used_pct >= t_disk.warning_percent:
                is_warn = True
                reasons.append(f"Mount '{mount_pt}' approaching capacity: {used_pct:.1f}% ({m_stats.free_gb:.1f} GB free)")

        state = HealthState.CRITICAL if is_crit else (HealthState.WARNING if is_warn else HealthState.HEALTHY)
        recovery_satisfied = max_used_pct <= t_disk.recovery_percent

        score = min(1.0, max_used_pct / 100.0)
        summary = "; ".join(reasons) if reasons else "Disk capacity normal"

        return MetricFactorEvaluation(
            factor=StressFactor.DISK_CAPACITY,
            state=state,
            score=score,
            summary=summary,
            details={"highest_mount_usage": f"{max_used_pct:.1f}%"},
            is_recovery_satisfied=recovery_satisfied,
        )

    def _eval_disk_io(self, snapshot: SystemSnapshot) -> MetricFactorEvaluation:
        """Evaluate disk I/O wait, throughput, and I/O PSI."""
        t_disk = self.config.thresholds.disk
        t_psi = self.config.thresholds.psi

        iowait = snapshot.cpu.iowait_percent
        psi_io = snapshot.psi.io if (snapshot.psi and snapshot.psi.available) else None
        psi_avg10 = psi_io.some_avg10 if psi_io else None

        is_crit = False
        is_warn = False
        reasons = []

        if iowait >= t_disk.iowait_critical_percent:
            is_crit = True
            reasons.append(f"Severe disk I/O wait: {iowait:.1f}%")
        elif iowait >= t_disk.iowait_warning_percent:
            is_warn = True
            reasons.append(f"Elevated disk I/O wait: {iowait:.1f}%")

        if psi_avg10 is not None:
            if psi_avg10 >= t_psi.io_avg10_crit:
                is_crit = True
                reasons.append(f"Severe I/O stall pressure: {psi_avg10:.1f}% PSI avg10")
            elif psi_avg10 >= t_psi.io_avg10_warn:
                is_warn = True
                reasons.append(f"Elevated I/O stall pressure: {psi_avg10:.1f}% PSI avg10")

        state = HealthState.CRITICAL if is_crit else (HealthState.WARNING if is_warn else HealthState.HEALTHY)
        recovery_satisfied = (
            iowait <= t_disk.recovery_iowait_percent
            and (psi_avg10 is None or psi_avg10 <= t_psi.io_avg10_recovery)
        )

        score = min(1.0, max(iowait / 50.0, (psi_avg10 or 0.0) / 50.0))
        summary = "; ".join(reasons) if reasons else "Disk I/O normal"

        return MetricFactorEvaluation(
            factor=StressFactor.DISK_IO,
            state=state,
            score=score,
            summary=summary,
            details={
                "iowait_percent": f"{iowait:.1f}%",
                "psi_io_avg10": f"{psi_avg10:.1f}%" if psi_avg10 is not None else "N/A",
                "read_mb_s": f"{snapshot.disk.read_mb_s:.2f} MB/s",
                "write_mb_s": f"{snapshot.disk.write_mb_s:.2f} MB/s",
            },
            is_recovery_satisfied=recovery_satisfied,
        )

    def _eval_thermal(self, snapshot: SystemSnapshot) -> MetricFactorEvaluation:
        """Evaluate hardware temperatures if sensors are available."""
        t_temp = self.config.thresholds.temperature
        thermal = snapshot.thermal

        if not thermal.available or thermal.cpu_temp_c is None:
            return MetricFactorEvaluation(
                factor=StressFactor.TEMPERATURE,
                state=HealthState.HEALTHY,
                score=0.0,
                summary="Temperature sensor unavailable",
                is_recovery_satisfied=True,
            )

        cpu_temp = thermal.cpu_temp_c
        is_crit = cpu_temp >= t_temp.critical_celsius
        is_warn = (not is_crit) and (cpu_temp >= t_temp.warning_celsius)

        state = HealthState.CRITICAL if is_crit else (HealthState.WARNING if is_warn else HealthState.HEALTHY)
        recovery_satisfied = cpu_temp <= t_temp.recovery_celsius

        reasons = []
        if is_crit:
            reasons.append(f"CPU temperature critically high: {cpu_temp:.1f}°C")
        elif is_warn:
            reasons.append(f"CPU temperature elevated: {cpu_temp:.1f}°C")

        score = min(1.0, max(0.0, (cpu_temp - 50.0) / 50.0))
        summary = "; ".join(reasons) if reasons else f"Temperature normal ({cpu_temp:.1f}°C)"

        return MetricFactorEvaluation(
            factor=StressFactor.TEMPERATURE,
            state=state,
            score=score,
            summary=summary,
            details={"cpu_temperature": f"{cpu_temp:.1f}°C"},
            is_recovery_satisfied=recovery_satisfied,
        )

    def _eval_docker(self, snapshot: SystemSnapshot) -> MetricFactorEvaluation:
        """Evaluate Docker containers and detect stopped or crash-looping services."""
        docker = snapshot.docker
        if not docker.available:
            return MetricFactorEvaluation(
                factor=StressFactor.DOCKER_SERVICE,
                state=HealthState.HEALTHY,
                score=0.0,
                summary=docker.error_message or "Docker not active",
                is_recovery_satisfied=True,
            )

        failed_containers = []
        restarting_containers = []

        for name, info in docker.containers.items():
            if info.restarting:
                restarting_containers.append(name)
            elif not info.running and info.status != "running":
                # Stopped or exited
                failed_containers.append(f"{name} ({info.status})")

        is_crit = bool(restarting_containers or failed_containers)
        state = HealthState.CRITICAL if is_crit else HealthState.HEALTHY
        recovery_satisfied = not is_crit

        reasons = []
        if restarting_containers:
            reasons.append(f"Containers restarting: {', '.join(restarting_containers)}")
        if failed_containers:
            reasons.append(f"Containers stopped/unhealthy: {', '.join(failed_containers)}")

        summary = "; ".join(reasons) if reasons else "All monitored containers healthy"

        return MetricFactorEvaluation(
            factor=StressFactor.DOCKER_SERVICE,
            state=state,
            score=0.9 if is_crit else 0.0,
            summary=summary,
            details={
                "failed_containers": ", ".join(failed_containers) if failed_containers else "none",
                "restarting_containers": ", ".join(restarting_containers) if restarting_containers else "none",
            },
            is_recovery_satisfied=recovery_satisfied,
        )

    def _eval_system_errors(self, snapshot: SystemSnapshot) -> MetricFactorEvaluation:
        """Evaluate OOM kills, read-only mounts, and failed systemd units."""
        errors = snapshot.system_errors
        reasons = []
        is_crit = False
        is_warn = False

        if errors.oom_kills_detected > 0:
            is_crit = True
            reasons.append(f"{errors.oom_kills_detected} new OOM kill(s) detected")

        if errors.readonly_mounts:
            is_crit = True
            reasons.append(f"Read-only filesystem corruption detected: {', '.join(errors.readonly_mounts)}")

        if errors.failed_systemd_units:
            is_warn = True
            reasons.append(f"Failed systemd services: {', '.join(errors.failed_systemd_units)}")

        state = HealthState.CRITICAL if is_crit else (HealthState.WARNING if is_warn else HealthState.HEALTHY)
        recovery_satisfied = not is_crit and not is_warn

        summary = "; ".join(reasons) if reasons else "No system-level errors detected"

        return MetricFactorEvaluation(
            factor=StressFactor.SYSTEM_ERROR,
            state=state,
            score=1.0 if is_crit else (0.6 if is_warn else 0.0),
            summary=summary,
            details={
                "oom_kills_detected": str(errors.oom_kills_detected),
                "failed_systemd_units": ", ".join(errors.failed_systemd_units) or "none",
            },
            is_recovery_satisfied=recovery_satisfied,
        )

    def evaluate(self, snapshot: SystemSnapshot) -> EvaluationResult:
        """Run all evaluators on snapshot and identify overall health and primary bottleneck."""
        evals: Dict[StressFactor, MetricFactorEvaluation] = {
            StressFactor.CPU_LOAD: self._eval_cpu_load(snapshot),
            StressFactor.MEMORY_PRESSURE: self._eval_memory(snapshot),
            StressFactor.DISK_CAPACITY: self._eval_disk_capacity(snapshot),
            StressFactor.DISK_IO: self._eval_disk_io(snapshot),
            StressFactor.TEMPERATURE: self._eval_thermal(snapshot),
            StressFactor.DOCKER_SERVICE: self._eval_docker(snapshot),
            StressFactor.SYSTEM_ERROR: self._eval_system_errors(snapshot),
        }

        # Determine overall state (highest severity)
        overall_state = HealthState.HEALTHY
        for e in evals.values():
            if e.state == HealthState.CRITICAL:
                overall_state = HealthState.CRITICAL
                break
            elif e.state == HealthState.WARNING:
                overall_state = HealthState.WARNING

        # Collect active factors & reasons
        active_factors: List[StressFactor] = []
        reasons: List[str] = []
        highest_factor: Optional[StressFactor] = None
        max_score = -1.0

        for factor, e in evals.items():
            if e.state != HealthState.HEALTHY:
                active_factors.append(factor)
                reasons.append(f"{factor.value}: {e.summary}")
                if e.score > max_score:
                    max_score = e.score
                    highest_factor = factor

        primary_bottleneck = highest_factor.value if highest_factor else "Normal operation"

        return EvaluationResult(
            state=overall_state,
            primary_bottleneck=primary_bottleneck,
            active_factors=active_factors,
            factor_evaluations=evals,
            reasons=reasons,
            snapshot=snapshot,
        )
