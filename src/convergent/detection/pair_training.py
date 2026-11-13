"""Training for the hand-relative temporal classifier (``temporal_v2``).

Dataset format ("raw landmark recordings", one ``.npz`` per video, written by
``scripts/extract_landmarks_v2.py``)::

    hands      (N, 2, 21, 3) float32  raw MediaPipe-normalised landmarks per slot (HandSlotter order)
    presence   (N, 2)        float32
    timestamps (N,)          float64  capture seconds
    labels     (N,)          <U24     technique name per frame ("palm_to_palm", ..., "none")
    attrs: recording_id, subject_id, dataset, group, aspect, source, fps, view, extractor_version

A window is the last ``window`` frames up to and including its end frame, on the frame clock:
frames without a hand stay in the window as empty frames (zeros, presence 0), and a window
that reaches back past the start of the recording is left-padded with empty frames. This is
exactly what :class:`pair_adapter.TemporalV2Adapter` feeds at inference, so the model does not
need a "warm-up" after a tracking dropout. A frame can end a window when a hand is visible in
it, at least ``min_present`` frames of the window have a hand, and its label is settled (see
:func:`build_window_index`). Splits are by *group* (a wash, a person, a recording round) so the
same person/session is never in two splits. Augmentation happens on raw landmarks per batch,
then :func:`pair_features.featurize` runs on the result.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from convergent.common.timestamps import utc_now_iso
from convergent.detection.labels import NONE, SCORED_TECHNIQUES
from convergent.detection.lstm_model import (
    PAIR_PREPROCESSING_VERSION,
    FeatureScaler,
    TemporalArtifact,
    TemporalArtifactMeta,
    build_model,
)
from convergent.detection.pair_features import (
    FEATURE_DIM_V2,
    REFERENCE_FPS,
    PairAugmentConfig,
    augment_raw,
    featurize,
    swap_slots,
)

V2_CLASSES: list[str] = [*SCORED_TECHNIQUES, NONE]
IGNORE_LABEL = "ignore"  # frames whose label is uncertain (around a label change); never a class
V2_MODEL_ID = "temporal_v2"
EXTRACTOR_VERSION_V2 = "raw-landmarks-v2"


@dataclass
class RawRecording:
    recording_id: str
    subject_id: str
    dataset: str
    group: str
    hands: np.ndarray
    presence: np.ndarray
    timestamps: np.ndarray
    labels: np.ndarray
    aspect: float = 4.0 / 3.0
    source: str = ""
    fps: float = 0.0
    view: str = ""

    def validate(self) -> None:
        n = len(self.timestamps)
        if self.hands.shape != (n, 2, 21, 3) or self.presence.shape != (n, 2) or self.labels.shape != (n,):
            raise ValueError(f"{self.recording_id}: inconsistent array shapes")
        if n > 1 and np.any(np.diff(self.timestamps) <= 0):
            raise ValueError(f"{self.recording_id}: timestamps are not strictly increasing")

    def save(self, path: Path) -> None:
        np.savez_compressed(path, hands=self.hands.astype(np.float32), presence=self.presence.astype(np.float32),
                            timestamps=self.timestamps.astype(np.float64), labels=self.labels.astype("<U24"),
                            recording_id=np.array(self.recording_id), subject_id=np.array(self.subject_id), dataset=np.array(self.dataset),
                            group=np.array(self.group), aspect=np.array(self.aspect), source=np.array(self.source), fps=np.array(self.fps),
                            view=np.array(self.view), extractor_version=np.array(EXTRACTOR_VERSION_V2))

    @classmethod
    def load(cls, path: Path) -> RawRecording:
        d = np.load(path, allow_pickle=False)
        rec = cls(str(d["recording_id"]), str(d["subject_id"]), str(d["dataset"]), str(d["group"]), d["hands"], d["presence"],
                  d["timestamps"], d["labels"].astype(str), float(d["aspect"]), str(d["source"]), float(d["fps"]), str(d["view"]))
        rec.validate()
        return rec


def load_raw_recordings(directory: Path) -> list[RawRecording]:
    recs = [RawRecording.load(p) for p in sorted(Path(directory).rglob("*.npz"))]
    if not recs:
        raise FileNotFoundError(f"no raw recordings (*.npz) under {directory}")
    return recs


# --------------------------------------------------------------------------- window index
@dataclass
class WindowIndex:
    """All frames of all recordings concatenated, plus one entry per usable window (identified by its last frame)."""

    hands: np.ndarray      # (N, 2, 21, 3)
    presence: np.ndarray   # (N, 2)
    timestamps: np.ndarray  # (N,)
    ends: np.ndarray       # (M,) global index of each window's last frame
    starts: np.ndarray     # (M,) global index of the first frame of that window's recording
    y: np.ndarray          # (M,) class index
    aspect: np.ndarray     # (M,)
    groups: np.ndarray     # (M,) str "<dataset>:<group>"
    datasets: np.ndarray   # (M,) str
    recordings: np.ndarray  # (M,) str

    def __len__(self) -> int:
        return int(len(self.ends))


LABEL_LOOKBACK = 12  # frames (0.8 s at 15 FPS) whose labels must agree with the window's label


def build_window_index(recs: list[RawRecording], window: int, stride: int = 3, min_present: int = 8, classes: list[str] | None = None,
                       min_label_fraction: float = 0.8, hold_frames: int = 0) -> WindowIndex:
    """Frame ``e`` ends a window when (a) a hand is visible in it or was visible at most
    ``hold_frames`` frames earlier (a short tracking dropout), (b) at least ``min_present`` of the
    last ``window`` frames have a hand, (c) its label is a class (not "ignore"), and (d) of the last
    ``LABEL_LOOKBACK`` frames at least two thirds carry a settled label and ``min_label_fraction`` of
    those agree with it (no windows that end in the middle of a change of technique)."""
    classes = classes or V2_CLASSES
    cidx = {c: i for i, c in enumerate(classes)}
    hs, ps, ts = [], [], []
    ends, starts, ys, asp, grp, dst, rcs = [], [], [], [], [], [], []
    offset = 0
    for r in recs:
        unknown = sorted(set(r.labels.tolist()) - set(classes) - {IGNORE_LABEL})
        if unknown:
            raise ValueError(f"{r.recording_id}: labels not in class list: {unknown}")
        n = len(r.timestamps)
        lab = np.array([cidx.get(v, -1) for v in r.labels])
        seen = r.presence.max(axis=1) > 0.5
        csum = np.concatenate([[0], np.cumsum(seen)])
        idx = np.arange(n)
        present = csum[idx + 1] - csum[np.maximum(idx + 1 - window, 0)]
        recent = (csum[idx + 1] - csum[np.maximum(idx - hold_frames, 0)]) > 0
        ok = recent & (present >= min_present) & (lab >= 0)
        for e in np.where(ok)[0]:
            if e % stride:
                continue
            seg = lab[max(0, e - LABEL_LOOKBACK + 1):e + 1]
            settled = seg[seg >= 0]
            if len(settled) < min(len(seg), LABEL_LOOKBACK) * 2 / 3 or (settled == lab[e]).mean() < min_label_fraction:
                continue
            ends.append(offset + e)
            starts.append(offset)
            ys.append(int(lab[e]))
            asp.append(r.aspect)
            grp.append(f"{r.dataset}:{r.group}")
            dst.append(r.dataset)
            rcs.append(r.recording_id)
        hs.append(r.hands)
        ps.append(r.presence)
        ts.append(r.timestamps)
        offset += n
    if not ends:
        raise ValueError("no windows could be built (no labelled frames with hands)")
    return WindowIndex(np.concatenate(hs).astype(np.float32), np.concatenate(ps).astype(np.float32), np.concatenate(ts),
                       np.array(ends), np.array(starts), np.array(ys), np.array(asp, np.float32), np.array(grp), np.array(dst), np.array(rcs))


def gather(wi: WindowIndex, sel: np.ndarray, window: int, speed: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Raw windows for the selected entries. ``speed`` (len(sel),) > 1 plays the motion faster,
    < 1 slower: frames are sampled at fractional positions (landmarks and timestamps interpolated
    when the hand is present on both sides, nearest frame otherwise) and the timestamps are
    rescaled, so the physical speed really changes. Positions before the start of the recording
    are empty frames. Returns raw (B,T,2,21,3), presence (B,T,2), timestamps (B,T)."""
    ends = wi.ends[sel].astype(np.float64)
    starts = wi.starts[sel]
    if speed is None:
        speed = np.ones(len(sel), np.float64)
    speed = np.asarray(speed, np.float64)
    back = np.linspace(window - 1, 0, window)[None, :] * speed[:, None]  # frames back from the end
    pos = ends[:, None] - back
    valid = pos >= starts[:, None] - 1e-6
    pos = np.maximum(pos, starts[:, None])
    i0 = np.floor(pos + 1e-9).astype(np.int64)
    i1 = np.minimum(i0 + 1, wi.ends[sel][:, None])
    w = (pos - i0).astype(np.float32)
    h0, h1, p0, p1 = wi.hands[i0], wi.hands[i1], wi.presence[i0], wi.presence[i1]
    both = (p0 > 0.5) & (p1 > 0.5)  # (B,T,2)
    near1 = (w >= 0.5)[..., None]
    lerp = (1.0 - w)[..., None, None, None] * h0 + w[..., None, None, None] * h1
    raw = np.where(both[..., None, None], lerp, np.where(near1[..., None, None], h1, h0))
    pres = np.where(both, 1.0, np.where(near1, p1, p0)).astype(np.float32)
    ts = (1.0 - w) * wi.timestamps[i0] + w * wi.timestamps[i1]
    ts = (ts - ts[:, -1:]) / speed[:, None]
    ts = np.where(valid, ts, -np.linspace(window - 1, 0, window)[None, :] / REFERENCE_FPS)
    raw = raw * valid[..., None, None, None]
    pres = pres * valid[..., None]
    raw = raw * (pres > 0.5)[..., None, None]
    return raw.astype(np.float32), pres.astype(np.float32), ts


