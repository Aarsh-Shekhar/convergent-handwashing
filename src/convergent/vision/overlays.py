"""Diagnostic overlay (debug visualization only – not a game interface)."""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from convergent.common.types import FramePacket, HandObservation, HandSide, TrackedHands
from convergent.scoring.wash_score import WashScore

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


# --------------------------------------------------------------------------- wash score panel
_STEP_NAMES = {
    "palm_to_palm": "palm to palm", "back_of_hand": "back of hand", "interlaced_fingers": "interlaced",
    "backs_of_fingers": "backs of fingers", "thumb_rubbing": "thumbs", "fingertip_rubbing": "fingertips",
    "wrist_rubbing": "wrists",
}
_GREEN, _YELLOW, _GREY, _WHITE = (80, 200, 80), (0, 215, 255), (90, 90, 90), (255, 255, 255)


def step_name(technique: str | None) -> str:
    return "-" if technique is None else _STEP_NAMES.get(technique, technique.replace("_", " "))


def _text(img: np.ndarray, s: str, org: tuple[int, int], scale: float = 0.45, color: tuple[int, int, int] = _WHITE, thick: int = 1) -> None:
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def _bar(img: np.ndarray, x: int, y: int, w: int, h: int, frac: float, color: tuple[int, int, int]) -> None:
    cv2.rectangle(img, (x, y), (x + w, y + h), _GREY, -1)
    fill = int(round(w * min(max(frac, 0.0), 1.0)))
    if fill > 0:
        cv2.rectangle(img, (x, y), (x + fill, y + h), color, -1)
    cv2.rectangle(img, (x, y), (x + w, y + h), _WHITE, 1)


def _star(img: np.ndarray, cx: int, cy: int, r: int, filled: bool) -> None:
    pts = []
    for k in range(10):
        rad = r if k % 2 == 0 else r * 0.45
        a = -math.pi / 2 + k * math.pi / 5
        pts.append((int(cx + rad * math.cos(a)), int(cy + rad * math.sin(a))))
    poly = np.array(pts, np.int32).reshape(-1, 1, 2)
    if filled:
        cv2.fillPoly(img, [poly], _YELLOW, cv2.LINE_AA)
    else:
        cv2.polylines(img, [poly], True, _GREY, 1, cv2.LINE_AA)


def draw_soap_chip(img: np.ndarray, soap: Any, x1: int, y: int) -> None:
    """Top-right 'SOAP' checkmark: green tick when lather has been seen this wash, bright while it is
    visible now, grey otherwise. Unvalidated heuristic; shows the proxy value small for tuning."""
    on = bool(getattr(soap, "seen", False))
    now = bool(getattr(soap, "detected", False))
    color = _GREEN if on else _GREY
    x0 = x1 - 96
    cv2.rectangle(img, (x0, y - 16), (x1, y + 6), (40, 40, 40), -1)
    cv2.rectangle(img, (x0, y - 16), (x1, y + 6), color, 1)
    _text(img, "SOAP", (x0 + 6, y), 0.5, color, 1)
    if on:  # tick
        cv2.polylines(img, [np.array([[x0 + 56, y - 5], [x0 + 62, y + 1], [x0 + 74, y - 11]], np.int32)], False, _GREEN if now else (60, 140, 60), 2, cv2.LINE_AA)
    else:
        _text(img, "-", (x0 + 60, y), 0.5, _GREY, 1)
    _text(img, f"{getattr(soap, 'proxy', 0.0):.2f}", (x0 + 78, y + 4), 0.32, color, 1)


def draw_score_panel(img: np.ndarray, score: WashScore, width: int = 236, soap: Any = None) -> np.ndarray:
    """Draw per-step timers, total time, stars, points and the finish banner on the right side (in place)."""
    h, w = img.shape[:2]
    row_h = 20
    height = 64 + row_h * len(score.steps) + 76 + (30 if score.finished else 0)
    x0, y0 = max(0, w - width - 6), 6
    x1, y1 = min(w, x0 + width), min(h, y0 + height)
    roi = img[y0:y1, x0:x1]
    if roi.size:
        roi[:] = cv2.addWeighted(roi, 0.35, np.zeros_like(roi), 0.65, 0)

    x, y = x0 + 8, y0 + 18
    _text(img, "WASH SCORE", (x, y), 0.5, _WHITE, 1)
    _text(img, f"{score.points} pts", (x1 - 62, y), 0.5, _WHITE, 1)
    y += 24
    if soap is not None:
        draw_soap_chip(img, soap, x0 - 8, y0 + 18)
    for i in range(5):
        _star(img, x + 10 + i * 24, y, 9, i < score.stars)
    y += 22

    bar_x, bar_w = x + 122, 56
    for st in score.steps:
        is_next = (not score.finished) and st.technique == score.next_step
        color = _GREEN if st.done else (_YELLOW if is_next else _WHITE)
        _text(img, (">" if is_next else " ") + step_name(st.technique), (x - 4, y + 10), 0.42, color)
        _bar(img, bar_x, y + 1, bar_w, 10, st.seconds / score.step_min_s if score.step_min_s > 0 else 1.0, _GREEN if st.done else _YELLOW)
        _text(img, f"{st.seconds:4.1f}s", (bar_x + bar_w + 6, y + 10), 0.38, color)
        y += row_h

    y += 6
    _text(img, f"total {score.total_s:4.1f} / {score.total_min_s:.0f}s", (x, y + 10), 0.45)
    y += 16
    total_ok = score.total_s + 1e-6 >= score.total_min_s
    _bar(img, x, y, width - 20, 10, score.total_s / score.total_min_s if score.total_min_s > 0 else 1.0, _GREEN if total_ok else _YELLOW)
    y += 26
    steps_ok = score.steps_done >= score.steps_required
    _text(img, f"steps {score.steps_done} / {score.steps_required} needed", (x, y), 0.45, _GREEN if steps_ok else _WHITE)
    y += 20
    if score.finished:
        cv2.rectangle(img, (x0 + 4, y - 4), (x1 - 4, y + 22), _GREEN, -1)
        _text(img, "DONE! score locked", (x + 4, y + 14), 0.55, (0, 0, 0), 2)
    else:
        _text(img, f"next: {step_name(score.next_step)}", (x, y), 0.45, _YELLOW)
    return img


