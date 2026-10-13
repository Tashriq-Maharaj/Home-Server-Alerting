"""
System error and stability collector.
Detects critical low-level host problems:
- Linux kernel OOM kills (/proc/vmstat oom_kill counter)
- Failed systemd units (systemctl --failed)
- Read-only remounts indicative of filesystem corruption
"""

import logging
import os
import subprocess
from typing import List, Optional

from src.collectors.base import BaseCollector, SystemErrorMetrics
from src.config import SystemErrorsConfig

logger = logging.getLogger(__name__)


class SystemErrorsCollector(BaseCollector):
    """Collects system error indicators."""

    def __init__(self, config: SystemErrorsConfig):
        self.config = config
        self._initial_oom_count: Optional[int] = None
        self._last_oom_count: Optional[int] = None

    def _get_oom_kill_count(self) -> int:
        """Reads cumulative oom_kill count from /proc/vmstat."""
        vmstat_path = "/proc/vmstat"
        if not os.path.isfile(vmstat_path):
            return 0

        try:
            with open(vmstat_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("oom_kill "):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1])
        except Exception as e:
            logger.debug("Failed reading oom_kill from /proc/vmstat: %s", e)
        return 0

    def _get_failed_systemd_units(self) -> List[str]:
        """Check for failed systemd units using systemctl."""
        if not self.config.check_failed_systemd_services:
            return []

        if not os.path.isfile("/bin/systemctl") and not os.path.isfile("/usr/bin/systemctl"):
            return []

        try:
            cmd = ["systemctl", "--failed", "--no-legend", "--plain"]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3,
                check=False
            )
            if res.returncode != 0:
                return []

            failed = []
            for line in res.stdout.strip().splitlines():
                parts = line.strip().split()
                if parts:
                    unit_name = parts[0]
                    # Filter out purely transient or expected user slice units if any
                    failed.append(unit_name)
            return failed
        except Exception as e:
            logger.debug("Failed checking systemctl --failed: %s", e)
            return []

    def _get_readonly_mounts(self) -> List[str]:
        """Check /proc/mounts for unexpectedly read-only root or data filesystems."""
        if not self.config.check_readonly_filesystems:
            return []

        mounts_path = "/proc/mounts"
        if not os.path.isfile(mounts_path):
            return []

        ro_critical = []
        try:
            with open(mounts_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4:
                        device, mount_pt, fs_type, opts = parts[0], parts[1], parts[2], parts[3]
                        opt_list = opts.split(",")
                        # Only check real disk filesystems (ext4, btrfs, xfs, zfs)
                        if fs_type in ("ext4", "btrfs", "xfs", "zfs", "vfat"):
                            if "ro" in opt_list and mount_pt in ("/", "/var", "/home", "/etc"):
                                ro_critical.append(f"{mount_pt} ({fs_type})")
        except Exception as e:
            logger.debug("Failed checking /proc/mounts: %s", e)

        return ro_critical

    def collect(self) -> SystemErrorMetrics:
        """Collect error metrics."""
        if not self.config.enabled:
            return SystemErrorMetrics()

        current_oom = self._get_oom_kill_count()
        if self._initial_oom_count is None:
            self._initial_oom_count = current_oom
            self._last_oom_count = current_oom
            oom_delta = 0
        else:
            oom_delta = max(0, current_oom - (self._last_oom_count or current_oom))
            self._last_oom_count = current_oom

        failed_units = self._get_failed_systemd_units()
        ro_mounts = self._get_readonly_mounts()

        return SystemErrorMetrics(
            oom_kill_count=current_oom,
            oom_kills_detected=oom_delta,
            failed_systemd_units=failed_units,
            readonly_mounts=ro_mounts,
        )
