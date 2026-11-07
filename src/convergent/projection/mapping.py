"""Point mapping between camera image space and the projector logical canvas, plus
landmark/region anchor mapping with smoothing and explicit validity."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from convergent.common.config import ProjectorConfig
from convergent.common.types import (
    AnchorType,
    CalibrationProfile,
    HandObservation,
    HandSide,
    ProjectionTarget,
    Region,
    TrackedHands,
)
from convergent.projection.homography import transform_point
from convergent.projection.smoothing import TargetSmoother
from convergent.regions.geometry import FINGERTIPS, compute_geometry


@dataclass
class MappedPoint:
    x: float | None
    y: float | None
    valid: bool
    reason: str = ""

    @property
    def xy(self) -> tuple[float, float] | None:
        return None if not self.valid or self.x is None or self.y is None else (self.x, self.y)


class ProjectionMapper:
    def __init__(self, profile: CalibrationProfile | None, cfg: ProjectorConfig | None = None) -> None:
        self.cfg = cfg or ProjectorConfig()
        self.profile = profile
        self._H = None if profile is None else profile.homography()
        self._Hinv = None if self._H is None else np.linalg.inv(self._H)
        self.smoother = TargetSmoother(self.cfg.smoothing)

    # ---- profile lifecycle
    def set_profile(self, profile: CalibrationProfile | None) -> None:
        self.profile = profile
        self._H = None if profile is None else profile.homography()
        self._Hinv = None if self._H is None else np.linalg.inv(self._H)
        self.smoother.reset()

    def invalidate(self, reason: str) -> None:
        if self.profile is not None:
            self.profile = self.profile.model_copy(update={"valid": False, "invalidation_reason": reason})
        self.smoother.reset()

    @property
    def ready(self) -> bool:
        return self.profile is not None and self.profile.valid and self._H is not None

    def _check(self) -> str:
        if self.profile is None:
            return "no calibration profile"
        if not self.profile.valid:
            return f"calibration invalid: {self.profile.invalidation_reason or 'unknown'}"
        return ""

    # ---- point mapping
    def camera_to_projector(self, x: float, y: float, image_size: tuple[int, int] | None = None) -> MappedPoint:
        err = self._check()
        if err:
            return MappedPoint(None, None, False, err)
        assert self.profile is not None and self._H is not None
        if image_size is not None and image_size != (self.profile.image_width, self.profile.image_height):
            return MappedPoint(None, None, False,
                               f"image size {image_size} != calibrated {(self.profile.image_width, self.profile.image_height)}")
        if not (np.isfinite(x) and np.isfinite(y)):
            return MappedPoint(None, None, False, "non-finite input")
        p = transform_point(self._H, x, y)
        if p is None:
            return MappedPoint(None, None, False, "point maps to infinity")
        u, v = p
        if not (0 <= u < self.profile.projector_width and 0 <= v < self.profile.projector_height):
            return MappedPoint(u, v, False, "outside projector canvas")
        return MappedPoint(u, v, True)

    def projector_to_camera(self, u: float, v: float) -> MappedPoint:
        err = self._check()
        if err:
            return MappedPoint(None, None, False, err)
        assert self.profile is not None and self._Hinv is not None
        if not (np.isfinite(u) and np.isfinite(v)):
            return MappedPoint(None, None, False, "non-finite input")
        p = transform_point(self._Hinv, u, v)
        if p is None:
            return MappedPoint(None, None, False, "point maps to infinity")
        x, y = p
        if not (0 <= x < self.profile.image_width and 0 <= y < self.profile.image_height):
            return MappedPoint(x, y, False, "outside camera image")
        return MappedPoint(x, y, True)

    # ---- anchors
    def _target(self, anchor_type: AnchorType, anchor_id: str, side: HandSide, cam_xy: tuple[float, float] | None,
                ts: float, confidence: float, image_size: tuple[int, int], smooth: bool = True) -> ProjectionTarget:
        pid = self.profile.profile_id if self.profile else None
        ver = self.profile.version if self.profile else None
        if cam_xy is None:
            self.smoother.invalidate(anchor_id)
            return ProjectionTarget(anchor_type=anchor_type, anchor_id=anchor_id, side=side, camera_xy=None, projector_xy=None,
                                    confidence=0.0, valid=False, reason="anchor not observed", timestamp=ts,
                                    calibration_profile_id=pid, calibration_version=ver)
        m = self.camera_to_projector(cam_xy[0], cam_xy[1], image_size)
        if not m.valid:
            self.smoother.invalidate(anchor_id)
            return ProjectionTarget(anchor_type=anchor_type, anchor_id=anchor_id, side=side, camera_xy=cam_xy,
                                    projector_xy=None if m.x is None else (m.x, m.y), confidence=0.0, valid=False, reason=m.reason,
                                    timestamp=ts, calibration_profile_id=pid, calibration_version=ver)
        xy = self.smoother.update(anchor_id, (m.x, m.y), ts) if smooth else (m.x, m.y)  # type: ignore[arg-type]
        return ProjectionTarget(anchor_type=anchor_type, anchor_id=anchor_id, side=side, camera_xy=cam_xy, projector_xy=xy,
                                confidence=float(min(max(confidence, 0.0), 1.0)), valid=True, timestamp=ts,
                                calibration_profile_id=pid, calibration_version=ver)

    def map_hands(self, hands: TrackedHands, image_size: tuple[int, int]) -> list[ProjectionTarget]:
        """Map hand centroids, fingertips and region anchors for all tracked hands."""
        w, h = image_size
        ts = hands.capture_ts
        out: list[ProjectionTarget] = []
        for side in (HandSide.LEFT, HandSide.RIGHT):
            hand = hands.get(side)
            if hand is None:
                for a in ("hand_centroid", "fingertips", "region"):
                    if a in self.cfg.anchors or a == "region":
                        self.smoother.invalidate(f"{side.value}:{a}")
                continue
            out.extend(self.map_hand(hand, ts, image_size))
        return out

    def map_hand(self, hand: HandObservation, ts: float, image_size: tuple[int, int]) -> list[ProjectionTarget]:
        w, h = image_size
        lm = hand.landmark_array()
        out: list[ProjectionTarget] = []
        conf = hand.tracking_quality
        if "hand_centroid" in self.cfg.anchors:
            c = lm[:, :2].mean(axis=0)
            out.append(self._target(AnchorType.HAND_CENTROID, f"{hand.side.value}:hand_centroid", hand.side, (float(c[0] * w), float(c[1] * h)), ts, conf, image_size))
        if "fingertips" in self.cfg.anchors:
            for i in FINGERTIPS:
                out.append(self._target(AnchorType.LANDMARK, f"{hand.side.value}:lm{i}", hand.side, (float(lm[i, 0] * w), float(lm[i, 1] * h)), ts, conf, image_size))
        if "regions" in self.cfg.anchors:
            geo = compute_geometry(hand)
            for region in Region:
                a = geo.anchor(region)
                out.append(self._target(AnchorType.REGION_CENTROID, f"{hand.side.value}:{region.value}", hand.side,
                                        None if a is None else (float(a[0] * w), float(a[1] * h)), ts, conf * geo.polygons[region].support, image_size))
        return out

    def map_landmark(self, hand: HandObservation, index: int, ts: float, image_size: tuple[int, int]) -> ProjectionTarget:
        w, h = image_size
        lm = hand.landmarks[index]
        return self._target(AnchorType.LANDMARK, f"{hand.side.value}:lm{index}", hand.side, (lm.x * w, lm.y * h), ts, hand.tracking_quality, image_size)
