"""HandHygiene (juannquinones/HandHygiene) spatial branch adapter.

What is reused (re-implemented from ``app/HandHygieneMain.py`` / ``app/video_thread.py``):

* centroid-relative normalization per hand (``get_normalized_rows``),
* the 126-feature layout: **right hand (21x3) followed by left hand (21x3)**, row-major
  ``[x0,y0,z0, x1,y1,z1, ...]``; a missing hand is all zeros (``np.zeros([21,3])``),
* scikit-learn ``Pipeline(StandardScaler -> {RF,LR,SVM})`` artifacts with ``classes_ = 1..10``
  (see configs/labels.yaml for the class semantics),
* the upstream ``predict_proba`` + ``max(prob) < 0.4 -> "no step"`` rejection, which we expose
  as :attr:`PredictionStatus.UNKNOWN` instead of a fake class,
* (optional, off by default) the 15-frame majority vote buffer – temporal validation is
  handled downstream instead.

What is fixed:

* hand identity: the upstream two-hand path assigned ``multi_hand_landmarks[0]`` to the right
  slot regardless of handedness. We fill slots from the handedness label (``feed_mode``
  ``raw_label`` reproduces the single-hand upstream convention; ``anatomical`` uses the
  resolved anatomical side).
* ``verify_hand_rows`` required *every* coordinate of a hand to be non-zero; we use the
  tracker's explicit missing-hand representation (a hand is present or it is ``None``).
* the full probability distribution is exposed, not only the winning class.

Compatibility caveat (recorded in IMPLEMENTATION_STATUS.md): because the upstream training
CSV was produced with the order-based assignment bug in two-hand frames, the pretrained
artifacts' behaviour with *correct* identity handling is unverified. The training script
``scripts/train_handhygiene.py`` reproduces the upstream training recipe on correctly
extracted features once source videos are available.
"""

from __future__ import annotations

from collections import Counter, deque

import numpy as np

from convergent.common.config import HandHygieneConfig, resolve_path
from convergent.common.logging import get_logger
from convergent.common.types import (
    HandObservation,
    HandSide,
    ModelPrediction,
    PredictionStatus,
    TrackedHands,
)
from convergent.detection.base import (
    ArtifactError,
    ArtifactStatus,
    Classifier,
    Stopwatch,
    safe_load_pickle,
    sha256_of,
    valid_prediction,
)
from convergent.detection.labels import LabelRegistry, ModelLabelMap, default_registry

log = get_logger(__name__)

HANDHYGIENE_NUM_FEATURES = 126
PREPROCESSING_VERSION = "handhygiene-centroid-v1"


# --------------------------------------------------------------------------- preprocessing
def centroid_normalize(hand_rows: np.ndarray) -> np.ndarray:
    """Upstream ``get_normalized_rows``: subtract the (x,y,z) centroid of the 21 landmarks."""
    arr = np.asarray(hand_rows, dtype=np.float64)
    if arr.shape != (21, 3):
        raise ValueError(f"expected (21,3), got {arr.shape}")
    return arr - arr.mean(axis=0)


def handhygiene_feature_vector(right: np.ndarray | None, left: np.ndarray | None) -> np.ndarray:
    """Build the 126-vector exactly as upstream: right-hand block then left-hand block.

    ``None`` means the hand is missing and yields an all-zero block (upstream used
    ``np.zeros([21,3])`` whose centroid normalization is still zeros).
    """
    if right is None and left is None:
        raise ValueError("at least one hand is required")
    r = np.zeros((21, 3)) if right is None else centroid_normalize(right)
    lft = np.zeros((21, 3)) if left is None else centroid_normalize(left)
    return np.concatenate([r, lft], axis=0).reshape(HANDHYGIENE_NUM_FEATURES)


def select_hands(hands: TrackedHands, feed_mode: str) -> tuple[HandObservation | None, HandObservation | None]:
    """Return (right_slot, left_slot) according to the feed mode."""
    if feed_mode == "anatomical":
        return hands.right, hands.left
    # raw_label: slots follow MediaPipe's label, the convention upstream used for single hands
    return hands.by_raw_label("Right"), hands.by_raw_label("Left")


