#!/usr/bin/env python
"""Small, honest hyper-parameter sweep for the corrected temporal LSTM.

Every configuration is trained on the SAME grouped split (``--split-seed`` fixed), the winner is
chosen on validation macro-F1 only, and the held-out test metrics of the winner are reported
once. The chosen artifact is copied to ``--install`` (default ``models/skia_temporal/current``).

    python scripts/sweep_lstm.py --data data/landmark_sequences --out runs/lstm_sweep --epochs 40

The grid is intentionally small (CPU laptop friendly). Edit ``GRID`` to extend it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.detection.training import (  # noqa: E402
    AugmentConfig,
    build_windows,
    load_recordings,
    train_temporal_model,
)

GRID = [
    # name, window, stride, hidden, layers, dropout, augment
    ("w16_s2_h128_noaug", 16, 2, 128, 2, 0.2, None),
    ("w16_s2_h128_aug", 16, 2, 128, 2, 0.2, AugmentConfig()),
    ("w16_s2_h128_aug_nomirror", 16, 2, 128, 2, 0.2, AugmentConfig(mirror=False)),
    ("w24_s2_h128_aug", 24, 2, 128, 2, 0.2, AugmentConfig()),
    ("w32_s2_h128_aug", 32, 2, 128, 2, 0.2, AugmentConfig()),
    ("w24_s2_h192_aug", 24, 2, 192, 2, 0.3, AugmentConfig()),
]


def install_artifact(src: Path, dest: Path) -> None:
    """Copy an artifact dir to ``dest``; refuses any destination outside models/skia_temporal/."""
    allowed = (ROOT / "models" / "skia_temporal").resolve()
    dest = dest.resolve()
    if dest == allowed or allowed not in dest.parents:
        raise SystemExit(f"refusing to install to {dest}: must be a sub-directory of {allowed}")
    for name in ("meta.json", "model.pt", "scaler.npz"):
        if not (src / name).is_file():
            raise SystemExit(f"{src} is not a complete temporal artifact (missing {name})")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "lstm_sweep")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--split-seed", type=int, default=0)
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--install", type=Path, default=ROOT / "models" / "skia_temporal" / "current",
                    help="where to copy the winner (must be inside models/skia_temporal/); --no-install to skip")
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--only", nargs="*", default=None, help="subset of GRID names")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    recs = load_recordings(args.data)
    provenance = {"dataset": str(args.data), "recordings": [r.recording_id for r in recs], "sources": sorted({r.source for r in recs})}
    total_frames = sum(len(r.timestamps) for r in recs)
    coverage = {}
    rows = []
    for name, window, stride, hidden, layers, dropout, aug in GRID:
        if args.only and name not in args.only:
            continue
        t0 = time.time()
        out = args.out / name
        res = train_temporal_model(recs, out, window, stride, 0.25, args.epochs, 64, 1e-3, hidden, layers, dropout, args.seed,
                                   version=f"{args.version}+{name}", provenance=provenance, patience=args.patience, augment=aug,
                                   split_seed=args.split_seed)
        val = res.metrics.get("val", {})
        if window not in coverage:
            coverage[window] = round(len(build_windows(recs, window, 1, 0.25).y) / total_frames, 3)
        row = {"name": name, "prediction_coverage": coverage[window], "first_prediction_s": round(window / 15.0, 2), "window": window, "hidden": hidden, "layers": layers, "dropout": dropout, "augment": aug.to_dict() if aug else None,
               "epochs_run": res.metrics["history_epochs"], "best_val_loss": res.metrics["best_val_loss"], "val_accuracy": val.get("accuracy"),
               "val_macro_f1": val.get("macro_f1"), "seconds": round(time.time() - t0, 1), "artifact": str(out)}
        rows.append(row)
        print(json.dumps(row), flush=True)
        (args.out / "sweep.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    best = max(rows, key=lambda r: (r["val_macro_f1"] or -1))
    test = json.loads((Path(best["artifact"]) / "meta.json").read_text())["metrics"].get("test", {})
    summary = {"selected_on": "val_macro_f1", "winner": best, "winner_test_metrics_reported_once": {k: test.get(k) for k in ("accuracy", "macro_f1", "precision_macro", "recall_macro")}}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if not args.no_install:
        install_artifact(Path(best["artifact"]), args.install)
        print(f"installed {best['artifact']} -> {args.install}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
