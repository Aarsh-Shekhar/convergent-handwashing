"""Timestamp-aware sliding window of landmark feature vectors for temporal models.

A window is only emitted when it consists of *contiguous* observations: consecutive
timestamps closer than ``max_gap_s``. A tracking gap resets the buffer so that frames from
before and after the gap are never stitched into one "motion". Each observation carries an
explicit presence mask per hand – a missing hand is zeros in the feature block **and**
``presence=0``; it is never mistaken for a hand at the origin.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from convergent.common.types import TrackedHands


@dataclass
class SequenceWindow:
    features: np.ndarray  # (T, F)
    presence: np.ndarray  # (T, 2)  [left, right]
    timestamps: np.ndarray  # (T,)
    frame_ids: list[int]
    tracking_quality: np.ndarray  # (T,)

    @property
    def start_ts(self) -> float:
        return float(self.timestamps[0])

    @property
    def end_ts(self) -> float:
        return float(self.timestamps[-1])

    @property
    def length(self) -> int:
        return int(self.features.shape[0])


FeatureFn = Callable[[TrackedHands], tuple[np.ndarray, np.ndarray, float] | None]
"""Returns (feature_vector, presence[2], tracking_quality) or None when nothing is observed."""


class SequenceBuffer:
    def __init__(self, window_frames: int = 16, max_gap_s: float = 0.25, stride_frames: int = 1,
                 feature_fn: FeatureFn | None = None, allow_empty_frames: bool = True) -> None:
        if window_frames < 2:
            raise ValueError("window_frames must be >= 2 (a temporal model needs >1 step)")
        if stride_frames < 1:
            raise ValueError("stride_frames must be >= 1")
        self.window_frames = window_frames
        self.max_gap_s = max_gap_s
        self.stride_frames = stride_frames
        self.feature_fn = feature_fn
        self.allow_empty_frames = allow_empty_frames
        self._buf: deque[tuple[float, int, np.ndarray, np.ndarray, float]] = deque(maxlen=window_frames)
        self._since_emit = 0
        self.resets = 0
        self.gaps_detected = 0

    def reset(self) -> None:
        if self._buf:
            self.resets += 1
        self._buf.clear()
        self._since_emit = 0

    def __len__(self) -> int:
        return len(self._buf)

    def push(self, ts: float, frame_id: int, features: np.ndarray, presence: np.ndarray, quality: float) -> SequenceWindow | None:
        if self._buf:
            last_ts = self._buf[-1][0]
            if ts <= last_ts:
                raise ValueError(f"non-increasing timestamp {ts} <= {last_ts}")
            if ts - last_ts > self.max_gap_s:
                self.gaps_detected += 1
                self.reset()
        self._buf.append((ts, frame_id, np.asarray(features, dtype=np.float32), np.asarray(presence, dtype=np.float32), float(quality)))
        self._since_emit += 1
        if len(self._buf) < self.window_frames or self._since_emit < self.stride_frames:
            return None
        self._since_emit = 0
        return SequenceWindow(
            features=np.stack([b[2] for b in self._buf]),
            presence=np.stack([b[3] for b in self._buf]),
            timestamps=np.array([b[0] for b in self._buf], dtype=np.float64),
            frame_ids=[b[1] for b in self._buf],
            tracking_quality=np.array([b[4] for b in self._buf], dtype=np.float32),
        )

    def update(self, hands: TrackedHands) -> SequenceWindow | None:
        if self.feature_fn is None:
            raise RuntimeError("feature_fn not set")
        out = self.feature_fn(hands)
        if out is None:
            # A frame with no hands is skipped, not pushed. If hands stay absent for longer than
            # max_gap_s the next push() breaks the window (timestamp gap) – a brief detector
            # dropout (1-3 frames at 15 FPS) does not throw away the whole sequence. Training
            # (training.build_windows) applies exactly the same rule.
            if not self.allow_empty_frames:
                self.reset()
            return None
        feats, presence, quality = out
        return self.push(hands.capture_ts, hands.frame_id, feats, presence, quality)


def windows_from_sequence(features: np.ndarray, timestamps: np.ndarray, window: int, stride: int,
                          max_gap_s: float, presence: np.ndarray | None = None) -> list[tuple[int, int]]:
    """Offline helper: index ranges [start, end) of contiguous windows in one recording.

    Used by training to build sequences that never cross a gap, never cross recordings
    (the caller passes one recording at a time) and never shuffle frames in time.
    """
    n = len(timestamps)
    if n != len(features):
        raise ValueError("features/timestamps length mismatch")
    out: list[tuple[int, int]] = []
    seg_start = 0
    for i in range(1, n + 1):
        boundary = i == n or (timestamps[i] - timestamps[i - 1] > max_gap_s) or timestamps[i] <= timestamps[i - 1]
        if boundary:
            s = seg_start
            while s + window <= i:
                out.append((s, s + window))
                s += stride
            seg_start = i
    return out
