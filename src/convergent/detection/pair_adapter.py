"""``temporal_v2`` branch: the hand-relative temporal classifier (see :mod:`pair_features`).

Differences from the v1 S-Kia branch:

* hands are taken from the tracker regardless of the left/right label (unassigned hands
  included) and slotted by position continuity (:class:`HandSlotter`);
* features are relative to the hands themselves, not to the image;
* the model is evaluated on both slot orders and the two results are averaged;
* the window is the last N frames on the frame clock: frames without a hand stay in it as
  empty frames and a short history is left-padded with empty frames, so a brief tracking
  dropout does not cost a multi-second warm-up (training builds windows the same way);
* the class list has an explicit ``none`` ("not washing") class;
* probabilities are temperature-calibrated (when ``calibrator.json`` ships with the artifact)
  and smoothed over ``smooth_s`` seconds, which removes one-or-two-frame label flips.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from convergent.common.config import TemporalV2Config, resolve_path
from convergent.common.logging import get_logger
from convergent.common.types import ModelPrediction, TrackedHands
from convergent.detection.base import (
    ArtifactStatus,
    Classifier,
    Stopwatch,
    sha256_of,
    valid_prediction,
)
from convergent.detection.confidence_calibration import Calibrator
from convergent.detection.labels import NONE, LabelRegistry, ModelLabelMap, default_registry
from convergent.detection.lstm_model import PAIR_PREPROCESSING_VERSION, TemporalArtifact
from convergent.detection.pair_features import (
    HandSlotter,
    featurize,
    smooth_probabilities,
    swap_slots,
)
from convergent.detection.sequence_buffer import SequenceWindow

log = get_logger(__name__)


class TemporalV2Adapter(Classifier):
    model_id = "temporal_v2"
    preprocessing_version = PAIR_PREPROCESSING_VERSION

    def __init__(self, cfg: TemporalV2Config | None = None, registry: LabelRegistry | None = None) -> None:
        self.cfg = cfg or TemporalV2Config()
        self.registry = registry or default_registry()
        self.label_map: ModelLabelMap = self.registry.model_map("temporal_v2")
        self._artifact: TemporalArtifact | None = None
        self._calibrator: Calibrator | None = None
        self._status = ArtifactStatus(self.model_id, False, message="not loaded")
        self.slotter = HandSlotter()
        self._window, self._min_present, self._reset_gap_s = 32, 8, 1.0
        self._hold_s = 0.0
        self._last_seen_ts = -1e9
        self._last_quality = 0.0
        self._buf: deque[tuple[float, int, np.ndarray, np.ndarray, float]] = deque(maxlen=self._window)
        self.aspect = 4.0 / 3.0  # image width / height; the pipeline sets it from the frame
        self._smooth: np.ndarray | None = None
        self._smooth_ts = -1e9
        self.model_version = "unloaded"

    def load(self) -> ArtifactStatus:
        d = resolve_path(self.cfg.artifact_dir)
        if not self.cfg.enabled:
            self._status = ArtifactStatus(self.model_id, False, str(d), message="disabled by config")
            return self._status
        if not d.exists():
            self._status = ArtifactStatus(self.model_id, False, str(d),
                                          message=f"MODEL_UNAVAILABLE: no temporal_v2 artifact at {d} (train with scripts/train_temporal_v2.py)")
            return self._status
        try:
            art = TemporalArtifact.load(d)
            if art.meta.preprocessing_version != PAIR_PREPROCESSING_VERSION:
                raise ValueError(f"artifact preprocessing {art.meta.preprocessing_version!r} is not {PAIR_PREPROCESSING_VERSION!r}")
            unknown = [c for c in art.meta.classes if c not in self.label_map.mappings]
            if unknown:
                raise ValueError(f"artifact classes without canonical mapping: {unknown}")
            cal_path = d / "calibrator.json"
            self._calibrator = Calibrator.load(cal_path) if cal_path.exists() else None
        except Exception as exc:  # noqa: BLE001
            log.error("temporal_v2 artifact unusable: %s", exc)
            self._status = ArtifactStatus(self.model_id, False, str(d), message=f"MODEL_UNAVAILABLE: {exc}")
            self._artifact = None
            return self._status
        self._artifact = art
        self.model_version = art.meta.model_version
        self._window = art.meta.window_frames
        self._min_present = max(2, art.meta.min_present_frames or 8)
        self._reset_gap_s = art.meta.max_gap_s
        self._hold_s = min(self.cfg.hold_s, art.meta.hold_frames / 15.0 + 0.02)
        self._buf = deque(maxlen=self._window)
        self._status = ArtifactStatus(self.model_id, True, str(d), self.model_version, sha256_of(d / "model.pt"), "loaded",
                                      art.meta.preprocessing_version,
                                      {"window_frames": art.meta.window_frames, "classes": list(art.meta.classes), "architecture": art.meta.architecture,
                                       "calibrated": self._calibrator is not None, "metrics": art.meta.metrics,
                                       "provenance": art.meta.dataset_provenance})
        return self._status

    @property
    def available(self) -> bool:
        return self._artifact is not None

    def status(self) -> ArtifactStatus:
        return self._status

    @property
    def window_frames(self) -> int:
        return self._window

    @property
    def min_present_frames(self) -> int:
        return self._min_present

    @property
    def hold_s(self) -> float:
        return self._hold_s

    def holding(self, ts: float) -> bool:
        """True while no hand is visible but one was at most ``hold_s`` ago (a short dropout the branch bridges)."""
        return self.available and 0.0 < ts - self._last_seen_ts <= self._hold_s

    @property
    def last_quality(self) -> float:
        return self._last_quality

    def reset(self) -> None:
        self._buf.clear()
        self.slotter.reset()
        self._smooth = None
        self._last_seen_ts = -1e9

    def predict(self, hands: TrackedHands) -> ModelPrediction:
        ts = hands.capture_ts
        if not self.available:
            return self.unavailable_prediction(ts)
        if self._buf:
            last = self._buf[-1][0]
            if ts <= last:
                return self.error_prediction(ts, f"non-increasing timestamp {ts} <= {last}")
            if ts - last > self._reset_gap_s:
                self.reset()  # the stream jumped: what is in the history is not "just before now"
        found = sorted(hands.hands + hands.unassigned, key=lambda h: -h.tracking_quality)[:2]
        raw, presence = self.slotter.assign([h.landmark_array() for h in found], ts)
        quality = float(np.mean([h.tracking_quality for h in found])) if found else 0.0
        self._buf.append((ts, hands.frame_id, raw, presence, quality))  # every frame, also the empty ones
        if found:
            self._last_seen_ts, self._last_quality = ts, quality
        elif not self.holding(ts):
            return self.no_input_prediction(ts, "no hands")
        seen = sum(1 for b in self._buf if b[3].max() > 0.5)
        if seen < self._min_present:
            return self.no_input_prediction(ts, f"warming up ({seen}/{self._min_present} frames with hands)")
        return self.predict_window(self._window_now())

    def _window_now(self) -> SequenceWindow:
        """The last ``window_frames`` frames, left-padded with empty frames when the history is shorter."""
        n, t = len(self._buf), self._window
        feats = np.zeros((t, 126), np.float32)
        pres = np.zeros((t, 2), np.float32)
        stamps = self._buf[-1][0] - np.arange(t - 1, -1, -1) / 15.0
        qual = np.zeros(t, np.float32)
        for i, (ts, _fid, raw, p, q) in enumerate(self._buf):
            k = t - n + i
            feats[k], pres[k], stamps[k], qual[k] = raw.reshape(-1), p, ts, q
        if n < t:  # keep the padded timestamps strictly before the first real frame
            stamps[:t - n] = self._buf[0][0] - np.arange(t - n, 0, -1) / 15.0
        return SequenceWindow(features=feats, presence=pres, timestamps=stamps, frame_ids=[b[1] for b in self._buf], tracking_quality=qual)

    def window_probabilities(self, window: SequenceWindow) -> np.ndarray:
        """Calibrated class probabilities for one raw window (both slot orders averaged, no smoothing)."""
        assert self._artifact is not None
        t = window.features.shape[0]
        feats = featurize(window.features.reshape(t, 2, 21, 3), window.presence, self.aspect, window.timestamps)
        proba = self._artifact.predict_proba(feats, None)
        if self.cfg.symmetric:
            proba = 0.5 * (proba + self._artifact.predict_proba(swap_slots(feats), None))
        if self._calibrator is not None:
            proba = self._calibrator.apply(proba)
        return np.asarray(proba, np.float64)

    def predict_window(self, window: SequenceWindow) -> ModelPrediction:
        assert self._artifact is not None
        try:
            with Stopwatch() as sw:
                proba = self.window_probabilities(window)
        except Exception as exc:  # noqa: BLE001
            log.exception("temporal_v2 inference failed")
            return self.error_prediction(window.end_ts, f"inference error: {exc}")
        dt = window.end_ts - self._smooth_ts
        if dt > max(1.0, 4 * self.cfg.smooth_s):
            self._smooth = None  # stale (tracking was lost for a while): start fresh
        proba = smooth_probabilities(self._smooth, proba, dt, self.cfg.smooth_s)
        self._smooth, self._smooth_ts = proba, window.end_ts
        classes = self._artifact.meta.classes
        probs = {c: float(p) for c, p in zip(classes, proba, strict=True)}
        canon_probs: dict[str, float] = {}
        for n, p in probs.items():
            k = self.label_map.canonical_for(n).key
            canon_probs[k] = canon_probs.get(k, 0.0) + p
        best_i = int(np.argmax(proba))
        best_p = float(proba[best_i])
        native = classes[best_i]
        if native == NONE or best_p < self.cfg.unknown_threshold:
            msg = "not washing" if native == NONE else f"max prob {best_p:.2f} < {self.cfg.unknown_threshold}"
            return self.unknown_prediction(window.start_ts, window.end_ts, probs, window.frame_ids, sw.ms, msg, canon_probs)
        return valid_prediction(self.model_id, self.model_version, window.start_ts, window.end_ts, window.frame_ids, native,
                                self.label_map.native_order.index(native) if native in self.label_map.native_order else None,
                                self.label_map.canonical_for(native), probs, canon_probs, best_p, sw.ms,
                                calibrated=self._calibrator is not None)
