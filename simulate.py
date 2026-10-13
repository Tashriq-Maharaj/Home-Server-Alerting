#!/usr/bin/env python3
"""
Server Alerting - Scenario Simulation & End-to-End Test Runner
Allows testing stress detection, Telegram notifications, and recovery alerts
without having to stress or destabilize your actual production server.
"""

import argparse
import sys
import time
from typing import Callable, List

# Ensure safe UTF-8 output across all consoles (Windows, Linux, macOS)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.collectors.base import (
    ContainerStatus,
    CpuMetrics,
    DiskMetrics,
    DiskMountMetrics,
    DockerMetrics,
    LoadMetrics,
    MemoryMetrics,
    PsiMetrics,
    PsiResourceMetrics,
    SystemErrorMetrics,
    SystemSnapshot,
    ThermalMetrics,
)
from src.config import load_config
from src.engine import MonitoringStateMachine, StressEvaluator
from src.notifiers import NotificationDispatcher, format_recovery_text, format_stress_text


def make_healthy_snapshot(hostname: str = "homeserver") -> SystemSnapshot:
    """Generate a baseline healthy snapshot."""
    return SystemSnapshot(
        hostname=hostname,
        load=LoadMetrics(load_1m=1.1, load_5m=0.9, load_15m=0.7, cpu_count=4, normalized_1m=0.28),
        cpu=CpuMetrics(overall_percent=22.0, user_percent=12.0, system_percent=8.0, idle_percent=78.0, iowait_percent=0.5),
        memory=MemoryMetrics(total_mb=16000, used_mb=5500, available_mb=10500, available_percent=65.6, used_percent=34.4, swap_percent=2.0),
        disk=DiskMetrics(
            mounts={"/": DiskMountMetrics(mount_point="/", total_gb=500, used_gb=180, free_gb=320, percent_used=36.0)},
            read_mb_s=1.2,
            write_mb_s=2.5,
            iowait_percent=0.5,
        ),
        psi=PsiMetrics(
            available=True,
            cpu=PsiResourceMetrics(some_avg10=0.5),
            memory=PsiResourceMetrics(some_avg10=0.0),
            io=PsiResourceMetrics(some_avg10=0.2),
        ),
        thermal=ThermalMetrics(available=True, cpu_temp_c=46.5),
        docker=DockerMetrics(
            available=True,
            containers={
                "prometheus": ContainerStatus(name="prometheus", status="running", running=True),
                "grafana": ContainerStatus(name="grafana", status="running", running=True),
                "sqlserver": ContainerStatus(name="sqlserver", status="running", running=True),
                "plex": ContainerStatus(name="plex", status="running", running=True),
            },
        ),
        system_errors=SystemErrorMetrics(oom_kills_detected=0, failed_systemd_units=[], readonly_mounts=[]),
    )


def run_simulation(
    scenario_name: str,
    description: str,
    snapshots_generator: Callable[[], List[tuple[str, SystemSnapshot, int]]],
    real_notify: bool = False,
):
    """
    Run a simulation scenario through the evaluator and state machine.
    snapshots_generator returns a list of tuples: (phase_description, snapshot, duration_seconds)
    """
    config = load_config()
    # Fast simulation timing: 5s sustained thresholds so tests complete quickly
    config.monitoring.stress_duration_seconds = 5
    config.monitoring.recovery_duration_seconds = 5

    evaluator = StressEvaluator(config)
    state_machine = MonitoringStateMachine(config)
    dispatcher = NotificationDispatcher(config)

    print("\n" + "=" * 65)
    print(f"🎬 SIMULATION SCENARIO: {scenario_name.upper()}")
    print(f"ℹ️  {description}")
    print(f"📡 Real Telegram Dispatch: {'ENABLED (will send to your chat)' if real_notify else 'DISABLED (Console output only)'}")
    print("=" * 65)

    phases = snapshots_generator()
    virtual_time = 1000.0
    alerts_fired = 0

    for phase_label, snapshot, phase_duration in phases:
        print(f"\n[PHASE] {phase_label} (Simulating {phase_duration}s)...")
        # Step through second-by-second in 1s increments
        steps = phase_duration
        for step in range(steps):
            virtual_time += 1.0

            # Mock time in state_machine
            import unittest.mock as mock
            with mock.patch("time.time", return_value=virtual_time):
                eval_res = evaluator.evaluate(snapshot)
                alert = state_machine.process(eval_res)

                if alert:
                    alerts_fired += 1
                    print(f"\n🔔 >>> ALERT TRIGGERED! ({alert.alert_type} - {alert.severity.value}) <<<")
                    print(f"Title:        {alert.title}")
                    print(f"Duration:     {alert.duration_str}")
                    print(f"Bottleneck:   {alert.primary_bottleneck}")
                    print("Reasons:")
                    for r in alert.trigger_reasons:
                        print(f"  • {r}")

                    if real_notify:
                        print("🚀 Sending live alert to Telegram...")
                        dispatched = dispatcher.dispatch(alert)
                        if dispatched > 0:
                            print("✅ Successfully delivered to Telegram!")
                        else:
                            print("❌ Delivery failed. Check .env credentials.")
                    else:
                        print("💡 (Dry-run mode: pass --notify to receive this on Telegram)")

        # Brief visual pause so the user can follow along in the console
        time.sleep(1.0)

    print("\n" + "=" * 65)
    print(f"🏁 Scenario '{scenario_name}' completed. Total alerts fired: {alerts_fired}")
    print("=" * 65 + "\n")


