import numpy as np
import pytest

from convergent.common.config import FusionConfig, TemporalConfig
from convergent.common.types import HandSide, PredictionStatus, ValidationStatus
from convergent.detection.confidence_calibration import Calibrator, expected_calibration_error
from convergent.detection.evaluation import (
    LatencyStats,
    RefEvent,
    branch_subsets,
    event_metrics,
    frame_metrics,
    missing_step_detection,
    run_ablation,
)
from convergent.detection.event_detector import EventDetector
from convergent.detection.fusion import FusionEngine, MetaClassifierFusion, PredictionAligner
from convergent.detection.temporal import TemporalValidator
from tests.conftest import make_pred

W = {"handhygiene": 1.0, "skia_temporal": 1.0, "yolo": 1.0}


def engine(**kw) -> FusionEngine:
    return FusionEngine(FusionConfig(weights=W, **kw))


# --------------------------------------------------------------------------- fusion
def test_fusion_all_three_agree():
    f = engine().combine({"handhygiene": make_pred("handhygiene", 1.0, "palm_to_palm", 0.9),
                          "skia_temporal": make_pred("skia_temporal", 1.0, "palm_to_palm", 0.8),
                          "yolo": make_pred("yolo", 1.0, "palm_to_palm", 0.7)}, 1.0)
    assert f.status == PredictionStatus.VALID and f.canonical.technique == "palm_to_palm"
    assert f.extras["participating"] == ["handhygiene", "skia_temporal", "yolo"]
    assert f.confidence == pytest.approx(0.8)
    assert f.canonical.side == HandSide.BOTH


def test_fusion_missing_branches_renormalize_without_implicit_support():
    preds = {"handhygiene": make_pred("handhygiene", 1.0, "thumb_rubbing", 0.9, side=HandSide.LEFT),
             "skia_temporal": make_pred("skia_temporal", 1.0, None, status=PredictionStatus.MODEL_UNAVAILABLE),
             "yolo": make_pred("yolo", 1.0, None, status=PredictionStatus.NO_INPUT)}
    f = engine().combine(preds, 1.0)
    assert f.status == PredictionStatus.VALID and f.extras["participating"] == ["handhygiene"]
    assert f.confidence == pytest.approx(0.9)  # not diluted by missing branches
    assert f.canonical.side == HandSide.LEFT and f.canonical.resolved
    f2 = engine(min_branches=2).combine(preds, 1.0)
    assert f2.status == PredictionStatus.NO_INPUT
    f3 = engine().combine({k: make_pred(k, 1.0, None, status=PredictionStatus.MODEL_UNAVAILABLE) for k in W}, 1.0)
    assert f3.status == PredictionStatus.NO_INPUT and f3.extras["participating"] == []


def test_fusion_contradiction_reduces_confidence_and_unknown_rejection():
    f = engine(unknown_threshold=0.45).combine({"handhygiene": make_pred("handhygiene", 1.0, "palm_to_palm", 0.9),
                                               "skia_temporal": make_pred("skia_temporal", 1.0, "interlaced_fingers", 0.85)}, 1.0)
    assert f.extras["contradictions"]  # one branch strongly disagrees
    assert f.status == PredictionStatus.UNKNOWN or f.confidence < 0.5
    g = engine(unknown_threshold=0.9).combine({"handhygiene": make_pred("handhygiene", 1.0, "palm_to_palm", 0.6)}, 1.0)
    assert g.status == PredictionStatus.UNKNOWN and "below threshold" in g.message


def test_fusion_invalid_label_mapping_marks_branch_error():
    bad = make_pred("yolo", 1.0, "palm_to_palm", 0.9, dist={"not_a_key": 0.9})
    f = engine().combine({"yolo": bad, "handhygiene": make_pred("handhygiene", 1.0, "palm_to_palm", 0.7)}, 1.0)
    statuses = {b["model_id"]: b["status"] for b in f.extras["branches"]}
    assert statuses["yolo"] == "error" and f.extras["participating"] == ["handhygiene"]


