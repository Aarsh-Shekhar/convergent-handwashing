"""Per-branch confidence calibration.

Branch outputs are not comparable as-is: RandomForest ``predict_proba`` is a vote fraction,
the LSTM softmax is typically over-confident, and YOLO "class scores" are detection
confidences that need not sum to one. Each branch gets a :class:`Calibrator` fitted on
held-out validation predictions (never in-sample). Until a calibrator is fitted the branch
is marked ``calibrated=False`` and fusion applies the configured prior weight only.

Implemented: identity (uncalibrated), temperature scaling (fit by minimizing NLL on a grid),
and histogram binning on the max-probability (reliability correction).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


def expected_calibration_error(confidences: np.ndarray, correct: np.ndarray, n_bins: int = 10) -> float:
    confidences = np.asarray(confidences, dtype=np.float64)
    correct = np.asarray(correct, dtype=np.float64)
    if len(confidences) == 0:
        return 0.0
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(bins[:-1], bins[1:], strict=True):
        m = (confidences > lo) & (confidences <= hi)
        if m.any():
            ece += m.mean() * abs(confidences[m].mean() - correct[m].mean())
    return float(ece)


@dataclass
class Calibrator:
    method: str = "identity"
    temperature: float = 1.0
    bin_edges: list[float] = field(default_factory=list)
    bin_accuracy: list[float] = field(default_factory=list)
    fitted: bool = False
    n_fit_samples: int = 0
    ece_before: float | None = None
    ece_after: float | None = None

    # ---- application
    def apply(self, probs: np.ndarray) -> np.ndarray:
        p = np.clip(np.asarray(probs, dtype=np.float64), 1e-9, 1.0)
        if not self.fitted or self.method == "identity":
            return p / p.sum()
        if self.method == "temperature":
            logits = np.log(p) / self.temperature
            logits -= logits.max()
            e = np.exp(logits)
            return e / e.sum()
        if self.method == "histogram":
            p = p / p.sum()
            i = int(np.argmax(p))
            conf = float(p[i])
            b = int(np.clip(np.searchsorted(self.bin_edges, conf, side="right") - 1, 0, len(self.bin_accuracy) - 1))
            new_conf = float(self.bin_accuracy[b])
            rest = 1.0 - p[i]
            out = p * ((1.0 - new_conf) / rest) if rest > 1e-9 else np.full_like(p, (1 - new_conf) / max(len(p) - 1, 1))
            out[i] = new_conf
            return out / out.sum()
        raise ValueError(f"unknown calibration method {self.method}")

    # ---- fitting (validation data only!)
    @classmethod
    def fit_temperature(cls, probs: np.ndarray, labels: np.ndarray, grid: np.ndarray | None = None) -> Calibrator:
        probs = np.clip(np.asarray(probs, dtype=np.float64), 1e-9, 1.0)
        labels = np.asarray(labels, dtype=int)
        if probs.ndim != 2 or len(labels) != len(probs):
            raise ValueError("probs must be (N,C) and labels (N,)")
        logits = np.log(probs)
        grid = np.linspace(0.25, 5.0, 96) if grid is None else grid
        best_t, best_nll = 1.0, np.inf
        for t in grid:
            z = logits / t
            z = z - z.max(axis=1, keepdims=True)
            logp = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
            nll = -logp[np.arange(len(labels)), labels].mean()
            if nll < best_nll:
                best_t, best_nll = float(t), float(nll)
        cal = cls(method="temperature", temperature=best_t, fitted=True, n_fit_samples=len(labels))
        cal.ece_before = expected_calibration_error(probs.max(axis=1), probs.argmax(axis=1) == labels)
        after = np.stack([cal.apply(p) for p in probs])
        cal.ece_after = expected_calibration_error(after.max(axis=1), after.argmax(axis=1) == labels)
        return cal

    @classmethod
    def fit_histogram(cls, probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> Calibrator:
        probs = np.asarray(probs, dtype=np.float64)
        labels = np.asarray(labels, dtype=int)
        conf = probs.max(axis=1)
        correct = (probs.argmax(axis=1) == labels).astype(float)
        edges = np.linspace(0, 1, n_bins + 1)
        acc = []
        for lo, hi in zip(edges[:-1], edges[1:], strict=True):
            m = (conf > lo) & (conf <= hi) if lo > 0 else (conf >= lo) & (conf <= hi)
            acc.append(float(correct[m].mean()) if m.any() else float((lo + hi) / 2))
        cal = cls(method="histogram", bin_edges=[float(e) for e in edges], bin_accuracy=acc, fitted=True, n_fit_samples=len(labels))
        cal.ece_before = expected_calibration_error(conf, correct)
        after = np.stack([cal.apply(p) for p in probs])
        cal.ece_after = expected_calibration_error(after.max(axis=1), after.argmax(axis=1) == labels)
        return cal

    # ---- persistence
    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Calibrator:
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
