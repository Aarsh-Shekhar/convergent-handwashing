#!/usr/bin/env python
"""Train the corrected multi-frame temporal landmark classifier (S-Kia branch).

Input: a directory of per-recording landmark sequences produced by
``scripts/extract_landmark_sequences.py`` (see convergent.detection.training for the format).

    python scripts/train_lstm.py --data data/landmark_sequences --out models/skia_temporal/v0.1.0 \
        --window 16 --stride 4 --epochs 40 --version 0.1.0

    # pipeline smoke test on deterministic synthetic motions (NOT a handwashing model):
    python scripts/train_lstm.py --synthetic --out models/skia_temporal/synthetic-smoke --epochs 5

After training, point ``skia.temporal_artifact_dir`` (configs/development.yaml) at the artifact
directory, or symlink/copy it to ``models/skia_temporal/current``.

What this script guarantees (spec §Stage 4):
  * windows are built from contiguous, timestamp-ordered frames of ONE recording;
  * train/val/test are split by subject (fallback: recording) – no frame-level leakage;
  * the scaler is fitted on training windows only and saved next to the model;
  * class list, preprocessing version, window/FPS, dataset fingerprint and metrics are in meta.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.detection.training import (  # noqa: E402
    AugmentConfig,
    load_recordings,
    synthetic_recordings,
    train_temporal_model,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=None, help="directory of recording .npz files")
    ap.add_argument("--synthetic", action="store_true", help="use deterministic synthetic recordings (smoke test only)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--window", type=int, default=16)
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--max-gap", type=float, default=0.25)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--no-class-weights", action="store_true")
    ap.add_argument("--augment", type=int, default=1, help="1 = geometric training-time augmentation (mirror+side-label swap, translate, scale, jitter)")
    ap.add_argument("--aug-translate", type=float, default=0.08)
    ap.add_argument("--aug-scale", type=float, default=0.12)
    ap.add_argument("--aug-jitter", type=float, default=0.004)
    ap.add_argument("--no-mirror", action="store_true")
    ap.add_argument("--split-seed", type=int, default=None, help="seed for the grouped split (default: --seed); keep it FIXED across a sweep")
    args = ap.parse_args()
    if args.window < 2:
        ap.error("--window must be > 1: a one-step window is not a temporal model")
    if args.synthetic:
        recs = synthetic_recordings(seed=args.seed)
        provenance = {"dataset": "SYNTHETIC smoke-test motions", "note": "no handwashing content; validates the code path only"}
        version = f"{args.version}-synthetic-smoke"
    else:
        if args.data is None:
            ap.error("--data is required unless --synthetic")
        recs = load_recordings(args.data)
        provenance = {"dataset": str(args.data), "recordings": [r.recording_id for r in recs], "sources": sorted({r.source for r in recs})}
        version = args.version
    aug = AugmentConfig(mirror=not args.no_mirror, translate=args.aug_translate, scale=args.aug_scale, jitter=args.aug_jitter) if args.augment else None
    res = train_temporal_model(recs, args.out, args.window, args.stride, args.max_gap, args.epochs, args.batch_size, args.lr, args.hidden,
                               args.layers, args.dropout, args.seed, version=version, provenance=provenance, patience=args.patience,
                               augment=aug, class_weights=not args.no_class_weights, weight_decay=args.weight_decay, split_seed=args.split_seed)
    print(json.dumps({"artifact": str(args.out), "version": version, "metrics": res.metrics, "split": res.artifact.meta.split}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
