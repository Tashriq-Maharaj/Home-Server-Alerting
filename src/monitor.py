"""
Main monitoring engine and loop orchestration.
Handles lifecycle, graceful shutdown signals, safe collection, and alerting.
"""

import logging
import logging.handlers
import os
import signal
import sys
import time
from typing import Optional

from src.collectors import (
    CpuCollector,
    DiskCollector,
    DockerCollector,
    MemoryCollector,
    PsiCollector,
    SystemErrorsCollector,
    SystemSnapshot,
    ThermalCollector,
)
from src.config import AppConfig
from src.engine import MonitoringStateMachine, StressEvaluator
from src.notifiers import NotificationDispatcher, format_stress_text

logger = logging.getLogger("server_alerting")


def setup_logging(config: AppConfig) -> None:
    """Set up structured logging with rotation and stdout formatting."""
    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (standard out, systemd journal friendly)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(log_level)
    ch.setFormatter(formatter)
    root_logger.addHandler(ch)

    # Rotating file handler (if log file path is specified and writable)
    log_file = config.logging.log_file
    if log_file:
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            fh = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=config.logging.max_bytes,
                backupCount=config.logging.backup_count,
                encoding="utf-8",
            )
            fh.setLevel(log_level)
            fh.setFormatter(formatter)
            root_logger.addHandler(fh)
        except Exception as e:
            root_logger.warning("Could not set up file logging to '%s': %s", log_file, e)


