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
import re
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


def group_of(rec: Recording, group_regex: str | None = None) -> str:
    """Split group for a recording: ``subject_id`` (fallback recording_id), or the first group of
    ``group_regex`` applied to the recording id (e.g. ``_G_?(\\d+)`` = Kaggle sink/location group)."""
    if group_regex:
        m = re.search(group_regex, rec.recording_id)
        if m is None:
            raise ValueError(f"group regex {group_regex!r} does not match recording id {rec.recording_id!r}")
        return m.group(1)
    return rec.subject_id or rec.recording_id


def _observed_indices(presence: np.ndarray) -> np.ndarray:
    """Indices of frames where at least one hand is present (frames with no hands are skipped,
    exactly like SequenceBuffer.update() at inference; a resulting timestamp gap > max_gap_s
    breaks the window in windows_from_sequence)."""
    return np.where(np.asarray(presence).max(axis=1) > 0.5)[0]


def build_windows(recs: list[Recording], window: int, stride: int, max_gap_s: float, min_label_fraction: float = 0.8,
                  group_regex: str | None = None) -> WindowSet:
    xs, ps, ys, gs, rs = [], [], [], [], []
    for r in recs:
        grp = group_of(r, group_regex)
        # Frames with NO hand are skipped (same rule as SequenceBuffer.update() at inference); the
        # remaining frames are windowed with the same max_gap_s rule, so a window never contains an
        # all-absent frame and never spans a hand-less pause longer than max_gap_s.
        idx = _observed_indices(r.presence)
        if len(idx) < window:
            continue
        feats, pres, ts, labels = r.features[idx], r.presence[idx], r.timestamps[idx], r.labels[idx]
        for s, e in windows_from_sequence(feats, ts, window, stride, max_gap_s):
            labs = Counter(labels[s:e].tolist())
            lab, cnt = labs.most_common(1)[0]
            if cnt / (e - s) < min_label_fraction:
                continue  # window straddles a label change: skip (no mixed-motion windows)
            xs.append(feats[s:e])
            ps.append(pres[s:e])
            ys.append(lab)
            gs.append(grp)
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


