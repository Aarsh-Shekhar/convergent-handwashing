"""Diagnostic overlay (debug visualization only – not a game interface)."""

from __future__ import annotations

import cv2
import numpy as np

from convergent.common.types import FramePacket, HandObservation, HandSide, TrackedHands

HAND_CONNECTIONS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)

_COLORS = {HandSide.LEFT: (255, 128, 0), HandSide.RIGHT: (0, 200, 255), HandSide.UNKNOWN: (128, 128, 128)}


def draw_hand(img: np.ndarray, hand: HandObservation) -> None:
    h, w = img.shape[:2]
    color = _COLORS.get(hand.side, (128, 128, 128))
    pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand.landmarks]
    for a, b in HAND_CONNECTIONS:
        cv2.line(img, pts[a], pts[b], color, 2)
    for p in pts:
        cv2.circle(img, p, 3, (255, 255, 255), -1)
    x0, y0 = int(hand.bbox.x_min * w), int(hand.bbox.y_min * h)
    x1, y1 = int(hand.bbox.x_max * w), int(hand.bbox.y_max * h)
    cv2.rectangle(img, (x0, y0), (x1, y1), color, 1)
    label = f"{hand.side.value.upper()} id={hand.track_id} q={hand.tracking_quality:.2f} h={hand.handedness_confidence:.2f} {hand.visibility.value}"
    cv2.putText(img, label, (x0, max(12, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def render_overlay(frame: FramePacket, hands: TrackedHands, extra_lines: list[str] | None = None) -> np.ndarray:
    if frame.image is None:
        raise ValueError("frame has no image")
    img = frame.image.copy()
    for hand in hands.hands + hands.unassigned:
        draw_hand(img, hand)
    lines = [f"frame={frame.frame_id} ts={frame.capture_ts:.3f}s src={frame.source_id}",
             f"hands={hands.num_hands} tracker={hands.tracker_id} {hands.processing_time_ms:.1f}ms"]
    if extra_lines:
        lines.extend(extra_lines)
    y = 18
    for line in lines:
        cv2.putText(img, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        y += 18
    return img