# --------------------------------------------------------------------------- adapter
class HandHygieneAdapter(Classifier):
    model_id = "handhygiene"
    preprocessing_version = PREPROCESSING_VERSION

    def __init__(self, cfg: HandHygieneConfig | None = None, registry: LabelRegistry | None = None) -> None:
        self.cfg = cfg or HandHygieneConfig()
        self.registry = registry or default_registry()
        self.label_map: ModelLabelMap = self.registry.model_map("handhygiene")
        self._model = None
        self._status = ArtifactStatus(self.model_id, False, message="not loaded")
        self._class_to_native: dict[int, str] = {}
        self._votes: deque[int] = deque(maxlen=max(1, self.cfg.legacy_vote_buffer or 1))
        self.model_version = "unloaded"

    # ---- artifact
    def load(self) -> ArtifactStatus:
        path = resolve_path(self.cfg.model_path)
        if not self.cfg.enabled:
            self._status = ArtifactStatus(self.model_id, False, str(path), message="disabled by config")
            return self._status
        if not path.exists():
            self._status = ArtifactStatus(self.model_id, False, str(path), message=f"MODEL_UNAVAILABLE: {path} not found (run `make models`)")
            return self._status
        try:
            digest = sha256_of(path)
            if self.cfg.sha256 and digest != self.cfg.sha256:
                raise ArtifactError(f"sha256 mismatch for {path}: {digest} != {self.cfg.sha256}")
            if path.suffix == ".npz":
                from convergent.detection.numpy_forest import NumpyForestPipeline

                model = NumpyForestPipeline.load(path)  # validated conversion, NumPy only
            else:
                model = safe_load_pickle(path)
            self._validate_model(model)
        except (ArtifactError, Exception) as exc:  # noqa: BLE001 - reported, never swallowed silently
            log.error("handhygiene artifact unusable: %s", exc)
            self._status = ArtifactStatus(self.model_id, False, str(path), message=f"MODEL_UNAVAILABLE: {exc}")
            self._model = None
            return self._status
        self._model = model
        self.model_version = path.stem
        self._status = ArtifactStatus(self.model_id, True, str(path), self.model_version, digest,
                                      "loaded", PREPROCESSING_VERSION,
                                      {"estimator": type(model).__name__, "classes": sorted(self._class_to_native),
                                       "conversion": getattr(model, "meta", {})})
        return self._status

    def _validate_model(self, model: object) -> None:
        if not hasattr(model, "predict_proba"):
            raise ArtifactError("artifact has no predict_proba (SVC without probability=True?)")
        n_in = getattr(model, "n_features_in_", None)
        if n_in is not None and int(n_in) != HANDHYGIENE_NUM_FEATURES:
            raise ArtifactError(f"artifact expects {n_in} features, adapter produces {HANDHYGIENE_NUM_FEATURES}")
        classes = getattr(model, "classes_", None)
        if classes is None:
            raise ArtifactError("artifact has no classes_")
        mapping: dict[int, str] = {}
        for c in classes:
            try:
                idx = int(round(float(c)))
            except (TypeError, ValueError) as exc:
                raise ArtifactError(f"unsupported class label {c!r}") from exc
            if abs(float(c) - idx) > 1e-9 or idx < 1 or idx > len(self.label_map.native_order):
                raise ArtifactError(f"class label {c!r} outside the documented 1..{len(self.label_map.native_order)} range")
            mapping[idx] = self.label_map.native_for_index(idx - 1)
        if len(mapping) != len(self.label_map.native_order):
            raise ArtifactError(f"artifact has {len(mapping)} classes, expected {len(self.label_map.native_order)}")
        self._class_to_native = mapping

    @property
    def available(self) -> bool:
        return self._model is not None

    def status(self) -> ArtifactStatus:
        return self._status

    # ---- inference
    def predict(self, hands: TrackedHands) -> ModelPrediction:
        ts = hands.capture_ts
        if not self.available:
            return self.unavailable_prediction(ts)
        right, left = select_hands(hands, self.cfg.feed_mode)
        if right is None and left is None:
            return self.no_input_prediction(ts, "no hands")
        try:
            with Stopwatch() as sw:
                x = handhygiene_feature_vector(None if right is None else right.landmark_array(),
                                               None if left is None else left.landmark_array())
                proba = np.asarray(self._model.predict_proba(x.reshape(1, -1))[0], dtype=np.float64)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            log.exception("handhygiene inference failed")
            return self.error_prediction(ts, f"inference error: {exc}")
        classes = [int(round(float(c))) for c in self._model.classes_]  # type: ignore[union-attr]
        probs = {self._class_to_native[c]: float(p) for c, p in zip(classes, proba, strict=True)}
        best_i = int(np.argmax(proba))
        best_p = float(proba[best_i])
        if best_p < self.cfg.unknown_threshold:
            return self.unknown_prediction(ts, ts, probs, [hands.frame_id], sw.ms,
                                           f"max prob {best_p:.2f} < {self.cfg.unknown_threshold} (upstream 'no step')")
        native = self._class_to_native[classes[best_i]]
        if self.cfg.legacy_vote_buffer > 1:
            self._votes.append(classes[best_i])
            native = self._class_to_native[Counter(self._votes).most_common(1)[0][0]]
        canonical = self.label_map.canonical_for(native)
        canon_probs: dict[str, float] = {}
        for n, p in probs.items():
            k = self.label_map.canonical_for(n).key
            canon_probs[k] = canon_probs.get(k, 0.0) + p
        return valid_prediction(self.model_id, self.model_version, ts, ts, [hands.frame_id], native,
                                self.label_map.native_order.index(native), canonical, probs, canon_probs,
                                best_p, sw.ms, calibrated=False)

    def side_for_slot(self, hands: TrackedHands, slot: str) -> HandSide:
        right, left = select_hands(hands, self.cfg.feed_mode)
        h = right if slot == "right" else left
        return HandSide.UNKNOWN if h is None else h.side


def prediction_status_summary(p: ModelPrediction) -> str:
    return f"{p.model_id}:{p.status.value}:{p.native_label or '-'}"


__all__ = [
    "HANDHYGIENE_NUM_FEATURES", "PREPROCESSING_VERSION", "HandHygieneAdapter", "centroid_normalize",
    "handhygiene_feature_vector", "select_hands", "PredictionStatus",
]
