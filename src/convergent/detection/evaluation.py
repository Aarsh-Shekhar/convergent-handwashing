"""Recording-level evaluation utilities.

Frame-level metrics (accuracy, precision, recall, macro-F1, confusion matrix), event-level
precision/recall with temporal IoU matching, false-completion rate, missing-step detection,
latency and resource statistics, and an ablation runner over branch subsets.

Scientific requirement: callers must pass predictions produced on recordings/subjects that
were held out from training. Nothing here can check that – ``EvaluationReport.split`` is
there so the provenance is recorded alongside the numbers.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import psutil

from convergent.common.types import GestureEvent, HandSide, ValidationStatus


# --------------------------------------------------------------------------- frame level
@dataclass
class FrameMetrics:
    labels: list[str]
    accuracy: float
    precision_macro: float
    recall_macro: float
    f1_macro: float
    per_class: dict[str, dict[str, float]]
    confusion: list[list[int]]
    support: int


def frame_metrics(y_true: Iterable[str], y_pred: Iterable[str], labels: list[str] | None = None) -> FrameMetrics:
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

    yt, yp = list(y_true), list(y_pred)
    if len(yt) != len(yp):
        raise ValueError("y_true and y_pred length mismatch")
    labels = labels or sorted(set(yt) | set(yp))
    if not yt:
        return FrameMetrics(labels, 0.0, 0.0, 0.0, 0.0, {}, [[0] * len(labels) for _ in labels], 0)
    p, r, f, s = precision_recall_fscore_support(yt, yp, labels=labels, average=None, zero_division=0)
    pm, rm, fm, _ = precision_recall_fscore_support(yt, yp, labels=labels, average="macro", zero_division=0)
    cm = confusion_matrix(yt, yp, labels=labels)
    per_class = {lab: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])} for i, lab in enumerate(labels)}
    acc = float(np.mean([a == b for a, b in zip(yt, yp, strict=True)]))
    return FrameMetrics(labels, acc, float(pm), float(rm), float(fm), per_class, cm.tolist(), len(yt))


# --------------------------------------------------------------------------- event level
@dataclass
class RefEvent:
    technique: str
    start_ts: float
    end_ts: float
    side: HandSide = HandSide.UNKNOWN


def temporal_iou(a0: float, a1: float, b0: float, b1: float) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


@dataclass
class EventMetrics:
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    false_completion_rate: float
    mean_matched_iou: float
    n_predicted: int
    n_reference: int


def event_metrics(predicted: list[GestureEvent], reference: list[RefEvent], iou_threshold: float = 0.3,
                  match_side: bool = False) -> EventMetrics:
    preds = [e for e in predicted if e.validation_status == ValidationStatus.VALIDATED]
    used: set[int] = set()
    ious: list[float] = []
    tp = 0
    for p in sorted(preds, key=lambda e: e.start_ts):
        best, best_j = 0.0, -1
        for j, r in enumerate(reference):
            if j in used or r.technique != p.technique:
                continue
            if match_side and r.side in (HandSide.LEFT, HandSide.RIGHT) and p.side != r.side:
                continue
            iou = temporal_iou(p.start_ts, p.end_ts, r.start_ts, r.end_ts)
            if iou > best:
                best, best_j = iou, j
        if best_j >= 0 and best >= iou_threshold:
            used.add(best_j)
            tp += 1
            ious.append(best)
    fp = len(preds) - tp
    fn = len(reference) - tp
    prec = tp / len(preds) if preds else 0.0
    rec = tp / len(reference) if reference else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec > 0 else 0.0
    return EventMetrics(tp, fp, fn, prec, rec, f1, fp / len(preds) if preds else 0.0,
                        float(np.mean(ious)) if ious else 0.0, len(preds), len(reference))


@dataclass
class MissingStepResult:
    required: list[str]
    predicted_missing: list[str]
    actual_missing: list[str]
    correct: bool
    per_step: dict[str, dict[str, bool]]


def missing_step_detection(predicted: list[GestureEvent], reference: list[RefEvent], required: list[str]) -> MissingStepResult:
    done_pred = {e.technique for e in predicted if e.validation_status == ValidationStatus.VALIDATED}
    done_ref = {r.technique for r in reference}
    pm = [t for t in required if t not in done_pred]
    am = [t for t in required if t not in done_ref]
    per = {t: {"predicted_missing": t in pm, "actually_missing": t in am} for t in required}
    return MissingStepResult(required, pm, am, pm == am, per)


# --------------------------------------------------------------------------- latency / resources
@dataclass
class LatencyStats:
    n: int
    mean_ms: float
    p50_ms: float
    p90_ms: float
    p99_ms: float
    max_ms: float

    @classmethod
    def from_samples(cls, ms: Iterable[float]) -> LatencyStats:
        a = np.asarray(list(ms), dtype=np.float64)
        if a.size == 0:
            return cls(0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return cls(int(a.size), float(a.mean()), float(np.percentile(a, 50)), float(np.percentile(a, 90)),
                   float(np.percentile(a, 99)), float(a.max()))


class ResourceMonitor:
    def __init__(self) -> None:
        self._proc = psutil.Process()
        self._cpu_samples: list[float] = []
        self._rss_samples: list[float] = []
        self._t0 = time.perf_counter()
        self._proc.cpu_percent(None)

    def sample(self) -> None:
        self._cpu_samples.append(self._proc.cpu_percent(None))
        self._rss_samples.append(self._proc.memory_info().rss / (1024 * 1024))

    def summary(self) -> dict[str, float]:
        return {
            "wall_s": time.perf_counter() - self._t0,
            "cpu_percent_mean": float(np.mean(self._cpu_samples)) if self._cpu_samples else 0.0,
            "cpu_percent_max": float(np.max(self._cpu_samples)) if self._cpu_samples else 0.0,
            "rss_mb_mean": float(np.mean(self._rss_samples)) if self._rss_samples else 0.0,
            "rss_mb_max": float(np.max(self._rss_samples)) if self._rss_samples else 0.0,
        }


# --------------------------------------------------------------------------- report & ablation
@dataclass
class EvaluationReport:
    dataset: str
    dataset_version: str
    split: dict[str, Any]
    model_config: dict[str, Any]
    frame: dict[str, Any] | None = None
    events: dict[str, Any] | None = None
    missing_steps: dict[str, Any] | None = None
    latency: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    ablations: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=_json_default)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")
        return p


def _json_default(o: Any) -> Any:
    if hasattr(o, "__dict__"):
        return o.__dict__
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


RunFn = Callable[[tuple[str, ...]], dict[str, Any]]
"""Given the enabled branch ids, run the pipeline on the evaluation set and return metrics."""


def branch_subsets(branches: tuple[str, ...]) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for k in range(1, len(branches) + 1):
        out.extend(combinations(branches, k))
    return out


def run_ablation(run: RunFn, branches: tuple[str, ...] = ("handhygiene", "skia_temporal", "yolo")) -> list[dict[str, Any]]:
    """Evaluate every non-empty subset of branches (single branches + all fusions).

    The caller decides whether combining branches *actually* helps; nothing is assumed."""
    results = []
    for subset in branch_subsets(branches):
        res = run(subset)
        results.append({"branches": list(subset), **res})
    return results
