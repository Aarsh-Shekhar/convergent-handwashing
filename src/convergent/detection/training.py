"""Training utilities for the corrected temporal landmark classifier.

Dataset format ("landmark sequence recordings"): a directory of ``*.npz`` files, one per
contiguous recording, each with::

    features   (N, 126) float32   S-Kia layout: left(63) then right(63) raw normalized landmarks
    presence   (N, 2)   float32   [left_present, right_present]
    timestamps (N,)     float64   capture seconds (video PTS)
    labels     (N,)     <U8       native S-Kia label per frame ("1", "2lt", ...)
    attrs: recording_id, subject_id, source, fps, extractor_version   (stored as 0-d string arrays)

``scripts/extract_landmark_sequences.py`` produces these from Kaggle-style videos. Windows are
built per recording with :func:`windows_from_sequence` (contiguous timestamps only), the split
is grouped by ``subject_id`` (fallback ``recording_id``), the scaler is fitted on the training
windows only and persisted with the model, and every artifact records dataset provenance.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from convergent.common.timestamps import utc_now_iso
from convergent.detection.lstm_model import (
    FEATURE_DIM,
    FeatureScaler,
    TemporalArtifact,
    TemporalArtifactMeta,
    assemble_input,
    build_model,
)
from convergent.detection.sequence_buffer import windows_from_sequence
from convergent.detection.skia_adapter import SKIA_STEP_NAMES

EXTRACTOR_VERSION = "landmark-sequences-v1"


@dataclass
class Recording:
    recording_id: str
    subject_id: str
    features: np.ndarray
    presence: np.ndarray
    timestamps: np.ndarray
    labels: np.ndarray
    source: str = ""
    fps: float = 0.0

    def validate(self) -> None:
        n = len(self.timestamps)
        if self.features.shape != (n, FEATURE_DIM) or self.presence.shape != (n, 2) or self.labels.shape != (n,):
            raise ValueError(f"{self.recording_id}: inconsistent array shapes")
        if n > 1 and np.any(np.diff(self.timestamps) <= 0):
            raise ValueError(f"{self.recording_id}: timestamps are not strictly increasing (frame order unreliable)")

    def save(self, path: Path) -> None:
        np.savez_compressed(path, features=self.features.astype(np.float32), presence=self.presence.astype(np.float32),
                            timestamps=self.timestamps.astype(np.float64), labels=self.labels.astype("<U8"),
                            recording_id=np.array(self.recording_id), subject_id=np.array(self.subject_id), source=np.array(self.source),
                            fps=np.array(self.fps), extractor_version=np.array(EXTRACTOR_VERSION))

    @classmethod
    def load(cls, path: Path) -> Recording:
        d = np.load(path, allow_pickle=False)
        rec = cls(str(d["recording_id"]), str(d["subject_id"]), d["features"], d["presence"], d["timestamps"], d["labels"].astype(str),
                  str(d["source"]) if "source" in d else "", float(d["fps"]) if "fps" in d else 0.0)
        rec.validate()
        return rec


def load_recordings(directory: Path) -> list[Recording]:
    recs = [Recording.load(p) for p in sorted(directory.glob("*.npz"))]
    if not recs:
        raise FileNotFoundError(f"no recordings (*.npz) in {directory}")
    return recs


@dataclass
class WindowSet:
    x: np.ndarray  # (M, T, 126)
    presence: np.ndarray  # (M, T, 2)
    y: list[str]
    groups: list[str]
    recordings: list[str]


def build_windows(recs: list[Recording], window: int, stride: int, max_gap_s: float, min_label_fraction: float = 0.8) -> WindowSet:
    xs, ps, ys, gs, rs = [], [], [], [], []
    for r in recs:
        for s, e in windows_from_sequence(r.features, r.timestamps, window, stride, max_gap_s):
            labs = Counter(r.labels[s:e].tolist())
            lab, cnt = labs.most_common(1)[0]
            if cnt / (e - s) < min_label_fraction:
                continue  # window straddles a label change: skip (no mixed-motion windows)
            xs.append(r.features[s:e])
            ps.append(r.presence[s:e])
            ys.append(lab)
            gs.append(r.subject_id or r.recording_id)
            rs.append(r.recording_id)
    if not xs:
        raise ValueError("no windows could be built (recordings too short or gaps too large)")
    return WindowSet(np.stack(xs).astype(np.float32), np.stack(ps).astype(np.float32), ys, gs, rs)


def grouped_split(groups: list[str], val_fraction: float = 0.15, test_fraction: float = 0.15, seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split window indices by group (subject/recording) – no group appears in two splits."""
    uniq = sorted(set(groups))
    if len(uniq) < 3:
        raise ValueError(f"grouped split needs >= 3 groups (subjects/recordings), got {len(uniq)}")
    rng = np.random.default_rng(seed)
    rng.shuffle(uniq)
    n_test = max(1, int(round(len(uniq) * test_fraction)))
    n_val = max(1, int(round(len(uniq) * val_fraction)))
    test_g, val_g = set(uniq[:n_test]), set(uniq[n_test:n_test + n_val])
    g = np.asarray(groups)
    test = np.where(np.isin(g, list(test_g)))[0]
    val = np.where(np.isin(g, list(val_g)))[0]
    train = np.where(~np.isin(g, list(test_g | val_g)))[0]
    if len(train) == 0:
        raise ValueError("empty training split")
    return train, val, test