def test_fusion_side_resolution_and_unresolved_flags():
    f = engine().combine({"handhygiene": make_pred("handhygiene", 1.0, "thumb_rubbing", 0.9, side=HandSide.UNRESOLVED, resolved=False)}, 1.0)
    assert f.canonical.technique == "thumb_rubbing" and f.canonical.side == HandSide.UNRESOLVED and not f.canonical.resolved
    g = engine().combine({"handhygiene": make_pred("handhygiene", 1.0, "thumb_rubbing", 0.9, side=HandSide.UNRESOLVED, resolved=False),
                          "skia_temporal": make_pred("skia_temporal", 1.0, "thumb_rubbing", 0.9, side=HandSide.RIGHT)}, 1.0)
    assert g.canonical.side == HandSide.RIGHT and g.canonical.resolved


def test_fusion_requires_tracking_and_weights_zero_excludes():
    f = engine().combine({"handhygiene": make_pred("handhygiene", 1.0, "palm_to_palm", 0.9)}, 1.0, tracking_ok=False)
    assert f.status == PredictionStatus.NO_INPUT
    e = FusionEngine(FusionConfig(weights={"handhygiene": 0.0, "yolo": 1.0}))
    g = e.combine({"handhygiene": make_pred("handhygiene", 1.0, "palm_to_palm", 0.9), "yolo": make_pred("yolo", 1.0, "thumb_rubbing", 0.8, side=HandSide.LEFT)}, 1.0)
    assert g.extras["participating"] == ["yolo"] and g.canonical.technique == "thumb_rubbing"


def test_prediction_aligner_window_and_staleness():
    al = PredictionAligner(tolerance_s=0.1, max_age_s=0.5)
    al.offer(make_pred("skia_temporal", 2.0, "palm_to_palm", 0.9, window=1.0))  # covers 1.0..2.0
    al.offer(make_pred("yolo", 1.0, "palm_to_palm", 0.9))
    assert set(al.collect(1.5)) == {"skia_temporal", "yolo"}
    assert set(al.collect(2.4)) == {"skia_temporal"}  # yolo is 1.4 s old -> stale
    assert set(al.collect(0.5)) == set()
    al.offer(make_pred("handhygiene", 0.0, None, status=PredictionStatus.MODEL_UNAVAILABLE))
    assert "handhygiene" in al.collect(99.0)  # unavailability is always reported


def test_calibration_temperature_and_histogram_reduce_ece():
    rng = np.random.default_rng(0)
    n = 2000
    logits = rng.normal(size=(n, 3))
    labels = logits.argmax(1)
    flip = rng.random(n) < 0.4  # 40% of the time the confident prediction is wrong -> over-confident
    labels[flip] = (labels[flip] + 1) % 3
    over = np.exp(logits * 6)
    probs = over / over.sum(axis=1, keepdims=True)
    before = expected_calibration_error(probs.max(1), probs.argmax(1) == labels)
    cal = Calibrator.fit_temperature(probs, labels)
    assert cal.fitted and cal.temperature > 1.0 and cal.ece_after < before
    hist = Calibrator.fit_histogram(probs, labels)
    assert hist.ece_after <= before + 1e-9
    out = cal.apply(probs[0])
    assert abs(out.sum() - 1) < 1e-9
    ident = Calibrator()
    assert np.allclose(ident.apply(np.array([2.0, 2.0])), [0.5, 0.5])
    fe = FusionEngine(FusionConfig(weights=W), calibrators={"handhygiene": cal})
    f = fe.combine({"handhygiene": make_pred("handhygiene", 1.0, "palm_to_palm", 0.99, dist={"palm_to_palm": 0.99, "none": 0.01})}, 1.0)
    assert f.calibrated and f.confidence < 0.99


