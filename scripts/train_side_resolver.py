#!/usr/bin/env python
"""Train the side resolver (which hand receives a sided technique) on the Kaggle landmark sequences.

    python scripts/train_side_resolver.py --data data/landmark_sequences --out models/side_resolver/current

Input: the per-video .npz written by scripts/extract_landmark_sequences.py (features (N,126) =
left|right raw landmarks by MediaPipe label, presence (N,2), labels like "2lt"/"5rt"). The
MediaPipe left/right assignment is NOT used as a feature – only as the two sources of landmark
arrays – so the model is label-free (detection/side_resolver.side_features).

Ground truth: Kaggle "Step_k_Left" = the LEFT hand receives (verified on the clips, see
configs/labels.yaml). Reports 5-fold cross-validation grouped by recording session (frame and
per-clip majority accuracy, per technique), then fits on everything and writes the artifact.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.detection.side_resolver import (  # noqa: E402
    FEATURE_VERSION,
    N_FEATURES,
    SIDED_ORDER,
    build_model,
    side_features,
)

KAGGLE_STEP_TO_TECHNIQUE = {"2": "back_of_hand", "4": "backs_of_fingers", "5": "thumb_rubbing", "6": "fingertip_rubbing", "7": "wrist_rubbing"}


def load(data: Path):
    xs, ys, groups, clips, techs = [], [], [], [], []
    for f in sorted(glob.glob(str(data / "*.npz"))):
        d = np.load(f, allow_pickle=True)
        lab = str(d["labels"][0])
        if lab[-2:] not in ("lt", "rt") or lab[0] not in KAGGLE_STEP_TO_TECHNIQUE:
            continue
        tech = KAGGLE_STEP_TO_TECHNIQUE[lab[0]]
        X = d["features"].reshape(-1, 2, 21, 3)
        P = d["presence"]
        for i in np.where(P.sum(1) > 0)[0]:
            hands = [X[i, s] for s in range(2) if P[i, s] > 0.5]
            xs.append(side_features(hands, tech))
            ys.append(1 if lab.endswith("rt") else 0)  # receiving hand: 0 = left, 1 = right
            groups.append(str(d["subject_id"]))
            clips.append(str(d["recording_id"]))
            techs.append(tech)
    return np.stack(xs), np.array(ys), np.array(groups), np.array(clips), np.array(techs)


def fit(x: np.ndarray, y: np.ndarray, hidden: tuple[int, ...], epochs: int, seed: int):
    import torch
    from torch import nn

    torch.manual_seed(seed)
    mu, sd = x.mean(0), x.std(0) + 1e-6
    xt = torch.from_numpy(((x - mu) / sd).astype(np.float32))
    yt = torch.from_numpy(y.astype(np.int64))
    model = build_model(x.shape[1], hidden)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss()
    for _ in range(epochs):
        model.train()
        perm = torch.randperm(len(xt))
        for i in range(0, len(xt), 256):
            b = perm[i : i + 256]
            opt.zero_grad()
            loss_fn(model(xt[b]), yt[b]).backward()
            opt.step()
    model.eval()
    return model, mu.astype(np.float32), sd.astype(np.float32)


def predict(model, mu, sd, x):
    import torch

    with torch.no_grad():
        return torch.softmax(model(torch.from_numpy(((x - mu) / sd).astype(np.float32))), 1)[:, 1].numpy()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "landmark_sequences")
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "side_resolver" / "current")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--hidden", default="128,64")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--no-cv", action="store_true")
    args = ap.parse_args()
    hidden = tuple(int(h) for h in args.hidden.split(","))
    t0 = time.time()
    x, y, groups, clips, techs = load(args.data)
    assert x.shape[1] == N_FEATURES
    print(f"{len(y)} frames, {len(np.unique(clips))} clips, {len(np.unique(groups))} sessions")
    metrics: dict = {"cv": None}
    if not args.no_cv:
        from sklearn.model_selection import GroupKFold

        prob = np.zeros(len(y))
        for tr, te in GroupKFold(5).split(x, y, groups):
            m, mu, sd = fit(x[tr], y[tr], hidden, args.epochs, args.seed)
            prob[te] = predict(m, mu, sd, x[te])
        pred = (prob > 0.5).astype(int)
        per_tech = {}
        for t in SIDED_ORDER:
            sel = techs == t
            cl = np.unique(clips[sel])
            per_tech[t] = {"frame_accuracy": float((pred[sel] == y[sel]).mean()),
                           "clip_majority_accuracy": float(np.mean([(prob[clips == c].mean() > 0.5) == bool(y[clips == c][0]) for c in cl])),
                           "frames": int(sel.sum()), "clips": int(len(cl))}
            print(f"{t:20s} frame {per_tech[t]['frame_accuracy']:.3f}  clip-majority {per_tech[t]['clip_majority_accuracy']:.3f}  ({len(cl)} clips)")
        metrics["cv"] = {"folds": 5, "grouped_by": "kaggle session id", "frame_accuracy": float((pred == y).mean()), "per_technique": per_tech}
        print(f"overall frame accuracy {metrics['cv']['frame_accuracy']:.3f}")
    model, mu, sd = fit(x, y, hidden, args.epochs, args.seed)
    import torch

    args.out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), args.out / "model.pt")
    np.savez(args.out / "scaler.npz", mu=mu, sd=sd)
    meta = {"model_version": args.version, "feature_version": FEATURE_VERSION, "classes": ["left", "right"], "techniques": SIDED_ORDER,
            "input_dim": int(x.shape[1]), "hidden": list(hidden), "epochs": args.epochs, "seed": args.seed,
            "camera_convention": "overhead, person at the bottom of the frame (image-left = person's left); set side_resolver.mirrored when the camera faces the user",
            "label_convention": "side = hand RECEIVING the action (static hand); Kaggle Step_k_Left = left receives, verified on frames 2026-11-14",
            "training_data": {"source": str(args.data), "frames": int(len(y)), "clips": int(len(np.unique(clips))), "sessions": int(len(np.unique(groups))),
                              "class_balance_right": float(y.mean())},
            "metrics": metrics, "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - t0, 1)}
    (args.out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {args.out} in {meta['seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
