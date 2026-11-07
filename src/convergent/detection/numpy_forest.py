"""Version-independent RandomForest/StandardScaler pipeline format ("validated conversion").

The upstream HandHygiene RandomForest was pickled with scikit-learn 1.0.2, whose tree node
layout cannot be unpickled by scikit-learn >= 1.3. Rather than pin the whole project to an
old scikit-learn, ``scripts/convert_handhygiene_rf.py`` (run once in a scikit-learn 1.2
environment) exports the fitted pipeline to a plain ``.npz`` that this module evaluates with
NumPy only. The conversion script validates that ``predict_proba`` of the export matches the
original on the full upstream training CSV before it writes the file.

Format (npz keys)::

    format_version      "numpy-forest-v1"
    scaler_mean, scaler_scale   (F,)
    classes             (C,)
    n_estimators        scalar
    tree{i}_left, tree{i}_right, tree{i}_feature, tree{i}_threshold  (n_nodes,)
    tree{i}_value       (n_nodes, C)  class fractions at each node (already normalized)
    source_sha256, source_sklearn_version, validation (json str)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

FORMAT_VERSION = "numpy-forest-v1"


class NumpyForestPipeline:
    """Drop-in for ``sklearn.pipeline.Pipeline(StandardScaler, RandomForestClassifier)``."""

    def __init__(self, scaler_mean: np.ndarray, scaler_scale: np.ndarray, classes: np.ndarray,
                 trees: list[dict[str, np.ndarray]], meta: dict[str, Any] | None = None) -> None:
        self.scaler_mean = np.asarray(scaler_mean, dtype=np.float64)
        self.scaler_scale = np.asarray(scaler_scale, dtype=np.float64)
        self.classes_ = np.asarray(classes)
        self.trees = trees
        self.meta = meta or {}
        self.n_features_in_ = int(self.scaler_mean.shape[0])
        for t in trees:
            if t["value"].shape[1] != len(self.classes_):
                raise ValueError("tree value width does not match classes")

    # ---- inference
    def _predict_tree(self, t: dict[str, np.ndarray], x: np.ndarray) -> np.ndarray:
        left, right, feat, thr, value = t["left"], t["right"], t["feature"], t["threshold"], t["value"]
        out = np.empty((x.shape[0], value.shape[1]), dtype=np.float64)
        for i in range(x.shape[0]):
            node = 0
            while left[node] != -1:  # -1 marks a leaf (sklearn TREE_LEAF)
                node = left[node] if x[i, feat[node]] <= thr[node] else right[node]
            out[i] = value[node]
        return out

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        if x.ndim != 2 or x.shape[1] != self.n_features_in_:
            raise ValueError(f"expected (N,{self.n_features_in_}) input, got {x.shape}")
        xs = (x - self.scaler_mean) / self.scaler_scale
        acc = np.zeros((x.shape[0], len(self.classes_)), dtype=np.float64)
        for t in self.trees:
            acc += self._predict_tree(t, xs)
        acc /= len(self.trees)
        return acc

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.classes_[np.argmax(self.predict_proba(x), axis=1)]

    # ---- persistence
    def save(self, path: str | Path) -> Path:
        arrays: dict[str, Any] = {
            "format_version": np.array(FORMAT_VERSION), "scaler_mean": self.scaler_mean, "scaler_scale": self.scaler_scale,
            "classes": self.classes_, "n_estimators": np.array(len(self.trees)), "meta": np.array(json.dumps(self.meta)),
        }
        for i, t in enumerate(self.trees):
            for k in ("left", "right", "feature", "threshold", "value"):
                arrays[f"tree{i}_{k}"] = t[k]
        np.savez_compressed(path, **arrays)
        return Path(path)

    @classmethod
    def load(cls, path: str | Path) -> NumpyForestPipeline:
        d = np.load(path, allow_pickle=False)
        if str(d["format_version"]) != FORMAT_VERSION:
            raise ValueError(f"unsupported forest format {d['format_version']}")
        n = int(d["n_estimators"])
        trees = [{k: d[f"tree{i}_{k}"] for k in ("left", "right", "feature", "threshold", "value")} for i in range(n)]
        meta = json.loads(str(d["meta"])) if "meta" in d else {}
        return cls(d["scaler_mean"], d["scaler_scale"], d["classes"], trees, meta)

    @classmethod
    def from_sklearn(cls, pipeline: Any, meta: dict[str, Any] | None = None) -> NumpyForestPipeline:
        """Export from a fitted ``Pipeline([('scaler', StandardScaler), ('classifier', RandomForestClassifier)])``.
        Must run in an environment that can unpickle the original (scikit-learn <= 1.2 for the upstream file)."""
        scaler = pipeline.named_steps.get("scaler")
        rf = pipeline.named_steps.get("classifier")
        if scaler is None or rf is None or not hasattr(rf, "estimators_"):
            raise ValueError("expected Pipeline with 'scaler' and RandomForest 'classifier'")
        trees = []
        for est in rf.estimators_:
            t = est.tree_
            value = np.asarray(t.value[:, 0, :], dtype=np.float64)
            sums = value.sum(axis=1, keepdims=True)
            value = np.where(sums > 0, value / np.maximum(sums, 1e-12), value)
            trees.append({
                "left": np.asarray(t.children_left, dtype=np.int64), "right": np.asarray(t.children_right, dtype=np.int64),
                "feature": np.asarray(t.feature, dtype=np.int64), "threshold": np.asarray(t.threshold, dtype=np.float64),
                "value": value,
            })
        return cls(np.asarray(scaler.mean_), np.asarray(scaler.scale_), np.asarray(rf.classes_), trees, meta)
