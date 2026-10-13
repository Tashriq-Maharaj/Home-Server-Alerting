"""
Linux Pressure Stall Information (PSI) collector.
Reads /proc/pressure/{cpu,memory,io} to detect actual resource starvation and contention.
Distinguishes between mere high utilization and processes actively stalling for resources.
"""

import logging
import os
from typing import Optional

from src.collectors.base import BaseCollector, PsiMetrics, PsiResourceMetrics

logger = logging.getLogger(__name__)


class PsiCollector(BaseCollector):
    """Collects Linux kernel Pressure Stall Information (PSI)."""

    PSI_DIR = "/proc/pressure"

    def __init__(self, psi_dir: Optional[str] = None):
        self.psi_dir = psi_dir or self.PSI_DIR
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if PSI interface exists on the current host."""
        if self._available is None:
            self._available = os.path.isdir(self.psi_dir) and os.path.isfile(
                os.path.join(self.psi_dir, "cpu")
            )
        return self._available

    def _parse_psi_file(self, filename: str) -> Optional[PsiResourceMetrics]:
        """Parse a single PSI file (e.g. cpu, memory, io)."""
        filepath = os.path.join(self.psi_dir, filename)
        if not os.path.isfile(filepath):
            return None

        metrics = PsiResourceMetrics()
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    line_type = parts[0]  # 'some' or 'full'
                    parsed_vals = {}
                    for item in parts[1:]:
                        if "=" in item:
                            k, v = item.split("=", 1)
                            try:
                                parsed_vals[k] = float(v)
                            except ValueError:
                                pass

                    if line_type == "some":
                        metrics.some_avg10 = parsed_vals.get("avg10", 0.0)
                        metrics.some_avg60 = parsed_vals.get("avg60", 0.0)
                        metrics.some_avg300 = parsed_vals.get("avg300", 0.0)
                    elif line_type == "full":
                        metrics.full_avg10 = parsed_vals.get("avg10", 0.0)
                        metrics.full_avg60 = parsed_vals.get("avg60", 0.0)
                        metrics.full_avg300 = parsed_vals.get("avg300", 0.0)

            return metrics
        except Exception as e:
            logger.debug("Failed reading PSI file %s: %s", filepath, e)
            return None

    def collect(self) -> PsiMetrics:
        """Collect current PSI metrics for CPU, Memory, and I/O."""
        if not self.is_available():
            return PsiMetrics(available=False)

        cpu_psi = self._parse_psi_file("cpu")
        mem_psi = self._parse_psi_file("memory")
        io_psi = self._parse_psi_file("io")

        return PsiMetrics(
            available=True,
            cpu=cpu_psi,
            memory=mem_psi,
            io=io_psi,
        )
