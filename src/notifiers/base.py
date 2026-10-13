"""
Base notification interfaces and message formatters.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.engine.models import AlertPayload


class BaseNotifier(ABC):
    """Abstract base notifier interface."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if notifier has necessary credentials and configuration."""
        pass

    @abstractmethod
    def send_alert(self, payload: AlertPayload) -> bool:
        """Send formatted alert payload. Return True if successfully sent."""
        pass


def format_stress_text(payload: AlertPayload) -> str:
    """Format stress alert into a structured, readable message."""
    snap = payload.snapshot
    load = snap.load
    cpu = snap.cpu
    mem = snap.memory
    disk = snap.disk
    psi = snap.psi
    temp = snap.thermal

    # Format mount point summary
    mount_lines = []
    for m_pt, m_data in disk.mounts.items():
        mount_lines.append(f"{m_pt}: {m_data.percent_used:.1f}% ({m_data.free_gb:.1f} GB free)")
    mounts_str = ", ".join(mount_lines) if mount_lines else "N/A"

    # Format PSI summary
    cpu_psi_str = f"{psi.cpu.some_avg10:.1f}%" if (psi.available and psi.cpu) else "N/A"
    io_psi_str = f"{psi.io.some_avg10:.1f}%" if (psi.available and psi.io) else "N/A"
    mem_psi_str = f"{psi.memory.some_avg10:.1f}%" if (psi.available and psi.memory) else "N/A"

    temp_str = f"{temp.cpu_temp_c:.1f}°C" if (temp.available and temp.cpu_temp_c is not None) else "N/A"

    reasons_formatted = "\n".join(f"• {r}" for r in payload.trigger_reasons)

    msg = f"""{payload.title}

Duration: {payload.duration_str}
Severity: {payload.severity.value}
Host: {snap.hostname}

Load:
1m: {load.load_1m:.2f} | 5m: {load.load_5m:.2f} | 15m: {load.load_15m:.2f}
(Logical CPUs: {load.cpu_count})

CPU: {cpu.overall_percent:.1f}% (Idle: {cpu.idle_percent:.1f}%)
CPU Pressure: {cpu_psi_str}
Temperature: {temp_str}

RAM: {mem.used_percent:.1f}% used
Available RAM: {mem.available_mb / 1024.0:.1f} GB ({mem.available_percent:.1f}%)
Swap: {mem.swap_percent:.1f}%
Memory Pressure: {mem_psi_str}

Disk Usage: {mounts_str}
I/O Wait: {disk.iowait_percent:.1f}% | I/O Pressure: {io_psi_str}

Top suspected resource:
{payload.primary_bottleneck}

Contributing factors:
{reasons_formatted}

Monitoring continues..."""
    return msg.strip()


def format_recovery_text(payload: AlertPayload) -> str:
    """Format recovery alert into a structured, readable message."""
    snap = payload.snapshot
    load = snap.load
    cpu = snap.cpu
    mem = snap.memory
    psi = snap.psi

    io_psi_str = f"{psi.io.some_avg10:.1f}%" if (psi.available and psi.io) else "Normal"

    msg = f"""{payload.title}

Stress duration: {payload.duration_str}
Host: {snap.hostname}

Current state:
CPU: {cpu.overall_percent:.1f}%
Load (1m): {load.load_1m:.2f} (Capacity: {load.cpu_count} CPUs)
RAM Available: {mem.available_mb / 1024.0:.1f} GB ({mem.available_percent:.1f}%)
Swap: {mem.swap_percent:.1f}%
I/O Pressure: {io_psi_str}

System resources have returned to normal operating thresholds."""
    return msg.strip()
