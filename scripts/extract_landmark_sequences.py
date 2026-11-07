#!/usr/bin/env python
"""Extract per-recording landmark sequences from labelled handwashing videos.

Expected input layout (Kaggle realtimear/hand-wash-dataset or your own recordings)::

    <root>/Step_1/HandWash_001_A_01_G01.mp4
    <root>/Step_2_Left/...
    ...

Folder name -> S-Kia native label via the mapping from S-Kia's Prepare_data.ipynb
(Step_1 -> "1", Step_2_Left -> "2lt", ...). The subject id is parsed from the file name with
``--subject-regex`` (default: the first number group, e.g. ``HandWash_001_...`` -> ``001``);
if nothing matches, the recording id is used as its own group (grouped split still valid).

Each video becomes one ``.npz`` recording with frame timestamps from the decoder (PTS),
features in the S-Kia layout (left 63 + right 63, from the SHARED tracker with the configured
``feed_mode``), presence flags, and per-frame labels. Frames without any hand are kept with
presence [0,0] and zero features so that gaps are explicit (the trainer breaks windows there).

    python scripts/extract_landmark_sequences.py --root data/HandWashDataset --out data/landmark_sequences
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.common.config import SourceConfig, TrackerConfig  # noqa: E402
from convergent.detection.skia_adapter import skia_observation  # noqa: E402
from convergent.detection.training import Recording  # noqa: E402
from convergent.vision.hand_tracker import HandTracker  # noqa: E402
from convergent.vision.sources import VideoFileSource  # noqa: E402

FOLDER_TO_LABEL = {"Step_1": "1", "Step_2_Left": "2lt", "Step_2_Right": "2rt", "Step_3": "3", "Step_4_Left": "4lt", "Step_4_Right": "4rt",
                   "Step_5_Left": "5lt", "Step_5_Right": "5rt", "Step_6_Left": "6lt", "Step_6_Right": "6rt", "Step_7_Left": "7lt", "Step_7_Right": "7rt"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--subject-regex", default=r"(\d{2,4})", help="regex whose first group is the subject id")
    ap.add_argument("--fps", type=float, default=15.0, help="decimation target (capture timestamps keep PTS)")
    ap.add_argument("--feed-mode", choices=["raw_label", "anatomical"], default="raw_label")
    ap.add_argument("--swap-handedness", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="max videos (debug)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    tracker = HandTracker(TrackerConfig(swap_handedness=bool(args.swap_handedness)))
    rx = re.compile(args.subject_regex)
    n = 0
    for folder, label in FOLDER_TO_LABEL.items():
        d = args.root / folder
        if not d.is_dir():
            print(f"  (missing folder {folder})")
            continue
        for video in sorted(d.glob("*.mp4")):
            if args.limit is not None and n >= args.limit:
                break
            rec_id = f"{folder}_{video.stem}"
            m = rx.search(video.stem)
            subject = m.group(1) if m else rec_id
            src = VideoFileSource(SourceConfig(kind="video", path=str(video), target_fps=args.fps), session_id=rec_id)
            feats, pres, ts = [], [], []
            tracker.reset()
            with src:
                for frame in src:
                    hands = tracker.detect(frame)
                    obs = skia_observation(hands, args.feed_mode)
                    if obs is None:
                        feats.append(np.zeros(126, np.float32))
                        pres.append(np.zeros(2, np.float32))
                    else:
                        feats.append(obs[0].astype(np.float32))
                        pres.append(obs[1])
                    ts.append(frame.capture_ts)
            if len(ts) < 2:
                print(f"  skip {video.name}: no frames")
                continue
            rec = Recording(rec_id, subject, np.stack(feats), np.stack(pres), np.array(ts), np.array([label] * len(ts)), str(video), args.fps)
            rec.validate()
            rec.save(args.out / f"{rec_id}.npz")
            n += 1
            print(f"  {rec_id}: {len(ts)} frames, subject={subject}, label={label}, hands-present={float(np.mean(np.stack(pres).max(1))):.2f}")
    print(f"wrote {n} recordings to {args.out}")
    return 0 if n else 1


if __name__ == "__main__":
    raise SystemExit(main())
