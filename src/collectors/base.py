"""
Base models and collectors for Server Alerting metrics.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class LoadMetrics:
    load_1m: float = 0.0
    load_5m: float = 0.0
    load_15m: float = 0.0
    cpu_count: int = 4
    normalized_1m: float = 0.0  # load_1m / cpu_count
    normalized_5m: float = 0.0  # load_5m / cpu_count
    normalized_15m: float = 0.0  # load_15m / cpu_count


@dataclass
class CpuMetrics:
    overall_percent: float = 0.0
    user_percent: float = 0.0
    system_percent: float = 0.0
    idle_percent: float = 100.0
    iowait_percent: float = 0.0


@dataclass
class MemoryMetrics:
    total_mb: float = 0.0
    used_mb: float = 0.0
    available_mb: float = 0.0
    available_percent: float = 100.0
    used_percent: float = 0.0
    swap_total_mb: float = 0.0
    swap_used_mb: float = 0.0
    swap_percent: float = 0.0
    swap_in_mb_s: float = 0.0
    swap_out_mb_s: float = 0.0


@dataclass
class DiskMountMetrics:
    mount_point: str = "/"
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    percent_used: float = 0.0


@dataclass
class DiskMetrics:
    mounts: Dict[str, DiskMountMetrics] = field(default_factory=dict)
    read_mb_s: float = 0.0
    write_mb_s: float = 0.0
    iowait_percent: float = 0.0


@dataclass
class PsiResourceMetrics:
    some_avg10: float = 0.0
    some_avg60: float = 0.0
    some_avg300: float = 0.0
    full_avg10: float = 0.0
    full_avg60: float = 0.0
    full_avg300: float = 0.0


@dataclass
class PsiMetrics:
    available: bool = False
    cpu: Optional[PsiResourceMetrics] = None
    memory: Optional[PsiResourceMetrics] = None
    io: Optional[PsiResourceMetrics] = None


@dataclass
class ThermalMetrics:
    available: bool = False
    cpu_temp_c: Optional[float] = None
    sensors: Dict[str, float] = field(default_factory=dict)


@dataclass
class ContainerStatus:
    name: str = ""
    status: str = "unknown"  # running, exited, restarting, paused, etc.
    running: bool = False
    restarting: bool = False
    restart_count: int = 0
    exit_code: int = 0
    health: str = "none"


@dataclass
class DockerMetrics:
    available: bool = False
    error_message: Optional[str] = None
    containers: Dict[str, ContainerStatus] = field(default_factory=dict)


@dataclass
class SystemErrorMetrics:
    oom_kill_count: int = 0
    oom_kills_detected: int = 0
    failed_systemd_units: List[str] = field(default_factory=list)
    readonly_mounts: List[str] = field(default_factory=list)


@dataclass
class SystemSnapshot:
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    hostname: str = "homeserver"
    load: LoadMetrics = field(default_factory=LoadMetrics)
    cpu: CpuMetrics = field(default_factory=CpuMetrics)
    memory: MemoryMetrics = field(default_factory=MemoryMetrics)
    disk: DiskMetrics = field(default_factory=DiskMetrics)
    psi: PsiMetrics = field(default_factory=PsiMetrics)
    thermal: ThermalMetrics = field(default_factory=ThermalMetrics)
    docker: DockerMetrics = field(default_factory=DockerMetrics)
    system_errors: SystemErrorMetrics = field(default_factory=SystemErrorMetrics)


class BaseCollector(ABC):
    """Abstract base class for all metric collectors."""

    @abstractmethod
    def collect(self) -> Any:
        """Collect and return metrics."""
        pass
