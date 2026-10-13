import os
import tempfile
import unittest
from pathlib import Path

from src.collectors.base import LoadMetrics
from src.collectors.cpu import CpuCollector
from src.collectors.docker_service import DockerCollector
from src.collectors.memory import MemoryCollector
from src.collectors.psi import PsiCollector
from src.config import DockerConfig, ServerConfig


class TestCollectors(unittest.TestCase):
    def test_cpu_collector(self):
        server_cfg = ServerConfig(hostname="testserver", cpu_count=4)
        collector = CpuCollector(server_cfg)
        load_m, cpu_m = collector.collect()
        self.assertIsInstance(load_m, LoadMetrics)
        self.assertEqual(load_m.cpu_count, 4)
        self.assertGreaterEqual(cpu_m.overall_percent, 0.0)
        self.assertLessEqual(cpu_m.overall_percent, 100.0)

    def test_memory_collector(self):
        collector = MemoryCollector()
        mem_m = collector.collect()
        self.assertGreaterEqual(mem_m.total_mb, 0.0)
        self.assertGreaterEqual(mem_m.available_percent, 0.0)
        self.assertLessEqual(mem_m.available_percent, 100.0)

    def test_psi_parser(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cpu_file = Path(tmpdir) / "cpu"
            mem_file = Path(tmpdir) / "memory"
            io_file = Path(tmpdir) / "io"

            with open(cpu_file, "w") as f:
                f.write("some avg10=12.50 avg60=8.20 avg300=3.10 total=456789\n")

            with open(mem_file, "w") as f:
                f.write("some avg10=5.40 avg60=2.10 avg300=0.80 total=123456\n")
                f.write("full avg10=1.20 avg60=0.40 avg300=0.10 total=3456\n")

            with open(io_file, "w") as f:
                f.write("some avg10=22.30 avg60=15.00 avg300=9.40 total=987654\n")
                f.write("full avg10=10.00 avg60=5.50 avg300=1.20 total=45678\n")

            collector = PsiCollector(psi_dir=tmpdir)
            self.assertTrue(collector.is_available())

            psi = collector.collect()
            self.assertTrue(psi.available)
            self.assertIsNotNone(psi.cpu)
            self.assertEqual(psi.cpu.some_avg10, 12.5)
            self.assertEqual(psi.cpu.some_avg60, 8.2)

            self.assertIsNotNone(psi.memory)
            self.assertEqual(psi.memory.some_avg10, 5.4)
            self.assertEqual(psi.memory.full_avg10, 1.2)

            self.assertIsNotNone(psi.io)
            self.assertEqual(psi.io.some_avg10, 22.3)
            self.assertEqual(psi.io.full_avg10, 10.0)

    def test_docker_matches_monitored(self):
        cfg = DockerConfig(
            monitored_containers=["prometheus", "grafana", "sqlserver", "plex"]
        )
        collector = DockerCollector(cfg)
        self.assertTrue(collector._matches_monitored("grafana"))
        self.assertTrue(collector._matches_monitored("/grafana"))
        self.assertTrue(collector._matches_monitored("my-plex-server"))
        self.assertFalse(collector._matches_monitored("random_unmonitored"))

    def test_docker_disappeared_container(self):
        cfg = DockerConfig(
            monitored_containers=["grafana", "sqlserver"]
        )
        collector = DockerCollector(cfg)
        # Simulate grafana was previously running
        collector._previously_running = {"grafana"}

        # Simulate docker returning empty list (grafana stopped & removed)
        collector._query_socket = lambda: []
        collector._query_cli = lambda: []

        metrics = collector.collect()
        self.assertIn("grafana", metrics.containers)
        self.assertFalse(metrics.containers["grafana"].running)
        self.assertEqual(metrics.containers["grafana"].status, "missing / terminated")


if __name__ == "__main__":
    unittest.main()
