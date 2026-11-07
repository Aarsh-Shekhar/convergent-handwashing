#!/usr/bin/env python
"""Validated conversion of the upstream HandHygiene RandomForest pickle (scikit-learn 1.0.2)
into the version-independent ``numpy-forest-v1`` format.

Run this ONCE in an environment that can unpickle the original (scikit-learn 1.2.x):

    uv venv /tmp/skl12 --python 3.11
    uv pip install --python /tmp/skl12/bin/python "scikit-learn==1.2.2" "numpy<1.27"
    /tmp/skl12/bin/python scripts/convert_handhygiene_rf.py \
        --pickle upstream/HandHygiene/Data/Models/rf_10102024.pkl \
        --csv upstream/HandHygiene/Data/TrainingData/Points_10102024.csv \
        --out models/handhygiene/rf_10102024.numpy-forest.npz

The export is only written if predict_proba matches the original on every row of the CSV
(max abs diff < 1e-9). The validation summary is embedded in the artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.detection.numpy_forest import NumpyForestPipeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pickle", required=True, type=Path)
    ap.add_argument("--csv", required=True, type=Path, help="upstream Points CSV used for validation")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-rows", type=int, default=None)
    args = ap.parse_args()

    import sklearn

    warnings.filterwarnings("ignore")
    with open(args.pickle, "rb") as f:
        pipeline = pickle.load(f)  # noqa: S301 - provenance audited in THIRD_PARTY.md; run only in the conversion env
    sha = hashlib.sha256(args.pickle.read_bytes()).hexdigest()
    with open(args.csv, encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        rows = [row for row in r]
    if args.max_rows:
        rows = rows[: args.max_rows]
    x = np.array([[float(v) for v in row[:126]] for row in rows])
    y = np.array([float(row[126]) for row in rows])
    assert header[-1] == "class" and len(header) == 127

    exported = NumpyForestPipeline.from_sklearn(pipeline, meta={
        "source_sha256": sha, "source_sklearn_version": sklearn.__version__, "source_file": args.pickle.name,
        "n_estimators": len(pipeline.named_steps["classifier"].estimators_),
    })
    p_ref = pipeline.predict_proba(x)
    p_new = exported.predict_proba(x)
    diff = float(np.abs(p_ref - p_new).max())
    agree = float((p_ref.argmax(1) == p_new.argmax(1)).mean())
    in_sample_acc = float((pipeline.predict(x) == y).mean())
    print(f"rows={len(x)} max|dp|={diff:.2e} argmax agreement={agree:.4f} in-sample acc (not generalization)={in_sample_acc:.4f}")
    if diff > 1e-9 or agree < 1.0:
        print("VALIDATION FAILED – export not written")
        return 1
    exported.meta["validation"] = {"rows": len(x), "max_abs_proba_diff": diff, "argmax_agreement": agree,
                                   "csv": args.csv.name, "note": "in-sample agreement with original pickle; not an accuracy claim"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    exported.save(args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
