import unittest

from src.collectors.base import (
    ContainerStatus,
    CpuMetrics,
    DiskMetrics,
    DiskMountMetrics,
    DockerMetrics,
    LoadMetrics,
    MemoryMetrics,
    PsiMetrics,
    PsiResourceMetrics,
    SystemErrorMetrics,
    SystemSnapshot,
    ThermalMetrics,
)
from src.config import AppConfig
from src.engine.evaluator import StressEvaluator
from src.engine.models import HealthState, StressFactor


class TestStressEvaluator(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        self.evaluator = StressEvaluator(self.config)

    def _create_healthy_snapshot(self) -> SystemSnapshot:
        return SystemSnapshot(
            hostname="homeserver",
            load=LoadMetrics(load_1m=1.2, load_5m=1.0, load_15m=0.8, cpu_count=4, normalized_1m=0.3),
            cpu=CpuMetrics(overall_percent=25.0, user_percent=15.0, system_percent=10.0, idle_percent=75.0, iowait_percent=0.5),
            memory=MemoryMetrics(total_mb=16000, used_mb=6000, available_mb=10000, available_percent=62.5, swap_percent=2.0),
            disk=DiskMetrics(mounts={"/": DiskMountMetrics(mount_point="/", total_gb=500, used_gb=200, free_gb=300, percent_used=40.0)}),
            psi=PsiMetrics(available=True, cpu=PsiResourceMetrics(some_avg10=0.0), memory=PsiResourceMetrics(some_avg10=0.0), io=PsiResourceMetrics(some_avg10=0.0)),
            thermal=ThermalMetrics(available=True, cpu_temp_c=48.0),
            docker=DockerMetrics(available=True, containers={"grafana": ContainerStatus(name="grafana", status="running", running=True)}),
            system_errors=SystemErrorMetrics(oom_kills_detected=0, readonly_mounts=[], failed_systemd_units=[]),
        )

    def test_healthy_snapshot(self):
        snap = self._create_healthy_snapshot()
        res = self.evaluator.evaluate(snap)
        self.assertEqual(res.state, HealthState.HEALTHY)
        self.assertEqual(len(res.active_factors), 0)

    def test_cpu_load_critical_stress(self):
        snap = self._create_healthy_snapshot()
        # High CPU (96%) and high load (6.2) on 4-core server
        snap.cpu.overall_percent = 96.0
        snap.load.load_1m = 6.2
        snap.load.normalized_1m = 1.55
        snap.psi.cpu.some_avg10 = 42.0

        res = self.evaluator.evaluate(snap)
        self.assertEqual(res.state, HealthState.CRITICAL)
        self.assertIn(StressFactor.CPU_LOAD, res.active_factors)
        self.assertEqual(res.primary_bottleneck, StressFactor.CPU_LOAD.value)

    def test_memory_starvation_stress(self):
        snap = self._create_healthy_snapshot()
        # Only 500 MB RAM available (3.1%) and high swap
        snap.memory.available_mb = 500.0
        snap.memory.available_percent = 3.1
        snap.memory.swap_percent = 85.0
        snap.psi.memory.some_avg10 = 30.0

        res = self.evaluator.evaluate(snap)
        self.assertEqual(res.state, HealthState.CRITICAL)
        self.assertIn(StressFactor.MEMORY_PRESSURE, res.active_factors)
        self.assertEqual(res.primary_bottleneck, StressFactor.MEMORY_PRESSURE.value)

    def test_disk_capacity_warning_and_critical(self):
        snap = self._create_healthy_snapshot()
        # 82% disk used -> Warning
        snap.disk.mounts["/"].percent_used = 82.0
        res = self.evaluator.evaluate(snap)
        self.assertEqual(res.state, HealthState.WARNING)

        # 94% disk used -> Critical
        snap.disk.mounts["/"].percent_used = 94.0
        res = self.evaluator.evaluate(snap)
        self.assertEqual(res.state, HealthState.CRITICAL)
        self.assertIn(StressFactor.DISK_CAPACITY, res.active_factors)

    def test_disk_io_contention(self):
        snap = self._create_healthy_snapshot()
        snap.cpu.iowait_percent = 35.0
        snap.psi.io.some_avg10 = 40.0

        res = self.evaluator.evaluate(snap)
        self.assertEqual(res.state, HealthState.CRITICAL)
        self.assertIn(StressFactor.DISK_IO, res.active_factors)
        self.assertEqual(res.primary_bottleneck, StressFactor.DISK_IO.value)

    def test_docker_container_failure(self):
        snap = self._create_healthy_snapshot()
        snap.docker.containers["sqlserver"] = ContainerStatus(
            name="sqlserver", status="exited (1)", running=False, exit_code=1
        )

        res = self.evaluator.evaluate(snap)
        self.assertEqual(res.state, HealthState.CRITICAL)
        self.assertIn(StressFactor.DOCKER_SERVICE, res.active_factors)

    def test_oom_kill_detection(self):
        snap = self._create_healthy_snapshot()
        snap.system_errors.oom_kills_detected = 2

        res = self.evaluator.evaluate(snap)
        self.assertEqual(res.state, HealthState.CRITICAL)
        self.assertIn(StressFactor.SYSTEM_ERROR, res.active_factors)


if __name__ == "__main__":
    unittest.main()
