"""Auto wash sessions (scoring/wash_session.py and the pipeline): one record per wash, for the parents' app."""

from __future__ import annotations

import json

from convergent.common.config import PipelineConfig, resolve_path
from convergent.pipeline import Pipeline
from convergent.scoring.wash_session import WashRecord, WashSessions
from convergent.vision.hand_tracker import HandTracker, ScriptedBackend
from tests.conftest import make_frame, synthetic_hand
from tests.unit.test_wash_score import ev

DT = 1 / 15
HAND = [(synthetic_hand(0.5, 0.5, scale=0.3), "Left", 0.95)]


def drive(w: WashSessions, t0: float, seconds: float, present: bool) -> tuple[float, list[tuple[float, str]]]:
    t, out = t0, []
    while t < t0 + seconds - 1e-9:
        t += DT
        change = w.update(t, present)
        if change:
            out.append((round(t, 2), change))
    return t, out


# ---------------------------------------------------------------- start / end rule
def test_a_wash_starts_after_half_a_second_of_hands_and_ends_four_seconds_after_they_leave():
    w = WashSessions()
    t, changes = drive(w, 0.0, 2.0, True)
    assert [c for _, c in changes] == ["start"] and 0.5 <= changes[0][0] <= 0.65 and w.washing
    assert abs(w.started_ts - DT) < 1e-6  # counted from the first frame with a hand
    t, changes = drive(w, t, 3.9, False)
    assert changes == [] and w.washing  # hands away for under 4 s: still the same wash
    t, changes = drive(w, t, 0.3, False)
    assert [c for _, c in changes] == ["end"] and not w.washing and abs(w.ended_ts - 2.0) < 1e-6  # ends when the hands were last seen


def test_a_flicker_of_a_hand_starts_nothing_and_a_short_gap_does_not_end_a_wash():
    w = WashSessions()
    t, changes = drive(w, 0.0, 0.3, True)
    t, more = drive(w, t, 1.0, False)
    assert changes + more == [] and not w.washing
    t, _ = drive(w, t, 1.0, True)
    t, _ = drive(w, t, 2.0, False)
    t, changes = drive(w, t, 1.0, True)
    assert changes == [] and w.washing


# ---------------------------------------------------------------- in the pipeline
def pipeline(script: list, enabled: bool = True) -> Pipeline:  # type: ignore[type-arg]
    cfg = PipelineConfig.load(resolve_path("configs/development.yaml"), {"wash_sessions": {"enabled": enabled}})
    return Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(script)))


def frames(pipe: Pipeline, n: int, start: int = 0) -> int:
    for i in range(start, start + n):
        pipe.process_frame(make_frame(i, i / 15))
    return start + n


def test_two_washes_give_two_records_and_the_second_starts_from_zero():
    pipe = pipeline([HAND] * 75 + [[]] * 75 + [HAND] * 75 + [[]] * 75)
    seen: list[WashRecord] = []
    pipe.on_wash = seen.append
    i = frames(pipe, 60)
    pipe.scorer.add_events([ev("palm_to_palm", 3.5)])  # the first wash: palms for 3.5 s
    i = frames(pipe, 240, i)
    assert len(pipe.wash_records) == 2 and seen == pipe.wash_records
    first, second = pipe.wash_records
    assert first.wash_id != second.wash_id and first.schema_version == "wash-record-v1"
    assert first.seconds["palm_to_palm"] == 3.5 and first.score.steps_done == 1
    assert all(v == 0 for v in second.seconds.values()) and second.score.points == 0  # nothing carried over
    assert 4.5 < first.duration_s < 5.5 and first.started_utc < first.ended_utc  # (this test runs faster than real time, so washes overlap on the wall clock)
    q = first.quality
    assert 70 <= q["frames"] <= 76 and q["no_hand_share"] == 0.0 and q["two_hand_share"] == 0.0 and 14 < q["fps"] < 16
    assert pipe.scene.germs_left == 80  # the germs are back for the next child


def test_a_walk_by_gives_no_record():
    pipe = pipeline([HAND] * 22 + [[]] * 90)  # a hand in view for 1.5 s, nothing washed
    frames(pipe, 112)
    assert pipe.wash_records == [] and not pipe.washes.washing


def test_switched_off_nothing_is_split_or_reset():
    pipe = pipeline([HAND] * 30 + [[]] * 90, enabled=False)
    i = frames(pipe, 20)
    pipe.scorer.add_events([ev("palm_to_palm", 3.5)])
    frames(pipe, 100, i)
    assert pipe.washes is None and pipe.wash_records == []
    assert pipe.scorer.final(8.0).steps_done == 1  # one run is still one session


def test_records_are_saved_as_lines_and_put_on_the_live_feed(tmp_path):
    pipe = pipeline([HAND] * 75 + [[]] * 75)
    pipe._results_dir = tmp_path
    results = [pipe.process_frame(make_frame(i, i / 15)) for i in range(150)]
    lines = (tmp_path / "washes.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["wash_id"] == pipe.wash_records[0].wash_id
    ended = [r for r in results if pipe.live_update(r).get("wash")]
    assert len(ended) == 1 and pipe.live_update(ended[0])["wash"]["duration_s"] == pipe.wash_records[0].duration_s


def test_a_wash_still_going_when_the_run_stops_is_recorded_in_the_summary():
    cfg = PipelineConfig.load(resolve_path("configs/development.yaml"),
                              {"wash_sessions": {"enabled": True}, "source": {"kind": "synthetic", "max_frames": 60, "target_fps": 15.0}, "live_status_every_s": 0})
    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend([HAND])))
    summary = pipe.run()
    assert len(summary.washes) == 1 and summary.washes[0]["duration_s"] > 3.0
    assert summary.washes[0]["soap_seen"] is False  # the soap check ran and saw none (None would mean it is switched off)
    assert json.loads(summary.to_json())["washes"][0]["wash_id"] == summary.washes[0]["wash_id"]
