"""Shared two-hand MediaPipe tracking.

One tracker instance processes every frame exactly once; all classifier adapters consume
its :class:`TrackedHands` output. Two MediaPipe backends are supported:

* ``tasks`` – the modern Hand Landmarker (``mediapipe.tasks``), VIDEO running mode. Needs the
  ``hand_landmarker.task`` asset (``make models`` downloads it; it is not bundled).
* ``solutions`` – the legacy ``mp.solutions.hands`` graph, bundled with the wheel. This is
  the interface both upstream landmark models (HandHygiene, S-Kia) were trained with, so it
  is also the *compatibility* backend. Landmark ordering/normalization are identical between
  the two backends; only the handedness/presence scoring differs slightly.

Image orientation
-----------------
Frames are processed exactly as the source delivers them (after the configured 90° rotation
in preprocessing). **Nothing flips horizontally.** MediaPipe's handedness label assumes a
mirrored (selfie) image; for our non-mirrored faucet camera ``swap_handedness=True`` turns
the raw label into the anatomical side. Both the raw label and the anatomical side are kept
on every :class:`HandObservation`.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from convergent.common.config import TrackerConfig, resolve_path
from convergent.common.logging import get_logger
from convergent.common.types import (
    NUM_HAND_LANDMARKS,
    BoundingBox,
    FramePacket,
    HandObservation,
    HandSide,
    Landmark,
    TrackedHands,
    VisibilityState,
)
from convergent.vision.hand_identity import HandIdentityResolver, RawHandDetection, ResolvedHand

log = get_logger(__name__)


class TrackerError(RuntimeError):
    pass


def swap_label(label: str) -> str:
    return {"Left": "Right", "Right": "Left"}.get(label, label)


def label_to_side(label: str) -> HandSide:
    return {"Left": HandSide.LEFT, "Right": HandSide.RIGHT}.get(label, HandSide.UNKNOWN)


# --------------------------------------------------------------------------- backends
class LandmarkBackend(ABC):
    name: str = "abstract"
    version: str = ""

    @abstractmethod
    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> list[tuple[np.ndarray, np.ndarray | None, str, float, float | None]]:
        """Return list of (landmarks(21,3), world(21,3)|None, raw_label, handedness_score, presence|None)."""

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class NullBackend(LandmarkBackend):
    """Never detects anything. Used when MediaPipe is unavailable or for plumbing tests."""

    name = "null"

    def detect(self, rgb: np.ndarray, timestamp_ms: int):  # type: ignore[override]
        return []


class ScriptedBackend(LandmarkBackend):
    """Test backend: returns pre-scripted detections keyed by call index."""

    name = "scripted"

    def __init__(self, script: list[list[tuple[np.ndarray, str, float]]]) -> None:
        self.script = script
        self.calls = 0

    def detect(self, rgb: np.ndarray, timestamp_ms: int):  # type: ignore[override]
        idx = min(self.calls, len(self.script) - 1) if self.script else 0
        self.calls += 1
        if not self.script:
            return []
        return [(np.asarray(lm, dtype=np.float64), None, label, score, None) for lm, label, score in self.script[idx]]


class SolutionsBackend(LandmarkBackend):
    name = "mediapipe.solutions.hands"

    def __init__(self, cfg: TrackerConfig) -> None:
        import mediapipe as mp

        self.version = getattr(mp, "__version__", "")
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=cfg.num_hands,
            model_complexity=cfg.model_complexity,
            min_detection_confidence=cfg.min_detection_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )

    def detect(self, rgb: np.ndarray, timestamp_ms: int):  # type: ignore[override]
        res = self._hands.process(rgb)
        out = []
        if not res.multi_hand_landmarks:
            return out
        world = res.multi_hand_world_landmarks or [None] * len(res.multi_hand_landmarks)
        for lms, handed, wl in zip(res.multi_hand_landmarks, res.multi_handedness, world, strict=False):
            arr = np.array([[p.x, p.y, p.z] for p in lms.landmark], dtype=np.float64)
            warr = None if wl is None else np.array([[p.x, p.y, p.z] for p in wl.landmark], dtype=np.float64)
            c = handed.classification[0]
            out.append((arr, warr, str(c.label), float(c.score), None))
        return out

    def close(self) -> None:
        self._hands.close()


class TasksBackend(LandmarkBackend):
    name = "mediapipe.tasks.HandLandmarker"

    def __init__(self, cfg: TrackerConfig) -> None:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        path = resolve_path(cfg.task_model_path)
        if not path.exists():
            raise TrackerError(f"hand_landmarker.task not found at {path} (run `make models`)")
        self.version = getattr(mp, "__version__", "")
        self._mp = mp
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=cfg.num_hands,
            min_hand_detection_confidence=cfg.min_detection_confidence,
            min_hand_presence_confidence=cfg.min_presence_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )
        self._lm = vision.HandLandmarker.create_from_options(options)
        self._last_ts_ms = -1

    def detect(self, rgb: np.ndarray, timestamp_ms: int):  # type: ignore[override]
        if timestamp_ms <= self._last_ts_ms:
            timestamp_ms = self._last_ts_ms + 1  # VIDEO mode requires strictly increasing timestamps
        self._last_ts_ms = timestamp_ms
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self._lm.detect_for_video(image, timestamp_ms)
        out = []
        for lms, wl, handed in zip(res.hand_landmarks, res.hand_world_landmarks, res.handedness, strict=False):
            arr = np.array([[p.x, p.y, p.z] for p in lms], dtype=np.float64)
            warr = np.array([[p.x, p.y, p.z] for p in wl], dtype=np.float64)
            c = handed[0]
            out.append((arr, warr, str(c.category_name), float(c.score), None))
        return out

    def close(self) -> None:
        self._lm.close()


def create_backend(cfg: TrackerConfig) -> LandmarkBackend:
    if cfg.backend == "null":
        return NullBackend()
    if cfg.backend == "tasks":
        return TasksBackend(cfg)
    if cfg.backend == "solutions":
        return SolutionsBackend(cfg)
    # auto: prefer tasks when the asset exists, else legacy solutions (bundled)
    if Path(resolve_path(cfg.task_model_path)).exists():
        try:
            return TasksBackend(cfg)
        except Exception as exc:  # noqa: BLE001 - we fall back deliberately and log it
            log.warning("tasks backend unavailable (%s); falling back to solutions", exc)
    try:
        return SolutionsBackend(cfg)
    except Exception as exc:  # noqa: BLE001
        raise TrackerError(f"no MediaPipe backend available: {exc}") from exc


# --------------------------------------------------------------------------- tracker
class HandTracker:
    def __init__(self, cfg: TrackerConfig | None = None, backend: LandmarkBackend | None = None) -> None:
        self.cfg = cfg or TrackerConfig()
        self.backend = backend or create_backend(self.cfg)
        self.identity = HandIdentityResolver(
            max_jump=self.cfg.identity_max_jump,
            max_gap_s=self.cfg.identity_max_gap_s,
            handedness_trust_threshold=self.cfg.handedness_trust_threshold,
        )
        self.frames_processed = 0

    @property
    def tracker_id(self) -> str:
        return self.backend.name

    def reset(self) -> None:
        self.identity.reset()

    def close(self) -> None:
        self.backend.close()

    def detect(self, frame: FramePacket) -> TrackedHands:
        if frame.image is None:
            raise TrackerError("frame has no image data")
        t0 = time.perf_counter()
        rgb = frame.image[..., ::-1] if frame.color_format.value == "bgr" else frame.image
        raw = self.backend.detect(np.ascontiguousarray(rgb), int(round(frame.capture_ts * 1000)))
        detections = []
        for lm, wl, label, score, presence in raw:
            if lm.shape != (NUM_HAND_LANDMARKS, 3):
                log.warning("backend returned malformed landmarks %s; skipping hand", lm.shape)
                continue
            anat = label_to_side(swap_label(label) if self.cfg.swap_handedness else label)
            detections.append(RawHandDetection(lm, label, float(np.clip(score, 0, 1)), anat, wl, presence))
        resolved = self.identity.update(detections, frame.capture_ts)
        self.frames_processed += 1
        return self._to_tracked(frame, resolved, (time.perf_counter() - t0) * 1000.0)

    # ---- conversion
    def _to_tracked(self, frame: FramePacket, resolved: list[ResolvedHand], ms: float) -> TrackedHands:
        left = right = None
        unassigned: list[HandObservation] = []
        others = [r for r in resolved]
        for r in resolved:
            obs = self._observation(r, others)
            if r.side == HandSide.LEFT and left is None:
                left = obs
            elif r.side == HandSide.RIGHT and right is None:
                right = obs
            else:
                unassigned.append(obs.model_copy(update={"side": HandSide.UNKNOWN}))
        return TrackedHands(
            frame_id=frame.frame_id,
            capture_ts=frame.capture_ts,
            left=left,
            right=right,
            unassigned=unassigned,
            tracker_id=self.backend.name,
            tracker_version=self.backend.version,
            processing_time_ms=ms,
        )

    def _observation(self, r: ResolvedHand, all_hands: list[ResolvedHand]) -> HandObservation:
        det = r.detection
        lm = det.landmarks
        m = self.cfg.partial_visibility_margin
        inside = np.mean((lm[:, 0] >= -m) & (lm[:, 0] <= 1 + m) & (lm[:, 1] >= -m) & (lm[:, 1] <= 1 + m))
        bbox = BoundingBox(
            x_min=float(np.clip(lm[:, 0].min(), 0, 1)),
            y_min=float(np.clip(lm[:, 1].min(), 0, 1)),
            x_max=float(np.clip(lm[:, 0].max(), 0, 1)),
            y_max=float(np.clip(lm[:, 1].max(), 0, 1)),
        )
        overlap = 0.0
        for o in all_hands:
            if o is r:
                continue
            overlap = max(overlap, _iou(lm, o.detection.landmarks))
        presence = det.presence_score if det.presence_score is not None else det.handedness_score
        if inside < 0.6:
            vis = VisibilityState.PARTIAL
        elif overlap > 0.6 and presence < 0.7:
            vis = VisibilityState.OCCLUDED
        elif inside < 1.0:
            vis = VisibilityState.PARTIAL
        else:
            vis = VisibilityState.VISIBLE
        age_factor = min(1.0, r.track_age / 5.0)
        quality = float(np.clip(0.4 * presence + 0.3 * inside + 0.2 * age_factor + 0.1 * (1.0 - overlap), 0, 1))
        side = r.side if r.side in (HandSide.LEFT, HandSide.RIGHT) else HandSide.UNKNOWN
        return HandObservation(
            track_id=r.track_id,
            side=side,
            handedness_confidence=float(np.clip(det.handedness_score, 0, 1)),
            raw_handedness_label=det.raw_label,
            landmarks=[Landmark(x=float(p[0]), y=float(p[1]), z=float(p[2])) for p in lm],
            world_landmarks=None
            if det.world_landmarks is None
            else [Landmark(x=float(p[0]), y=float(p[1]), z=float(p[2])) for p in det.world_landmarks],
            bbox=bbox,
            tracking_quality=quality,
            visibility=vis,
            presence_confidence=None if det.presence_score is None else float(np.clip(det.presence_score, 0, 1)),
        )


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    ax0, ay0, ax1, ay1 = a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()
    bx0, by0, bx1, by1 = b[:, 0].min(), b[:, 1].min(), b[:, 0].max(), b[:, 1].max()
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return float(inter / union) if union > 0 else 0.0
