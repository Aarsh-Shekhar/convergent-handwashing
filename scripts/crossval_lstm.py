#!/usr/bin/env python
"""Leave-one-group-out cross-validation for the temporal LSTM (stricter generalisation estimate).

The Kaggle hand-wash dataset has 25 recording sessions in 5 sink/location groups
(``HandWash_NNN_A_XX_G_0k``). Sessions in one group share the sink, camera placement and most
likely the washer, so a session-level split can still leak "who/where" into the test set.
This script holds out one *group* at a time (``--group-regex`` default = the Kaggle ``G`` id),
uses one other group for early stopping, trains on the remaining groups, and reports the test
metrics per fold plus mean ± std. Nothing from a held-out fold is used for any decision.

    python scripts/crossval_lstm.py --data data/landmark_sequences --out runs/lstm_crossval \
        --window 24 --stride 2 --hidden 128 --epochs 80

Use the same hyper-parameters that ``scripts/sweep_lstm.py`` selected; this script does not pick
hyper-parameters, it only estimates how the chosen configuration generalises to unseen groups.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.detection.training import (  # noqa: E402
    AugmentConfig,
    group_of,
    load_recordings,
    train_temporal_model,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "lstm_crossval")
    ap.add_argument("--group-regex", default=r"_G_?(\d+)$", help="regex on recording_id whose group 1 is the fold id")
    ap.add_argument("--window", type=int, default=16)
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--patience", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-augment", action="store_true")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    recs = load_recordings(args.data)
    groups = sorted({group_of(r, args.group_regex) for r in recs})
    if len(groups) < 3:
        raise SystemExit(f"need >= 3 groups for cross-validation, got {groups}")
    aug = None if args.no_augment else AugmentConfig()
    folds = []
    for i, test_g in enumerate(groups):
        val_g = groups[(i + 1) % len(groups)]
        t0 = time.time()
        res = train_temporal_model(recs, args.out / f"fold_{test_g}", args.window, args.stride, 0.25, args.epochs, 64, 1e-3, args.hidden,
                                   args.layers, args.dropout, args.seed, version=f"cv-fold-{test_g}", patience=args.patience, augment=aug,
                                   group_regex=args.group_regex, val_groups=[val_g], test_groups=[test_g],
                                   provenance={"dataset": str(args.data), "cross_validation": True})
        te = res.metrics["test"]
        row = {"test_group": test_g, "val_group": val_g, "train_groups": [g for g in groups if g not in (test_g, val_g)],
               "epochs_run": res.metrics["history_epochs"], "test_accuracy": te["accuracy"], "test_macro_f1": te["macro_f1"],
               "test_windows": sum(te["support"].values()) if isinstance(te["support"], dict) else None, "seconds": round(time.time() - t0, 1)}
        folds.append(row)
        print(json.dumps(row), flush=True)
    accs = [f["test_accuracy"] for f in folds]
    f1s = [f["test_macro_f1"] for f in folds]
    summary = {"grouping": args.group_regex, "groups": groups, "config": {k: getattr(args, k) for k in ("window", "stride", "hidden", "layers", "dropout", "epochs", "patience", "seed")},
               "augment": aug.to_dict() if aug else None, "folds": folds,
               "test_accuracy_mean": statistics.mean(accs), "test_accuracy_std": statistics.pstdev(accs),
               "test_macro_f1_mean": statistics.mean(f1s), "test_macro_f1_std": statistics.pstdev(f1s)}
    (args.out / "crossval.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "folds"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
