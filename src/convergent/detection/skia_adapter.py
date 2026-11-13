"""S-Kia (S-Kia/Hand_washing_application) temporal branch adapter.

Reused from upstream (``Hand_washing_application.py`` / ``Hand_washing_train.py``):

* feature layout: **left hand (21x3) then right hand (21x3)** raw MediaPipe normalized
  landmarks, flattened row-major; missing hand = ``np.zeros(63)``,
* the 12 native labels ``["1","2lt","2rt","3","4lt","4rt","5lt","5rt","6lt","6rt","7lt","7rt"]``,
* legacy normalization ``(x - X.mean(axis=0)) / (X.std(axis=0) + 1e-8)`` where ``X`` is the
  *entire* dataset (``X.pkl``; train and test – a leak we keep only for exact legacy compat),
* the ``10``-prediction majority vote with 0.5 agreement threshold is NOT reproduced: the
  shared temporal validator handles stability.

Two modes:

* ``legacy`` – runs the original ``generalized_lstm_model.keras`` with input ``(1, 1, 126)``.
  It is a *one-time-step* classifier and is reported as such (``model_version`` prefixed
  ``legacy-1step``). Requires the optional ``skia-legacy`` extra (TensorFlow).
* ``temporal`` (default) – the corrected multi-frame model from :mod:`lstm_model`, fed by a
  :class:`SequenceBuffer` built from contiguous timestamps. Its artifact is produced by
  ``scripts/train_lstm.py`` and is a separate, versioned directory.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from convergent.common.config import SkiaConfig, resolve_path
from convergent.common.logging import get_logger
from convergent.common.types import HandObservation, ModelPrediction, TrackedHands
from convergent.detection.base import (
    ArtifactStatus,
    Classifier,
    Stopwatch,
    sha256_of,
    valid_prediction,
)
from convergent.detection.labels import LabelRegistry, ModelLabelMap, default_registry
from convergent.detection.lstm_model import TemporalArtifact
from convergent.detection.sequence_buffer import SequenceBuffer, SequenceWindow

log = get_logger(__name__)

SKIA_NUM_FEATURES = 126
LEGACY_PREPROCESSING_VERSION = "skia-legacy-1step-v1"
SKIA_STEP_NAMES = ["1", "2lt", "2rt", "3", "4lt", "4rt", "5lt", "5rt", "6lt", "6rt", "7lt", "7rt"]


# --------------------------------------------------------------------------- preprocessing
def skia_feature_vector(left: np.ndarray | None, right: np.ndarray | None) -> np.ndarray:
    """Upstream ``preprocess_landmarks``: left block then right block, zeros when missing."""
    if left is None and right is None:
        raise ValueError("at least one hand is required")
    lft = np.zeros(63) if left is None else np.asarray(left, dtype=np.float64).reshape(63)
    r = np.zeros(63) if right is None else np.asarray(right, dtype=np.float64).reshape(63)
    return np.concatenate([lft, r])


def select_hands(hands: TrackedHands, feed_mode: str) -> tuple[HandObservation | None, HandObservation | None]:
    """Return (left_slot, right_slot). Upstream filled slots from MediaPipe's label."""
    if feed_mode == "anatomical":
        return hands.left, hands.right
    return hands.by_raw_label("Left"), hands.by_raw_label("Right")


def skia_observation(hands: TrackedHands, feed_mode: str) -> tuple[np.ndarray, np.ndarray, float] | None:
    left, right = select_hands(hands, feed_mode)
    if left is None and right is None:
        return None
    feats = skia_feature_vector(None if left is None else left.landmark_array(), None if right is None else right.landmark_array())
    presence = np.array([0.0 if left is None else 1.0, 0.0 if right is None else 1.0], dtype=np.float32)
    quals = [h.tracking_quality for h in (left, right) if h is not None]
    return feats, presence, float(np.mean(quals)) if quals else 0.0