def explicit_split(groups: list[str], val_groups: list[str], test_groups: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split by explicitly named groups (cross-validation folds). Val and test must be disjoint."""
    g = np.asarray(groups)
    vg, tg = set(val_groups), set(test_groups)
    if vg & tg:
        raise ValueError(f"val/test groups overlap: {sorted(vg & tg)}")
    missing = (vg | tg) - set(g.tolist())
    if missing:
        raise ValueError(f"unknown groups: {sorted(missing)}")
    test = np.where(np.isin(g, list(tg)))[0]
    val = np.where(np.isin(g, list(vg)))[0]
    train = np.where(~np.isin(g, list(vg | tg)))[0]
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


# --------------------------------------------------------------------------- training-time augmentation
@dataclass
class AugmentConfig:
    """Geometric augmentation applied to RAW landmark windows during training only.

    The inference preprocessing (``skia-sequence-v1``: raw normalized landmarks + presence) is
    unchanged; augmentation just makes the model less dependent on where in the frame and how
    large the hands were in the training videos (our faucet camera will differ from Kaggle's).

    * ``mirror``: horizontal flip (x -> 1-x), swap the left/right 63-blocks and presence columns,
      and swap the side suffix of the label (``2lt`` <-> ``2rt``). A mirrored video of
      "technique 2, left variant" is the right variant by construction, whatever "lt" turns out
      to denote (see configs/labels.yaml ``side_resolution``).
    * ``translate``: one random offset for both hands, x/y only, uniform in ±translate.
    * ``scale``: one random isotropic scale about the image centre, uniform in [1-scale, 1+scale].
    * ``jitter``: Gaussian noise (std) on every coordinate of present hands.
    Absent hands (presence 0, zero features) stay exactly zero.
    """

    mirror: bool = True
    translate: float = 0.08
    scale: float = 0.12
    jitter: float = 0.004

    def to_dict(self) -> dict[str, Any]:
        return {"mirror": self.mirror, "translate": self.translate, "scale": self.scale, "jitter": self.jitter}


def mirror_label(label: str) -> str:
    if label.endswith("lt"):
        return label[:-2] + "rt"
    if label.endswith("rt"):
        return label[:-2] + "lt"
    return label


def augment_windows(x: np.ndarray, presence: np.ndarray, labels: np.ndarray, cfg: AugmentConfig, rng: np.random.Generator
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """x (B,T,126) raw landmarks, presence (B,T,2), labels (B,) object/str. Returns augmented copies."""
    x = x.copy()
    presence = presence.copy()
    labels = labels.copy()
    b, t, _ = x.shape
    hands = x.reshape(b, t, 2, 21, 3)  # [left, right]
    present = presence.reshape(b, t, 2, 1, 1) > 0.5
    if cfg.mirror:
        flip = rng.random(b) < 0.5
        if flip.any():
            h = hands[flip]
            h[..., 0] = np.where(present[flip][..., 0], 1.0 - h[..., 0], 0.0)
            hands[flip] = h[:, :, ::-1]  # swap left/right blocks
            presence[flip] = presence[flip][:, :, ::-1]
            present = presence.reshape(b, t, 2, 1, 1) > 0.5
            labels[flip] = np.array([mirror_label(str(v)) for v in labels[flip]], dtype=labels.dtype)
    if cfg.scale > 0:
        s = rng.uniform(1 - cfg.scale, 1 + cfg.scale, size=(b, 1, 1, 1, 1))
        hands[..., :2] = (hands[..., :2] - 0.5) * s + 0.5
    if cfg.translate > 0:
        d = rng.uniform(-cfg.translate, cfg.translate, size=(b, 1, 1, 1, 2))
        hands[..., :2] = hands[..., :2] + d
    if cfg.jitter > 0:  # x/y only: z is MediaPipe's relative depth (wrist z == 0 by definition)
        hands[..., :2] += rng.normal(0.0, cfg.jitter, size=hands[..., :2].shape).astype(np.float32)
    hands *= present  # absent hands stay zero
    return hands.reshape(b, t, -1).astype(np.float32), presence.astype(np.float32), labels


def train_temporal_model(recs: list[Recording], out_dir: Path, window: int = 16, stride: int = 4, max_gap_s: float = 0.25,
                         epochs: int = 30, batch_size: int = 64, lr: float = 1e-3, hidden: int = 128, layers: int = 2, dropout: float = 0.2,
                         seed: int = 0, classes: list[str] | None = None, version: str = "0.1.0", provenance: dict[str, Any] | None = None,
                         patience: int = 6, device: str = "cpu", augment: AugmentConfig | None = None, class_weights: bool = True,
                         weight_decay: float = 1e-4, split_seed: int | None = None, group_regex: str | None = None,
                         val_groups: list[str] | None = None, test_groups: list[str] | None = None) -> TrainResult:
    import torch
    from torch import nn

    torch.manual_seed(seed)
    np.random.seed(seed)
    rng = np.random.default_rng(seed)
    classes = classes or SKIA_STEP_NAMES
    ws = build_windows(recs, window, stride, max_gap_s, group_regex=group_regex)
    unknown = sorted(set(ws.y) - set(classes))
    if unknown:
        raise ValueError(f"labels not in class list: {unknown}")
    if augment is not None and augment.mirror:
        missing = sorted({mirror_label(c) for c in classes} - set(classes))
        if missing:
            raise ValueError(f"mirror augmentation needs the side counterparts in the class list: {missing}")
    if val_groups is not None or test_groups is not None:
        tr, va, te = explicit_split(ws.groups, val_groups or [], test_groups or [])
    else:
        tr, va, te = grouped_split(ws.groups, seed=seed if split_seed is None else split_seed)
    scaler = FeatureScaler.fit(ws.x[tr])  # TRAIN ONLY
    meta = TemporalArtifactMeta(model_version=version, classes=list(classes), hidden_size=hidden, num_layers=layers, dropout=dropout,
                                window_frames=window, stride_frames=stride, max_gap_s=max_gap_s, created_at_utc=utc_now_iso(),
                                dataset_provenance={**(provenance or {}), "fingerprint": dataset_fingerprint(recs), "recordings": len(recs),
                                                    "subjects": len(set(r.subject_id for r in recs)), "windows": int(len(ws.y))},
                                split={"train_windows": int(len(tr)), "val_windows": int(len(va)), "test_windows": int(len(te)),
                                       "train_groups": sorted(set(np.asarray(ws.groups)[tr].tolist())),
                                       "val_groups": sorted(set(np.asarray(ws.groups)[va].tolist())),
                                       "test_groups": sorted(set(np.asarray(ws.groups)[te].tolist())),
                                       "grouping": f"recording_id regex {group_regex!r}" if group_regex else "subject_id (fallback recording_id)"},
                                notes=json.dumps({"augmentation": augment.to_dict() if augment else None, "class_weights": class_weights,
                                                  "weight_decay": weight_decay, "lr": lr, "batch_size": batch_size, "patience": patience, "seed": seed}))
    cls_index = {c: i for i, c in enumerate(classes)}
    y = np.array([cls_index[v] for v in ws.y], dtype=np.int64)
    y_labels = np.asarray(ws.y, dtype="<U8")

    def assemble(xs: np.ndarray, ps: np.ndarray) -> torch.Tensor:
        if len(xs) == 0:
            return torch.zeros((0, window, meta.input_dim))
        return torch.from_numpy(np.stack([assemble_input(xs[i], ps[i], scaler, meta.use_presence) for i in range(len(xs))])).float()

    def tensors(idx: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
        return assemble(ws.x[idx], ws.presence[idx]), torch.from_numpy(y[idx])

    xtr_raw, ptr_raw, ltr_raw = ws.x[tr], ws.presence[tr], y_labels[tr]
    xtr, ytr = tensors(tr)
    xva, yva = tensors(va)
    xte, yte = tensors(te)
    model = build_model(meta).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode="min", factor=0.5, patience=max(1, patience // 3))
    weights = None
    if class_weights:
        counts = np.bincount(y[tr], minlength=len(classes)).astype(np.float64)
        w = counts.sum() / (len(classes) * np.maximum(counts, 1.0))
        weights = torch.tensor(w, dtype=torch.float32, device=device)
    loss_fn = nn.CrossEntropyLoss(weight=weights, label_smoothing=0.05)
    best_state, best_val, bad, history = None, np.inf, 0, []
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(len(xtr))
        tot = 0.0
        if augment is not None:
            ax, ap_, al = augment_windows(xtr_raw, ptr_raw, ltr_raw, augment, rng)
            xep = assemble(ax, ap_)
            yep = torch.from_numpy(np.array([cls_index[str(v)] for v in al], dtype=np.int64))
        else:
            xep, yep = xtr, ytr
        for i in range(0, len(xep), batch_size):
            b = perm[i:i + batch_size]
            opt.zero_grad()
            loss = loss_fn(model(xep[b].to(device)), yep[b].to(device))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += float(loss) * len(b)
        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(xva.to(device)), yva.to(device))) if len(xva) else float("nan")
            val_acc = float((model(xva.to(device)).argmax(1).cpu() == yva).float().mean()) if len(xva) else float("nan")
        history.append({"epoch": epoch, "train_loss": tot / max(len(xtr), 1), "val_loss": val_loss, "val_acc": val_acc, "lr": opt.param_groups[0]["lr"]})
        if len(xva):
            sched.step(val_loss)
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
    from convergent.detection.evaluation import frame_metrics

    def split_metrics(xs: torch.Tensor, ys: torch.Tensor, note: str) -> dict[str, Any]:
        with torch.no_grad():
            pred = model(xs.to(device)).argmax(1).cpu().numpy()
        fm = frame_metrics([classes[i] for i in ys.numpy()], [classes[i] for i in pred], classes)
        return {"accuracy": fm.accuracy, "macro_f1": fm.f1_macro, "precision_macro": fm.precision_macro, "recall_macro": fm.recall_macro,
                "support": fm.support, "confusion": fm.confusion, "note": note}

    if len(xva):
        metrics["val"] = split_metrics(xva, yva, "validation subjects (used for early stopping / model selection)")
    if len(xte):
        metrics["test"] = split_metrics(xte, yte, "held-out subjects/recordings (grouped split; never used for any decision)")
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