def partition_groups(dataset: str, groups: list[str], seed: int = 0, val_fraction: float = 0.15, test_fraction: float = 0.15
                     ) -> tuple[set[str], set[str]]:
    """Deterministic (test, val) group names for one dataset. Depends only on the dataset name, its
    group names and the seed, so adding another dataset never moves a group between splits."""
    gs = sorted(set(groups))
    if len(gs) < 6:
        return set(), set()
    rng = np.random.default_rng([seed, zlib.crc32(dataset.encode())])
    rng.shuffle(gs)
    n_te, n_va = max(1, round(len(gs) * test_fraction)), max(1, round(len(gs) * val_fraction))
    return set(gs[:n_te]), set(gs[n_te:n_te + n_va])


def split_groups(wi: WindowIndex, test_groups: set[str], val_fraction: float = 0.15, test_fraction: float = 0.15, seed: int = 0,
                 val_groups: set[str] | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, list[str]]]:
    """Grouped split. ``test_groups`` (and optional ``val_groups``) are held out by name; every
    dataset with at least six other groups additionally gives ``test_fraction`` / ``val_fraction``
    of them (see :func:`partition_groups`)."""
    test, val = set(test_groups), set(val_groups or set())
    for ds in sorted(set(wi.datasets.tolist())):
        te_g, va_g = partition_groups(ds, sorted(set(wi.groups[wi.datasets == ds].tolist()) - test - val), seed, val_fraction, test_fraction)
        test |= te_g
        val |= va_g
    te = np.where(np.isin(wi.groups, list(test)))[0]
    va = np.where(np.isin(wi.groups, list(val)))[0]
    tr = np.where(~np.isin(wi.groups, list(test | val)))[0]
    if len(tr) == 0:
        raise ValueError("empty training split")
    return tr, va, te, {"train": sorted(set(wi.groups[tr].tolist())), "val": sorted(val), "test": sorted(test)}


