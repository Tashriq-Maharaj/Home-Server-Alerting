"""
CPU and System Load metric collector.
Calibrated for multi-core systems (e.g. 4 logical CPUs on Lenovo ThinkPad T440p).
"""

import logging
import os
import time
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None

from src.collectors.base import BaseCollector, CpuMetrics, LoadMetrics
from src.config import ServerConfig

logger = logging.getLogger(__name__)


class CpuCollector(BaseCollector):
    """Collects CPU utilization and 1m/5m/15m system load averages."""

    def __init__(self, server_config: ServerConfig):
        self.server_config = server_config
        self.cpu_count = server_config.cpu_count or (os.cpu_count() or 4)
        self._last_cpu_times = None
        self._last_time = None

        # Prime psutil if available
        if psutil:
            try:
                psutil.cpu_percent(interval=None)
                psutil.cpu_times_percent(interval=None)
            except Exception:
                pass

    def _collect_load(self) -> LoadMetrics:
        """Collect system load average from OS or /proc/loadavg."""
        load_1m, load_5m, load_15m = 0.0, 0.0, 0.0

        if hasattr(os, "getloadavg"):
            try:
                load_1m, load_5m, load_15m = os.getloadavg()
            except (OSError, AttributeError):
                pass
        elif os.path.isfile("/proc/loadavg"):
            try:
                with open("/proc/loadavg", "r", encoding="utf-8") as f:
                    parts = f.read().split()
                    if len(parts) >= 3:
                        load_1m = float(parts[0])
                        load_5m = float(parts[1])
                        load_15m = float(parts[2])
            except Exception as e:
                logger.debug("Failed to read /proc/loadavg: %s", e)

        normalized_1m = load_1m / max(self.cpu_count, 1)
        normalized_5m = load_5m / max(self.cpu_count, 1)
        normalized_15m = load_15m / max(self.cpu_count, 1)

        return LoadMetrics(
            load_1m=round(load_1m, 2),
            load_5m=round(load_5m, 2),
            load_15m=round(load_15m, 2),
            cpu_count=self.cpu_count,
            normalized_1m=round(normalized_1m, 2),
            normalized_5m=round(normalized_5m, 2),
            normalized_15m=round(normalized_15m, 2),
        )

    def _collect_cpu(self) -> CpuMetrics:
        """Collect CPU percentages (overall, user, system, idle, iowait)."""
        overall_pct = 0.0
        user_pct = 0.0
        sys_pct = 0.0
        idle_pct = 100.0
        iowait_pct = 0.0

        if psutil:
            try:
                overall_pct = psutil.cpu_percent(interval=None)
                times = psutil.cpu_times_percent(interval=None)
                user_pct = getattr(times, "user", 0.0)
                sys_pct = getattr(times, "system", 0.0)
                idle_pct = getattr(times, "idle", 100.0)
                iowait_pct = getattr(times, "iowait", 0.0)
            except Exception as e:
                logger.debug("psutil cpu metrics collection error: %s", e)
        else:
            # Fallback for Linux /proc/stat if psutil is unavailable
            stat_file = "/proc/stat"
            if os.path.isfile(stat_file):
                try:
                    with open(stat_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("cpu "):
                                parts = [float(x) for x in line.split()[1:8]]
                                # user, nice, system, idle, iowait, irq, softirq
                                user, nice, system, idle, iowait = parts[0], parts[1], parts[2], parts[3], parts[4]
                                total = sum(parts)
                                now = time.time()
                                if self._last_cpu_times and self._last_time:
                                    dt_total = total - self._last_cpu_times["total"]
                                    if dt_total > 0:
                                        user_pct = ((user + nice) - self._last_cpu_times["user"]) / dt_total * 100
                                        sys_pct = (system - self._last_cpu_times["system"]) / dt_total * 100
                                        idle_pct = (idle - self._last_cpu_times["idle"]) / dt_total * 100
                                        iowait_pct = (iowait - self._last_cpu_times["iowait"]) / dt_total * 100
                                        overall_pct = max(0.0, 100.0 - idle_pct)
                                self._last_cpu_times = {
                                    "user": user + nice,
                                    "system": system,
                                    "idle": idle,
                                    "iowait": iowait,
                                    "total": total,
                                }
                                self._last_time = now
                                break
                except Exception as e:
                    logger.debug("Linux /proc/stat read error: %s", e)

        return CpuMetrics(
            overall_percent=round(max(0.0, min(100.0, overall_pct)), 1),
            user_percent=round(max(0.0, user_pct), 1),
            system_percent=round(max(0.0, sys_pct), 1),
            idle_percent=round(max(0.0, idle_pct), 1),
            iowait_percent=round(max(0.0, iowait_pct), 1),
        )

    def collect(self) -> tuple[LoadMetrics, CpuMetrics]:
        """Collect both load and CPU utilization metrics."""
        return self._collect_load(), self._collect_cpu()
