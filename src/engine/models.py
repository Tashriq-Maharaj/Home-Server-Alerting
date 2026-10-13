"""
Data models for health status, stress evaluation, and alert generation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from src.collectors.base import SystemSnapshot


class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class StressFactor(str, Enum):
    CPU_LOAD = "CPU / system load"
    MEMORY_PRESSURE = "Memory / swap pressure"
    DISK_IO = "Disk I/O contention"
    DISK_CAPACITY = "Disk capacity exhaustion"
    TEMPERATURE = "Excessive temperature"
    DOCKER_SERVICE = "Docker container failure"
    SYSTEM_ERROR = "Kernel / system errors"


@dataclass
class MetricFactorEvaluation:
    factor: StressFactor
    state: HealthState
    score: float  # 0.0 (normal) to 1.0 (max critical)
    summary: str
    details: Dict[str, str] = field(default_factory=dict)
    is_recovery_satisfied: bool = True


@dataclass
class EvaluationResult:
    state: HealthState
    primary_bottleneck: Optional[str] = None
    active_factors: List[StressFactor] = field(default_factory=list)
    factor_evaluations: Dict[StressFactor, MetricFactorEvaluation] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    snapshot: Optional[SystemSnapshot] = None


@dataclass
class AlertPayload:
    alert_type: str  # "STRESS" or "RECOVERY"
    title: str
    severity: HealthState
    duration_str: str
    primary_bottleneck: str
    trigger_reasons: List[str]
    snapshot: SystemSnapshot
    initial_trigger_snapshot: Optional[SystemSnapshot] = None
    stress_factors: List[StressFactor] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