# --------------------------------------------------------------------------- training
@dataclass
class PairTrainConfig:
    window: int = 32
    stride: int = 3
    min_present: int = 8       # frames with a hand needed in a window before the model may answer
    hold_frames: int = 5       # keep answering this many frames (0.33 s) after the last visible hand
    reset_gap_s: float = 1.0   # inference: a timestamp jump larger than this clears the history
    architecture: str = "tcn"
    hidden: int = 128
    layers: int = 4
    dropout: float = 0.25
    epochs: int = 40
    batch_size: int = 256
    lr: float = 2e-3
    weight_decay: float = 1e-4
    patience: int = 8
    seed: int = 0
    device: str = "cpu"
    speed_range: tuple[float, float] = (0.75, 1.3)
    dataset_weights: dict[str, float] = field(default_factory=lambda: {"own": 4.0})
    samples_per_epoch: int | None = None
    label_smoothing: float = 0.05
    augment: PairAugmentConfig | None = field(default_factory=PairAugmentConfig)
    # fine-tuning: start from this artifact's weights and feature scaler (window, classes and
    # architecture must match) and keep the LAST epoch instead of the best public-validation epoch,
    # because the public validation split does not measure the target camera
    init_from: str | None = None


@dataclass
class PairTrainResult:
    artifact: TemporalArtifact
    metrics: dict[str, Any]
    history: list[dict[str, float]]


