"""Corrected temporal landmark classifier (PyTorch) and its versioned artifact format.

Why a new model: the upstream S-Kia checkpoint is an LSTM trained on shape ``(N, 1, 126)``
– one time step – so it never saw motion. This module defines a genuinely sequential model
(``window_frames`` > 1) plus an artifact layout that pins everything needed to reproduce
inference exactly: architecture, class list, scaler fitted on *training data only*,
feature layout version, window/FPS, and dataset provenance.

Artifact directory layout::

    <dir>/model.pt        state_dict only (loaded with weights_only=True)
    <dir>/meta.json       TemporalArtifactMeta
    <dir>/scaler.npz      mean, std  (shape (F,))
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

SKIA_TEMPORAL_PREPROCESSING_VERSION = "skia-sequence-v1"  # left(63)+right(63) raw landmarks + presence(2)
FEATURE_DIM = 126
PRESENCE_DIM = 2


@dataclass
class TemporalArtifactMeta:
    model_id: str = "skia_temporal"
    model_version: str = "0.0.0"
    architecture: str = "lstm"
    classes: list[str] = field(default_factory=list)  # native labels (S-Kia order by default)
    feature_dim: int = FEATURE_DIM
    use_presence: bool = True
    hidden_size: int = 128
    num_layers: int = 2
    dropout: float = 0.2
    window_frames: int = 16
    stride_frames: int = 1
    target_fps: float = 15.0
    max_gap_s: float = 0.25
    preprocessing_version: str = SKIA_TEMPORAL_PREPROCESSING_VERSION
    feed_mode: str = "raw_label"
    dataset_provenance: dict[str, Any] = field(default_factory=dict)
    split: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at_utc: str = ""
    framework: str = "torch"
    notes: str = ""

    @property
    def input_dim(self) -> int:
        return self.feature_dim + (PRESENCE_DIM if self.use_presence else 0)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> TemporalArtifactMeta:
        data = json.loads(text)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class FeatureScaler:
    """Per-feature standardization. Fit on training windows only; persisted with the model."""

    def __init__(self, mean: np.ndarray, std: np.ndarray, eps: float = 1e-8) -> None:
        self.mean = np.asarray(mean, dtype=np.float32)
        self.std = np.asarray(std, dtype=np.float32)
        self.eps = eps
        if self.mean.shape != self.std.shape:
            raise ValueError("scaler mean/std shape mismatch")

    MIN_STD = 1e-3  # floor: a near-constant feature (e.g. MediaPipe's wrist z, always ~0) must not amplify noise 10^6x

    @classmethod
    def fit(cls, x: np.ndarray, min_std: float = MIN_STD) -> FeatureScaler:
        flat = x.reshape(-1, x.shape[-1])
        return cls(flat.mean(axis=0), np.maximum(flat.std(axis=0), min_std))

    def transform(self, x: np.ndarray) -> np.ndarray:
        if x.shape[-1] != self.mean.shape[0]:
            raise ValueError(f"scaler expects {self.mean.shape[0]} features, got {x.shape[-1]}")
        return (np.asarray(x, dtype=np.float32) - self.mean) / (self.std + self.eps)

    def save(self, path: Path) -> None:
        np.savez(path, mean=self.mean, std=self.std, eps=np.array(self.eps))

    @classmethod
    def load(cls, path: Path) -> FeatureScaler:
        d = np.load(path)
        return cls(d["mean"], d["std"], float(d["eps"]))


def build_model(meta: TemporalArtifactMeta):  # -> torch.nn.Module (import deferred: torch is heavy)
    import torch
    from torch import nn

    class TemporalLandmarkLSTM(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(meta.input_dim, meta.hidden_size, num_layers=meta.num_layers,
                                batch_first=True, dropout=meta.dropout if meta.num_layers > 1 else 0.0)
            self.head = nn.Sequential(nn.Dropout(meta.dropout), nn.Linear(meta.hidden_size, 32), nn.ReLU(),
                                      nn.Linear(32, len(meta.classes)))

        def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: (B, T, D)
            if x.dim() != 3:
                raise ValueError("expected (batch, time, features)")
            if x.shape[1] < 2:
                raise ValueError("temporal model requires more than one time step")
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])

    return TemporalLandmarkLSTM()


def assemble_input(features: np.ndarray, presence: np.ndarray | None, scaler: FeatureScaler, use_presence: bool) -> np.ndarray:
    """(T,126) + (T,2) -> (T, D) scaled model input. Presence flags are not scaled."""
    x = scaler.transform(features)
    if use_presence:
        if presence is None:
            raise ValueError("presence flags required")
        x = np.concatenate([x, np.asarray(presence, dtype=np.float32)], axis=-1)
    return x


class TemporalArtifact:
    def __init__(self, meta: TemporalArtifactMeta, scaler: FeatureScaler, model: Any, path: Path | None = None) -> None:
        self.meta = meta
        self.scaler = scaler
        self.model = model
        self.path = path

    @classmethod
    def load(cls, directory: str | Path, device: str = "cpu") -> TemporalArtifact:
        import torch

        d = Path(directory)
        meta_p, model_p, scaler_p = d / "meta.json", d / "model.pt", d / "scaler.npz"
        for p in (meta_p, model_p, scaler_p):
            if not p.exists():
                raise FileNotFoundError(f"temporal artifact incomplete: missing {p.name} in {d}")
        meta = TemporalArtifactMeta.from_json(meta_p.read_text(encoding="utf-8"))
        if meta.window_frames < 2:
            raise ValueError("artifact window_frames < 2 is not a temporal model")
        if meta.preprocessing_version != SKIA_TEMPORAL_PREPROCESSING_VERSION:
            raise ValueError(f"preprocessing version {meta.preprocessing_version!r} != {SKIA_TEMPORAL_PREPROCESSING_VERSION!r}")
        scaler = FeatureScaler.load(scaler_p)
        model = build_model(meta)
        state = torch.load(model_p, map_location=device, weights_only=True)
        model.load_state_dict(state)
        model.eval()
        return cls(meta, scaler, model, d)

    def save(self, directory: str | Path) -> Path:
        import torch

        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(self.meta.to_json(), encoding="utf-8")
        self.scaler.save(d / "scaler.npz")
        torch.save(self.model.state_dict(), d / "model.pt")
        self.path = d
        return d

    def predict_proba(self, features: np.ndarray, presence: np.ndarray | None) -> np.ndarray:
        import torch

        x = assemble_input(features, presence, self.scaler, self.meta.use_presence)
        if x.shape[0] != self.meta.window_frames:
            raise ValueError(f"window length {x.shape[0]} != artifact window {self.meta.window_frames}")
        with torch.no_grad():
            logits = self.model(torch.from_numpy(x[None]).float())
            return torch.softmax(logits, dim=-1)[0].cpu().numpy().astype(np.float64)
