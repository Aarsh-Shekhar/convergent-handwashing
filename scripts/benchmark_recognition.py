#!/usr/bin/env python
"""Benchmark the live recognition pipeline on labelled video.

Two kinds of labelled video are supported:

* own clips recorded with ``convergent record`` (``data/own/<round>/<class>.mp4``): one class for
  the whole clip;
* METC videos (Zenodo 5808789) with a label on every frame. Only the videos of the held-out
  METC subjects are used (the same subjects ``pair_training.partition_groups`` keeps out of
  training), so the numbers are honest for a model trained with the default split.

Each video is replayed through the real pipeline (tracker, model branches, fusion, temporal
validator) and the numbers that matter for step timing are reported:

* frame accuracy / per-class recall of the fused label (``none`` = unknown or no input);
* palm-to-palm recall split by how many hands the tracker saw;
* credited seconds / performed seconds per step (validated events of the right technique);
* seconds credited to a WRONG technique, and seconds credited while not washing;
* label changes per minute (flicker) compared with how often the truth changes;
* per-branch frame accuracy (to set fusion weights).

    python scripts/benchmark_recognition.py --rounds down2,front2 --out runs/benchmark_baseline.json
    python scripts/benchmark_recognition.py --metc data/METC --weights temporal_v2=1,skia_temporal=0,handhygiene=0
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.common.config import PipelineConfig, resolve_path  # noqa: E402
from convergent.common.types import PredictionStatus  # noqa: E402
from convergent.detection.evaluation import frame_metrics  # noqa: E402
from convergent.detection.pair_training import (  # noqa: E402
    IGNORE_LABEL,
    V2_CLASSES,
    partition_groups,
)

TRIM_S = 0.7  # the first moments of an own clip are the person getting into the motion
FPS = 15.0


def _extractor():
    spec = importlib.util.spec_from_file_location("extract_landmarks_v2", ROOT / "scripts" / "extract_landmarks_v2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_clip(job: dict) -> dict:
    """Replay one video through the pipeline. Returns per-frame truth/prediction rows and events."""
    import cv2

    from convergent.pipeline import Pipeline

    logging.getLogger().setLevel(logging.ERROR)
    cfg = PipelineConfig.load(resolve_path(job["config"] or "configs/development.yaml"),
                              {**job["overrides"], "source": {"kind": "video", "path": job["video"], "target_fps": FPS}, "live_status_every_s": 0})
    frame_labels = None
    if job.get("annotation"):
        cap = cv2.VideoCapture(job["video"])
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 16.0
        cap.release()
        frame_labels = _extractor().metc_frame_labels(Path(job["annotation"]), src_fps)
    pipe = Pipeline(cfg, deterministic=True)
    rows: list[tuple[float, str, str, int, dict[str, str]]] = []

    def on_frame(r):  # type: ignore[no-untyped-def]
        ts = r.frame.capture_ts
        if frame_labels is not None:
            si = r.frame.source_frame_index if r.frame.source_frame_index is not None else r.frame.frame_id
            truth = frame_labels[si] if si < len(frame_labels) else IGNORE_LABEL
        else:
            truth = IGNORE_LABEL if ts < TRIM_S else job["label"]
        fused = r.fused.canonical.technique if r.fused.status == PredictionStatus.VALID and r.fused.canonical else "none"
        branches = {k: (p.canonical.technique if p.status == PredictionStatus.VALID and p.canonical else "none") for k, p in r.branch_predictions.items()}
        rows.append((ts, truth, fused, len(r.hands.hands) + len(r.hands.unassigned), branches))

    pipe.on_frame = on_frame
    try:
        summary = pipe.run()
    finally:
        pipe.close()
    return {"job": {k: job[k] for k in ("name", "dataset")}, "rows": rows,
            "events": [(e.technique, e.validated_duration_s, e.start_ts, e.end_ts) for e in summary.events],
            "models": {k: v["available"] for k, v in summary.model_status.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--own", type=Path, default=Path("data/own"))
    ap.add_argument("--rounds", default=None, help="own rounds to use, comma-separated (default: none unless --all-rounds)")
    ap.add_argument("--all-rounds", action="store_true")
    ap.add_argument("--metc", type=Path, default=None, help="METC root: benchmark on the held-out METC subjects")
    ap.add_argument("--metc-limit", type=int, default=None, help="use at most this many METC videos")
    ap.add_argument("--seed", type=int, default=0, help="split seed (must match training)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--weights", default=None, help="fusion weight overrides, e.g. temporal_v2=1,skia_temporal=0,handhygiene=0")
    ap.add_argument("--disable", default=None, help="comma-separated branches to disable: handhygiene,skia,temporal_v2")
    ap.add_argument("--set", action="append", default=[], help="config override section.key=value (repeatable), e.g. temporal_v2.smooth_s=0")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    overrides: dict = {}
    if args.weights:
        overrides["fusion"] = {"weights": {k: float(v) for k, v in (kv.split("=") for kv in args.weights.split(","))}}
    for b in (args.disable.split(",") if args.disable else []):
        overrides.setdefault(b.strip(), {})["enabled"] = False
    for kv in args.set:
        path, val = kv.split("=", 1)
        sec, key = path.split(".", 1)
        try:
            parsed = json.loads(val)
        except json.JSONDecodeError:
            parsed = val  # plain strings such as paths
        overrides.setdefault(sec, {})[key] = parsed
    jobs: list[dict] = []
    root = resolve_path(args.own)
    rounds = [r.strip() for r in args.rounds.split(",")] if args.rounds else (sorted(p.name for p in root.iterdir() if p.is_dir()) if args.all_rounds and root.exists() else [])
    for r in rounds:
        for v in sorted((root / r).glob("*.mp4")):
            if v.stem in V2_CLASSES:
                jobs.append({"video": str(v), "label": v.stem, "name": f"{r}/{v.stem}", "dataset": "own"})
    if args.metc:
        mj = _extractor().jobs_metc(resolve_path(args.metc))
        test, _val = partition_groups("metc", [f"metc:{j['group']}" for j in mj], args.seed)
        held = [j for j in mj if f"metc:{j['group']}" in test][:args.metc_limit]
        jobs += [{"video": j["video"], "annotation": j["annotation"], "name": Path(j["video"]).stem, "dataset": "metc"} for j in held]
    if not jobs:
        print("no clips: give --rounds / --all-rounds and/or --metc")
        return 1
    for j in jobs:
        j.update(config=args.config, overrides=overrides)
    if args.workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(run_clip, jobs))
    else:
        results = [run_clip(j) for j in jobs]

    y_true: list[str] = []
    y_pred: list[str] = []
    hand_counts: list[int] = []
    branch_pred: dict[str, list[str]] = defaultdict(list)
    per_clip, models = [], {}
    perf_s: Counter = Counter()
    credit_s: Counter = Counter()
    wrong_s: Counter = Counter()
    pred_changes = truth_changes = 0
    total_s = 0.0
    for res in results:
        models = res["models"]
        rows = res["rows"]
        ts = np.array([r[0] for r in rows])
        truth = np.array([r[1] for r in rows])
        keep = truth != IGNORE_LABEL
        if not keep.any():
            continue
        labels = [r[2] for r, k in zip(rows, keep, strict=True) if k]
        y_true += truth[keep].tolist()
        y_pred += labels
        hand_counts += [r[3] for r, k in zip(rows, keep, strict=True) if k]
        for mid in models:
            branch_pred[mid] += [r[4].get(mid, "none") for r, k in zip(rows, keep, strict=True) if k]
        clip_perf = Counter(truth[keep].tolist())
        for c, n in clip_perf.items():
            perf_s[c] += n / FPS
        right_total = wrong_total = 0.0
        for tech, dur, s0, s1 in res["events"]:
            inside = (ts >= s0) & (ts <= s1)
            same = float((truth[inside] == tech).sum()) / FPS       # event time that overlaps the same true technique
            unsure = float((truth[inside] == IGNORE_LABEL).sum()) / FPS  # around label changes: not counted either way
            right = min(dur, same)
            wrong = max(0.0, dur - same - unsure)
            credit_s[tech] += right
            right_total += right
            wrong_total += wrong
            if wrong > 0:
                others = Counter(truth[inside & (truth != tech) & (truth != IGNORE_LABEL)].tolist())
                wrong_s[others.most_common(1)[0][0] if others else "none"] += wrong  # booked on the step that was really being done
        pred_changes += sum(1 for a, b in zip(labels, labels[1:], strict=False) if a != b)
        tk = truth[keep]
        truth_changes += int((tk[1:] != tk[:-1]).sum())
        total_s += float(keep.sum()) / FPS
        acc = float(np.mean(np.array(labels) == truth[keep]))
        per_clip.append({"name": res["job"]["name"], "dataset": res["job"]["dataset"], "frames": int(keep.sum()), "frame_acc": round(acc, 3),
                         "credited_s": round(right_total, 2), "wrong_credit_s": round(wrong_total, 2), "top_pred": Counter(labels).most_common(3)})
        if not args.quiet:
            print(f"  {res['job']['name'][:38]:<38} acc={acc:5.2f} credited={right_total:5.1f}s wrong={wrong_total:4.1f}s top={Counter(labels).most_common(2)}")
    fm = frame_metrics(y_true, y_pred, V2_CLASSES)
    yt, yp, hc = np.array(y_true), np.array(y_pred), np.array(hand_counts)
    steps = [c for c in V2_CLASSES if c != "none" and perf_s[c] > 0]
    palm = yt == "palm_to_palm"
    report = {
        "clips": len(per_clip), "frames": len(y_true), "seconds": round(total_s, 1), "models": models, "overrides": overrides,
        "frame_accuracy": round(fm.accuracy, 4),
        "step_frame_accuracy": round(float((yp[yt != "none"] == yt[yt != "none"]).mean()), 4) if (yt != "none").any() else None,
        "recall": {c: round(fm.per_class[c]["recall"], 4) for c in V2_CLASSES if fm.per_class[c]["support"]},
        "precision": {c: round(fm.per_class[c]["precision"], 4) for c in V2_CLASSES if fm.per_class[c]["support"]},
        "confusion_rows_true_cols_pred": {"labels": V2_CLASSES, "matrix": fm.confusion},
        "palm_recall_by_hands": {str(n): {"frames": int((palm & (hc == n)).sum()),
                                           "recall": round(float((yp[palm & (hc == n)] == "palm_to_palm").mean()), 4) if (palm & (hc == n)).any() else None}
                                 for n in (0, 1, 2)},
        "two_hand_rate": round(float((hc >= 2).mean()), 4),
        "performed_s": {c: round(perf_s[c], 1) for c in V2_CLASSES if perf_s[c] > 0},
        "credited_ratio": {c: round(credit_s[c] / perf_s[c], 4) for c in steps},
        "credited_ratio_mean": round(float(np.mean([credit_s[c] / perf_s[c] for c in steps])), 4) if steps else None,
        "wrong_credit_s_per_10s": {c: round(10 * wrong_s[c] / perf_s[c], 3) for c in steps},
        "false_credit_s_per_10s_not_washing": round(10 * wrong_s["none"] / perf_s["none"], 3) if perf_s["none"] else None,
        "label_changes_per_min": round(60 * pred_changes / max(total_s, 1e-9), 1),
        "true_changes_per_min": round(60 * truth_changes / max(total_s, 1e-9), 1),
        "branch_frame_accuracy": {m: round(float(np.mean(np.array(p) == yt)), 4) for m, p in branch_pred.items() if models.get(m)},
        "per_clip": per_clip,
    }
    print(json.dumps({k: v for k, v in report.items() if k not in ("per_clip", "confusion_rows_true_cols_pred")}, indent=2))
    print("confusion (rows = truth, cols = predicted):")
    print("  " + " ".join(f"{c[:6]:>7}" for c in V2_CLASSES))
    for c, row in zip(V2_CLASSES, fm.confusion, strict=True):
        print(f"  {' '.join(f'{v:7d}' for v in row)}  {c}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
