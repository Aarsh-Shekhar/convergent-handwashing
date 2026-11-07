#!/usr/bin/env python
"""Fetch / derive model artifacts into ``models/`` (never committed to git).

Sources:
  * HandHygiene sklearn pickles      -> raw.githubusercontent.com (MIT license file; see THIRD_PARTY.md)
  * S-Kia Keras checkpoint + X.pkl   -> raw.githubusercontent.com (NO license file upstream; artifacts are
                                        downloaded for local evaluation only, not vendored)
  * MediaPipe hand_landmarker.task   -> storage.googleapis.com (Apache-2.0)
  * YOLO weights                     -> none exist upstream; train with scripts/train_yolo.py

Every downloaded file is hash-checked against configs/models.yaml (``upstream_sha256``) and a
mismatch is reported loudly. ``--from-local <dir>`` copies from local clones instead of
downloading (useful offline / behind an allow-listing proxy).

Usage:
    python scripts/fetch_models.py [--from-local upstream/] [--skip-mediapipe]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.detection.base import sha256_of  # noqa: E402
from convergent.detection.registry import ModelRegistry  # noqa: E402

RAW = "https://raw.githubusercontent.com"
ITEMS = [
    # (dest relative path, remote url, local relative path inside upstream clones)
    ("models/handhygiene/rf_10102024.pkl", f"{RAW}/juannquinones/HandHygiene/main/Data/Models/rf_10102024.pkl", "HandHygiene/Data/Models/rf_10102024.pkl"),
    ("models/handhygiene/lr_10102024.pkl", f"{RAW}/juannquinones/HandHygiene/main/Data/Models/lr_10102024.pkl", "HandHygiene/Data/Models/lr_10102024.pkl"),
    ("models/handhygiene/svm_10102024.pkl", f"{RAW}/juannquinones/HandHygiene/main/Data/Models/svm_10102024.pkl", "HandHygiene/Data/Models/svm_10102024.pkl"),
    ("models/skia_legacy/generalized_lstm_model.keras", f"{RAW}/S-Kia/Hand_washing_application/main/generalized_lstm_model.keras", "Hand_washing_application/generalized_lstm_model.keras"),
    ("models/skia_legacy/X.pkl", f"{RAW}/S-Kia/Hand_washing_application/main/X.pkl", "Hand_washing_application/X.pkl"),
]
MEDIAPIPE = ("models/mediapipe/hand_landmarker.task",
             "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task")


def fetch(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:  # noqa: S310 - fixed allow-listed URLs
            shutil.copyfileobj(r, f)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  !! download failed: {url}: {exc}")
        dest.unlink(missing_ok=True)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-local", type=Path, default=None, help="directory containing upstream clones")
    ap.add_argument("--skip-mediapipe", action="store_true")
    args = ap.parse_args()
    ok = True
    for rel, url, local in ITEMS:
        dest = ROOT / rel
        if dest.exists():
            print(f"  = {rel} (exists)")
        elif args.from_local and (args.from_local / local).exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.from_local / local, dest)
            print(f"  + {rel} (copied from {args.from_local / local})")
        else:
            print(f"  > {rel} <- {url}")
            ok &= fetch(url, dest)
    if not args.skip_mediapipe:
        dest = ROOT / MEDIAPIPE[0]
        if not dest.exists():
            print(f"  > {MEDIAPIPE[0]} <- {MEDIAPIPE[1]}")
            if not fetch(MEDIAPIPE[1], dest):
                print("  (tracker will fall back to the bundled mp.solutions.hands graph)")
    # derive legacy scaler stats from X.pkl
    xpkl = ROOT / "models/skia_legacy/X.pkl"
    stats = ROOT / "models/skia_legacy/legacy_scaler_stats.npz"
    if xpkl.exists() and not stats.exists():
        from convergent.detection.skia_adapter import compute_legacy_scaler_stats

        compute_legacy_scaler_stats(xpkl, stats)
        print(f"  + {stats.relative_to(ROOT)} derived from X.pkl")
    # verify hashes
    reg = ModelRegistry.load()
    print("\nArtifact discovery:")
    for d in reg.discover_all():
        flag = "OK " if d["exists"] and (d["trusted"] or d["kind"] in ("torch_artifact_dir", "mediapipe_task")) else ("?? " if d["exists"] else "-- ")
        print(f"  [{flag}] {d['model_key']:<28} exists={d['exists']!s:<5} trusted={d['trusted']!s:<5} {d['path']}")
        if d["exists"] and d["sha256"] and not d["trusted"] and d["kind"] not in ("torch_artifact_dir", "mediapipe_task"):
            print(f"         sha256={d['sha256']} is NOT registered in configs/models.yaml")
    for rel in ("models/handhygiene/rf_10102024.pkl",):
        p = ROOT / rel
        if p.exists():
            print(f"  sha256 {rel}: {sha256_of(p)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
