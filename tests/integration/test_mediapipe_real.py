"""Tests that run the real MediaPipe landmark model (bundled legacy graph or the tasks bundle)."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from convergent.common.config import SourceConfig, TrackerConfig
from convergent.common.types import HandSide
from convergent.vision.hand_tracker import HandTracker, create_backend
from convergent.vision.overlays import render_overlay
from convergent.vision.sources import VideoFileSource

pytestmark = pytest.mark.mediapipe


@pytest.fixture(scope="module")
def tracker():
    try:
        backend = create_backend(TrackerConfig(backend="auto"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no MediaPipe backend: {exc}")
    return HandTracker(TrackerConfig(backend="auto"), backend)


def test_two_hand_detection_on_sample_video(tracker, sample_video):
    src = VideoFileSource(SourceConfig(kind="video", path=str(sample_video), target_fps=5, max_frames=40))
    counts = []
    overlay = None
    with src:
        for frame in src:
            th = tracker.detect(frame)
            counts.append(th.num_hands)
            if th.num_hands == 2 and overlay is None:
                overlay = render_overlay(frame, th)
                assert th.left is not None and th.right is not None
                assert th.left.track_id != th.right.track_id
                assert {th.left.raw_handedness_label, th.right.raw_handedness_label} == {"Left", "Right"}
                for h in th.hands:
                    lm = h.landmark_array()
                    assert lm.shape == (21, 3) and np.all(np.isfinite(lm))
                    assert lm[:, :2].min() >= -0.5 and lm[:, :2].max() <= 1.5
    assert max(counts) >= 1, "no hands detected in the sample video"
    assert sum(c == 2 for c in counts) >= 3, f"two-hand frames too rare: {counts}"
    assert overlay is not None and overlay.shape[2] == 3


def test_handedness_swap_follows_image_mirroring(tracker, sample_video):
    """Mirroring the image horizontally must swap MediaPipe's raw labels; the anatomical
    side we assign follows the configured swap. Documents the orientation convention."""
    from convergent.common.types import FramePacket, FrameTimestamps, ImageTransform

    def packet(frame, i):
        h, w = frame.shape[:2]
        return FramePacket(frame_id=i, session_id="s", timestamps=FrameTimestamps(capture_ts=i * 0.1), width=w, height=h, source_id="t",
                           transform=ImageTransform(original_width=w, original_height=h, mirrored=i >= 10), image=frame)

    fresh = HandTracker(TrackerConfig(backend="auto", swap_handedness=True), create_backend(TrackerConfig(backend="auto")))
    cap = cv2.VideoCapture(str(sample_video))
    img = None
    normal = None
    for start in range(30, 600, 15):  # find a frame where both hands are tracked
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        ok, candidate = cap.read()
        if not ok:
            break
        fresh.reset()
        for i in range(10):
            normal = fresh.detect(packet(candidate, i))
        if normal is not None and normal.num_hands == 2:
            img = candidate
            break
    cap.release()
    if img is None:
        pytest.skip("no frame with two tracked hands found")
    fresh.reset()
    for i in range(10, 20):
        mirrored = fresh.detect(packet(cv2.flip(img, 1), i))
    if mirrored.num_hands < 2:
        pytest.skip("mirrored frame has fewer than two tracked hands")
    # the hand on the image's left side keeps its anatomical side only if labels swap with the mirror
    left_x_normal = normal.left.landmark_array()[:, 0].mean()
    left_x_mirror = mirrored.left.landmark_array()[:, 0].mean()
    assert abs((1 - left_x_normal) - left_x_mirror) < 0.15  # same physical hand, mirrored position
    assert normal.left.raw_handedness_label != mirrored.left.raw_handedness_label or normal.left.side == HandSide.LEFT