def legacy_normalize(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return (x - mean) / (std + 1e-8)


# --------------------------------------------------------------------------- temporal adapter
class SkiaTemporalAdapter(Classifier):
    model_id = "skia_temporal"

    def __init__(self, cfg: SkiaConfig | None = None, registry: LabelRegistry | None = None) -> None:
        self.cfg = cfg or SkiaConfig()
        self.registry = registry or default_registry()
        self.label_map: ModelLabelMap = self.registry.model_map("skia")
        self._artifact: TemporalArtifact | None = None
        self._status = ArtifactStatus(self.model_id, False, message="not loaded")
        self.buffer = SequenceBuffer(self.cfg.window_frames, self.cfg.max_gap_s, self.cfg.stride_frames,
                                     feature_fn=lambda h: skia_observation(h, self.cfg.feed_mode))
        self.model_version = "unloaded"
        self.preprocessing_version = "skia-sequence-v1"

    def load(self) -> ArtifactStatus:
        d = resolve_path(self.cfg.temporal_artifact_dir)
        if not self.cfg.enabled or self.cfg.mode == "legacy":
            self._status = ArtifactStatus(self.model_id, False, str(d), message="disabled by config")
            return self._status
        if not d.exists():
            self._status = ArtifactStatus(self.model_id, False, str(d), message=f"MODEL_UNAVAILABLE: no temporal artifact at {d} (train with scripts/train_lstm.py)")
            return self._status
        try:
            art = TemporalArtifact.load(d)
            if art.meta.preprocessing_version != self.preprocessing_version:
                raise ValueError(f"artifact preprocessing {art.meta.preprocessing_version!r} is not a skia-sequence artifact")
            classes = list(art.meta.classes)
            unknown = [c for c in classes if c not in self.label_map.mappings]
            if unknown:
                raise ValueError(f"artifact classes without canonical mapping: {unknown}")
        except Exception as exc:  # noqa: BLE001
            log.error("skia temporal artifact unusable: %s", exc)
            self._status = ArtifactStatus(self.model_id, False, str(d), message=f"MODEL_UNAVAILABLE: {exc}")
            self._artifact = None
            return self._status
        self._artifact = art
        self.model_version = art.meta.model_version
        self.preprocessing_version = art.meta.preprocessing_version
        # buffer geometry is dictated by the artifact
        self.buffer = SequenceBuffer(art.meta.window_frames, art.meta.max_gap_s, self.cfg.stride_frames,
                                     feature_fn=lambda h: skia_observation(h, art.meta.feed_mode))
        self._status = ArtifactStatus(self.model_id, True, str(d), self.model_version, sha256_of(d / "model.pt"), "loaded",
                                      art.meta.preprocessing_version,
                                      {"window_frames": art.meta.window_frames, "classes": classes,
                                       "metrics": art.meta.metrics, "provenance": art.meta.dataset_provenance})
        return self._status

    @property
    def available(self) -> bool:
        return self._artifact is not None

    def status(self) -> ArtifactStatus:
        return self._status

    @property
    def window_frames(self) -> int:
        return self._artifact.meta.window_frames if self._artifact else self.cfg.window_frames

    def reset(self) -> None:
        self.buffer.reset()

    def predict(self, hands: TrackedHands) -> ModelPrediction:
        ts = hands.capture_ts
        if not self.available:
            return self.unavailable_prediction(ts)
        try:
            window = self.buffer.update(hands)
        except ValueError as exc:
            return self.error_prediction(ts, f"sequence buffer: {exc}")
        if window is None:
            return self.no_input_prediction(ts, f"sequence not full ({len(self.buffer)}/{self.window_frames})")
        return self.predict_window(window)

    def predict_window(self, window: SequenceWindow) -> ModelPrediction:
        assert self._artifact is not None
        try:
            with Stopwatch() as sw:
                proba = self._artifact.predict_proba(window.features, window.presence)
        except Exception as exc:  # noqa: BLE001
            log.exception("skia temporal inference failed")
            return self.error_prediction(window.end_ts, f"inference error: {exc}")
        classes = self._artifact.meta.classes
        probs = {c: float(p) for c, p in zip(classes, proba, strict=True)}
        best_i = int(np.argmax(proba))
        best_p = float(proba[best_i])
        canon_probs: dict[str, float] = {}
        for n, p in probs.items():
            k = self.label_map.canonical_for(n).key
            canon_probs[k] = canon_probs.get(k, 0.0) + p
        if best_p < self.cfg.unknown_threshold:
            return self.unknown_prediction(window.start_ts, window.end_ts, probs, window.frame_ids, sw.ms,
                                           f"max prob {best_p:.2f} < {self.cfg.unknown_threshold}", canon_probs)
        native = classes[best_i]
        canonical = self.label_map.canonical_for(native)
        return valid_prediction(self.model_id, self.model_version, window.start_ts, window.end_ts, window.frame_ids,
                                native, self.label_map.native_order.index(native) if native in self.label_map.native_order else None,
                                canonical, probs, canon_probs, best_p, sw.ms)


# --------------------------------------------------------------------------- legacy adapter
class SkiaLegacyAdapter(Classifier):
    """Runs the upstream one-time-step Keras checkpoint unchanged (compat mode only)."""

    model_id = "skia_legacy"
    preprocessing_version = LEGACY_PREPROCESSING_VERSION

    def __init__(self, cfg: SkiaConfig | None = None, registry: LabelRegistry | None = None) -> None:
        self.cfg = cfg or SkiaConfig()
        self.registry = registry or default_registry()
        self.label_map = self.registry.model_map("skia")
        self._model = None
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None
        self._status = ArtifactStatus(self.model_id, False, message="not loaded")
        self.model_version = "legacy-1step-unloaded"

    def load(self) -> ArtifactStatus:
        mp, sp = resolve_path(self.cfg.legacy_model_path), resolve_path(self.cfg.legacy_stats_path)
        if not self.cfg.enabled or self.cfg.mode == "temporal":
            self._status = ArtifactStatus(self.model_id, False, str(mp), message="disabled by config (mode != legacy/both)")
            return self._status
        if not mp.exists() or not sp.exists():
            self._status = ArtifactStatus(self.model_id, False, str(mp), message=f"MODEL_UNAVAILABLE: need {mp.name} and {sp.name} (run `make models`)")
            return self._status
        try:
            stats = np.load(sp)
            mean, std = np.asarray(stats["mean"], dtype=np.float64), np.asarray(stats["std"], dtype=np.float64)
            if mean.shape != (SKIA_NUM_FEATURES,) or std.shape != (SKIA_NUM_FEATURES,):
                raise ValueError(f"legacy scaler stats must be ({SKIA_NUM_FEATURES},)")
            try:
                from tensorflow.keras.models import load_model  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError("TensorFlow not installed; install the `skia-legacy` extra") from exc
            model = load_model(str(mp), compile=False)
            shape = tuple(model.input_shape)
            if shape[-1] != SKIA_NUM_FEATURES:
                raise ValueError(f"legacy model expects {shape[-1]} features")
            n_out = int(model.output_shape[-1])
            if n_out != len(SKIA_STEP_NAMES):
                raise ValueError(f"legacy model has {n_out} outputs, expected {len(SKIA_STEP_NAMES)}")
        except Exception as exc:  # noqa: BLE001
            log.error("skia legacy artifact unusable: %s", exc)
            self._status = ArtifactStatus(self.model_id, False, str(mp), message=f"MODEL_UNAVAILABLE: {exc}")
            return self._status
        self._model, self._mean, self._std = model, mean, std
        self.model_version = f"legacy-1step-{Path(mp).stem}"
        self._status = ArtifactStatus(self.model_id, True, str(mp), self.model_version, sha256_of(mp), "loaded (ONE time step; not a corrected temporal model)",
                                      LEGACY_PREPROCESSING_VERSION, {"input_shape": list(shape)})
        return self._status

    @property
    def available(self) -> bool:
        return self._model is not None

    def status(self) -> ArtifactStatus:
        return self._status

    def predict(self, hands: TrackedHands) -> ModelPrediction:
        ts = hands.capture_ts
        if not self.available:
            return self.unavailable_prediction(ts)
        obs = skia_observation(hands, self.cfg.feed_mode)
        if obs is None:
            return self.no_input_prediction(ts, "no hands")
        feats, _presence, _q = obs
        try:
            with Stopwatch() as sw:
                x = legacy_normalize(feats, self._mean, self._std).reshape((1, 1, SKIA_NUM_FEATURES)).astype(np.float32)  # type: ignore[arg-type]
                proba = np.asarray(self._model.predict(x, verbose=0)[0], dtype=np.float64)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            return self.error_prediction(ts, f"inference error: {exc}")
        probs = {c: float(p) for c, p in zip(SKIA_STEP_NAMES, proba, strict=True)}
        best_i = int(np.argmax(proba))
        best_p = float(proba[best_i])
        if best_p < self.cfg.unknown_threshold:
            return self.unknown_prediction(ts, ts, probs, [hands.frame_id], sw.ms, f"max prob {best_p:.2f} < threshold")
        native = SKIA_STEP_NAMES[best_i]
        canonical = self.label_map.canonical_for(native)
        canon_probs: dict[str, float] = {}
        for n, p in probs.items():
            k = self.label_map.canonical_for(n).key
            canon_probs[k] = canon_probs.get(k, 0.0) + p
        return valid_prediction(self.model_id, self.model_version, ts, ts, [hands.frame_id], native, best_i, canonical,
                                probs, canon_probs, best_p, sw.ms)


def compute_legacy_scaler_stats(x_pkl_path: str | Path, out_path: str | Path) -> Path:
    """Derive the legacy mean/std from upstream ``X.pkl`` (a plain NumPy array pickle) once,
    so the 7 MB dataset pickle never needs to be loaded at runtime."""
    from convergent.detection.base import safe_load_joblib_array

    x = np.asarray(safe_load_joblib_array(x_pkl_path), dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != SKIA_NUM_FEATURES:
        raise ValueError(f"unexpected X.pkl shape {x.shape}")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, mean=x.mean(axis=0), std=x.std(axis=0), n=np.array(x.shape[0]))
    return out