def test_meta_fusion_requires_out_of_sample_acknowledgement():
    mf = MetaClassifierFusion()
    fe = engine()
    x = np.stack([mf.featurize({"handhygiene": make_pred("handhygiene", 1.0, t, 0.9)}, fe) for t in ("palm_to_palm", "thumb_rubbing") * 10])
    y = ["palm_to_palm", "thumb_rubbing"] * 10
    with pytest.raises(ValueError):
        mf.fit(x, y)
    mf.fit(x, y, out_of_sample=True)
    assert max(mf.predict_proba(x[0]), key=mf.predict_proba(x[0]).get) == "palm_to_palm"


# --------------------------------------------------------------------------- temporal
def run_validator(seq, cfg=None, fps=15.0, quality=0.9):
    v = TemporalValidator(cfg or TemporalConfig(min_duration_s=1.0, max_gap_s=0.5), "s")
    ended = []
    for i, (tech, conf) in enumerate(seq):
        ts = i / fps
        p = make_pred("fusion", ts, tech, conf) if tech else make_pred("fusion", ts, None, status=PredictionStatus.UNKNOWN)
        ended.extend(v.update(p, quality).ended)
    ended.extend(v.flush())
    return ended


def test_sustained_gesture_validated_and_short_one_rejected():
    ev = run_validator([("palm_to_palm", 0.9)] * 30)  # 2 s at 15 fps
    assert len(ev) == 1 and ev[0].validation_status == ValidationStatus.VALIDATED
    assert ev[0].validated_duration_s == pytest.approx(29 / 15, abs=1e-6)
    short = run_validator([("palm_to_palm", 0.9)] * 5 + [(None, 0)] * 20)
    assert len(short) == 1 and short[0].validation_status == ValidationStatus.REJECTED


def test_same_duration_at_different_frame_rates():
    e10 = run_validator([("palm_to_palm", 0.9)] * 21, fps=10)  # 2.0 s
    e30 = run_validator([("palm_to_palm", 0.9)] * 61, fps=30)  # 2.0 s
    assert e10[0].validated_duration_s == pytest.approx(e30[0].validated_duration_s, abs=1e-6)


def test_transition_switches_candidate_and_repeated_gestures_are_separate():
    seq = [("palm_to_palm", 0.9)] * 20 + [("thumb_rubbing", 0.9)] * 20 + [("palm_to_palm", 0.9)] * 20
    ev = run_validator(seq)
    assert [e.technique for e in ev] == ["palm_to_palm", "thumb_rubbing", "palm_to_palm"]
    assert all(e.validation_status == ValidationStatus.VALIDATED for e in ev)


def test_uncertain_frames_pause_without_advancing_and_long_gap_ends():
    seq = [("palm_to_palm", 0.9)] * 10 + [(None, 0)] * 5 + [("palm_to_palm", 0.9)] * 10  # 0.33 s gap < max_gap
    ev = run_validator(seq)
    assert len(ev) == 1 and ev[0].validation_status == ValidationStatus.VALIDATED
    assert ev[0].validated_duration_s < ev[0].end_ts - ev[0].start_ts  # gap did not count as support
    seq2 = [("palm_to_palm", 0.9)] * 20 + [(None, 0)] * 15 + [("palm_to_palm", 0.9)] * 20  # 1 s gap > max_gap
    ev2 = run_validator(seq2)
    assert len(ev2) == 2


def test_hysteresis_exit_and_tracking_gating():
    cfg = TemporalConfig(enter_confidence=0.7, exit_confidence=0.4, min_duration_s=0.5, max_gap_s=0.5)
    ev = run_validator([("palm_to_palm", 0.75)] * 5 + [("palm_to_palm", 0.5)] * 20, cfg)  # stays above exit
    assert len(ev) == 1 and ev[0].validation_status == ValidationStatus.VALIDATED
    none = run_validator([("palm_to_palm", 0.6)] * 20, cfg)  # never reaches enter
    assert none == []
    gated = run_validator([("palm_to_palm", 0.9)] * 20, cfg, quality=0.1)
    assert gated == []


