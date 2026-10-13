"""
Memory and Swap metric collector.
Accurately accounts for Linux kernel memory semantics:
Distinguishes between cached/buffer memory and genuinely available memory.
"""

import logging
import os
import time
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None

from src.collectors.base import BaseCollector, MemoryMetrics

logger = logging.getLogger(__name__)


class MemoryCollector(BaseCollector):
    """Collects RAM, available memory, swap usage, and swap rates."""

    def __init__(self):
        self._last_swap_stats = None
        self._last_swap_time = None

    def _collect_proc_meminfo(self) -> Optional[MemoryMetrics]:
        """Read /proc/meminfo directly on Linux systems."""
        if not os.path.isfile("/proc/meminfo"):
            return None

        mem_info = {}
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val_str = parts[1].strip().split()[0]
                        mem_info[key] = float(val_str)  # kB
        except Exception as e:
            logger.debug("Failed reading /proc/meminfo: %s", e)
            return None

        total_kb = mem_info.get("MemTotal", 0.0)
        # MemAvailable is the kernel's accurate estimate of memory available without swapping
        avail_kb = mem_info.get("MemAvailable", mem_info.get("MemFree", 0.0))
        used_kb = max(0.0, total_kb - avail_kb)

        swap_total_kb = mem_info.get("SwapTotal", 0.0)
        swap_free_kb = mem_info.get("SwapFree", 0.0)
        swap_used_kb = max(0.0, swap_total_kb - swap_free_kb)

        total_mb = total_kb / 1024.0
        used_mb = used_kb / 1024.0
        avail_mb = avail_kb / 1024.0
        avail_pct = (avail_mb / total_mb * 100.0) if total_mb > 0 else 100.0
        used_pct = (used_mb / total_mb * 100.0) if total_mb > 0 else 0.0

        swap_total_mb = swap_total_kb / 1024.0
        swap_used_mb = swap_used_kb / 1024.0
        swap_pct = (swap_used_mb / swap_total_mb * 100.0) if swap_total_mb > 0 else 0.0

        return MemoryMetrics(
            total_mb=round(total_mb, 1),
            used_mb=round(used_mb, 1),
            available_mb=round(avail_mb, 1),
            available_percent=round(avail_pct, 1),
            used_percent=round(used_pct, 1),
            swap_total_mb=round(swap_total_mb, 1),
            swap_used_mb=round(swap_used_mb, 1),
            swap_percent=round(swap_pct, 1),
        )

    def _collect_swap_rate(self) -> tuple[float, float]:
        """Calculates swap in/out rate (MB/s) via /proc/vmstat."""
        if not os.path.isfile("/proc/vmstat"):
            return 0.0, 0.0

        pswpin = 0.0
        pswpout = 0.0
        try:
            with open("/proc/vmstat", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) == 2:
                        if parts[0] == "pswpin":
                            pswpin = float(parts[1])
                        elif parts[0] == "pswpout":
                            pswpout = float(parts[1])
        except Exception:
            return 0.0, 0.0

        now = time.time()
        swap_in_rate = 0.0
        swap_out_rate = 0.0

        if self._last_swap_stats and self._last_swap_time:
            dt = now - self._last_swap_time
            if dt > 0.1:
                # 1 page in x86/x86_64 is 4096 bytes (4 KB)
                pages_in = max(0.0, pswpin - self._last_swap_stats[0])
                pages_out = max(0.0, pswpout - self._last_swap_stats[1])
                swap_in_rate = (pages_in * 4.0 / 1024.0) / dt  # MB/s
                swap_out_rate = (pages_out * 4.0 / 1024.0) / dt  # MB/s

        self._last_swap_stats = (pswpin, pswpout)
        self._last_swap_time = now
        return round(swap_in_rate, 2), round(swap_out_rate, 2)

    def collect(self) -> MemoryMetrics:
        """Collect memory metrics via psutil or /proc fallback."""
        metrics: Optional[MemoryMetrics] = None

        if psutil:
            try:
                vm = psutil.virtual_memory()
                sm = psutil.swap_memory()
                total_mb = vm.total / (1024.0 * 1024.0)
                available_mb = vm.available / (1024.0 * 1024.0)
                used_mb = (vm.total - vm.available) / (1024.0 * 1024.0)
                avail_pct = (available_mb / total_mb * 100.0) if total_mb > 0 else 100.0
                used_pct = (used_mb / total_mb * 100.0) if total_mb > 0 else 0.0

                swap_total_mb = sm.total / (1024.0 * 1024.0)
                swap_used_mb = sm.used / (1024.0 * 1024.0)
                swap_pct = sm.percent

                metrics = MemoryMetrics(
                    total_mb=round(total_mb, 1),
                    used_mb=round(used_mb, 1),
                    available_mb=round(available_mb, 1),
                    available_percent=round(avail_pct, 1),
                    used_percent=round(used_pct, 1),
                    swap_total_mb=round(swap_total_mb, 1),
                    swap_used_mb=round(swap_used_mb, 1),
                    swap_percent=round(swap_pct, 1),
                )
            except Exception as e:
                logger.debug("psutil memory collection error: %s", e)

        if not metrics:
            metrics = self._collect_proc_meminfo() or MemoryMetrics()

        swap_in_rate, swap_out_rate = self._collect_swap_rate()
        metrics.swap_in_mb_s = swap_in_rate
        metrics.swap_out_mb_s = swap_out_rate

        return metrics
