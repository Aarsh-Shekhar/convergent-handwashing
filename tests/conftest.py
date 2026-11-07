"""Shared fixtures. No child-identifying data anywhere; all hands are synthetic."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from convergent.common.types import (
    BoundingBox,
    CanonicalLabel,
    FramePacket,
    FrameTimestamps,
    HandObservation,
    HandSide,
    ImageTransform,
    ModelPrediction,
    PredictionStatus,
    TrackedHands,
)

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CONVERGENT_ROOT", str(ROOT))
os.environ.setdefault("CONVERGENT_LOG_DIR", str(ROOT / "logs"))


def synthetic_hand(cx: float = 0.5, cy: float = 0.5, scale: float = 0.15, seed: int = 0, mirror: bool = False) -> np.ndarray:
    """A plausible 21x3 normalized hand: wrist at bottom, fingers pointing up (image y down)."""
    rng = np.random.default_rng(seed)
    pts = np.zeros((21, 3))
    pts[0] = [0.0, 0.5, 0.0]  # wrist
    finger_x = [-0.45, -0.2, 0.0, 0.2, 0.4]  # thumb .. pinky
    finger_len = [0.5, 0.95, 1.0, 0.92, 0.75]
    for f in range(5):
        base = 1 + f * 4
        for j in range(4):
            frac = (j + 1) / 4
            pts[base + j] = [finger_x[f] * (0.4 + 0.6 * frac), 0.5 - finger_len[f] * frac, -0.02 * frac]
    pts[:, :2] += rng.normal(0, 0.005, size=(21, 2))
    if mirror:
        pts[:, 0] *= -1
    pts[:, 0] = cx + pts[:, 0] * scale
    pts[:, 1] = cy + pts[:, 1] * scale
    return pts


def make_obs(side: HandSide, track_id: int = 0, cx: float = 0.5, cy: float = 0.5, quality: float = 0.9, raw: str | None = None,
             seed: int = 0, lm: np.ndarray | None = None) -> HandObservation:
    arr = synthetic_hand(cx, cy, seed=seed, mirror=side == HandSide.LEFT) if lm is None else lm
    raw = raw if raw is not None else ("Right" if side == HandSide.LEFT else "Left")  # swapped convention by default
    return HandObservation.from_array(arr, track_id=track_id, side=side, handedness_confidence=0.95, raw_handedness_label=raw,
                                      tracking_quality=quality)


def make_hands(ts: float, frame_id: int = 0, left: bool = True, right: bool = True, quality: float = 0.9, seed: int = 0) -> TrackedHands:
    return TrackedHands(frame_id=frame_id, capture_ts=ts,
                        left=make_obs(HandSide.LEFT, 0, 0.35, 0.5, quality, seed=seed) if left else None,
                        right=make_obs(HandSide.RIGHT, 1, 0.65, 0.5, quality, seed=seed + 1) if right else None)


def make_frame(frame_id: int = 0, ts: float = 0.0, w: int = 640, h: int = 480, session: str = "ses_test") -> FramePacket:
    img = np.full((h, w, 3), 30, dtype=np.uint8)
    return FramePacket(frame_id=frame_id, session_id=session, timestamps=FrameTimestamps(capture_ts=ts), width=w, height=h,
                       source_id="test", transform=ImageTransform(original_width=w, original_height=h), image=img)


def make_pred(model_id: str, ts: float, technique: str | None, conf: float = 0.9, side: HandSide = HandSide.BOTH,
              status: PredictionStatus = PredictionStatus.VALID, dist: dict[str, float] | None = None, resolved: bool = True,
              window: float = 0.0) -> ModelPrediction:
    canonical = None if technique is None else CanonicalLabel(technique=technique, side=side, resolved=resolved)
    if dist is None and technique is not None:
        key = canonical.key  # type: ignore[union-attr]
        dist = {key: conf, "none": max(0.0, 1 - conf)}
    return ModelPrediction(model_id=model_id, model_version="t", window_start_ts=ts - window, window_end_ts=ts, canonical=canonical,
                           canonical_probabilities=dist, confidence=conf if technique else None, status=status)


@pytest.fixture
def hand_array() -> np.ndarray:
    return synthetic_hand()


@pytest.fixture
def bbox() -> BoundingBox:
    return BoundingBox(x_min=0.1, y_min=0.1, x_max=0.4, y_max=0.5)


@pytest.fixture
def sample_video() -> Path:
    p = ROOT / "data" / "samples" / "handwashing_missing_step.mp4"
    if not p.exists():
        pytest.skip("sample video not present (make samples)")
    return p


@pytest.fixture
def tiny_video(tmp_path: Path) -> Path:
    """A 2-second 15 fps synthetic mp4 written with OpenCV."""
    import cv2

    path = tmp_path / "tiny.mp4"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 15.0, (320, 240))
    for i in range(30):
        img = np.full((240, 320, 3), 20, dtype=np.uint8)
        cv2.circle(img, (40 + i * 8, 120), 20, (200, 200, 200), -1)
        w.write(img)
    w.release()
    return path
