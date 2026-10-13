"""
Configuration management module for Server Alerting.
Handles reading JSON configuration files and merging environment variables (.env).
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_env_file(dotenv_path: Optional[Path] = None, override: bool = False) -> None:
    """Lightweight .env parser that populates os.environ without requiring external packages."""
    if dotenv_path is None:
        dotenv_path = Path.cwd() / ".env"
    if not dotenv_path.is_file():
        return

    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if override or key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass


@dataclass
class ServerConfig:
    hostname: str = "homeserver"
    cpu_count: int = 4
    ip_address: str = "192.168.0.56"


@dataclass
class MonitoringConfig:
    interval_seconds: int = 10
    stress_duration_seconds: int = 60
    recovery_duration_seconds: int = 60
    alert_cooldown_seconds: int = 1800


@dataclass
class LoadThresholds:
    warning_1m: float = 3.8
    critical_1m: float = 5.5
    warning_5m: float = 3.4
    critical_5m: float = 4.5
    recovery_1m: float = 2.8
    recovery_5m: float = 2.5


@dataclass
class CpuThresholds:
    warning_percent: float = 85.0
    critical_percent: float = 95.0
    recovery_percent: float = 70.0


@dataclass
class PsiThresholds:
    cpu_avg10_warn: float = 15.0
    cpu_avg10_crit: float = 35.0
    cpu_avg10_recovery: float = 5.0
    memory_avg10_warn: float = 10.0
    memory_avg10_crit: float = 25.0
    memory_avg10_recovery: float = 3.0
    io_avg10_warn: float = 15.0
    io_avg10_crit: float = 35.0
    io_avg10_recovery: float = 5.0


@dataclass
class MemoryThresholds:
    min_available_mb_warn: float = 1500.0
    min_available_mb_crit: float = 700.0
    min_available_percent_warn: float = 15.0
    min_available_percent_crit: float = 8.0
    recovery_available_percent: float = 20.0
    swap_percent_warn: float = 50.0
    swap_percent_crit: float = 80.0
    recovery_swap_percent: float = 40.0


@dataclass
class DiskThresholds:
    mounts: List[str] = field(default_factory=lambda: ["/"])
    warning_percent: float = 80.0
    critical_percent: float = 90.0
    recovery_percent: float = 78.0
    iowait_warning_percent: float = 15.0
    iowait_critical_percent: float = 30.0
    recovery_iowait_percent: float = 8.0


@dataclass
class TemperatureThresholds:
    warning_celsius: float = 80.0
    critical_celsius: float = 90.0
    recovery_celsius: float = 72.0


@dataclass
class ThresholdsConfig:
    load: LoadThresholds = field(default_factory=LoadThresholds)
    cpu: CpuThresholds = field(default_factory=CpuThresholds)
    psi: PsiThresholds = field(default_factory=PsiThresholds)
    memory: MemoryThresholds = field(default_factory=MemoryThresholds)
    disk: DiskThresholds = field(default_factory=DiskThresholds)
    temperature: TemperatureThresholds = field(default_factory=TemperatureThresholds)


@dataclass
class DockerConfig:
    enabled: bool = True
    socket_path: str = "/var/run/docker.sock"
    monitored_containers: List[str] = field(default_factory=lambda: [
        "prometheus",
        "grafana",
        "node-exporter",
        "node_exporter",
        "sqlserver",
        "sql-server",
        "plex",
        "plex-exporter",
        "plex_exporter",
        "portainer",
        "sql-exporter",
        "sql_exporter",
    ])
    max_acceptable_restarts: int = 3


@dataclass
class SystemErrorsConfig:
    enabled: bool = True
    check_oom_kills: bool = True
    check_failed_systemd_services: bool = True
    check_readonly_filesystems: bool = True


@dataclass
class TelegramConfig:
    enabled: bool = True
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class EmailConfig:
    enabled: bool = False
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    sender_email: str = ""
    recipient_emails: List[str] = field(default_factory=list)


@dataclass
class NotificationsConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    email: EmailConfig = field(default_factory=EmailConfig)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_file: Optional[str] = None
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 3


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    system_errors: SystemErrorsConfig = field(default_factory=SystemErrorsConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _safe_float(val: Any, default: float) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_bool(val: Any, default: bool) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "on")
    return default


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load and merge configuration from config file and environment variables."""
    load_env_file()

    # Determine config file path
    path = config_path or os.environ.get("CONFIG_PATH")
    if not path:
        default_candidate = Path(__file__).resolve().parent.parent / "config" / "config.default.json"
        if default_candidate.is_file():
            path = str(default_candidate)

    raw_data: Dict[str, Any] = {}
    if path and Path(path).is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            # Fall back to defaults but keep note
            pass

    config = AppConfig()

    # Server settings
    srv_data = raw_data.get("server", {})
    config.server.hostname = srv_data.get("hostname", os.uname().nodename if hasattr(os, "uname") else "homeserver")
    detected_cpu = os.cpu_count() or 4
    config.server.cpu_count = _safe_int(srv_data.get("cpu_count", detected_cpu), detected_cpu)
    config.server.ip_address = srv_data.get("ip_address", "192.168.0.56")

    # Monitoring settings
    mon_data = raw_data.get("monitoring", {})
    config.monitoring.interval_seconds = _safe_int(mon_data.get("interval_seconds"), 10)
    config.monitoring.stress_duration_seconds = _safe_int(mon_data.get("stress_duration_seconds"), 60)
    config.monitoring.recovery_duration_seconds = _safe_int(mon_data.get("recovery_duration_seconds"), 60)
    config.monitoring.alert_cooldown_seconds = _safe_int(mon_data.get("alert_cooldown_seconds"), 1800)

    # Thresholds
    thresh_data = raw_data.get("thresholds", {})

    load_data = thresh_data.get("load", {})
    config.thresholds.load = LoadThresholds(
        warning_1m=_safe_float(load_data.get("warning_1m"), 3.8),
        critical_1m=_safe_float(load_data.get("critical_1m"), 5.5),
        warning_5m=_safe_float(load_data.get("warning_5m"), 3.4),
        critical_5m=_safe_float(load_data.get("critical_5m"), 4.5),
        recovery_1m=_safe_float(load_data.get("recovery_1m"), 2.8),
        recovery_5m=_safe_float(load_data.get("recovery_5m"), 2.5),
    )

    cpu_data = thresh_data.get("cpu", {})
    config.thresholds.cpu = CpuThresholds(
        warning_percent=_safe_float(cpu_data.get("warning_percent"), 85.0),
        critical_percent=_safe_float(cpu_data.get("critical_percent"), 95.0),
        recovery_percent=_safe_float(cpu_data.get("recovery_percent"), 70.0),
    )

    psi_data = thresh_data.get("psi", {})
    config.thresholds.psi = PsiThresholds(
        cpu_avg10_warn=_safe_float(psi_data.get("cpu_avg10_warn"), 15.0),
        cpu_avg10_crit=_safe_float(psi_data.get("cpu_avg10_crit"), 35.0),
        cpu_avg10_recovery=_safe_float(psi_data.get("cpu_avg10_recovery"), 5.0),
        memory_avg10_warn=_safe_float(psi_data.get("memory_avg10_warn"), 10.0),
        memory_avg10_crit=_safe_float(psi_data.get("memory_avg10_crit"), 25.0),
        memory_avg10_recovery=_safe_float(psi_data.get("memory_avg10_recovery"), 3.0),
        io_avg10_warn=_safe_float(psi_data.get("io_avg10_warn"), 15.0),
        io_avg10_crit=_safe_float(psi_data.get("io_avg10_crit"), 35.0),
        io_avg10_recovery=_safe_float(psi_data.get("io_avg10_recovery"), 5.0),
    )

    mem_data = thresh_data.get("memory", {})
    config.thresholds.memory = MemoryThresholds(
        min_available_mb_warn=_safe_float(mem_data.get("min_available_mb_warn"), 1500.0),
        min_available_mb_crit=_safe_float(mem_data.get("min_available_mb_crit"), 700.0),
        min_available_percent_warn=_safe_float(mem_data.get("min_available_percent_warn"), 15.0),
        min_available_percent_crit=_safe_float(mem_data.get("min_available_percent_crit"), 8.0),
        recovery_available_percent=_safe_float(mem_data.get("recovery_available_percent"), 20.0),
        swap_percent_warn=_safe_float(mem_data.get("swap_percent_warn"), 50.0),
        swap_percent_crit=_safe_float(mem_data.get("swap_percent_crit"), 80.0),
        recovery_swap_percent=_safe_float(mem_data.get("recovery_swap_percent"), 40.0),
    )

    disk_data = thresh_data.get("disk", {})
    config.thresholds.disk = DiskThresholds(
        mounts=disk_data.get("mounts", ["/"]),
        warning_percent=_safe_float(disk_data.get("warning_percent"), 80.0),
        critical_percent=_safe_float(disk_data.get("critical_percent"), 90.0),
        recovery_percent=_safe_float(disk_data.get("recovery_percent"), 78.0),
        iowait_warning_percent=_safe_float(disk_data.get("iowait_warning_percent"), 15.0),
        iowait_critical_percent=_safe_float(disk_data.get("iowait_critical_percent"), 30.0),
        recovery_iowait_percent=_safe_float(disk_data.get("recovery_iowait_percent"), 8.0),
    )

    temp_data = thresh_data.get("temperature", {})
    config.thresholds.temperature = TemperatureThresholds(
        warning_celsius=_safe_float(temp_data.get("warning_celsius"), 80.0),
        critical_celsius=_safe_float(temp_data.get("critical_celsius"), 90.0),
        recovery_celsius=_safe_float(temp_data.get("recovery_celsius"), 72.0),
    )

    # Docker
    doc_data = raw_data.get("docker", {})
    config.docker.enabled = _safe_bool(doc_data.get("enabled"), True)
    config.docker.socket_path = doc_data.get("socket_path", "/var/run/docker.sock")
    config.docker.monitored_containers = doc_data.get("monitored_containers", config.docker.monitored_containers)
    config.docker.max_acceptable_restarts = _safe_int(doc_data.get("max_acceptable_restarts"), 3)

    # System errors
    sys_err_data = raw_data.get("system_errors", {})
    config.system_errors.enabled = _safe_bool(sys_err_data.get("enabled"), True)
    config.system_errors.check_oom_kills = _safe_bool(sys_err_data.get("check_oom_kills"), True)
    config.system_errors.check_failed_systemd_services = _safe_bool(sys_err_data.get("check_failed_systemd_services"), True)
    config.system_errors.check_readonly_filesystems = _safe_bool(sys_err_data.get("check_readonly_filesystems"), True)

    # Notifications & Environment variables overrides
    notif_data = raw_data.get("notifications", {})
    tg_data = notif_data.get("telegram", {})
    config.notifications.telegram.enabled = _safe_bool(
        os.environ.get("TELEGRAM_ENABLED", tg_data.get("enabled", True)),
        True
    )
    config.notifications.telegram.bot_token = os.environ.get(
        "TELEGRAM_BOT_TOKEN", tg_data.get("bot_token", "")
    ).strip()
    config.notifications.telegram.chat_id = os.environ.get(
        "TELEGRAM_CHAT_ID", tg_data.get("chat_id", "")
    ).strip()

    em_data = notif_data.get("email", {})
    config.notifications.email.enabled = _safe_bool(
        os.environ.get("EMAIL_ENABLED", em_data.get("enabled", False)),
        False
    )
    config.notifications.email.smtp_server = os.environ.get(
        "EMAIL_SMTP_SERVER", em_data.get("smtp_server", "smtp.gmail.com")
    ).strip()
    config.notifications.email.smtp_port = _safe_int(
        os.environ.get("EMAIL_SMTP_PORT", em_data.get("smtp_port", 587)),
        587
    )
    config.notifications.email.use_tls = _safe_bool(
        os.environ.get("EMAIL_USE_TLS", em_data.get("use_tls", True)),
        True
    )
    config.notifications.email.username = os.environ.get(
        "EMAIL_USERNAME", em_data.get("username", "")
    ).strip()
    config.notifications.email.password = os.environ.get(
        "EMAIL_PASSWORD", em_data.get("password", "")
    ).strip()
    config.notifications.email.sender_email = os.environ.get(
        "EMAIL_SENDER", em_data.get("sender_email", "")
    ).strip()

    recipient_env = os.environ.get("EMAIL_RECIPIENTS")
    if recipient_env:
        config.notifications.email.recipient_emails = [
            r.strip() for r in recipient_env.split(",") if r.strip()
        ]
    else:
        config.notifications.email.recipient_emails = em_data.get("recipient_emails", [])

    # Logging
    log_data = raw_data.get("logging", {})
    config.logging.level = os.environ.get("LOG_LEVEL", log_data.get("level", "INFO")).upper()
    config.logging.log_file = log_data.get("log_file")
    config.logging.max_bytes = _safe_int(log_data.get("max_bytes"), 10 * 1024 * 1024)
    config.logging.backup_count = _safe_int(log_data.get("backup_count"), 3)

    return config
