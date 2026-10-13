"""
Thermal sensor collector.
Monitors CPU package/core temperature and thermal sensors on Linux systems
(e.g., Lenovo ThinkPad T440p coretemp/thinkpad ACPI drivers).
Gracefully handles missing sensors.
"""

import glob
import logging
import os
from typing import Dict, Optional

try:
    import psutil
except ImportError:
    psutil = None

from src.collectors.base import BaseCollector, ThermalMetrics

logger = logging.getLogger(__name__)


class ThermalCollector(BaseCollector):
    """Collects hardware temperature metrics from psutil, hwmon, or thermal_zone."""

    def __init__(self):
        pass

    def _collect_via_psutil(self) -> Optional[ThermalMetrics]:
        """Attempt to read temperatures using psutil.sensors_temperatures()."""
        if not psutil or not hasattr(psutil, "sensors_temperatures"):
            return None

        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return None

            sensor_map: Dict[str, float] = {}
            cpu_candidates = []

            for chip_name, entries in temps.items():
                for entry in entries:
                    label = entry.label or chip_name
                    val = float(entry.current)
                    sensor_key = f"{chip_name}:{label}"
                    sensor_map[sensor_key] = val

                    # Prioritize Intel Core / ThinkPad CPU package / core readings
                    chip_lower = chip_name.lower()
                    label_lower = label.lower()
                    if any(k in chip_lower for k in ("coretemp", "thinkpad", "cpu", "k10temp", "acpitz")):
                        if "package" in label_lower or "core" in label_lower or "cpu" in label_lower:
                            cpu_candidates.append(val)
                        elif not cpu_candidates:
                            cpu_candidates.append(val)

            cpu_temp = max(cpu_candidates) if cpu_candidates else (max(sensor_map.values()) if sensor_map else None)

            return ThermalMetrics(
                available=bool(sensor_map),
                cpu_temp_c=round(cpu_temp, 1) if cpu_temp is not None else None,
                sensors=sensor_map,
            )
        except Exception as e:
            logger.debug("psutil sensors_temperatures error: %s", e)
            return None

    def _collect_via_sysfs(self) -> Optional[ThermalMetrics]:
        """Fallback to reading /sys/class/thermal and /sys/class/hwmon."""
        sensor_map: Dict[str, float] = {}
        cpu_candidates = []

        # 1. Check /sys/class/thermal/thermal_zone*
        thermal_zones = glob.glob("/sys/class/thermal/thermal_zone*")
        for zone in thermal_zones:
            temp_path = os.path.join(zone, "temp")
            type_path = os.path.join(zone, "type")
            if os.path.isfile(temp_path):
                try:
                    with open(temp_path, "r", encoding="utf-8") as f:
                        raw_temp = float(f.read().strip())
                        temp_c = raw_temp / 1000.0 if raw_temp > 1000 else raw_temp

                    zone_name = os.path.basename(zone)
                    if os.path.isfile(type_path):
                        with open(type_path, "r", encoding="utf-8") as f:
                            zone_type = f.read().strip()
                            zone_name = f"{zone_type} ({zone_name})"

                    sensor_map[zone_name] = round(temp_c, 1)
                    if "x86_pkg_temp" in zone_name.lower() or "cpu" in zone_name.lower():
                        cpu_candidates.append(temp_c)
                except Exception:
                    pass

        # 2. Check /sys/class/hwmon/hwmon*
        hwmon_dirs = glob.glob("/sys/class/hwmon/hwmon*")
        for hwdir in hwmon_dirs:
            name_path = os.path.join(hwdir, "name")
            hw_name = "hwmon"
            if os.path.isfile(name_path):
                try:
                    with open(name_path, "r", encoding="utf-8") as f:
                        hw_name = f.read().strip()
                except Exception:
                    pass

            for temp_input in glob.glob(os.path.join(hwdir, "temp*_input")):
                try:
                    with open(temp_input, "r", encoding="utf-8") as f:
                        raw_temp = float(f.read().strip())
                        temp_c = raw_temp / 1000.0 if raw_temp > 1000 else raw_temp

                    base = os.path.basename(temp_input).replace("_input", "")
                    label_path = os.path.join(hwdir, f"{base}_label")
                    label = base
                    if os.path.isfile(label_path):
                        with open(label_path, "r", encoding="utf-8") as lf:
                            label = lf.read().strip()

                    key = f"{hw_name}:{label}"
                    sensor_map[key] = round(temp_c, 1)
                    if any(k in hw_name.lower() for k in ("coretemp", "thinkpad", "cpu")):
                        cpu_candidates.append(temp_c)
                except Exception:
                    pass

        if not sensor_map:
            return None

        cpu_temp = max(cpu_candidates) if cpu_candidates else max(sensor_map.values())
        return ThermalMetrics(
            available=True,
            cpu_temp_c=round(cpu_temp, 1),
            sensors=sensor_map,
        )

    def collect(self) -> ThermalMetrics:
        """Collect current thermal metrics."""
        result = self._collect_via_psutil()
        if result and result.available:
            return result

        result = self._collect_via_sysfs()
        if result and result.available:
            return result

        return ThermalMetrics(available=False, cpu_temp_c=None, sensors={})
