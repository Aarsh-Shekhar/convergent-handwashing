"""Shared, validated data structures exchanged between every module.

Coordinate systems
------------------
* **Image (camera) pixel space** – origin at the top-left of the *processing* frame
  (after any configured resize/rotation), x to the right, y down, units: pixels.
  ``FramePacket.width``/``height`` give the processing-frame size; ``FramePacket.transform``
  records how to map back to the original capture resolution.
* **Normalized image space** – MediaPipe landmark convention: x, y in ``[0, 1]`` relative to
  processing-frame width/height. ``z`` is a *relative* depth estimate with the wrist as
  origin and roughly the same scale as x; it is **not** a calibrated metric depth.
* **Projector logical space** – an ``854 x 480`` canvas (RIF6 native). Origin top-left,
  pixels. The negotiated HDMI mode on hardware may differ and is handled by the Pi renderer.

Timestamp semantics
-------------------
All timestamps are ``float`` seconds. Three clocks are kept apart on purpose:

* ``capture_ts`` – when the frame was captured, on the *source's* clock. For a Pi this is
  the device monotonic clock (``time.monotonic()`` on the Pi); for a video file it is the
  decoded presentation timestamp (PTS) relative to the first frame; for a webcam it is the
  laptop monotonic clock at read time.
* ``arrival_ts`` – laptop monotonic clock when the frame entered the pipeline.
* ``processed_ts`` – laptop monotonic clock when processing finished (filled late).

``capture_ts`` is the only clock used for temporal reasoning (durations, windows, events).
UTC wall-clock time is recorded once per session (``Session.started_at_utc``) and by the
backend; it is never used to measure gesture durations.
"""

from __future__ import annotations

import hashlib
import uuid
from enum import StrEnum
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0.0"
NUM_HAND_LANDMARKS = 21
PROJECTOR_LOGICAL_WIDTH = 854
PROJECTOR_LOGICAL_HEIGHT = 480


# --------------------------------------------------------------------------- enums
class ColorFormat(StrEnum):
    BGR = "bgr"
    RGB = "rgb"
    GRAY = "gray"
    JPEG = "jpeg"  # encoded payload (transport only)


class HandSide(StrEnum):
    """Anatomical side. ``UNRESOLVED`` is used for model labels whose side semantics are not
    verified; ``BOTH`` for symmetric two-hand techniques; ``UNKNOWN`` when not determinable."""

    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    UNRESOLVED = "unresolved"
    UNKNOWN = "unknown"


class VisibilityState(StrEnum):
    VISIBLE = "visible"
    PARTIAL = "partial"  # some landmarks outside the frame or low presence score
    OCCLUDED = "occluded"  # tracked but mostly hidden (e.g. covered by the other hand)
    MISSING = "missing"  # explicitly not observed in this frame


class PredictionStatus(StrEnum):
    VALID = "valid"
    UNKNOWN = "unknown"  # model ran but rejected its own output (low confidence / no-step)
    NO_INPUT = "no_input"  # not enough input (e.g. no hands, sequence not full)
    MODEL_UNAVAILABLE = "model_unavailable"  # artifact missing/unloadable – branch did not run
    ERROR = "error"


class ValidationStatus(StrEnum):
    CANDIDATE = "candidate"  # gesture entered, not yet long enough
    VALIDATED = "validated"  # satisfied duration + confidence + tracking requirements
    REJECTED = "rejected"  # ended before validation
    ABORTED = "aborted"  # tracking lost / contradiction while candidate


class EvidenceStatus(StrEnum):
    UNKNOWN = "unknown"  # never observed / not determinable
    INSUFFICIENT = "insufficient"  # some evidence, below configured minimum
    PARTIAL = "partial"  # evidence present but visibility/side uncertainty
    SUFFICIENT = "sufficient"  # configured minimum evidence reached (NOT a cleanliness claim)


class AnchorType(StrEnum):
    LANDMARK = "landmark"
    HAND_CENTROID = "hand_centroid"
    REGION_CENTROID = "region_centroid"
    FIXED_POINT = "fixed_point"
    CALIBRATION_MARKER = "calibration_marker"


class Region(StrEnum):
    PALM = "palm"
    BACK_OF_HAND = "back_of_hand"
    THUMB = "thumb"
    FINGERS = "fingers"  # fingers / interdigital area
    FINGERTIPS = "fingertips"


# --------------------------------------------------------------------------- helpers
def new_id(prefix: str = "") -> str:
    value = uuid.uuid4().hex
    return f"{prefix}{value}" if prefix else value