def _features(wi: WindowIndex, sel: np.ndarray, window: int) -> np.ndarray:
    out = []
    for i in range(0, len(sel), 4096):
        s = sel[i:i + 4096]
        raw, pres, ts = gather(wi, s, window)
        out.append(featurize(raw, pres, wi.aspect[s], ts))
    return np.concatenate(out) if out else np.zeros((0, window, FEATURE_DIM_V2), np.float32)


def predict_symmetric(model: Any, x: np.ndarray, device: str = "cpu", batch: int = 2048) -> np.ndarray:
    """Class probabilities averaged over both slot orders. x: scaled features (B,T,D) -> (B,C)."""
    import torch

    out = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            xb = torch.from_numpy(x[i:i + batch]).float().to(device)
            out.append(torch.softmax(model(xb), dim=-1).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 0))


def _symmetric_probs(model: Any, feats: np.ndarray, scaler: FeatureScaler, device: str) -> np.ndarray:
    a = predict_symmetric(model, scaler.transform(feats), device)
    b = predict_symmetric(model, scaler.transform(swap_slots(feats)), device)
    return 0.5 * (a + b)


def evaluate_split(model: Any, feats: np.ndarray, y: np.ndarray, scaler: FeatureScaler, classes: list[str], device: str,
                   note: str = "") -> dict[str, Any]:
    from convergent.detection.evaluation import frame_metrics

    if len(y) == 0:
        return {"support": 0, "note": note}
    probs = _symmetric_probs(model, feats, scaler, device)
    pred = probs.argmax(1)
    fm = frame_metrics([classes[i] for i in y], [classes[i] for i in pred], classes)
    present = [c for c in classes if fm.per_class[c]["support"] > 0]
    return {"accuracy": fm.accuracy, "macro_f1": float(np.mean([fm.per_class[c]["f1"] for c in present])),
            "recall": {c: round(fm.per_class[c]["recall"], 4) for c in present}, "precision": {c: round(fm.per_class[c]["precision"], 4) for c in present},
            "support": int(len(y)), "confusion": fm.confusion, "note": note}


