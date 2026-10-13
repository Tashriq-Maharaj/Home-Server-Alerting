"""
Docker container and service health collector.
Communicates directly with Docker daemon via Unix socket /var/run/docker.sock
or subprocess fallback, requiring zero external dependencies.
"""

import http.client
import json
import logging
import os
import socket
import subprocess
from typing import Dict, List, Optional

from src.collectors.base import BaseCollector, ContainerStatus, DockerMetrics
from src.config import DockerConfig

logger = logging.getLogger(__name__)


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection subclass that connects over a Unix domain socket."""

    def __init__(self, socket_path: str, timeout: float = 3.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


class DockerCollector(BaseCollector):
    """Collects status and restart counts of monitored Docker containers."""

    def __init__(self, config: DockerConfig):
        self.config = config
        self.socket_path = config.socket_path
        self.monitored = [c.lower().strip() for c in config.monitored_containers]
        self._previous_restarts: Dict[str, int] = {}
        self._previously_running: set = set()

    def _query_socket(self) -> Optional[List[dict]]:
        """Query Docker engine API via /var/run/docker.sock."""
        if not hasattr(socket, "AF_UNIX") or not os.path.exists(self.socket_path):
            return None

        conn = None
        try:
            conn = UnixSocketHTTPConnection(self.socket_path, timeout=3.0)
            conn.request("GET", "/containers/json?all=1")
            res = conn.getresponse()
            if res.status == 200:
                body = res.read().decode("utf-8")
                return json.loads(body)
        except Exception as e:
            logger.debug("Docker socket query error: %s", e)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        return None

    def _query_cli(self) -> Optional[List[dict]]:
        """Fallback query using 'docker ps -a --format json'."""
        try:
            cmd = ["docker", "ps", "-a", "--format", "{{json .}}"]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=4,
                check=False
            )
            if res.returncode != 0:
                return None

            containers = []
            for line in res.stdout.strip().splitlines():
                if line.strip():
                    containers.append(json.loads(line.strip()))
            return containers
        except Exception as e:
            logger.debug("Docker CLI query error: %s", e)
            return None

    def _matches_monitored(self, container_name: str) -> bool:
        """Check if container name matches any configured monitored name pattern."""
        c_name = container_name.lower().lstrip("/")
        for target in self.monitored:
            if target == c_name or target in c_name:
                return True
        return False

    def collect(self) -> DockerMetrics:
        """Collect container statuses for all monitored services."""
        if not self.config.enabled:
            return DockerMetrics(available=False, error_message="Docker monitoring disabled")

        raw_list = self._query_socket()
        used_socket = True
        if raw_list is None:
            raw_list = self._query_cli()
            used_socket = False

        if raw_list is None:
            return DockerMetrics(
                available=False,
                error_message="Docker daemon unavailable or socket not accessible"
            )

        container_statuses: Dict[str, ContainerStatus] = {}

        for item in raw_list:
            if used_socket:
                # Docker API format
                raw_names = item.get("Names", [])
                primary_name = raw_names[0].lstrip("/") if raw_names else item.get("Id", "")[:12]
                state = item.get("State", "").lower()
                status_str = item.get("Status", "").lower()

                # Restart count or health check if present
                # Note: /containers/json gives state e.g. "running", "exited", "restarting"
                is_running = state == "running"
                is_restarting = state == "restarting" or "restarting" in status_str
            else:
                # Docker CLI format
                primary_name = item.get("Names", item.get("ID", "")[:12]).lstrip("/")
                state = item.get("State", "").lower()
                status_str = item.get("Status", "").lower()
                is_running = state == "running"
                is_restarting = state == "restarting" or "restarting" in status_str

            if self._matches_monitored(primary_name):
                # Check for exit code
                exit_code = 0
                if "exit (" in status_str:
                    try:
                        exit_part = status_str.split("exit (")[1].split(")")[0]
                        exit_code = int(exit_part)
                    except Exception:
                        pass

                status_obj = ContainerStatus(
                    name=primary_name,
                    status=state or status_str,
                    running=is_running,
                    restarting=is_restarting,
                    exit_code=exit_code,
                    health=item.get("Health", "unknown"),
                )
                container_statuses[primary_name] = status_obj

        # Detect any monitored container that was previously running but has completely disappeared
        for prev_name in self._previously_running:
            if prev_name not in container_statuses and self._matches_monitored(prev_name):
                container_statuses[prev_name] = ContainerStatus(
                    name=prev_name,
                    status="missing / terminated",
                    running=False,
                    restarting=False,
                    exit_code=1,
                    health="missing",
                )

        # Update set of running monitored containers
        self._previously_running = {
            name for name, c in container_statuses.items() if c.running
        }

        return DockerMetrics(
            available=True,
            error_message=None,
            containers=container_statuses
        )
