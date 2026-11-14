"""Experimental soap/foam analysis branch – NOT a prerequisite of the core detector.

The camera can sometimes see lather; it cannot prove soap contact or germ removal. This
module defines the interface and a training entry point that refuses to run without a real
labeled dataset. The only runtime implementation is an *unvalidated* diagnostic proxy
(bright, low-saturation pixel fraction inside the hand polygon) that is reported with
``validated=False`` and must never feed region evidence or progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from convergent.common.types import HandObservation, Region
from convergent.regions.geometry import compute_geometry


@dataclass
class FoamObservation:
    side: str
    lather_proxy: float  # 0..1 fraction of hand-polygon pixels that look like white lather
    validated: bool = False
    method: str = "hsv_bright_lowsat_proxy"
    limitations: str = ("unvalidated heuristic; confounded by skin tone, lighting, wet skin and sink glare; "
                        "does not indicate soap coverage or cleanliness")


class FoamProxy:
    def __init__(self, min_value: int = 190, max_saturation: int = 60) -> None:
        self.min_value = min_value
        self.max_saturation = max_saturation

    def observe(self, bgr: np.ndarray, hand: HandObservation) -> FoamObservation:
        h, w = bgr.shape[:2]
        geo = compute_geometry(hand)
        pts = np.round(geo.polygons[Region.PALM].points * np.array([w, h])).astype(np.int32)
        mask = np.zeros((h, w), dtype=np.uint8)
        if len(pts) >= 3:
            cv2.fillPoly(mask, [pts], 255)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        inside = mask > 0
        if not inside.any():
            return FoamObservation(hand.side.value, 0.0)
        lather = (hsv[..., 2] >= self.min_value) & (hsv[..., 1] <= self.max_saturation) & inside
        return FoamObservation(hand.side.value, float(lather.sum() / inside.sum()))


def train_foam_classifier(dataset_dir: str | Path) -> None:
    """Entry point for a real foam classifier. Requires a labeled dataset layout::

        <dataset_dir>/labels.csv   image_path,hand_side,foam_label(0/1)
        <dataset_dir>/images/...

    No such dataset exists in this project yet, so this raises instead of training on nothing."""
    d = Path(dataset_dir)
    if not (d / "labels.csv").exists():
        raise FileNotFoundError(f"foam training requires a labeled dataset at {d}/labels.csv; none is available")
    raise NotImplementedError("foam classifier training is deferred until a labeled dataset exists (see docs/MODEL_INTEGRATION.md)")


# --------------------------------------------------------------------------- binary soap check (demo-grade)
@dataclass
class SoapState:
    """Binary soap/lather check for the UI. Unvalidated heuristic: a checkmark, not a measurement."""

    detected: bool          # lather visible on the hands right now (smoothed)
    seen: bool              # lather was seen at some point in this wash (latched)
    proxy: float            # 0..1 smoothed fraction of hand pixels that look like white lather
    seen_ts: float | None = None
    validated: bool = False
    method: str = "hsv_bright_lowsat_proxy"


class SoapDetector:
    """Smooths the per-frame lather proxy over all visible hands and latches "seen".

    Thresholds are first guesses (configs/development.yaml ``soap:``); tune them by watching
    ``proxy`` in the live window with dry and soapy hands. Never feeds score or region evidence.
    """

    def __init__(self, min_value: int = 190, max_saturation: int = 60, on_threshold: float = 0.05, off_threshold: float = 0.025,
                 min_s: float = 0.7, ema_s: float = 0.5) -> None:
        self.proxy = FoamProxy(min_value, max_saturation)
        self.on_threshold, self.off_threshold, self.min_s, self.ema_s = on_threshold, off_threshold, min_s, ema_s
        self.reset()

    def reset(self) -> None:
        self._ema: float | None = None
        self._last_ts: float | None = None
        self._above_since: float | None = None
        self._detected = False
        self._seen_ts: float | None = None

    def update(self, bgr: np.ndarray | None, hands: list[HandObservation], ts: float) -> SoapState:
        value: float | None = None
        if bgr is not None and hands:
            h, w = bgr.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)
            for hand in hands:
                pts = np.round(hand.landmark_array()[:, :2] * np.array([w, h])).astype(np.int32)
                if len(pts) >= 3:
                    cv2.fillConvexPoly(mask, cv2.convexHull(pts), 255)
            k = max(3, int(0.03 * min(h, w)) | 1)
            inside = cv2.dilate(mask, np.ones((k, k), np.uint8)) > 0
            if inside.any():
                hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
                lather = (hsv[..., 2] >= self.proxy.min_value) & (hsv[..., 1] <= self.proxy.max_saturation) & inside
                value = float(lather.sum() / inside.sum())
        if value is not None:
            if self._ema is None or self._last_ts is None:
                self._ema = value
            else:
                a = 1.0 - float(np.exp(-max(ts - self._last_ts, 0.0) / max(self.ema_s, 1e-3)))
                self._ema += a * (value - self._ema)
            self._last_ts = ts
        ema = self._ema if self._ema is not None else 0.0
        if value is not None and ema >= self.on_threshold:
            self._above_since = ts if self._above_since is None else self._above_since
            if ts - self._above_since >= self.min_s:
                self._detected = True
                self._seen_ts = self._seen_ts if self._seen_ts is not None else ts
        elif value is None or ema < self.off_threshold:
            self._above_since = None
            self._detected = False
        return SoapState(detected=self._detected, seen=self._seen_ts is not None, proxy=round(ema, 3), seen_ts=self._seen_ts)
