"""Wash scorer: step timers, finish rule, stars/points, freezing and live timing."""

from __future__ import annotations

import numpy as np
import pytest

from convergent.common.config import PipelineConfig, ScoringConfig, TemporalConfig, resolve_path
from convergent.common.types import GestureEvent, HandSide, PredictionStatus, ValidationStatus
from convergent.detection.event_detector import EventDetector
from convergent.detection.labels import SCORED_TECHNIQUES
from convergent.detection.temporal import Candidate
from convergent.scoring.wash_score import WashScorer
from tests.conftest import make_pred

STEPS = list(SCORED_TECHNIQUES)
_t = [0.0]


def ev(tech, dur, status=ValidationStatus.VALIDATED, side=HandSide.UNRESOLVED):
    start = _t[0]
    _t[0] += dur + 1.0
    return GestureEvent(session_id="s", technique=tech, side=side, start_ts=start, end_ts=start + dur,
                        validated_duration_s=dur if status == ValidationStatus.VALIDATED else 0.0, confidence=0.9,
                        validation_status=status, side_resolved=side in (HandSide.LEFT, HandSide.RIGHT))


def score_of(times: dict[str, float], ts: float = 100.0):
    sc = WashScorer()
    sc.add_events([ev(t, d) for t, d in times.items()])
    return sc.update(ts)


def secs(score, tech):
    return next(st.seconds for st in score.steps if st.technique == tech)


def test_default_steps_match_labels_and_dev_config():
    assert ScoringConfig().steps == STEPS and len(STEPS) == 7 and STEPS[-1] == "wrist_rubbing"
    dev = PipelineConfig.load(resolve_path("configs/development.yaml"))
    assert dev.scoring.steps == STEPS and dev.scoring.step_min_s == 3.0 and dev.scoring.steps_required == 5
    assert dev.scoring.total_min_s == 20.0


def test_step_time_adds_up_across_tries_and_hands():
    sc = WashScorer()
    sc.add_events([ev("palm_to_palm", 1.5), ev("palm_to_palm", 1.5, side=HandSide.LEFT)])
    s = sc.update(10.0)
    assert secs(s, "palm_to_palm") == pytest.approx(3.0) and s.steps[0].done and s.steps_done == 1
    assert not score_of({"palm_to_palm": 2.9}).steps[0].done


def test_finish_needs_enough_steps_and_enough_total_time():
    five_short = {t: 3.0 for t in STEPS[:5]}  # 5 steps done but only 15 s
    s = score_of(five_short)
    assert s.steps_done == 5 and s.total_s == pytest.approx(15.0) and not s.finished and s.stars == 2
    many_seconds_few_steps = {t: 8.0 for t in STEPS[:4]}  # 32 s but only 4 steps
    s = score_of(many_seconds_few_steps)
    assert s.total_s >= 20 and s.steps_done == 4 and not s.finished
    s = score_of({**five_short, "palm_to_palm": 8.0})  # 5 steps and 20 s
    assert s.finished and s.finished_at_ts == 100.0 and s.stars == 3


@pytest.mark.parametrize("times,stars,points", [
    ({}, 0, 0),
    ({"palm_to_palm": 1.5}, 1, 7),                        # 5 + 30*1.5/20 = 7.25
    ({"palm_to_palm": 3.0, "back_of_hand": 3.0, "interlaced_fingers": 3.0}, 2, 44),  # 30 + 13.5
    ({"palm_to_palm": 10.0}, 2, 25),                       # time path to 2 stars: 10 + 15
    ({t: 4.0 for t in STEPS[:5]}, 3, 80),                  # finished with 5 steps
    ({t: 3.4 for t in STEPS[:6]}, 4, 90),                  # finished with 6 steps (20.4 s)
    ({t: 3.0 for t in STEPS}, 5, 100),                     # all 7 steps (21 s)
])
def test_stars_and_points_milestones(times, stars, points):
    s = score_of(times)
    assert s.stars == stars and s.points == points