# ==============================================================================
# Scenario Generators
# ==============================================================================

def scenario_cpu_stress():
    """Simulates sustained high CPU and 4-core load, followed by complete recovery."""
    healthy = make_healthy_snapshot()

    stressed = make_healthy_snapshot()
    stressed.cpu.overall_percent = 94.5
    stressed.cpu.idle_percent = 5.5
    stressed.load.load_1m = 6.42
    stressed.load.load_5m = 5.10
    stressed.psi.cpu.some_avg10 = 36.5
    stressed.thermal.cpu_temp_c = 78.0

    return [
        ("Baseline Normal Operation", healthy, 2),
        ("Sustained CPU Contention (94% CPU, Load 6.42, PSI 36%)", stressed, 8),
        ("System Load Normalizing & Cooling Down", healthy, 8),
    ]


def scenario_docker_failure():
    """Simulates a critical container (sqlserver) crashing and then restarting."""
    healthy = make_healthy_snapshot()

    crashed = make_healthy_snapshot()
    crashed.docker.containers["sqlserver"] = ContainerStatus(
        name="sqlserver",
        status="exited (1)",
        running=False,
        restarting=False,
        exit_code=1,
    )

    return [
        ("All Containers Healthy", healthy, 2),
        ("Container 'sqlserver' Crashes (exit code 1)", crashed, 8),
        ("Container 'sqlserver' Restarted & Healthy", healthy, 8),
    ]


def scenario_memory_pressure():
    """Simulates memory exhaustion: low available RAM and swap pressure."""
    healthy = make_healthy_snapshot()

    low_ram = make_healthy_snapshot()
    low_ram.memory.available_mb = 450.0
    low_ram.memory.available_percent = 2.8
    low_ram.memory.used_percent = 97.2
    low_ram.memory.swap_percent = 84.0
    low_ram.psi.memory.some_avg10 = 28.0

    return [
        ("Normal Memory Usage", healthy, 2),
        ("Memory Exhaustion (450 MB available, 84% swap, 28% PSI)", low_ram, 8),
        ("Memory Freed / Leaked Process Terminated", healthy, 8),
    ]


def scenario_transient_spike():
    """Simulates a brief 2-second spike to verify that false alarms are suppressed."""
    healthy = make_healthy_snapshot()

    spike = make_healthy_snapshot()
    spike.cpu.overall_percent = 99.0
    spike.load.load_1m = 7.0

    return [
        ("Normal Operation", healthy, 2),
        ("Brief 2-second CPU Spike (Testing Anti-False-Alarm Filter)", spike, 2),
        ("Returned to Normal immediately", healthy, 5),
    ]


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run simulated testing scenarios for Server Alerting without risking host stability."
    )
    parser.add_argument(
        "--scenario",
        "-s",
        choices=["cpu", "docker", "memory", "transient", "all"],
        default="cpu",
        help="Simulation scenario to execute (default: cpu).",
    )
    parser.add_argument(
        "--notify",
        "-n",
        action="store_true",
        help="Send real notifications to your Telegram/Email channels during simulation.",
    )

    args = parser.parse_args()

    scenarios = {
        "cpu": (
            "CPU & 4-Core System Load Contention",
            "Simulates high CPU (94%), load 6.42, and PSI stall pressure for sustained duration, then full recovery.",
            scenario_cpu_stress,
        ),
        "docker": (
            "Docker Container Failure & Recovery",
            "Simulates monitored container 'sqlserver' crashing (exit 1), triggering alert, followed by container restart recovery.",
            scenario_docker_failure,
        ),
        "memory": (
            "RAM Starvation & Swap Pressure",
            "Simulates memory dropping to 450 MB available with heavy swap and memory PSI stalls, then recovering.",
            scenario_memory_pressure,
        ),
        "transient": (
            "Anti-False-Alarm / Transient Spike Test",
            "Simulates a brief 2-second spike to 99% CPU to prove that the system does NOT fire nuisance alerts.",
            scenario_transient_spike,
        ),
    }

    if args.scenario == "all":
        for sc_key, (sc_name, sc_desc, sc_func) in scenarios.items():
            run_simulation(sc_name, sc_desc, sc_func, real_notify=args.notify)
    else:
        sc_name, sc_desc, sc_func = scenarios[args.scenario]
        run_simulation(sc_name, sc_desc, sc_func, real_notify=args.notify)


if __name__ == "__main__":
    main()