def test_max_event_duration_cap_and_timestamp_monotonicity():
    cfg = TemporalConfig(min_duration_s=0.5, max_event_duration_s=1.0, max_gap_s=0.5)
    ev = run_validator([("palm_to_palm", 0.9)] * 60, cfg)  # 4 s -> capped into several
    assert len(ev) >= 3 and all(e.end_ts - e.start_ts <= 1.0 + 1e-6 for e in ev)
    v = TemporalValidator(cfg, "s")
    v.update(make_pred("fusion", 1.0, "palm_to_palm", 0.9), 0.9)
    with pytest.raises(ValueError):
        v.update(make_pred("fusion", 0.5, "palm_to_palm", 0.9), 0.9)


def test_event_detector_merges_fragments_and_suppresses_duplicates():
    cfg = TemporalConfig(min_duration_s=0.5, max_gap_s=0.3, merge_gap_s=0.75, duplicate_window_s=1.0)
    det = EventDetector(cfg, "s")
    out = []
    fps = 15
    seq = [("palm_to_palm", 0.9)] * 15 + [(None, 0)] * 6 + [("palm_to_palm", 0.9)] * 15 + [(None, 0)] * 40
    for i, (tech, conf) in enumerate(seq):
        p = make_pred("fusion", i / fps, tech, conf) if tech else make_pred("fusion", i / fps, None, status=PredictionStatus.UNKNOWN)
        out.extend(det.update(p, 0.9))
    out.extend(det.flush())
    assert len(out) == 1 and det.state.merged_count == 1
    assert out[0].validated_duration_s > 1.5 and out[0].tracking_gaps_s > 0
    assert out[0].side_resolved and out[0].sequence_no >= 1


def test_no_duplicate_completion_for_same_event():
    det = EventDetector(TemporalConfig(min_duration_s=0.5, max_gap_s=0.3), "s")
    out = []
    for i in range(20):
        out.extend(det.update(make_pred("fusion", i / 15, "palm_to_palm", 0.9), 0.9))
    out.extend(det.flush())
    out.extend(det.flush())  # second flush must not re-emit
    assert len(out) == 1 and len(det.state.events) == 1


# --------------------------------------------------------------------------- evaluation
def test_frame_and_event_metrics():
    fm = frame_metrics(["a", "a", "b", "b"], ["a", "b", "b", "b"], ["a", "b"])
    assert fm.accuracy == 0.75 and fm.confusion == [[1, 1], [0, 2]] and fm.per_class["a"]["recall"] == 0.5
    ev = run_validator([("palm_to_palm", 0.9)] * 30 + [("thumb_rubbing", 0.9)] * 30)
    refs = [RefEvent("palm_to_palm", 0.0, 2.0), RefEvent("interlaced_fingers", 2.0, 4.0)]
    em = event_metrics(ev, refs, iou_threshold=0.3)
    assert em.true_positives == 1 and em.false_positives == 1 and em.false_negatives == 1
    assert em.false_completion_rate == 0.5 and 0 < em.mean_matched_iou <= 1
    ms = missing_step_detection(ev, refs, ["palm_to_palm", "interlaced_fingers", "thumb_rubbing"])
    assert ms.predicted_missing == ["interlaced_fingers"] and ms.actual_missing == ["thumb_rubbing"] and not ms.correct
    ls = LatencyStats.from_samples([10, 20, 30])
    assert ls.p50_ms == 20 and ls.max_ms == 30 and LatencyStats.from_samples([]).n == 0


def test_ablation_covers_all_subsets():
    subsets = branch_subsets(("a", "b", "c"))
    assert len(subsets) == 7
    res = run_ablation(lambda s: {"n": len(s)}, ("a", "b"))
    assert [r["branches"] for r in res] == [["a"], ["b"], ["a", "b"]]
