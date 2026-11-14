"""Model v1.0 acceptance: the installed recognition stack must reproduce the known answer on the
sample clip, end to end (tracker -> temporal_v2 -> fusion -> validator -> side resolver -> score).

This is the contract the game layer builds on. If a model, threshold or config change breaks it,
that change needs a new agreed answer here, not a quiet regression.

Known answer for data/samples/handwashing_missing_step.mp4 (a full wash with the THUMB step left
out; verified by eye 2026-11-14): six validated events in WHO order, thumb absent, every sided
event resolved to the LEFT hand receiving, wash finished with >= 3 stars.
Runs the whole 90 s clip (~1 min on a laptop): marked slow + mediapipe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from convergent.common.config import PipelineConfig
from convergent.common.types import HandSide
from convergent.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ORDER = ["palm_to_palm", "back_of_hand", "interlaced_fingers", "backs_of_fingers", "fingertip_rubbing", "wrist_rubbing"]
SIDED = {"back_of_hand", "backs_of_fingers", "fingertip_rubbing", "wrist_rubbing"}

pytestmark = [pytest.mark.slow, pytest.mark.mediapipe]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    sample_video = ROOT / "data" / "samples" / "handwashing_missing_step.mp4"
    if not sample_video.is_file():
        pytest.skip("sample video not present (make samples)")
    for req in ("models/temporal_v2/current/model.pt", "models/side_resolver/current/model.pt"):
        if not (ROOT / req).is_file():
            pytest.skip(f"{req} missing")
    cfg = PipelineConfig.load(ROOT / "configs" / "development.yaml",
                              {"source": {"kind": "video", "path": str(sample_video)}, "results_dir": str(tmp_path_factory.mktemp("acc")),
                               "backend": {"enabled": False}, "projector": {"profile_path": None}})
    pipe = Pipeline(cfg, deterministic=True)
    status = pipe.load_models()
    assert status["temporal_v2"].available and status["side_resolver"].available
    return pipe.run()


def test_events_in_who_order_with_thumb_missing(run):
    techs = [e.technique for e in run.events]
    assert techs == EXPECTED_ORDER, techs
    assert "thumb_rubbing" not in techs
    assert all(e.validated_duration_s >= 5.0 for e in run.events), [(e.technique, e.validated_duration_s) for e in run.events]
    assert all(e.confidence >= 0.85 for e in run.events)


def test_sided_events_are_resolved_to_the_hand_seen_in_the_clip(run):
    for e in run.events:
        if e.technique in SIDED:
            assert e.side_resolved and e.side == HandSide.LEFT, (e.technique, e.side)
        else:
            assert e.side == HandSide.BOTH


def test_wash_score_and_coverage(run):
    sc = run.score
    assert sc is not None and sc["finished"] and sc["stars"] >= 3 and sc["points"] >= 80
    secs = {s["technique"]: s["seconds"] for s in sc["steps"]}
    assert secs["thumb_rubbing"] == 0.0 and secs["wrist_rubbing"] >= 5.0 and secs["fingertip_rubbing"] >= 8.0  # timers keep accruing after "finished"
    assert run.progress["coverage_estimate"] >= 0.55, run.progress["coverage_estimate"]  # 6 of 10 region cells (thumbs and one back/fingertips cell unknown)
    assert run.fused_counts.get("unknown", 0) < 0.05 * run.frames
