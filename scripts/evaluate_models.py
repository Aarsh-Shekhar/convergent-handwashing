#!/usr/bin/env python
"""Recording-level evaluation of the integrated detector with branch ablations.

Two evaluation modes (both can run in one invocation):

1. ``--video <mp4> --reference <json>`` – runs the full pipeline on a held-out recording and
   compares validated gesture events against reference annotations. Reports event precision/
   recall/F1, false-completion rate, missing-step detection, frame-level technique accuracy
   (reference label per timestamp), latency and CPU/memory. ``--ablation`` repeats the run for
   every non-empty subset of the available branches so you can SEE whether fusion helps.

   Reference JSON format::

       {"recording_id": "...", "subject_id": "...", "approximate": true,
        "events": [{"technique": "palm_to_palm", "side": "both", "start_ts": 0.0, "end_ts": 11.0}, ...],
        "required": ["palm_to_palm", "back_of_hand", "interlaced_fingers", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing"]}

2. ``--sequences <dir>`` – evaluates the temporal LSTM artifact on the grouped test split of a
   landmark-sequence dataset (frame/window-level metrics, confusion matrix).

Results are written as an EvaluationReport JSON (``--out``) and optionally POSTed to the
backend (``--backend-url`` + CONVERGENT_API_TOKEN).

    python scripts/evaluate_models.py --video data/samples/handwashing_missing_step.mp4 \
        --reference data/fixtures/handwashing_missing_step.reference.json --ablation --out runs/eval.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.common.config import PipelineConfig, load_settings, resolve_path  # noqa: E402
from convergent.common.types import HandSide  # noqa: E402
from convergent.detection.evaluation import (  # noqa: E402
    EvaluationReport,
    RefEvent,
    branch_subsets,
    event_metrics,
    frame_metrics,
    missing_step_detection,
)

BRANCHES = ("handhygiene", "skia_temporal", "skia_legacy", "yolo")


def branch_overrides(enabled: tuple[str, ...]) -> dict[str, Any]:
    temporal, legacy = "skia_temporal" in enabled, "skia_legacy" in enabled
    return {"handhygiene": {"enabled": "handhygiene" in enabled}, "yolo": {"enabled": "yolo" in enabled},
            "skia": {"enabled": temporal or legacy, "mode": "both" if temporal and legacy else ("legacy" if legacy else "temporal")}}


def available_branches(cfg: PipelineConfig) -> list[str]:
    """Probe which branches have a usable artifact (no tracker, no frames)."""
    from convergent.pipeline import Pipeline

    probe = PipelineConfig.load(None, {**cfg.model_dump(mode="json"), **branch_overrides(BRANCHES), "tracker": {"backend": "null"}})
    st = Pipeline(probe, deterministic=True).load_models()
    return [b for b in BRANCHES if st.get(b) is not None and st[b].available]


def load_reference(path: Path) -> tuple[list[RefEvent], list[str], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    refs = [RefEvent(e["technique"], float(e["start_ts"]), float(e["end_ts"]), HandSide(e.get("side", "unknown"))) for e in data["events"]]
    return refs, list(data.get("required", [])), data


def reference_label_at(refs: list[RefEvent], ts: float) -> str:
    for r in refs:
        if r.start_ts <= ts <= r.end_ts:
            return r.technique
    return "none"


def run_once(cfg: PipelineConfig, video: Path, enabled: tuple[str, ...], refs: list[RefEvent], required: list[str],
             max_frames: int | None) -> dict[str, Any]:
    from convergent.pipeline import Pipeline

    overrides: dict[str, Any] = {"source": {"kind": "video", "path": str(video), "max_frames": max_frames}, **branch_overrides(enabled)}
    c = PipelineConfig.load(None, {**cfg.model_dump(mode="json"), **overrides})
    pipe = Pipeline(c, deterministic=True)
    y_true: list[str] = []
    y_pred: list[str] = []

    def on_frame(r):  # type: ignore[no-untyped-def]
        y_true.append(reference_label_at(refs, r.frame.capture_ts))
        y_pred.append(r.fused.canonical.technique if r.fused.canonical is not None and r.fused.is_valid else "none")

    pipe.on_frame = on_frame
    try:
        summary = pipe.run()
    finally:
        pipe.close()
    available = [k for k, v in summary.model_status.items() if v["available"]]
    fm = frame_metrics(y_true, y_pred)
    em = event_metrics(summary.events, refs, iou_threshold=0.3)
    ms = missing_step_detection(summary.events, refs, required) if required else None
    return {"enabled": list(enabled), "available_branches": available, "frames": summary.frames,
            "frame": {"accuracy": fm.accuracy, "macro_f1": fm.f1_macro, "precision_macro": fm.precision_macro, "recall_macro": fm.recall_macro,
                      "labels": fm.labels, "confusion": fm.confusion},
            "events": em.__dict__, "missing_steps": None if ms is None else ms.__dict__, "latency_ms": summary.latency,
            "resources": summary.resources, "fused_counts": summary.fused_counts,
            "validated_events": [{"technique": e.technique, "side": e.side.value, "start": e.start_ts, "end": e.end_ts, "dur": e.validated_duration_s} for e in summary.events]}


def evaluate_sequences(seq_dir: Path, artifact_dir: Path) -> dict[str, Any]:
    import numpy as np

    from convergent.detection.lstm_model import TemporalArtifact
    from convergent.detection.training import build_windows, grouped_split, load_recordings

    art = TemporalArtifact.load(artifact_dir)
    recs = load_recordings(seq_dir)
    ws = build_windows(recs, art.meta.window_frames, art.meta.stride_frames, art.meta.max_gap_s)
    _tr, _va, te = grouped_split(ws.groups)
    preds = [art.meta.classes[int(np.argmax(art.predict_proba(ws.x[i], ws.presence[i])))] for i in te]
    fm = frame_metrics([ws.y[i] for i in te], preds, art.meta.classes)
    return {"artifact": str(artifact_dir), "version": art.meta.model_version, "test_windows": int(len(te)),
            "test_groups": sorted(set(np.asarray(ws.groups)[te].tolist())), "accuracy": fm.accuracy, "macro_f1": fm.f1_macro,
            "precision_macro": fm.precision_macro, "recall_macro": fm.recall_macro, "confusion": fm.confusion, "labels": fm.labels,
            "note": "grouped (subject/recording) held-out split; the artifact's own meta.split may differ if trained on another dataset"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/development.yaml")
    ap.add_argument("--video", type=Path, default=None)
    ap.add_argument("--reference", type=Path, default=None)
    ap.add_argument("--ablation", action="store_true")
    ap.add_argument("--branches", default=None, help="comma-separated subset to evaluate (default: every branch with an artifact)")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--sequences", type=Path, default=None)
    ap.add_argument("--artifact", type=Path, default=None, help="temporal artifact dir (default from config)")
    ap.add_argument("--out", type=Path, default=Path("runs/evaluation.json"))
    ap.add_argument("--backend-url", default=None)
    args = ap.parse_args()
    cfg = PipelineConfig.load(resolve_path(args.config) if Path(args.config).exists() or resolve_path(args.config).exists() else None)
    report = EvaluationReport(dataset="", dataset_version="", split={}, model_config=cfg.model_dump(mode="json"))
    if args.video:
        if not args.reference:
            ap.error("--reference is required with --video")
        refs, required, meta = load_reference(args.reference)
        report.dataset = str(args.video)
        report.dataset_version = str(meta.get("recording_id", args.video.stem))
        report.split = {"recording_id": meta.get("recording_id"), "subject_id": meta.get("subject_id"),
                        "held_out": meta.get("held_out", "unknown"), "reference_approximate": meta.get("approximate", False)}
        if meta.get("approximate"):
            report.notes.append("reference annotations are APPROXIMATE (derived from upstream step durations); event metrics are indicative only")
        avail = tuple(available_branches(cfg))
        unavailable = sorted(set(BRANCHES) - set(avail))
        if unavailable:
            report.notes.append(f"branches without a usable artifact did not participate: {unavailable}")
        if not avail:
            report.notes.append("no branch available: pipeline runs in model-unavailable mode")
        if args.branches:
            wanted = tuple(b.strip() for b in args.branches.split(",") if b.strip())
            bad = sorted(set(wanted) - set(avail))
            if bad:
                ap.error(f"requested branches without a usable artifact: {bad} (available: {list(avail)})")
            avail = wanted
        subsets = branch_subsets(avail) if (args.ablation and avail) else [avail]
        for subset in subsets:
            res = run_once(cfg, args.video, subset, refs, required, args.max_frames)
            if not args.ablation:
                report.frame, report.events, report.missing_steps = res["frame"], res["events"], res["missing_steps"]
                report.latency, report.resources = res["latency_ms"], res["resources"]
            report.ablations.append(res)
            print(f"branches={list(subset)} available={res['available_branches']} frame_acc={res['frame']['accuracy']:.3f} "
                  f"event_P={res['events']['precision']:.2f} R={res['events']['recall']:.2f} false_completion={res['events']['false_completion_rate']:.2f}")
    if args.sequences:
        art = args.artifact or resolve_path(cfg.skia.temporal_artifact_dir)
        report.artifacts["temporal_sequences"] = evaluate_sequences(args.sequences, art)  # type: ignore[assignment]
        print(json.dumps(report.artifacts["temporal_sequences"], indent=2))
    out = report.save(args.out)
    print(f"report written to {out}")
    if args.backend_url:
        from convergent.backend.client import BackendClient

        token = load_settings().api_token
        client = BackendClient(args.backend_url, token)
        res = client.post_evaluation({"dataset": report.dataset, "dataset_version": report.dataset_version, "split": report.split,
                                      "model_config": {"branches": [a["enabled"] for a in report.ablations]},
                                      "metrics": {"ablations": [{k: v for k, v in a.items() if k != "validated_events"} for a in report.ablations],
                                                  "sequences": report.artifacts.get("temporal_sequences")},
                                      "artifacts": {"report": str(out)}, "notes": "; ".join(report.notes)})
        print(f"backend evaluation run: {res['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