def stable_hash(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


class StrictModel(BaseModel):
    """Base model: extra fields are rejected so wire-format drift is caught early."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------- frames
class ImageTransform(StrictModel):
    """Maps processing-frame pixels back to original capture pixels.

    ``orig = (proc + offset) / scale`` after undoing ``rotation_deg`` (multiple of 90).
    """

    original_width: int = Field(gt=0)
    original_height: int = Field(gt=0)
    scale_x: float = Field(gt=0, default=1.0)
    scale_y: float = Field(gt=0, default=1.0)
    crop_x: int = Field(ge=0, default=0)
    crop_y: int = Field(ge=0, default=0)
    rotation_deg: int = 0
    mirrored: bool = False  # True ONLY if the source explicitly produced a mirrored image

    @field_validator("rotation_deg")
    @classmethod
    def _rot(cls, v: int) -> int:
        if v % 90 != 0:
            raise ValueError("rotation_deg must be a multiple of 90")
        return v % 360


class FrameTimestamps(StrictModel):
    capture_ts: float = Field(description="seconds on the source clock (see module docstring)")
    arrival_ts: float | None = Field(default=None, description="laptop monotonic seconds")
    processed_ts: float | None = Field(default=None, description="laptop monotonic seconds")
    capture_clock: str = Field(
        default="source_monotonic",
        description="'source_monotonic' | 'video_pts' | 'laptop_monotonic' | 'synthetic'",
    )

    @model_validator(mode="after")
    def _order(self) -> FrameTimestamps:
        if (
            self.arrival_ts is not None
            and self.processed_ts is not None
            and self.processed_ts < self.arrival_ts
        ):
            raise ValueError("processed_ts cannot precede arrival_ts")
        return self


class FramePacket(StrictModel):
    """Metadata for one frame. The pixel data lives in ``image`` (excluded from serialization).

    ``frame_id`` is a per-session monotonically increasing sequence number assigned by the
    source. ``source_frame_index`` is the source's own index (decoder index / device counter).
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    frame_id: int = Field(ge=0)
    session_id: str = Field(min_length=1)
    timestamps: FrameTimestamps
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    color_format: ColorFormat = ColorFormat.BGR
    source_id: str = Field(min_length=1)
    source_frame_index: int | None = None
    transform: ImageTransform
    metadata: dict[str, Any] = Field(default_factory=dict)
    image: np.ndarray | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def _image_matches(self) -> FramePacket:
        if self.image is not None:
            if self.image.ndim not in (2, 3):
                raise ValueError("image must be HxW or HxWxC")
            h, w = self.image.shape[:2]
            if (w, h) != (self.width, self.height):
                raise ValueError(
                    f"image shape {w}x{h} does not match declared {self.width}x{self.height}"
                )
        return self

    @property
    def capture_ts(self) -> float:
        return self.timestamps.capture_ts

    def without_image(self) -> FramePacket:
        return self.model_copy(update={"image": None})


# --------------------------------------------------------------------------- hands
class Landmark(StrictModel):
    x: float
    y: float
    z: float = 0.0


class BoundingBox(StrictModel):
    """Normalized [0,1] box in processing-frame coordinates."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @model_validator(mode="after")
    def _ordered(self) -> BoundingBox:
        if self.x_max < self.x_min or self.y_max < self.y_min:
            raise ValueError("bounding box max must be >= min")
        return self

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0)


class HandObservation(StrictModel):
    """One tracked hand in one frame.

    ``side`` is the *anatomical* side after the configured handedness resolution.
    ``raw_handedness_label`` is MediaPipe's label before any swap; adapters that must
    reproduce an upstream model's training convention use it (see ``vision.hand_tracker``).
    """

    track_id: int = Field(ge=0)
    side: HandSide
    handedness_confidence: float = Field(ge=0.0, le=1.0)
    raw_handedness_label: str = Field(default="", description="MediaPipe label as returned")
    landmarks: list[Landmark] = Field(min_length=NUM_HAND_LANDMARKS, max_length=NUM_HAND_LANDMARKS)
    world_landmarks: list[Landmark] | None = None
    bbox: BoundingBox
    tracking_quality: float = Field(ge=0.0, le=1.0, description="0..1 composite quality score")
    visibility: VisibilityState = VisibilityState.VISIBLE
    presence_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("world_landmarks")
    @classmethod
    def _world_len(cls, v: list[Landmark] | None) -> list[Landmark] | None:
        if v is not None and len(v) != NUM_HAND_LANDMARKS:
            raise ValueError("world_landmarks must have 21 entries")
        return v

    @field_validator("side")
    @classmethod
    def _single_side(cls, v: HandSide) -> HandSide:
        if v not in (HandSide.LEFT, HandSide.RIGHT, HandSide.UNKNOWN):
            raise ValueError("a HandObservation side must be left, right or unknown")
        return v

    def landmark_array(self) -> np.ndarray:
        """(21, 3) float64 array of normalized landmarks in MediaPipe order."""
        return np.array([[lm.x, lm.y, lm.z] for lm in self.landmarks], dtype=np.float64)

    @classmethod
    def from_array(cls, arr: np.ndarray, **kwargs: Any) -> HandObservation:
        arr = np.asarray(arr, dtype=np.float64)
        if arr.shape != (NUM_HAND_LANDMARKS, 3):
            raise ValueError(f"expected (21,3) landmarks, got {arr.shape}")
        lms = [Landmark(x=float(r[0]), y=float(r[1]), z=float(r[2])) for r in arr]
        kwargs.setdefault(
            "bbox",
            BoundingBox(
                x_min=float(arr[:, 0].min()),
                y_min=float(arr[:, 1].min()),
                x_max=float(arr[:, 0].max()),
                y_max=float(arr[:, 1].max()),
            ),
        )
        return cls(landmarks=lms, **kwargs)


class TrackedHands(StrictModel):
    """Shared tracker output for one frame. Missing hands are explicit ``None``s."""

    frame_id: int
    capture_ts: float
    left: HandObservation | None = None
    right: HandObservation | None = None
    unassigned: list[HandObservation] = Field(default_factory=list)
    tracker_id: str = "mediapipe"
    tracker_version: str = ""
    processing_time_ms: float = 0.0

    @model_validator(mode="after")
    def _sides(self) -> TrackedHands:
        if self.left is not None and self.left.side != HandSide.LEFT:
            raise ValueError("left slot must hold a LEFT hand")
        if self.right is not None and self.right.side != HandSide.RIGHT:
            raise ValueError("right slot must hold a RIGHT hand")
        return self

    @property
    def hands(self) -> list[HandObservation]:
        return [h for h in (self.left, self.right) if h is not None]

    @property
    def num_hands(self) -> int:
        return len(self.hands)

    def get(self, side: HandSide) -> HandObservation | None:
        return self.left if side == HandSide.LEFT else self.right if side == HandSide.RIGHT else None

    def by_raw_label(self, label: str) -> HandObservation | None:
        for h in self.hands:
            if h.raw_handedness_label == label:
                return h
        return None


# --------------------------------------------------------------------------- predictions
class CanonicalLabel(StrictModel):
    """Canonical technique + side. ``resolved`` is False when the upstream class semantics
    (usually which side is acted upon) have not been verified against source material."""

    technique: str
    side: HandSide = HandSide.UNKNOWN
    resolved: bool = True

    @property
    def key(self) -> str:
        return f"{self.side.value}_{self.technique}" if self.side in (HandSide.LEFT, HandSide.RIGHT) else self.technique


class ModelPrediction(StrictModel):
    model_id: str
    model_version: str
    window_start_ts: float
    window_end_ts: float
    frame_ids: list[int] = Field(default_factory=list)
    native_label: str | None = None
    native_index: int | None = None
    canonical: CanonicalLabel | None = None
    probabilities: dict[str, float] | None = Field(
        default=None, description="native label -> probability (as produced by the model)"
    )
    canonical_probabilities: dict[str, float] | None = Field(
        default=None, description="canonical key -> probability after mapping (unnormalized sum ok)"
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    calibrated: bool = False
    processing_time_ms: float = 0.0
    status: PredictionStatus = PredictionStatus.VALID
    message: str = ""
    extras: dict[str, Any] = Field(default_factory=dict, description="model-specific debug data (e.g. boxes)")

    @model_validator(mode="after")
    def _window(self) -> ModelPrediction:
        if self.window_end_ts < self.window_start_ts:
            raise ValueError("window_end_ts must be >= window_start_ts")
        if self.status == PredictionStatus.VALID and self.canonical is None:
            raise ValueError("VALID predictions must carry a canonical label")
        return self

    @property
    def is_valid(self) -> bool:
        return self.status == PredictionStatus.VALID


class PredictionRef(StrictModel):
    model_id: str
    model_version: str
    window_start_ts: float
    window_end_ts: float
    canonical_key: str | None
    confidence: float | None


class GestureEvent(StrictModel):
    event_id: str = Field(default_factory=lambda: new_id("evt_"))
    session_id: str
    technique: str
    side: HandSide
    start_ts: float
    end_ts: float
    validated_duration_s: float = Field(ge=0.0)
    supporting_predictions: list[PredictionRef] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    quality: float = Field(ge=0.0, le=1.0, default=1.0)
    validation_status: ValidationStatus
    side_resolved: bool = True
    tracking_gaps_s: float = 0.0
    sequence_no: int = 0

    @model_validator(mode="after")
    def _times(self) -> GestureEvent:
        if self.end_ts < self.start_ts:
            raise ValueError("end_ts must be >= start_ts")
        if self.validated_duration_s > (self.end_ts - self.start_ts) + 1e-9:
            raise ValueError("validated_duration_s cannot exceed the event span")
        return self

    @property
    def dedupe_key(self) -> str:
        return stable_hash(self.session_id, self.technique, self.side.value, round(self.start_ts, 3))


class RegionEvidence(StrictModel):
    region: Region
    side: HandSide
    supporting_events: list[str] = Field(default_factory=list)
    supporting_techniques: list[str] = Field(default_factory=list)
    visibility: VisibilityState = VisibilityState.MISSING
    observed_duration_s: float = Field(ge=0.0, default=0.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    status: EvidenceStatus = EvidenceStatus.UNKNOWN
    first_ts: float | None = None
    last_ts: float | None = None

    @field_validator("side")
    @classmethod
    def _side(cls, v: HandSide) -> HandSide:
        if v not in (HandSide.LEFT, HandSide.RIGHT):
            raise ValueError("region evidence is tracked per anatomical hand (left/right)")
        return v


# --------------------------------------------------------------------------- projection
class CameraIntrinsics(StrictModel):
    fx: float
    fy: float
    cx: float
    cy: float
    distortion: list[float] = Field(default_factory=list)
    image_width: int
    image_height: int
    rms_reprojection_error: float | None = None

    def matrix(self) -> np.ndarray:
        return np.array([[self.fx, 0, self.cx], [0, self.fy, self.cy], [0, 0, 1]], dtype=np.float64)


class CalibrationProfile(StrictModel):
    profile_id: str = Field(default_factory=lambda: new_id("cal_"))
    version: int = Field(ge=1, default=1)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    image_rotation_deg: int = 0
    image_mirrored: bool = False
    crop: tuple[int, int, int, int] | None = Field(
        default=None, description="(x, y, w, h) crop applied to the capture before processing"
    )
    projector_width: int = Field(gt=0, default=PROJECTOR_LOGICAL_WIDTH)
    projector_height: int = Field(gt=0, default=PROJECTOR_LOGICAL_HEIGHT)
    intrinsics: CameraIntrinsics | None = None
    camera_to_projector: list[list[float]] = Field(
        description="3x3 planar homography camera px -> projector px"
    )
    calibration_plane_id: str = Field(default="sink_plane", min_length=1)
    inlier_count: int = Field(ge=0, default=0)
    total_correspondences: int = Field(ge=0, default=0)
    reprojection_rmse_px: float | None = Field(default=None, ge=0.0)
    max_reprojection_error_px: float | None = Field(default=None, ge=0.0)
    created_at_utc: str = ""
    valid: bool = True
    invalidation_reason: str = ""
    method: str = "homography_ransac"
    notes: str = ""

    @field_validator("camera_to_projector")
    @classmethod
    def _h(cls, v: list[list[float]]) -> list[list[float]]:
        arr = np.asarray(v, dtype=np.float64)
        if arr.shape != (3, 3):
            raise ValueError("camera_to_projector must be 3x3")
        if not np.all(np.isfinite(arr)):
            raise ValueError("homography contains non-finite values")
        if abs(np.linalg.det(arr)) < 1e-12:
            raise ValueError("homography is singular")
        return [[float(x) for x in row] for row in arr]

    def homography(self) -> np.ndarray:
        return np.asarray(self.camera_to_projector, dtype=np.float64)


class ProjectionTarget(StrictModel):
    anchor_type: AnchorType
    anchor_id: str
    side: HandSide = HandSide.UNKNOWN
    camera_xy: tuple[float, float] | None
    projector_xy: tuple[float, float] | None
    confidence: float = Field(ge=0.0, le=1.0)
    valid: bool
    reason: str = ""
    timestamp: float
    calibration_profile_id: str | None = None
    calibration_version: int | None = None


# --------------------------------------------------------------------------- session-level
class SessionInfo(StrictModel):
    session_id: str = Field(default_factory=lambda: new_id("ses_"))
    device_id: str = "laptop-dev"
    source_id: str
    started_at_utc: str
    ended_at_utc: str | None = None
    width: int
    height: int
    target_fps: float
    processing_config: dict[str, Any] = Field(default_factory=dict)
    recording_enabled: bool = False
    recording_path: str | None = None
    schema_version: str = SCHEMA_VERSION