class ServerMonitor:
    """Continuous server monitoring agent."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._running = False

        # Collectors
        self.cpu_collector = CpuCollector(config.server)
        self.memory_collector = MemoryCollector()
        self.disk_collector = DiskCollector(config.thresholds.disk.mounts)
        self.psi_collector = PsiCollector()
        self.thermal_collector = ThermalCollector()
        self.docker_collector = DockerCollector(config.docker)
        self.system_errors_collector = SystemErrorsCollector(config.system_errors)

        # Engine & Notifiers
        self.evaluator = StressEvaluator(config)
        self.state_machine = MonitoringStateMachine(config)
        self.dispatcher = NotificationDispatcher(config)

    def _setup_signal_handlers(self) -> None:
        """Register graceful shutdown handlers for SIGINT and SIGTERM."""
        def handle_signal(sig, frame):
            sig_name = "SIGTERM" if sig == signal.SIGTERM else "SIGINT"
            logger.info("Received %s signal. Initiating graceful shutdown...", sig_name)
            self._running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    def take_snapshot(self) -> SystemSnapshot:
        """Take a complete system metrics snapshot safely without crashing."""
        snapshot = SystemSnapshot(hostname=self.config.server.hostname)

        # 1. CPU & Load
        try:
            load_m, cpu_m = self.cpu_collector.collect()
            snapshot.load = load_m
            snapshot.cpu = cpu_m
        except Exception as e:
            logger.error("Error collecting CPU/Load metrics: %s", e)

        # 2. Memory
        try:
            snapshot.memory = self.memory_collector.collect()
        except Exception as e:
            logger.error("Error collecting memory metrics: %s", e)

        # 3. Disk (with iowait from CPU)
        try:
            iowait = snapshot.cpu.iowait_percent
            snapshot.disk = self.disk_collector.collect(iowait_percent=iowait)
        except Exception as e:
            logger.error("Error collecting disk metrics: %s", e)

        # 4. Linux PSI
        try:
            snapshot.psi = self.psi_collector.collect()
        except Exception as e:
            logger.debug("Error collecting PSI metrics: %s", e)

        # 5. Thermal
        try:
            snapshot.thermal = self.thermal_collector.collect()
        except Exception as e:
            logger.debug("Error collecting thermal metrics: %s", e)

        # 6. Docker
        try:
            snapshot.docker = self.docker_collector.collect()
        except Exception as e:
            logger.debug("Error collecting Docker metrics: %s", e)

        # 7. System Errors
        try:
            snapshot.system_errors = self.system_errors_collector.collect()
        except Exception as e:
            logger.debug("Error collecting system errors: %s", e)

        return snapshot

    def step(self) -> None:
        """Execute a single monitoring cycle."""
        snapshot = self.take_snapshot()
        eval_result = self.evaluator.evaluate(snapshot)

        # Process through state machine
        alert = self.state_machine.process(eval_result)
        if alert:
            logger.info("Alert triggered: %s - %s", alert.title, alert.primary_bottleneck)
            self.dispatcher.dispatch(alert)

    def run_once(self) -> None:
        """Execute one collection step and display status summary."""
        snapshot = self.take_snapshot()
        eval_result = self.evaluator.evaluate(snapshot)

        print("\n" + "=" * 55)
        print(f"Server Health Snapshot: {snapshot.hostname}")
        print("=" * 55)
        print(f"Overall State:       {eval_result.state.value}")
        print(f"Primary Bottleneck:  {eval_result.primary_bottleneck}")
        print(f"Load Average:        1m={snapshot.load.load_1m}, 5m={snapshot.load.load_5m}, 15m={snapshot.load.load_15m} (CPUs: {snapshot.load.cpu_count})")
        print(f"CPU Utilization:     {snapshot.cpu.overall_percent}% (Idle: {snapshot.cpu.idle_percent}%, I/O Wait: {snapshot.cpu.iowait_percent}%)")
        print(f"RAM Available:       {snapshot.memory.available_mb / 1024.0:.2f} GB ({snapshot.memory.available_percent}%)")
        print(f"Swap Usage:          {snapshot.memory.swap_percent}%")

        if snapshot.psi.available and snapshot.psi.cpu:
            print(f"Linux PSI:           CPU={snapshot.psi.cpu.some_avg10}%, Mem={snapshot.psi.memory.some_avg10 if snapshot.psi.memory else 'N/A'}%, IO={snapshot.psi.io.some_avg10 if snapshot.psi.io else 'N/A'}%")
        else:
            print("Linux PSI:           Not available on this platform/kernel")

        if snapshot.thermal.available and snapshot.thermal.cpu_temp_c is not None:
            print(f"CPU Temperature:     {snapshot.thermal.cpu_temp_c}°C")

        for m_pt, m_data in snapshot.disk.mounts.items():
            print(f"Disk '{m_pt}':         {m_data.percent_used}% used ({m_data.free_gb:.1f} GB free)")

        if snapshot.docker.available:
            containers = snapshot.docker.containers
            running_cnt = sum(1 for c in containers.values() if c.running)
            print(f"Monitored Containers:{running_cnt}/{len(containers)} running")
        else:
            print(f"Docker Monitoring:   {snapshot.docker.error_message or 'Unavailable'}")

        if eval_result.reasons:
            print("\nActive Warnings/Errors:")
            for r in eval_result.reasons:
                print(f"  • {r}")
        print("=" * 55 + "\n")

    def run(self) -> None:
        """Start the continuous monitoring loop."""
        self._setup_signal_handlers()
        self._running = True
        interval = self.config.monitoring.interval_seconds

        logger.info(
            "Starting Server Alerting Service for %s (%s). Check interval: %ss, stress duration: %ss, recovery duration: %ss",
            self.config.server.hostname,
            self.config.server.ip_address,
            interval,
            self.config.monitoring.stress_duration_seconds,
            self.config.monitoring.recovery_duration_seconds,
        )

        while self._running:
            loop_start = time.time()
            try:
                self.step()
            except Exception as e:
                logger.exception("Unexpected exception in monitoring loop: %s", e)

            # Accurate sleep accounting for execution time
            elapsed = time.time() - loop_start
            sleep_time = max(0.5, interval - elapsed)

            # Interruptible sleep
            end_sleep = time.time() + sleep_time
            while self._running and time.time() < end_sleep:
                time.sleep(0.5)

        logger.info("Server Alerting Service stopped gracefully.")