def dataset_fingerprint(recs: list[Recording]) -> str:
    h = hashlib.sha256()
    for r in recs:
        h.update(r.recording_id.encode())
        h.update(np.ascontiguousarray(r.features[:64]).tobytes())
        h.update(str(len(r.timestamps)).encode())
    return h.hexdigest()[:16]


@dataclass
class TrainResult:
    artifact: TemporalArtifact
    metrics: dict[str, Any]
    history: list[dict[str, float]] = field(default_factory=list)


def train_temporal_model(recs: list[Recording], out_dir: Path, window: int = 16, stride: int = 4, max_gap_s: float = 0.25,
                         epochs: int = 30, batch_size: int = 64, lr: float = 1e-3, hidden: int = 128, layers: int = 2, dropout: float = 0.2,
                         seed: int = 0, classes: list[str] | None = None, version: str = "0.1.0", provenance: dict[str, Any] | None = None,
                         patience: int = 6, device: str = "cpu") -> TrainResult:
    import torch
    from torch import nn

    torch.manual_seed(seed)
    np.random.seed(seed)
    classes = classes or SKIA_STEP_NAMES
    ws = build_windows(recs, window, stride, max_gap_s)
    unknown = sorted(set(ws.y) - set(classes))
    if unknown:
        raise ValueError(f"labels not in class list: {unknown}")
    tr, va, te = grouped_split(ws.groups, seed=seed)
    scaler = FeatureScaler.fit(ws.x[tr])  # TRAIN ONLY
    meta = TemporalArtifactMeta(model_version=version, classes=list(classes), hidden_size=hidden, num_layers=layers, dropout=dropout,
                                window_frames=window, stride_frames=stride, max_gap_s=max_gap_s, created_at_utc=utc_now_iso(),
                                dataset_provenance={**(provenance or {}), "fingerprint": dataset_fingerprint(recs), "recordings": len(recs),
                                                    "subjects": len(set(r.subject_id for r in recs)), "windows": int(len(ws.y))},
                                split={"train_windows": int(len(tr)), "val_windows": int(len(va)), "test_windows": int(len(te)),
                                       "train_groups": sorted(set(np.asarray(ws.groups)[tr].tolist())),
                                       "val_groups": sorted(set(np.asarray(ws.groups)[va].tolist())),
                                       "test_groups": sorted(set(np.asarray(ws.groups)[te].tolist())), "grouping": "subject_id (fallback recording_id)"})
    cls_index = {c: i for i, c in enumerate(classes)}
    y = np.array([cls_index[v] for v in ws.y], dtype=np.int64)

    def tensors(idx: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
        x = np.stack([assemble_input(ws.x[i], ws.presence[i], scaler, meta.use_presence) for i in idx]) if len(idx) else np.zeros((0, window, meta.input_dim), np.float32)
        return torch.from_numpy(x).float(), torch.from_numpy(y[idx])

    xtr, ytr = tensors(tr)
    xva, yva = tensors(va)
    xte, yte = tensors(te)
    model = build_model(meta).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    best_state, best_val, bad, history = None, np.inf, 0, []
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(len(xtr))
        tot = 0.0
        for i in range(0, len(xtr), batch_size):
            b = perm[i:i + batch_size]
            opt.zero_grad()
            loss = loss_fn(model(xtr[b].to(device)), ytr[b].to(device))
            loss.backward()
            opt.step()
            tot += float(loss) * len(b)
        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(xva.to(device)), yva.to(device))) if len(xva) else float("nan")
            val_acc = float((model(xva.to(device)).argmax(1).cpu() == yva).float().mean()) if len(xva) else float("nan")
        history.append({"epoch": epoch, "train_loss": tot / max(len(xtr), 1), "val_loss": val_loss, "val_acc": val_acc})
        if len(xva) and val_loss < best_val:
            best_val, bad = val_loss, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience and len(xva):
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    metrics: dict[str, Any] = {"history_epochs": len(history), "best_val_loss": None if best_val == np.inf else best_val}
    if len(xte):
        from convergent.detection.evaluation import frame_metrics

        with torch.no_grad():
            pred = model(xte.to(device)).argmax(1).cpu().numpy()
        fm = frame_metrics([classes[i] for i in yte.numpy()], [classes[i] for i in pred], classes)
        metrics["test"] = {"accuracy": fm.accuracy, "macro_f1": fm.f1_macro, "precision_macro": fm.precision_macro, "recall_macro": fm.recall_macro,
                           "support": fm.support, "confusion": fm.confusion, "note": "held-out subjects/recordings (grouped split)"}
    meta.metrics = metrics
    art = TemporalArtifact(meta, scaler, model.cpu())
    art.save(out_dir)
    (out_dir / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    return TrainResult(art, metrics, history)


# --------------------------------------------------------------------------- synthetic data (pipeline smoke test ONLY)
def synthetic_recordings(n_subjects: int = 6, per_subject: int = 2, frames: int = 120, fps: float = 15.0, seed: int = 0,
                         classes: list[str] | None = None) -> list[Recording]:
    """Deterministic fake landmark motions, one class per recording. Only to exercise the
    training/inference code path; a model trained on this says nothing about handwashing."""
    rng = np.random.default_rng(seed)
    classes = classes or SKIA_STEP_NAMES
    recs = []
    for s in range(n_subjects):
        for k in range(per_subject):
            lab = classes[(s * per_subject + k) % len(classes)]
            ci = classes.index(lab)
            t = np.arange(frames) / fps
            base = rng.normal(0.5, 0.05, size=(2, 21, 3))
            feats = np.zeros((frames, 126), dtype=np.float32)
            for i in range(frames):
                phase = 2 * np.pi * (0.5 + 0.1 * ci) * t[i]
                motion = 0.03 * np.array([np.sin(phase + ci), np.cos(phase * 0.7), 0.0])
                hands = base + motion + rng.normal(0, 0.004, size=base.shape) + 0.01 * ci
                feats[i] = hands.reshape(-1)
            recs.append(Recording(f"synthetic_s{s}_r{k}", f"subject{s}", feats, np.ones((frames, 2), np.float32), t, np.array([lab] * frames), "synthetic", fps))
    return recs