def test_score_freezes_once_finished():
    sc = WashScorer()
    sc.add_events([ev(t, 4.0) for t in STEPS[:5]])
    first = sc.update(50.0)
    assert first.finished and first.stars == 3
    sc.add_events([ev("fingertip_rubbing", 5.0), ev("wrist_rubbing", 5.0)])
    later = sc.update(80.0)
    assert later == first and later.finished_at_ts == 50.0 and later.stars == 3
    assert sc.final(90.0) == first


def test_next_step_follows_who_order_and_skips_done_steps():
    assert score_of({}).next_step == "palm_to_palm"
    s = score_of({"palm_to_palm": 3.0, "interlaced_fingers": 3.0, "back_of_hand": 1.0})
    assert s.next_step == "back_of_hand"
    s = score_of({"palm_to_palm": 3.0, "interlaced_fingers": 3.0, "back_of_hand": 3.0})
    assert s.next_step == "backs_of_fingers"


def test_wrist_counts_and_rejected_unknown_and_duplicate_events_do_not():
    assert score_of({"wrist_rubbing": 3.0}).steps[-1].done
    sc = WashScorer()
    e = ev("palm_to_palm", 2.0)
    sc.add_events([e, e])  # same event twice counts once
    sc.add_events([ev("palm_to_palm", 5.0, status=ValidationStatus.REJECTED), ev("none", 5.0), ev("transition", 5.0)])
    s = sc.update(20.0)
    assert secs(s, "palm_to_palm") == pytest.approx(2.0) and s.total_s == pytest.approx(2.0)


def _drive(seq, cfg, fps=15):
    """Run frames through a real EventDetector + scorer; return (live palm seconds per frame, scorer, detector)."""
    det, sc, live = EventDetector(cfg, "s"), WashScorer(), []
    for i, (tech, conf) in enumerate(seq):
        ts = i / fps
        p = make_pred("fusion", ts, tech, conf) if tech else make_pred("fusion", ts, None, status=PredictionStatus.UNKNOWN)
        sc.add_events(det.update(p, 0.9))
        live.append((secs(sc.update(ts, det.state.active, det.pending), "palm_to_palm"), len(det.state.events), det.state.active))
    sc.add_events(det.flush())
    return live, sc, det


def test_live_timer_counts_candidate_only_after_validation_and_never_double_counts():
    cfg = TemporalConfig(min_duration_s=1.0, max_gap_s=0.5, merge_gap_s=0.75)
    live, sc, det = _drive([("palm_to_palm", 0.9)] * 45 + [(None, 0)] * 40, cfg)
    vals = [v for v, _, _ in live]
    assert vals[5] == 0.0  # 0.33 s in: not validated yet
    first_live = next(i for i, v in enumerate(vals) if v > 0)
    assert live[first_live][2] is not None and live[first_live][2].validated and live[first_live][1] == 0  # live before any event is released
    assert all(b >= a for a, b in zip(vals, vals[1:], strict=False))
    final = secs(sc.final(10.0), "palm_to_palm")
    assert final == pytest.approx(sum(e.validated_duration_s for e in det.state.events), abs=1e-3)
    assert max(vals) == pytest.approx(final, abs=1e-3)


def test_merged_fragments_are_not_double_counted():
    cfg = TemporalConfig(min_duration_s=0.5, max_gap_s=0.3, merge_gap_s=0.75, duplicate_window_s=1.0)
    seq = [("palm_to_palm", 0.9)] * 15 + [(None, 0)] * 6 + [("palm_to_palm", 0.9)] * 15 + [(None, 0)] * 40
    live, sc, det = _drive(seq, cfg)
    assert det.state.merged_count == 1 and len(det.state.events) == 1
    vals = [v for v, _, _ in live]
    final = secs(sc.final(10.0), "palm_to_palm")
    assert final == pytest.approx(det.state.events[0].validated_duration_s, abs=1e-3)
    assert max(vals) <= final + 1e-3 and vals[-1] == pytest.approx(final, abs=1e-3)
    assert all(b >= a for a, b in zip(vals, vals[1:], strict=False))


