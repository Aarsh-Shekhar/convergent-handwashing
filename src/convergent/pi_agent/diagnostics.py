"""Device health for the Raspberry Pi agent (vcgencmd throttling flags, temperature, memory)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class ThrottleFlags:
    raw: int

    # bit meanings from the Raspberry Pi documentation (vcgencmd get_throttled)
    @property
    def under_voltage_now(self) -> bool:
        return bool(self.raw & 0x1)

    @property
    def freq_capped_now(self) -> bool:
        return bool(self.raw & 0x2)

    @property
    def throttled_now(self) -> bool:
        return bool(self.raw & 0x4)

    @property
    def under_voltage_occurred(self) -> bool:
        return bool(self.raw & 0x10000)

    def describe(self) -> str:
        parts = []
        if self.under_voltage_now:
            parts.append("UNDER-VOLTAGE NOW")
        if self.freq_capped_now:
            parts.append("freq capped")
        if self.throttled_now:
            parts.append("throttled")
        if self.under_voltage_occurred:
            parts.append("under-voltage occurred since boot")
        return ", ".join(parts) or "ok"


def read_throttled() -> ThrottleFlags | None:
    if shutil.which("vcgencmd") is None:
        return None
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2, check=False).stdout
        return ThrottleFlags(int(out.strip().split("=")[1], 16))
    except (ValueError, IndexError, subprocess.SubprocessError):
        return None


def read_cpu_temp() -> float | None:
    path = "/sys/class/thermal/thermal_zone0/temp"
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def read_mem_available_mb() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        return None
    return None


def display_available(device: str = "/dev/fb0") -> bool:
    return os.path.exists(device)


def collect() -> dict[str, object]:
    t = read_throttled()
    return {
        "cpu_temp_c": read_cpu_temp(),
        "throttled_flags": None if t is None else f"0x{t.raw:x} ({t.describe()})",
        "under_voltage": None if t is None else (t.under_voltage_now or t.under_voltage_occurred),
        "mem_available_mb": read_mem_available_mb(),
        "display_ok": display_available(),
    }
