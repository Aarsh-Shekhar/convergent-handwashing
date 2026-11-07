"""Timestamp-aware fusion of the three recognition branches.

Design rules (from the specification):

* branches are aligned by *capture timestamps*, never by frame counts;
* every branch's native distribution is first mapped into the canonical label space
  (``configs/labels.yaml``) – raw class vectors with incompatible indices are never averaged;
* each branch passes through its own :class:`Calibrator` (identity until fitted on held-out
  data) and gets a configurable reliability weight that must come from validation, not from
  assumptions;
* when a branch is unavailable, has no input, or errored, the fused distribution is
  renormalized over the branches that actually participated – a missing branch never gets
  implicit support, and the fused result records exactly who participated;
* contradictions (a confident branch disagreeing with the fused winner) are detected and
  reduce the fused confidence; low fused confidence yields ``UNKNOWN`` rather than a guess;
* per-branch outputs are preserved on the fused prediction for debugging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from convergent.common.config import FusionConfig
from convergent.common.types import CanonicalLabel, HandSide, ModelPrediction, PredictionStatus
from convergent.detection.confidence_calibration import Calibrator
from convergent.detection.labels import NONE, LabelRegistry, default_registry

FUSION_MODEL_ID = "fusion"
FUSION_VERSION = "reliability-weighted-v1"


@dataclass
class BranchContribution:
    model_id: str
    model_version: str
    status: PredictionStatus
    weight: float
    distribution: dict[str, float] = field(default_factory=dict)  # canonical, normalized
    top_key: str | None = None
    top_prob: float = 0.0
    calibrated: bool = False
    window_end_ts: float = 0.0
    message: str = ""

    @property
    def participating(self) -> bool:
        return self.status in (PredictionStatus.VALID, PredictionStatus.UNKNOWN) and bool(self.distribution)


class PredictionAligner:
    """Keeps the most recent prediction per branch and answers "what did each branch say
    about time ``t``?" using window overlap with a tolerance and a maximum staleness."""

    def __init__(self, tolerance_s: float = 0.25, max_age_s: float = 0.6) -> None:
        self.tolerance_s = tolerance_s
        self.max_age_s = max_age_s
        self._latest: dict[str, ModelPrediction] = {}

    def offer(self, pred: ModelPrediction) -> None:
        self._latest[pred.model_id] = pred

    def reset(self) -> None:
        self._latest.clear()

    def collect(self, ts: float) -> dict[str, ModelPrediction]:
        out: dict[str, ModelPrediction] = {}
        for mid, p in self._latest.items():
            if p.status == PredictionStatus.MODEL_UNAVAILABLE:
                out[mid] = p
                continue
            overlaps = p.window_start_ts - self.tolerance_s <= ts <= p.window_end_ts + self.tolerance_s
            fresh = 0.0 <= ts - p.window_end_ts <= self.max_age_s
            if overlaps or fresh:
                out[mid] = p
        return out


