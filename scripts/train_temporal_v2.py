#!/usr/bin/env python
"""Train the hand-relative temporal model (temporal_v2) from raw landmark recordings.

    python scripts/extract_landmarks_v2.py --kaggle data/HandWashDataset --metc data/METC --own data/own
    python scripts/train_temporal_v2.py --data data/landmarks_v2 --test-own-rounds down2,front2 --device mps --out runs/v2/tcn32

Own rounds named in ``--test-own-rounds`` are never trained on (they are the honest test).
``--install`` copies the result to models/temporal_v2/current (what the live pipeline loads).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.common.config import resolve_path  # noqa: E402
from convergent.detection.pair_features import PairAugmentConfig  # noqa: E402
from convergent.detection.pair_training import (  # noqa: E402
    PairTrainConfig,
    load_raw_recordings,
    train_pair_model,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path("data/landmarks_v2"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--test-own-rounds", default="", help="own rounds held out as the test set (comma-separated)")
    ap.add_argument("--val-own-rounds", default="", help="own rounds used for model selection (comma-separated)")
    ap.add_argument("--exclude-datasets", default="", help="e.g. kaggle,metc")
    ap.add_argument("--arch", default="tcn", choices=["tcn", "gru", "lstm"])
    ap.add_argument("--window", type=int, default=32)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--dropout", type=float, default=0.25)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--own-weight", type=float, default=4.0)
    ap.add_argument("--samples-per-epoch", type=int, default=None)
    ap.add_argument("--no-augment", action="store_true")
    ap.add_argument("--device", default="cpu", help="cpu | mps | cuda")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--version", default="2.0.0")
    ap.add_argument("--init-from", default=None, help="fine-tune: start from this artifact dir (same window/classes/size); keeps the last epoch")
    ap.add_argument("--install", action="store_true", help="copy the artifact to models/temporal_v2/current")
    args = ap.parse_args()
    recs = load_raw_recordings(resolve_path(args.data))
    excl = {d.strip() for d in args.exclude_datasets.split(",") if d.strip()}
    recs = [r for r in recs if r.dataset not in excl]
    test = {f"own:{r.strip()}" for r in args.test_own_rounds.split(",") if r.strip()}
    val = {f"own:{r.strip()}" for r in args.val_own_rounds.split(",") if r.strip()}
    by_ds: dict[str, int] = {}
    for r in recs:
        by_ds[r.dataset] = by_ds.get(r.dataset, 0) + 1
    print(f"{len(recs)} recordings: {by_ds}; own test rounds: {sorted(test)}")
    cfg = PairTrainConfig(window=args.window, stride=args.stride, architecture=args.arch, hidden=args.hidden, layers=args.layers,
                          dropout=args.dropout, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr, patience=args.patience,
                          seed=args.seed, device=args.device, dataset_weights={"own": args.own_weight},
                          samples_per_epoch=args.samples_per_epoch, augment=None if args.no_augment else PairAugmentConfig(),
                          init_from=args.init_from)
    out = resolve_path(args.out)
    res = train_pair_model(recs, out, cfg, test_groups=test, val_groups=val, version=args.version,
                           provenance={"data": str(args.data), "recordings_by_dataset": by_ds})
    brief = {k: {kk: vv for kk, vv in v.items() if kk != "confusion"} if isinstance(v, dict) else v for k, v in res.metrics.items()}
    print(json.dumps(brief, indent=2))
    if args.install:
        dst = resolve_path("models/temporal_v2/current")
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(out, dst)
        print(f"installed to {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