def train_pair_model(recs: list[RawRecording], out_dir: Path, cfg: PairTrainConfig | None = None, test_groups: set[str] | None = None,
                     val_groups: set[str] | None = None, version: str = "2.0.0", provenance: dict[str, Any] | None = None,
                     classes: list[str] | None = None, log: Any = print) -> PairTrainResult:
    import torch
    from torch import nn

    cfg = cfg or PairTrainConfig()
    classes = classes or V2_CLASSES
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    wi = build_window_index(recs, cfg.window, cfg.stride, cfg.min_present, classes, hold_frames=cfg.hold_frames)
    tr, va, te, split = split_groups(wi, test_groups or set(), seed=cfg.seed, val_groups=val_groups)
    log(f"windows: train={len(tr)} val={len(va)} test={len(te)}  frames={len(wi.timestamps)}")
    xva, xte = _features(wi, va, cfg.window), _features(wi, te, cfg.window)
    fit_sel = tr if len(tr) <= 20000 else rng.choice(tr, 20000, replace=False)
    init_art = None
    if cfg.init_from:
        init_art = TemporalArtifact.load(Path(cfg.init_from))
        im = init_art.meta
        if (im.window_frames, list(im.classes), im.architecture, im.hidden_size, im.num_layers) != (cfg.window, list(classes), cfg.architecture, cfg.hidden, cfg.layers):
            raise ValueError(f"--init-from artifact {cfg.init_from} does not match window/classes/architecture/size")
        scaler = init_art.scaler
        log(f"fine-tuning from {cfg.init_from}")
    else:
        scaler = FeatureScaler.fit(_features(wi, fit_sel, cfg.window))  # TRAIN ONLY
    meta = TemporalArtifactMeta(model_id=V2_MODEL_ID, model_version=version, architecture=cfg.architecture, classes=list(classes),
                                feature_dim=FEATURE_DIM_V2, use_presence=False, hidden_size=cfg.hidden, num_layers=cfg.layers,
                                dropout=cfg.dropout, window_frames=cfg.window, stride_frames=cfg.stride, target_fps=REFERENCE_FPS,
                                max_gap_s=cfg.reset_gap_s, min_present_frames=cfg.min_present, hold_frames=cfg.hold_frames, preprocessing_version=PAIR_PREPROCESSING_VERSION, feed_mode="slots",
                                created_at_utc=utc_now_iso(),
                                dataset_provenance={**(provenance or {}), "recordings": len(recs), "windows": len(wi),
                                                    "datasets": {d: int((wi.datasets == d).sum()) for d in sorted(set(wi.datasets.tolist()))}},
                                split={"grouping": "<dataset>:<group> (wash / person / recording round)", "train_windows": int(len(tr)),
                                       "val_windows": int(len(va)), "test_windows": int(len(te)), **{f"{k}_groups": v for k, v in split.items()}},
                                notes=json.dumps({"augmentation": cfg.augment.to_dict() if cfg.augment else None, "speed_range": cfg.speed_range,
                                                  "dataset_weights": cfg.dataset_weights, "lr": cfg.lr, "batch_size": cfg.batch_size,
                                                  "weight_decay": cfg.weight_decay, "seed": cfg.seed, "symmetric_inference": True}))
    model = build_model(meta)
    if init_art is not None:
        model.load_state_dict(init_art.model.state_dict())
    model = model.to(cfg.device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    n_epoch = cfg.samples_per_epoch or len(tr)
    steps = max(1, (n_epoch // cfg.batch_size)) * cfg.epochs
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=cfg.lr, total_steps=steps, pct_start=0.1)
    # sampling weights: every (dataset, class) cell is equally likely, then the dataset weight applies
    ytr, dtr = wi.y[tr], wi.datasets[tr]
    w = np.zeros(len(tr), np.float64)
    for d in set(dtr.tolist()):
        md = dtr == d
        counts = np.bincount(ytr[md], minlength=len(classes)).astype(np.float64)
        w[md] = cfg.dataset_weights.get(d, 1.0) * md.sum() / (np.count_nonzero(counts) * np.maximum(counts[ytr[md]], 1.0))
    w /= w.sum()
    loss_fn = nn.CrossEntropyLoss(label_smoothing=cfg.label_smoothing)
    best_state, best_score, bad, history = None, -1.0, 0, []
    for epoch in range(cfg.epochs):
        model.train()
        order = rng.choice(len(tr), size=n_epoch, replace=True, p=w)
        tot, seen = 0.0, 0
        for i in range(0, n_epoch - cfg.batch_size + 1, cfg.batch_size):
            b = tr[order[i:i + cfg.batch_size]]
            speed = rng.uniform(*cfg.speed_range, size=len(b)) if cfg.speed_range else None
            raw, pres, ts = gather(wi, b, cfg.window, speed)
            if cfg.augment is not None:
                raw, pres = augment_raw(raw, pres, wi.aspect[b], cfg.augment, rng)
            x = torch.from_numpy(scaler.transform(featurize(raw, pres, wi.aspect[b], ts))).float().to(cfg.device)
            y = torch.from_numpy(wi.y[b]).to(cfg.device)
            opt.zero_grad()
            loss = loss_fn(model(x), y)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += float(loss) * len(b)
            seen += len(b)
        model.eval()
        vm = evaluate_split(model, xva, wi.y[va], scaler, classes, cfg.device)
        score = float(vm.get("macro_f1", 0.0))
        history.append({"epoch": epoch, "train_loss": tot / max(seen, 1), "val_acc": float(vm.get("accuracy", 0.0)), "val_macro_f1": score})
        log(f"epoch {epoch:02d} loss={tot / max(seen, 1):.4f} val_acc={vm.get('accuracy', 0):.4f} val_f1={score:.4f}")
        if score > best_score or len(va) == 0 or cfg.init_from:
            best_score, bad = score, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= cfg.patience:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    metrics: dict[str, Any] = {"history_epochs": len(history), "best_val_macro_f1": best_score,
                               "val": evaluate_split(model, xva, wi.y[va], scaler, classes, cfg.device, "validation groups (model selection)"),
                               "test": evaluate_split(model, xte, wi.y[te], scaler, classes, cfg.device, "held-out groups (never used for any decision)")}
    for d in sorted(set(wi.datasets[te].tolist())):
        m = wi.datasets[te] == d
        metrics[f"test_{d}"] = evaluate_split(model, xte[m], wi.y[te][m], scaler, classes, cfg.device, f"held-out groups of dataset {d}")
    # temperature calibration on validation predictions (never in-sample)
    calibrator = None
    if len(va) >= 50:
        from convergent.detection.confidence_calibration import Calibrator

        calibrator = Calibrator.fit_temperature(_symmetric_probs(model, xva, scaler, cfg.device), wi.y[va])
        metrics["calibration"] = {"temperature": calibrator.temperature, "ece_before": calibrator.ece_before, "ece_after": calibrator.ece_after}
    meta.metrics = metrics
    art = TemporalArtifact(meta, scaler, model.cpu())
    art.save(out_dir)
    (Path(out_dir) / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    if calibrator is not None:
        calibrator.save(Path(out_dir) / "calibrator.json")
    return PairTrainResult(art, metrics, history)


# --------------------------------------------------------------------------- synthetic data (smoke tests ONLY)
def synthetic_raw_recordings(n_groups: int = 8, frames: int = 90, seed: int = 0, classes: list[str] | None = None) -> list[RawRecording]:
    """Fake two-hand motions, one class per recording: the class decides where the second hand
    sits around the first and how it is turned. Exercises the code path only; a model trained on
    this says nothing about handwashing."""
    rng = np.random.default_rng(seed)
    classes = classes or V2_CLASSES
    recs = []
    finger = np.linspace(0.0, 0.16, 21, dtype=np.float32)
    for g in range(n_groups):
        spread = rng.normal(0.0, 0.012, size=(2, 21)).astype(np.float32)
        centre = rng.uniform(0.35, 0.65, size=2)
        for ci, lab in enumerate(classes):
            t = np.arange(frames) / REFERENCE_FPS
            ang = 2 * np.pi * ci / len(classes)   # where hand B sits around hand A
            turn = np.pi * ci / len(classes)      # how hand B is turned
            hands = np.zeros((frames, 2, 21, 3), np.float32)
            for i in range(frames):
                wob = 0.02 * np.sin(2 * np.pi * 1.2 * t[i])
                for k, (base_ang, pos) in enumerate([(0.0, centre), (turn, centre + (0.2 + wob) * np.array([np.cos(ang), np.sin(ang)]))]):
                    d = np.array([np.sin(base_ang), -np.cos(base_ang)])  # finger direction
                    n = np.array([-d[1], d[0]])
                    hands[i, k, :, 0] = pos[0] + finger * d[0] + spread[k] * n[0]
                    hands[i, k, :, 1] = pos[1] + finger * d[1] + spread[k] * n[1]
                hands[i] += rng.normal(0, 0.002, size=(2, 21, 3))
            hands[..., 0] /= 4.0 / 3.0
            hands[:, :, 0, 2] = 0.0
            recs.append(RawRecording(f"syn_g{g}_{lab}", f"g{g}", "synthetic", f"g{g}", hands, np.ones((frames, 2), np.float32), t,
                                     np.array([lab] * frames), 4.0 / 3.0, "synthetic", REFERENCE_FPS))
    return recs
