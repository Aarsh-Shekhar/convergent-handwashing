"""Replaceable hand-segmentation interface (optional research branch).

The baseline implementation rasterizes the landmark-derived region polygons into masks.
A learned segmenter (SAM, YOLO-seg, ...) can be plugged in behind the same interface later;
none of them establishes surface cleanliness – a mask only says where a region appears in
the image.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import cv2
import numpy as np

from convergent.common.types import HandObservation, Region
from convergent.regions.geometry import compute_geometry


class SegmentationBackend(ABC):
    name: str = "abstract"

    @abstractmethod
    def masks(self, image_shape: tuple[int, int], hand: HandObservation) -> dict[Region, np.ndarray]:
        """Return {region: HxW uint8 mask (0/255)} for one hand."""


class LandmarkMaskSegmenter(SegmentationBackend):
    name = "landmark_polygons"

    def masks(self, image_shape: tuple[int, int], hand: HandObservation) -> dict[Region, np.ndarray]:
        h, w = image_shape
        geo = compute_geometry(hand)
        out: dict[Region, np.ndarray] = {}
        for region, poly in geo.polygons.items():
            m = np.zeros((h, w), dtype=np.uint8)
            pts = np.round(poly.points * np.array([w, h])).astype(np.int32)
            if len(pts) >= 3:
                cv2.fillPoly(m, [pts], 255)
            out[region] = m
        return out


def mask_overlap(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a > 0, b > 0).sum()
    union = np.logical_or(a > 0, b > 0).sum()
    return float(inter / union) if union else 0.0
