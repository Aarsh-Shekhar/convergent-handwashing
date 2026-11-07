#!/usr/bin/env python
"""Reproducible YOLOv5 training for the handwashing detector (dpt-xyz annotations).

Upstream (HWD_YOLOv5.ipynb) trained YOLOv5s for 100 epochs, batch 16, img 640 from COCO
``yolov5s.pt`` on 567 train / 140 val frames with 7 classes. This script reproduces that
recipe against the pinned ``third_party/yolov5`` checkout and writes the dataset YAML.

    bash scripts/fetch_yolov5.sh                                    # pinned clone
    python scripts/train_yolo.py --dataset upstream/hand-wash-compliance-yolo/HandWashDataset_yoloFormat \
        --epochs 100 --out runs/yolo_handwash
    # then register the resulting weights:
    cp runs/yolo_handwash/exp/weights/best.pt models/yolo/handwash_yolov5.pt
    sha256sum models/yolo/handwash_yolov5.pt   # -> add to configs/models.yaml artifacts.yolo.trusted_sha256

IMPORTANT limitations recorded for the evaluation report:
  * the upstream val split consists of frames from the SAME videos as the training frames
    (file names ``<class>_<frame>.jpg``); its mAP therefore measures memorisation, not
    generalisation. Use ``--group-split`` to hold out whole class-videos... which with one
    video per class is impossible – real validation needs new recordings (Kaggle videos).
  * ``yolov5s.pt`` is a COCO initialisation only; it is never used as a handwashing detector.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAMES = ["Step1", "Step2", "Step3", "Step4", "Step5", "Step6", "Step7"]


def write_dataset_yaml(dataset: Path, out: Path) -> Path:
    train = dataset / "TrainingData" / "images" / "train"
    val = dataset / "TrainingData" / "images" / "val"
    for d in (train, val):
        if not d.is_dir():
            raise SystemExit(f"dataset folder missing: {d}")
    data = {"path": str(dataset.resolve()), "train": str(train.resolve()), "val": str(val.resolve()), "nc": len(NAMES), "names": NAMES,
            "note": "val frames come from the same source videos as train (upstream split); not a generalisation estimate"}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, required=True, help="HandWashDataset_yoloFormat directory")
    ap.add_argument("--yolov5", type=Path, default=ROOT / "third_party" / "yolov5")
    ap.add_argument("--weights", default="yolov5s.pt", help="initial weights (COCO init, downloaded by yolov5)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--img", type=int, default=640)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "yolo_handwash")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--dry-run", action="store_true", help="write the dataset yaml and print the command only")
    args = ap.parse_args()
    data_yaml = write_dataset_yaml(args.dataset, args.out / "handwash.yaml")
    train_py = args.yolov5 / "train.py"
    cmd = [sys.executable, str(train_py), "--img", str(args.img), "--batch", str(args.batch), "--epochs", str(args.epochs), "--data", str(data_yaml),
           "--weights", args.weights, "--project", str(args.out), "--name", "exp", "--exist-ok", "--device", args.device]
    print("dataset yaml:", data_yaml)
    print("command:", " ".join(cmd))
    if args.dry_run:
        return 0
    if not train_py.exists():
        raise SystemExit(f"yolov5 checkout missing at {args.yolov5}; run scripts/fetch_yolov5.sh")
    env = dict(os.environ)
    # yolov5 v7.0 predates torch 2.6's weights_only default; its checkpoints are full pickled models.
    env.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    return subprocess.call(cmd, cwd=str(args.yolov5), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
