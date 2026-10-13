"""
Disk capacity and I/O performance metric collector.
Monitors mount point utilization (including /) and I/O throughput.
"""

import logging
import os
import shutil
import time
from typing import Dict, List, Optional

try:
    import psutil
except ImportError:
    psutil = None

from src.collectors.base import BaseCollector, DiskMetrics, DiskMountMetrics

logger = logging.getLogger(__name__)


class DiskCollector(BaseCollector):
    """Collects disk capacity usage and I/O throughput metrics."""

    def __init__(self, mounts: Optional[List[str]] = None):
        self.mounts = mounts or ["/"]
        self._last_io_counters = None
        self._last_io_time = None

    def _get_mount_usage(self, path: str) -> Optional[DiskMountMetrics]:
        """Collect filesystem capacity metrics for a given mount path."""
        # On Windows during tests, "/" doesn't exist, so fallback to current drive
        target_path = path
        if not os.path.exists(target_path):
            if os.name == "nt":
                target_path = os.environ.get("SystemDrive", "C:") + "\\"
            else:
                return None

        try:
            usage = shutil.disk_usage(target_path)
            total_gb = usage.total / (1024.0 ** 3)
            used_gb = usage.used / (1024.0 ** 3)
            free_gb = usage.free / (1024.0 ** 3)
            percent_used = (usage.used / usage.total * 100.0) if usage.total > 0 else 0.0

            return DiskMountMetrics(
                mount_point=path,
                total_gb=round(total_gb, 1),
                used_gb=round(used_gb, 1),
                free_gb=round(free_gb, 1),
                percent_used=round(percent_used, 1),
            )
        except Exception as e:
            logger.debug("Failed checking disk usage for '%s': %s", path, e)
            return None

    def _get_io_throughput(self) -> tuple[float, float]:
        """Calculate aggregate read and write throughput in MB/s."""
        if not psutil:
            return 0.0, 0.0

        try:
            counters = psutil.disk_io_counters()
            if not counters:
                return 0.0, 0.0

            now = time.time()
            read_mb_s, write_mb_s = 0.0, 0.0

            if self._last_io_counters and self._last_io_time:
                dt = now - self._last_io_time
                if dt > 0.1:
                    read_bytes = max(0, counters.read_bytes - self._last_io_counters.read_bytes)
                    write_bytes = max(0, counters.write_bytes - self._last_io_counters.write_bytes)
                    read_mb_s = (read_bytes / (1024.0 * 1024.0)) / dt
                    write_mb_s = (write_bytes / (1024.0 * 1024.0)) / dt

            self._last_io_counters = counters
            self._last_io_time = now
            return round(read_mb_s, 2), round(write_mb_s, 2)
        except Exception as e:
            logger.debug("psutil disk_io_counters error: %s", e)
            return 0.0, 0.0

    def collect(self, iowait_percent: float = 0.0) -> DiskMetrics:
        """Collect disk mount usage and I/O statistics."""
        mount_results: Dict[str, DiskMountMetrics] = {}
        for mount in self.mounts:
            usage = self._get_mount_usage(mount)
            if usage:
                mount_results[mount] = usage

        read_mb_s, write_mb_s = self._get_io_throughput()

        return DiskMetrics(
            mounts=mount_results,
            read_mb_s=read_mb_s,
            write_mb_s=write_mb_s,
            iowait_percent=round(iowait_percent, 1),
        )