def test_displayed_time_never_decreases_but_final_uses_released_events():
    sc = WashScorer()
    cand = Candidate(technique="palm_to_palm", side=HandSide.BOTH, side_resolved=True, start_ts=0.0, last_ts=2.0,
                     last_support_ts=2.0, supported_s=2.0, validated=True)
    assert secs(sc.update(2.0, cand), "palm_to_palm") == pytest.approx(2.0)
    assert secs(sc.update(3.0), "palm_to_palm") == pytest.approx(2.0)  # candidate vanished (e.g. dropped): bar holds
    assert secs(sc.final(3.0), "palm_to_palm") == 0.0  # nothing was released, so nothing is saved


def test_unvalidated_candidate_does_not_count_and_reset_clears():
    sc = WashScorer()
    cand = Candidate(technique="thumb_rubbing", side=HandSide.UNRESOLVED, side_resolved=False, start_ts=0.0, last_ts=0.6,
                     last_support_ts=0.6, supported_s=0.6, validated=False)
    assert sc.update(0.6, cand).total_s == 0.0
    sc.add_events([ev(t, 4.0) for t in STEPS[:5]])
    assert sc.update(30.0).finished and sc.finished
    sc.reset()
    s = sc.update(31.0)
    assert not s.finished and s.total_s == 0.0 and s.stars == 0 and not sc.finished


def test_score_panel_draws_without_error():
    from convergent.vision.overlays import draw_score_panel

    img = np.zeros((480, 640, 3), np.uint8)
    draw_score_panel(img, score_of({"palm_to_palm": 2.0}))
    assert img.any()
    img2 = np.zeros((480, 640, 3), np.uint8)
    draw_score_panel(img2, score_of({t: 3.0 for t in STEPS}))
    assert img2.any()


def _cand(tech, start, supported, validated=True):
    return Candidate(technique=tech, side=HandSide.UNRESOLVED, side_resolved=False, start_ts=start, last_ts=start + supported,
                     last_support_ts=start + supported, supported_s=supported, validated=validated)


def _released(tech, start, end):
    return GestureEvent(session_id="s", technique=tech, side=HandSide.UNRESOLVED, start_ts=start, end_ts=end,
                        validated_duration_s=end - start, confidence=0.9, validation_status=ValidationStatus.VALIDATED, side_resolved=False)


def test_validated_step_is_backfilled_for_recognition_lag():
    sc = WashScorer(ScoringConfig(backfill_s=1.5))
    sc.add_events([_released("palm_to_palm", 0.0, 10.0)])
    s = sc.update(14.0, _cand("back_of_hand", 13.0, 1.0))  # 3 s unrecognized gap before the new step
    assert secs(s, "back_of_hand") == pytest.approx(2.5)
    assert secs(sc.update(14.0, _cand("thumb_rubbing", 14.0, 1.0, validated=False)), "thumb_rubbing") == 0.0


def test_backfill_never_takes_time_already_credited():
    sc = WashScorer(ScoringConfig(backfill_s=1.5))
    sc.add_events([_released("palm_to_palm", 0.0, 10.0)])
    s = sc.update(11.5, _cand("back_of_hand", 10.5, 1.0))  # only 0.5 s since palm stopped counting
    assert secs(s, "back_of_hand") == pytest.approx(1.5)


def test_backfill_is_kept_after_the_step_is_released():
    sc = WashScorer(ScoringConfig(backfill_s=1.5))
    sc.add_events([_released("palm_to_palm", 0.0, 10.0)])
    sc.update(14.0, _cand("back_of_hand", 13.0, 1.0))
    sc.add_events([_released("back_of_hand", 13.0, 16.0)])
    assert secs(sc.final(20.0), "back_of_hand") == pytest.approx(4.5)