# --------------------------------------------------------------------------- projection preview (laptop stand-in for the projector)
class ProjectionPreview:
    """Shows what the projector would draw, on the laptop: the render canvas composited onto the
    camera view (additive, like light on skin) plus a small inset of the raw canvas (what the Pi
    sends to the projector). An on-screen button and the P key toggle the graphics."""

    BUTTON = (10, 60, 230, 92)  # x0, y0, x1, y1 in window px

    def __init__(self, pipe: Any, window: str = "convergent diagnostics") -> None:
        self.pipe, self.window = pipe, window
        self._mouse_bound = False

    @property
    def on(self) -> bool:
        return bool(self.pipe.scene.enabled)

    def toggle(self) -> None:
        self.pipe.scene.enabled = not self.pipe.scene.enabled
        if self.pipe.scene.enabled:
            self.pipe.scene.reset()

    def _mouse(self, event: int, x: int, y: int, flags: int, param: Any) -> None:  # noqa: ARG002
        x0, y0, x1, y1 = self.BUTTON
        if event == cv2.EVENT_LBUTTONDOWN and x0 <= x <= x1 and y0 <= y <= y1:
            self.toggle()

    def bind(self) -> None:
        if not self._mouse_bound:
            try:
                cv2.setMouseCallback(self.window, self._mouse)
                self._mouse_bound = True
            except cv2.error:
                pass

    def compose(self, img: np.ndarray, render: Any, clean: bool = False) -> np.ndarray:
        """Blend the rendered canvas over the camera image; inset the raw canvas bottom-right.
        ``clean`` (game view): only the picture and the graphics, drawn as solid stickers instead of added light
        (vivid on a screen; a projector can only add light), no inset and no button."""
        from convergent.pi_agent.renderer import render_canvas

        h, w = img.shape[:2]
        if render is not None and clean:
            layer = render_canvas(render, transparent=True)
            if self.pipe.mapper.ready and self.pipe.mapper._Hinv is not None:
                layer = cv2.warpPerspective(layer, self.pipe.mapper._Hinv, (w, h))
            elif layer.shape[:2] != (h, w):
                layer = cv2.resize(layer, (w, h), interpolation=cv2.INTER_LINEAR)
            a = layer[..., 3:4].astype(np.uint16)
            a += a > 127  # 0..256, so the blend is a shift instead of a division
            return ((img.astype(np.uint16) * (256 - a) + layer[..., 2::-1].astype(np.uint16) * a) >> 8).astype(np.uint8)
        if render is not None:
            canvas = cv2.cvtColor(render_canvas(render), cv2.COLOR_RGB2BGR)
            if self.pipe.mapper.ready and self.pipe.mapper._Hinv is not None:
                warped = cv2.warpPerspective(canvas, self.pipe.mapper._Hinv, (w, h))
            else:
                warped = cv2.resize(canvas, (w, h), interpolation=cv2.INTER_LINEAR)
            img = cv2.add(img, warped)  # additive: projected light brightens the surface
            iw = max(120, w // 4)
            ih = int(iw * canvas.shape[0] / canvas.shape[1])
            x0i, y0i = w - iw - 8, h - ih - 8  # bottom-right inset: what the Pi sends to the projector
            img[y0i : y0i + ih, x0i : x0i + iw] = cv2.resize(canvas, (iw, ih))
            cv2.rectangle(img, (x0i, y0i), (x0i + iw, y0i + ih), (200, 200, 200), 1)
            _text(img, "projector canvas", (x0i + 2, y0i - 4), 0.4, (200, 200, 200))
        if clean:
            return img
        x0, y0, x1, y1 = self.BUTTON
        cv2.rectangle(img, (x0, y0), (x1, y1), (40, 120, 40) if self.on else (60, 60, 60), -1)
        cv2.rectangle(img, (x0, y0), (x1, y1), _GREEN if self.on else _GREY, 1)
        _text(img, f"PROJECTION: {'ON' if self.on else 'OFF'}  (P)", (x0 + 8, y0 + 21), 0.5, _WHITE, 1)
        return img
