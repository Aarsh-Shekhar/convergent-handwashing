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
