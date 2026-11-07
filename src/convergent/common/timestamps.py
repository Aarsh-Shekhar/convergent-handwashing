"""Clock utilities.

Three clocks are kept distinct (see ``common.types`` module docstring):
capture (source clock), arrival (laptop monotonic) and processed (laptop monotonic).
UTC wall-clock is only for session bookkeeping.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


def monotonic() -> float:
    """Laptop monotonic clock in seconds."""
    return time.monotonic()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(UTC)


def ns_to_s(ns: int) -> float:
    return ns / 1_000_000_000.0


def s_to_ns(s: float) -> int:
    return int(round(s * 1_000_000_000))


@dataclass
class ClockOffsetEstimator:
    """Estimates ``laptop_monotonic - device_monotonic`` from (device_ts, arrival_ts) pairs.

    The minimum observed offset over a sliding window approximates the true offset plus the
    minimum one-way network latency (classic NTP-style lower envelope). The estimate is
    only used for *diagnostics and latency reporting*; temporal reasoning stays on the
    device capture clock so that it is independent of network jitter.
    """

    window: int = 200
    _samples: deque[float] = field(default_factory=lambda: deque(maxlen=200))

    def __post_init__(self) -> None:
        self._samples = deque(maxlen=self.window)

    def add(self, device_ts: float, arrival_ts: float) -> None:
        self._samples.append(arrival_ts - device_ts)

    @property
    def offset(self) -> float | None:
        if not self._samples:
            return None
        return min(self._samples)

    def device_to_laptop(self, device_ts: float) -> float | None:
        off = self.offset
        return None if off is None else device_ts + off

    def latency_estimate(self, device_ts: float, arrival_ts: float) -> float | None:
        """Transport latency estimate above the minimum observed (>= 0)."""
        off = self.offset
        return None if off is None else (arrival_ts - device_ts) - off


class OrderGuard:
    """Rejects frames that arrive out of order on the capture clock.

    ``tolerance_s`` allows small jitter (frames with equal timestamps are rejected too).
    """

    def __init__(self, tolerance_s: float = 0.0) -> None:
        self.tolerance_s = tolerance_s
        self._last_ts: float | None = None
        self._last_id: int | None = None
        self.rejected = 0

    def accept(self, frame_id: int, capture_ts: float) -> bool:
        if self._last_ts is not None and (
            capture_ts + self.tolerance_s <= self._last_ts
            or (self._last_id is not None and frame_id <= self._last_id)
        ):
            self.rejected += 1
            return False
        self._last_ts = capture_ts
        self._last_id = frame_id
        return True

    def reset(self) -> None:
        self._last_ts = None
        self._last_id = None
