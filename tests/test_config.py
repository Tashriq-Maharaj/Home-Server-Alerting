import os
import tempfile
import unittest
from pathlib import Path

from src.config import AppConfig, load_config, load_env_file


class TestConfig(unittest.TestCase):
    def test_default_config(self):
        config = load_config()
        self.assertIsInstance(config, AppConfig)
        self.assertEqual(config.server.cpu_count, 4)
        self.assertEqual(config.thresholds.load.warning_1m, 3.8)
        self.assertEqual(config.thresholds.load.critical_1m, 5.5)
        self.assertEqual(config.thresholds.cpu.warning_percent, 85.0)
        self.assertEqual(config.thresholds.disk.warning_percent, 80.0)
        self.assertEqual(config.thresholds.disk.critical_percent, 90.0)

    def test_load_env_file(self):
        saved_env = dict(os.environ)
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".env") as f:
            f.write("TEST_ALERTING_SAMPLE_TOKEN=sample_token_123\n")
            f.write("TEST_ALERTING_SAMPLE_CHAT_ID=sample_chat_456\n")
            f.write("TEST_ALERTING_SAMPLE_LOG_LEVEL=DEBUG\n")
            f_path = Path(f.name)

        try:
            load_env_file(f_path, override=True)
            self.assertEqual(os.environ.get("TEST_ALERTING_SAMPLE_TOKEN"), "sample_token_123")
            self.assertEqual(os.environ.get("TEST_ALERTING_SAMPLE_CHAT_ID"), "sample_chat_456")
            self.assertEqual(os.environ.get("TEST_ALERTING_SAMPLE_LOG_LEVEL"), "DEBUG")
        finally:
            if f_path.is_file():
                f_path.unlink()
            os.environ.clear()
            os.environ.update(saved_env)


if __name__ == "__main__":
    unittest.main()
