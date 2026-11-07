#!/usr/bin/env python
"""Train/retrain the HandHygiene spatial classifier on correctly extracted features.

Two inputs:
  --videos <root>   folders ``Step1 .. Step10`` (upstream numbering: 1, 2.1, 2.2, 3, 4.1, ...) or
                    ``Paso_<n>.MOV`` files; features are re-extracted with the SHARED tracker and the
                    FIXED hand identity handling (handhygiene_feature_vector), one group per video.
  --csv <Points.csv>  the upstream training CSV (126 features + class). NOTE: it was produced
                    with the order-based two-hand assignment bug and has no video ids, so only
                    a random split is possible – results are not a generalisation estimate.

The upstream recipe is reproduced: Pipeline(StandardScaler, RandomForest(n_estimators=15,
max_features='sqrt', min_samples_split=5, bootstrap=False)). The result is exported in the
version-independent numpy-forest format read by the adapter.

    python scripts/train_handhygiene.py --videos data/handhygiene_videos --out models/handhygiene/rf_retrained.numpy-forest.npz
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.common.config import SourceConfig, TrackerConfig  # noqa: E402
from convergent.detection.handhygiene_adapter import (  # noqa: E402
    handhygiene_feature_vector,
    select_hands,
)
from convergent.detection.numpy_forest import NumpyForestPipeline  # noqa: E402
from convergent.vision.hand_tracker import HandTracker  # noqa: E402
from convergent.vision.sources import VideoFileSource  # noqa: E402

NATIVE = ["1", "2.1", "2.2", "3", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]


def extract(root: Path, fps: float, feed_mode: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    tracker = HandTracker(TrackerConfig())
    X, y, groups = [], [], []
    for video in sorted(root.rglob("*.mp4")) + sorted(root.rglob("*.MOV")):
        m = re.search(r"(?:step|paso)[_ ]?(\d+)", str(video), re.IGNORECASE)
        if not m:
            print(f"  skip {video}: no step number in path")
            continue
        cls = int(m.group(1))
        if not 1 <= cls <= 10:
            continue
        src = VideoFileSource(SourceConfig(kind="video", path=str(video), target_fps=fps))
        tracker.reset()
        n = 0
        with src:
            for frame in src:
                hands = tracker.detect(frame)
                right, left = select_hands(hands, feed_mode)
                if right is None and left is None:
                    continue
                X.append(handhygiene_feature_vector(None if right is None else right.landmark_array(), None if left is None else left.landmark_array()))
                y.append(float(cls))
                groups.append(video.stem)
                n += 1
        print(f"  {video.name}: class {cls} ({NATIVE[cls - 1]}) {n} frames")
    return np.array(X), np.array(y), groups


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--videos", type=Path, default=None)
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--feed-mode", choices=["raw_label", "anatomical"], default="raw_label")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import GroupShuffleSplit, train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if args.videos:
        X, y, groups = extract(args.videos, args.fps, args.feed_mode)
        split = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=args.seed)
        tr, te = next(split.split(X, y, groups))
        split_note = "grouped by video"
    elif args.csv:
        with open(args.csv, encoding="utf-8") as f:
            r = csv.reader(f)
            next(r)
            rows = [row for row in r]
        X = np.array([[float(v) for v in row[:126]] for row in rows])
        y = np.array([float(row[126]) for row in rows])
        tr, te = train_test_split(np.arange(len(X)), test_size=0.2, random_state=args.seed)
        split_note = "RANDOM frame split (no video ids in the upstream CSV) – not a generalisation estimate"
    else:
        ap.error("--videos or --csv required")
    if len(X) == 0:
        raise SystemExit("no training samples")
    pipe = Pipeline([("scaler", StandardScaler()), ("classifier", RandomForestClassifier(n_estimators=15, max_features="sqrt", min_samples_split=5,
                                                                                             bootstrap=False, random_state=args.seed))])
    pipe.fit(X[tr], y[tr])
    pred = pipe.predict(X[te])
    metrics = {"accuracy": float(accuracy_score(y[te], pred)), "macro_f1": float(f1_score(y[te], pred, average="macro")), "n_train": int(len(tr)),
               "n_test": int(len(te)), "split": split_note}
    print(json.dumps(metrics, indent=2))
    pipe.fit(X, y)  # final model on everything (as upstream did)
    exported = NumpyForestPipeline.from_sklearn(pipe, meta={"trained_by": "scripts/train_handhygiene.py", "metrics_heldout": metrics,
                                                            "feed_mode": args.feed_mode, "classes": NATIVE})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    exported.save(args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
