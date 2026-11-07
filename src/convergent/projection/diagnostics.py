"""Minimal calibration/debug renderer for the projector canvas (laptop side, OpenCV).

Draws crosshairs, markers, calibration patterns and landmark anchors onto an 854x480 logical
canvas and builds the corresponding :class:`RenderCommand` for the Pi. Infrastructure only –
not the game interface.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from convergent.common.types import (
    PROJECTOR_LOGICAL_HEIGHT,
    PROJECTOR_LOGICAL_WIDTH,
    CalibrationProfile,
    ProjectionTarget,
)
from convergent.communication.protocol import RenderCommand, RenderItem
from convergent.projection.calibration import Pattern


def blank_canvas(width: int = PROJECTOR_LOGICAL_WIDTH, height: int = PROJECTOR_LOGICAL_HEIGHT) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def draw_items(canvas: np.ndarray, items: list[RenderItem]) -> np.ndarray:
    h, w = canvas.shape[:2]
    for it in items:
        color = tuple(int(c) for c in it.color[::-1])  # RGB -> BGR
        if it.shape == "clear":
            canvas[:] = 0
        elif it.shape in ("crosshair", "circle") and it.x is not None and it.y is not None:
            x, y = int(round(it.x)), int(round(it.y))
            if 0 <= x < w and 0 <= y < h:
                r = int(it.radius)
                if it.shape == "crosshair":
                    cv2.line(canvas, (x - r, y), (x + r, y), color, 2)
                    cv2.line(canvas, (x, y - r), (x, y + r), color, 2)
                cv2.circle(canvas, (x, y), r, color, 2)
                if it.label:
                    cv2.putText(canvas, it.label, (x + r + 4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
        elif it.shape in ("polygon", "skeleton") and it.points:
            pts = np.round(np.asarray(it.points, dtype=np.float64)).astype(np.int32)
            cv2.polylines(canvas, [pts], it.shape == "polygon", color, 2)
        elif it.shape == "text" and it.x is not None and it.y is not None:
            cv2.putText(canvas, it.label, (int(it.x), int(it.y)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)
    return canvas


def render_targets(targets: list[ProjectionTarget], width: int = PROJECTOR_LOGICAL_WIDTH, height: int = PROJECTOR_LOGICAL_HEIGHT) -> np.ndarray:
    return draw_items(blank_canvas(width, height), targets_to_items(targets))


def targets_to_items(targets: list[ProjectionTarget]) -> list[RenderItem]:
    items: list[RenderItem] = []
    for t in targets:
        if not t.valid or t.projector_xy is None:
            continue
        color = [255, 128, 0] if t.side.value == "left" else [0, 200, 255]
        shape = "crosshair" if t.anchor_type.value in ("hand_centroid", "region_centroid") else "circle"
        items.append(RenderItem(shape=shape, x=t.projector_xy[0], y=t.projector_xy[1], radius=14 if shape == "crosshair" else 6,
                                color=color, label=t.anchor_id if shape == "crosshair" else "", anchor_id=t.anchor_id))
    return items


def render_command_for_targets(seq: int, targets: list[ProjectionTarget], profile: CalibrationProfile | None,
                               valid_for_s: float = 0.5, text: str = "") -> RenderCommand:
    return RenderCommand(seq=seq, command="draw", calibration_profile_id=profile.profile_id if profile else None,
                         calibration_version=profile.version if profile else None,
                         canvas_width=profile.projector_width if profile else PROJECTOR_LOGICAL_WIDTH,
                         canvas_height=profile.projector_height if profile else PROJECTOR_LOGICAL_HEIGHT,
                         items=targets_to_items(targets), text=text, valid_until_ns=0 if valid_for_s <= 0 else int(time.monotonic_ns() + valid_for_s * 1e9))


def render_command_for_pattern(seq: int, pattern: Pattern) -> RenderCommand:
    """Patterns are regenerated on the Pi from parameters (no bitmap transfer)."""
    h, w = pattern.image.shape[:2]
    item = RenderItem(shape=pattern.kind, x=0, y=0, label=pattern.kind, points=[[float(p[0]), float(p[1])] for p in pattern.points[:4]])
    cmd = RenderCommand(seq=seq, command="pattern", calibration_profile_id=None, calibration_version=None, canvas_width=w,
                        canvas_height=h, items=[item], text=str(pattern.meta))
    return cmd


def draw_calibration_debug(canvas: np.ndarray, profile: CalibrationProfile | None) -> np.ndarray:
    h, w = canvas.shape[:2]
    cv2.rectangle(canvas, (0, 0), (w - 1, h - 1), (0, 255, 0), 2)
    cv2.line(canvas, (w // 2 - 20, h // 2), (w // 2 + 20, h // 2), (0, 255, 0), 1)
    cv2.line(canvas, (w // 2, h // 2 - 20), (w // 2, h // 2 + 20), (0, 255, 0), 1)
    text = "no calibration" if profile is None else f"{profile.profile_id} v{profile.version} rmse={profile.reprojection_rmse_px:.2f}px valid={profile.valid}"
    cv2.putText(canvas, text, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return canvas
