#!/usr/bin/env python
"""Extract raw two-hand landmark recordings for the temporal_v2 model.

Uses the SAME tracker settings as the live pipeline (``configs/development.yaml: tracker``),
keeps every detected hand (no left/right filtering) and stores raw landmarks, so features
can be recomputed later without running MediaPipe again. One ``.npz`` per video.

Sources (give any combination)::

    --kaggle data/HandWashDataset   Kaggle realtimear/hand-wash-dataset: Step_1/, Step_2_Left/, ... (one label per clip)
    --metc   data/METC              Zenodo 5808789: Interface_number_*/Videos + Annotations/Annotator_1/*.json (label per frame)
    --own    data/own               `convergent record` rounds: <round>/<class>.mp4 (+ <class>.json, round.json)
    --labelled-video V --label L    one extra clip with a single label (debugging)

    python scripts/extract_landmarks_v2.py --metc data/METC --own data/own --out data/landmarks_v2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.common.config import PipelineConfig, SourceConfig, resolve_path  # noqa: E402
from convergent.detection.pair_features import HandSlotter  # noqa: E402
from convergent.detection.pair_training import IGNORE_LABEL, V2_CLASSES, RawRecording  # noqa: E402

KAGGLE_FOLDERS = {"Step_1": "palm_to_palm", "Step_2_Left": "back_of_hand", "Step_2_Right": "back_of_hand", "Step_3": "interlaced_fingers",
                  "Step_4_Left": "backs_of_fingers", "Step_4_Right": "backs_of_fingers", "Step_5_Left": "thumb_rubbing",
                  "Step_5_Right": "thumb_rubbing", "Step_6_Left": "fingertip_rubbing", "Step_6_Right": "fingertip_rubbing",
                  "Step_7_Left": "wrist_rubbing", "Step_7_Right": "wrist_rubbing"}
# METC movement codes (Lulla et al. 2021): 0 other, 1..6 WHO steps, 7 turning the tap off (treated as other)
METC_CODES = {0: "none", 1: "palm_to_palm", 2: "back_of_hand", 3: "interlaced_fingers", 4: "backs_of_fingers", 5: "thumb_rubbing",
              6: "fingertip_rubbing", 7: "none"}
REACTION_S = 0.5  # METC was labelled live: frames within +-0.5 s of a label change are uncertain


def metc_frame_labels(json_path: Path, src_fps: float) -> list[str]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    labs = [METC_CODES.get(int(x["code"]), "none") if x.get("is_washing", 1) else "none" for x in data["labels"]]
    out = list(labs)
    k = max(1, int(round(REACTION_S * src_fps)))
    for i in range(1, len(labs)):
        if labs[i] != labs[i - 1]:
            for j in range(max(0, i - k), min(len(labs), i + k)):
                out[j] = IGNORE_LABEL
    return out


def jobs_kaggle(root: Path) -> list[dict]:
    out = []
    for folder, label in KAGGLE_FOLDERS.items():
        for v in sorted((root / folder).glob("*.mp4")):
            m = re.search(r"HandWash_(\d+)", v.stem)
            g = re.search(r"_G_?(\d+)", v.stem)
            wash = m.group(1) if m else v.stem
            out.append({"video": str(v), "rec_id": f"kaggle_{folder}_{v.stem}", "dataset": "kaggle", "group": wash, "subject": wash,
                        "label": label, "view": f"sink_G{g.group(1) if g else '?'}"})
    return out


def jobs_metc(root: Path) -> list[dict]:
    out = []
    for v in sorted(root.glob("Interface_number_*/**/*.mp4")):
        iface = next(p for p in v.parts if p.startswith("Interface_number_"))
        ann = list((root / iface).glob(f"**/Annotator_*/{v.stem}.json"))
        if not ann:
            print(f"  (no annotation for {v.name}; skipped)")
            continue
        m = re.match(r"(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}-(\d+)", v.stem)
        subject = f"{m.group(1)}_{m.group(2)}" if m else v.stem[:19]
        out.append({"video": str(v), "rec_id": f"metc_{iface[-1]}_{v.stem}", "dataset": "metc", "group": subject, "subject": subject,
                    "annotation": str(ann[0]), "view": iface})
    return out


def jobs_own(root: Path) -> list[dict]:
    out = []
    for rdir in sorted(p for p in root.iterdir() if p.is_dir()):
        meta = json.loads((rdir / "round.json").read_text()) if (rdir / "round.json").exists() else {}
        for v in sorted(rdir.glob("*.mp4")):
            if v.stem not in V2_CLASSES:
                print(f"  (own clip {v} is not named after a class; skipped)")
                continue
            side = rdir / f"{v.stem}.json"
            out.append({"video": str(v), "rec_id": f"own_{rdir.name}_{v.stem}", "dataset": "own", "group": rdir.name, "subject": rdir.name,
                        "label": v.stem, "view": str(meta.get("view", "")), "sidecar": str(side) if side.exists() else None, "trim_s": 0.7})
    return out


def extract_one(job: dict, out_dir: str, fps: float, config: str | None) -> str:
    import cv2

    from convergent.vision.hand_tracker import HandTracker
    from convergent.vision.sources import VideoFileSource

    dst = Path(out_dir) / job["dataset"] / f"{job['rec_id']}.npz"
    if dst.exists():
        return f"  = {job['rec_id']} (exists)"
    dst.parent.mkdir(parents=True, exist_ok=True)
    cfg = PipelineConfig.load(resolve_path(config or "configs/development.yaml"))
    tracker = HandTracker(cfg.tracker)  # a fresh tracker per video: VIDEO-mode state must not leak between clips
    frame_labels: list[str] | None = None
    if job.get("annotation"):
        cap = cv2.VideoCapture(job["video"])
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 16.0
        cap.release()
        frame_labels = metc_frame_labels(Path(job["annotation"]), src_fps)
    stamps = None
    if job.get("sidecar"):
        stamps = json.loads(Path(job["sidecar"]).read_text()).get("timestamps")
    slotter = HandSlotter()
    hands_l, pres_l, ts_l, lab_l = [], [], [], []
    aspect = 4.0 / 3.0
    src = VideoFileSource(SourceConfig(kind="video", path=job["video"], target_fps=fps, width=cfg.source.width, height=cfg.source.height),
                          session_id=job["rec_id"])
    try:
        with src:
            for frame in src:
                aspect = frame.width / float(frame.height)
                th = tracker.detect(frame)
                found = sorted(th.hands + th.unassigned, key=lambda h: -h.tracking_quality)[:2]
                si = frame.source_frame_index if frame.source_frame_index is not None else frame.frame_id
                ts = float(stamps[si]) if stamps and si < len(stamps) else float(frame.capture_ts)
                if ts_l and ts <= ts_l[-1]:
                    continue
                raw, pres = slotter.assign([h.landmark_array() for h in found], ts)
                if frame_labels is not None:
                    lab = frame_labels[si] if si < len(frame_labels) else IGNORE_LABEL
                else:
                    lab = IGNORE_LABEL if ts < job.get("trim_s", 0.0) else job["label"]
                hands_l.append(raw)
                pres_l.append(pres)
                ts_l.append(ts)
                lab_l.append(lab)
    finally:
        tracker.close()
    if len(ts_l) < 2:
        return f"  ! {job['rec_id']}: no frames"
    rec = RawRecording(job["rec_id"], job["subject"], job["dataset"], job["group"], np.stack(hands_l), np.stack(pres_l), np.array(ts_l),
                       np.array(lab_l), aspect, job["video"], fps, job.get("view", ""))
    rec.validate()
    rec.save(dst)
    pr = np.stack(pres_l)
    return (f"  + {job['rec_id']}: {len(ts_l)} frames, any-hand={float((pr.max(1) > 0).mean()):.2f}, "
            f"two-hands={float((pr.min(1) > 0).mean()):.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kaggle", type=Path)
    ap.add_argument("--metc", type=Path)
    ap.add_argument("--own", type=Path)
    ap.add_argument("--labelled-video", type=Path)
    ap.add_argument("--label", default="none")
    ap.add_argument("--out", type=Path, default=Path("data/landmarks_v2"))
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--config", default=None, help="pipeline YAML whose tracker section is used (default configs/development.yaml)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    jobs: list[dict] = []
    if args.kaggle:
        jobs += jobs_kaggle(args.kaggle)
    if args.metc:
        jobs += jobs_metc(args.metc)
    if args.own and args.own.exists():
        jobs += jobs_own(args.own)
    if args.labelled_video:
        v = args.labelled_video
        jobs.append({"video": str(v), "rec_id": f"extra_{v.stem}", "dataset": "extra", "group": v.stem, "subject": v.stem, "label": args.label})
    if args.limit:
        jobs = jobs[:args.limit]
    if not jobs:
        print("no videos found")
        return 1
    print(f"{len(jobs)} videos -> {args.out}")
    n = 0
    if args.workers <= 1:
        for j in jobs:
            print(extract_one(j, str(args.out), args.fps, args.config), flush=True)
            n += 1
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(extract_one, j, str(args.out), args.fps, args.config): j for j in jobs}
            for f in as_completed(futs):
                try:
                    print(f.result(), flush=True)
                    n += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {futs[f]['rec_id']}: {exc}", flush=True)
    print(f"done: {n}/{len(jobs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
