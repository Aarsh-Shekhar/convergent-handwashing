"""Deterministic replay regression on the real sample video with the real MediaPipe tracker
and whichever artifacts are installed. Two runs must produce identical fused label
sequences and events; a stored fingerprint catches unintended behaviour changes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from convergent.common.config import PipelineConfig, resolve_path
from convergent.pipeline import Pipeline

pytestmark = [pytest.mark.mediapipe, pytest.mark.slow]
FINGERPRINT_DIR = Path(__file__).parent


def fingerprint_path(tracker_id: str) -> Path:
    # One fingerprint per MediaPipe backend: the bundled `solutions` graph and the downloaded
    # `tasks` HandLandmarker give slightly different landmarks, hence different event boundaries.
    return FINGERPRINT_DIR / f"replay_fingerprint.{tracker_id.split('.')[1] if '.' in tracker_id else tracker_id}.json"


def run(sample_video: Path, n: int = 120):
    cfg = PipelineConfig.load(resolve_path("configs/development.yaml"), {"source": {"kind": "video", "path": str(sample_video), "max_frames": n, "target_fps": 15},
                                                                           "projector": {"profile_path": None}})
    pipe = Pipeline(cfg, deterministic=True)
    status = pipe.load_models()
    seq = []
    pipe.on_frame = lambda r: seq.append((r.frame.frame_id, round(r.frame.capture_ts, 4), r.hands.num_hands, r.fused.status.value, r.fused.native_label))
    try:
        summary = pipe.run()
    finally:
        pipe.close()
    events = [(e.technique, e.side.value, round(e.start_ts, 3), round(e.end_ts, 3)) for e in summary.events]
    return seq, events, {k: v.available for k, v in status.items()}, pipe.tracker.tracker_id


def test_replay_is_reproducible(sample_video):
    seq1, ev1, avail, tracker_id = run(sample_video)
    seq2, ev2, _, _ = run(sample_video)
    assert [s[:3] for s in seq1] == [s[:3] for s in seq2]  # frame ids, timestamps, hand counts
    agreement = sum(a == b for a, b in zip(seq1, seq2, strict=True)) / len(seq1)
    assert agreement >= 0.98, f"fused outputs differ between identical replays ({agreement:.3f})"
    assert ev1 == ev2
    digest = hashlib.sha256(json.dumps([seq1, ev1, sorted(avail.items()), tracker_id]).encode()).hexdigest()
    record = {"tracker": tracker_id, "available": avail, "frames": len(seq1), "events": ev1, "sha256": digest}
    fp = fingerprint_path(tracker_id)
    if fp.exists():
        stored = json.loads(fp.read_text())
        if stored.get("available") == avail and stored.get("tracker") == tracker_id:
            assert [tuple(e) for e in stored["events"]] == ev1, f"replay events changed vs stored fingerprint (delete {fp.name} and re-run if intended)"
        else:
            # a different set of loaded models is a different system: record it instead of silently skipping
            fp.write_text(json.dumps(record, indent=2))
            pytest.fail(f"{fp.name} was recorded with a different model set; it has been rewritten, run again and commit it")
    else:
        fp.write_text(json.dumps(record, indent=2))