class FusionEngine:
    def __init__(self, cfg: FusionConfig | None = None, registry: LabelRegistry | None = None,
                 calibrators: dict[str, Calibrator] | None = None) -> None:
        self.cfg = cfg or FusionConfig()
        self.registry = registry or default_registry()
        self.calibrators = calibrators or {}
        self.keys = self.registry.canonical_keys()
        self.model_version = FUSION_VERSION

    # ---- per-branch normalisation
    def branch_distribution(self, pred: ModelPrediction) -> dict[str, float]:
        if not pred.canonical_probabilities:
            return {}
        keys = [k for k in pred.canonical_probabilities if k in self.keys]
        unknown_keys = [k for k in pred.canonical_probabilities if k not in self.keys]
        if unknown_keys:
            raise ValueError(f"{pred.model_id}: canonical keys not in registry: {unknown_keys}")
        if not keys:
            return {}
        vec = np.array([max(0.0, float(pred.canonical_probabilities[k])) for k in keys], dtype=np.float64)
        if vec.sum() <= 0:
            return {}
        cal = self.calibrators.get(pred.model_id)
        vec = cal.apply(vec) if cal is not None else vec / vec.sum()
        return {k: float(v) for k, v in zip(keys, vec, strict=True)}

    # ---- main
    def combine(self, predictions: dict[str, ModelPrediction], ts: float, tracking_ok: bool = True,
                frame_ids: list[int] | None = None) -> ModelPrediction:
        contributions: list[BranchContribution] = []
        for mid, p in predictions.items():
            w = float(self.cfg.weights.get(mid, 0.0))
            try:
                dist = self.branch_distribution(p) if p.status in (PredictionStatus.VALID, PredictionStatus.UNKNOWN) else {}
            except ValueError as exc:
                contributions.append(BranchContribution(mid, p.model_version, PredictionStatus.ERROR, w, message=str(exc)))
                continue
            top = max(dist, key=dist.get) if dist else None
            contributions.append(BranchContribution(mid, p.model_version, p.status, w if w > 0 else 0.0, dist, top,
                                                    dist.get(top, 0.0) if top else 0.0,
                                                    p.calibrated or mid in self.calibrators, p.window_end_ts, p.message))
        participating = [c for c in contributions if c.participating and c.weight > 0]
        extras: dict[str, Any] = {
            "branches": [self._contrib_dict(c) for c in contributions],
            "participating": [c.model_id for c in participating],
            "weights": {c.model_id: c.weight for c in participating},
        }
        base = dict(model_id=FUSION_MODEL_ID, model_version=self.model_version, window_start_ts=ts, window_end_ts=ts,
                    frame_ids=frame_ids or [], extras=extras)
        if self.cfg.require_tracking and not tracking_ok:
            return ModelPrediction(**base, status=PredictionStatus.NO_INPUT, message="tracking lost")
        if len(participating) < max(1, self.cfg.min_branches):
            return ModelPrediction(**base, status=PredictionStatus.NO_INPUT,
                                   message=f"{len(participating)} participating branch(es) < min_branches={self.cfg.min_branches}")
        total_w = sum(c.weight for c in participating)
        fused = dict.fromkeys(self.keys, 0.0)
        for c in participating:
            for k, v in c.distribution.items():
                fused[k] += c.weight * v / total_w
        # technique-level aggregation (left_t + right_t + t)
        tech: dict[str, float] = {}
        for k, v in fused.items():
            t = self.registry.technique_of_key(k)
            tech[t] = tech.get(t, 0.0) + v
        best_t = max(tech, key=tech.get)
        best_p = tech[best_t]
        second = sorted(tech.values(), reverse=True)[1] if len(tech) > 1 else 0.0
        side, side_resolved = self._resolve_side(best_t, fused, participating, predictions)
        # contradictions: a confident branch whose winner differs from the fused winner
        contradictions = [c.model_id for c in participating
                          if c.top_key and self.registry.technique_of_key(c.top_key) != best_t
                          and c.top_prob >= 0.5 and c.top_prob >= best_p - self.cfg.contradiction_margin]
        confidence = best_p
        if contradictions:
            confidence *= 0.5
        extras.update({"technique_distribution": tech, "contradictions": contradictions, "margin": best_p - second,
                       "unknown_threshold": self.cfg.unknown_threshold})
        canonical = CanonicalLabel(technique=best_t, side=side, resolved=side_resolved)
        if best_t == NONE or confidence < self.cfg.unknown_threshold:
            return ModelPrediction(**base, status=PredictionStatus.UNKNOWN, canonical_probabilities=fused,
                                   confidence=float(min(confidence, 1.0)),
                                   message=f"fused confidence {confidence:.2f} below threshold" if best_t != NONE else "no technique")
        return ModelPrediction(**base, status=PredictionStatus.VALID, native_label=canonical.key, canonical=canonical,
                               canonical_probabilities=fused, confidence=float(min(confidence, 1.0)),
                               calibrated=all(c.calibrated for c in participating))

    def _resolve_side(self, technique: str, fused: dict[str, float], participating: list[BranchContribution],
                      preds: dict[str, ModelPrediction]) -> tuple[HandSide, bool]:
        if not self.registry.is_sided(technique):
            return HandSide.BOTH, True
        left = fused.get(f"left_{technique}", 0.0)
        right = fused.get(f"right_{technique}", 0.0)
        unsided = fused.get(technique, 0.0)
        if left == right == 0.0:
            # no branch offered a side; report whether sides are unresolved (mapping) or unknown
            unresolved = any((p.canonical is not None and p.canonical.technique == technique and not p.canonical.resolved)
                             for p in preds.values() if p.status == PredictionStatus.VALID)
            return (HandSide.UNRESOLVED if unresolved else HandSide.UNKNOWN), False
        if max(left, right) < unsided:
            return HandSide.UNKNOWN, False
        return (HandSide.LEFT if left > right else HandSide.RIGHT), True

    @staticmethod
    def _contrib_dict(c: BranchContribution) -> dict[str, Any]:
        return {"model_id": c.model_id, "model_version": c.model_version, "status": c.status.value, "weight": c.weight,
                "top": c.top_key, "top_prob": round(c.top_prob, 4), "calibrated": c.calibrated,
                "distribution": {k: round(v, 4) for k, v in c.distribution.items()}, "message": c.message}


# --------------------------------------------------------------------------- learnable fusion
class MetaClassifierFusion:
    """Alternative learnable fusion: a small logistic-regression meta-classifier over the
    concatenated per-branch canonical distributions plus availability flags.

    It must be fitted on **out-of-sample** base-model predictions (predictions on recordings
    the base models were not trained on); fitting on in-sample predictions and reporting the
    result as unbiased is exactly the mistake the spec forbids, so :meth:`fit` requires an
    explicit ``out_of_sample=True`` acknowledgement.
    """

    def __init__(self, registry: LabelRegistry | None = None, branch_order: tuple[str, ...] = ("handhygiene", "skia_temporal", "yolo")) -> None:
        self.registry = registry or default_registry()
        self.keys = self.registry.canonical_keys()
        self.branch_order = branch_order
        self.model = None
        self.classes_: list[str] = []

    def featurize(self, predictions: dict[str, ModelPrediction], engine: FusionEngine) -> np.ndarray:
        feats: list[float] = []
        for b in self.branch_order:
            p = predictions.get(b)
            dist = engine.branch_distribution(p) if p is not None and p.status in (PredictionStatus.VALID, PredictionStatus.UNKNOWN) else {}
            feats.append(1.0 if dist else 0.0)
            feats.extend(dist.get(k, 0.0) for k in self.keys)
        return np.array(feats, dtype=np.float64)

    def fit(self, x: np.ndarray, y: list[str], out_of_sample: bool = False) -> None:
        if not out_of_sample:
            raise ValueError("MetaClassifierFusion.fit requires out_of_sample=True: train it only on held-out base predictions")
        from sklearn.linear_model import LogisticRegression

        self.model = LogisticRegression(max_iter=2000, C=1.0)
        self.model.fit(x, y)
        self.classes_ = [str(c) for c in self.model.classes_]

    def predict_proba(self, x: np.ndarray) -> dict[str, float]:
        if self.model is None:
            raise RuntimeError("meta fusion not fitted")
        p = self.model.predict_proba(x.reshape(1, -1))[0]
        return {c: float(v) for c, v in zip(self.classes_, p, strict=True)}
