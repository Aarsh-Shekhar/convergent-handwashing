"""temporal_v2: hand-relative features, slotting, augmentation, training, adapter, fusion vote."""

from __future__ import annotations

import json

import numpy as np
import pytest

from convergent.common.config import FusionConfig, PipelineConfig, TemporalV2Config, resolve_path
from convergent.common.types import HandObservation, HandSide, PredictionStatus, TrackedHands
from convergent.detection.fusion import FusionEngine
from convergent.detection.labels import LabelRegistry
from convergent.detection.pair_adapter import TemporalV2Adapter
from convergent.detection.pair_features import (
    FEATURE_DIM_V2,
    HandSlotter,
    PairAugmentConfig,
    augment_raw,
    featurize,
    smooth_probabilities,
    swap_slots,
)
from convergent.detection.pair_training import (
    IGNORE_LABEL,
    V2_CLASSES,
    PairTrainConfig,
    RawRecording,
    build_window_index,
    gather,
    split_groups,
    synthetic_raw_recordings,
    train_pair_model,
)
from convergent.detection.skia_adapter import SkiaTemporalAdapter

ASPECT = 4.0 / 3.0


def fake_hands(t: int = 24, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    raw = rng.uniform(0.3, 0.7, size=(t, 2, 21, 3)).astype(np.float32)
    raw[..., 2] *= 0.1
    raw[..., 0, 2] = 0.0
    pres = np.ones((t, 2), np.float32)
    pres[5:9, 1] = 0.0
    raw[5:9, 1] = 0.0
    return raw, pres


def transform(raw: np.ndarray, pres: np.ndarray, angle: float, scale: float, shift: tuple[float, float]) -> np.ndarray:
    p = raw.copy()
    p[..., 0] *= ASPECT
    p[..., 2] *= ASPECT
    c, s = np.cos(angle), np.sin(angle)
    x, y = p[..., 0] * c - p[..., 1] * s, p[..., 0] * s + p[..., 1] * c
    p[..., 0], p[..., 1], p[..., 2] = x * scale + shift[0], y * scale + shift[1], p[..., 2] * scale
    p[..., 0] /= ASPECT
    p[..., 2] /= ASPECT
    return p * (pres > 0.5)[..., None, None]


# --------------------------------------------------------------------------- features
def test_features_ignore_position_size_and_in_plane_rotation():
    raw, pres = fake_hands()
    f = featurize(raw, pres, ASPECT)
    assert f.shape == (24, FEATURE_DIM_V2) and np.isfinite(f).all()
    g = featurize(transform(raw, pres, 1.1, 1.7, (0.2, -0.1)), pres, ASPECT)
    assert np.abs(f - g).max() < 1e-3
    assert np.abs(f - featurize(transform(raw, pres, 0.4, 1.0, (0.0, 0.0)) + 0.0, pres, ASPECT)).max() < 1e-3


def test_absent_hand_is_zero_and_swap_matches_recomputation():
    raw, pres = fake_hands()
    f = featurize(raw, pres, ASPECT)
    assert not f[5:9, 90:180].any() and (f[5:9, -2:] == [1.0, 0.0]).all()  # slot 1 block zero, presence flags
    assert not f[5:9, 67:90].any()  # slot 0 has no "other hand" view while slot 1 is absent
    assert np.abs(swap_slots(f) - featurize(raw[:, ::-1], pres[:, ::-1], ASPECT)).max() < 1e-6


def test_motion_features_are_frame_rate_independent():
    t = np.arange(40) / 30.0
    raw = np.zeros((40, 2, 21, 3), np.float32)
    raw[:, :, :, 1] = 0.5 - np.linspace(0, 0.1, 21)[None, None, :]
    raw[:, 0, :, 0] = (0.3 + 0.1 * t)[:, None]  # hand 0 drifts right at a constant speed
    raw[:, 1, :, 0] = 0.7
    pres = np.ones((40, 2), np.float32)
    fast = featurize(raw, pres, ASPECT, t)            # 30 fps
    slow = featurize(raw[::2], pres[::2], ASPECT, t[::2])  # 15 fps, same physical motion
    assert fast[5, 63] == pytest.approx(slow[5, 63], rel=1e-3) and abs(fast[5, 63]) > 1e-3


def test_slotter_keeps_each_hand_in_its_slot():
    s = HandSlotter()
    a = np.zeros((21, 3), np.float32) + [0.3, 0.5, 0.0]
    b = np.zeros((21, 3), np.float32) + [0.7, 0.5, 0.0]
    raw, pres = s.assign([b, a], 0.0)  # detection order must not matter: left-most starts in slot 0
    assert pres.tolist() == [1.0, 1.0] and raw[0, 0, 0] == pytest.approx(0.3)
    raw, pres = s.assign([b + [0.01, 0, 0]], 0.07)  # only hand b visible -> stays in slot 1
    assert pres.tolist() == [0.0, 1.0]
    raw, pres = s.assign([b + [0.02, 0, 0], a], 0.14)  # a comes back, listed second
    assert raw[0, 0, 0] == pytest.approx(0.3) and raw[1, 0, 0] == pytest.approx(0.72)
    assert s.assign([], 0.2)[1].tolist() == [0.0, 0.0]


def test_augmentation_keeps_shapes_and_never_hides_the_only_hand():
    raw, pres = fake_hands(32, seed=1)
    rb, pb = np.stack([raw] * 64), np.stack([pres] * 64)
    ra, pa = augment_raw(rb, pb, np.full(64, ASPECT), PairAugmentConfig(drop_hand_p=1.0), np.random.default_rng(0))
    assert ra.shape == rb.shape and pa.shape == pb.shape and np.isfinite(ra).all()
    assert (pa.max(axis=2) == pb.max(axis=2)).all()  # a frame that had a hand still has one
    assert pa.sum() < pb.sum()  # hand dropout did hide something
    assert not ra[pa < 0.5].any()  # hidden hands are zeros
    assert np.isfinite(featurize(ra, pa, np.full(64, ASPECT))).all()


def test_probability_smoothing():
    a, b = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    assert (smooth_probabilities(None, b, 0.07, 0.4) == b).all() and (smooth_probabilities(a, b, 0.07, 0.0) == b).all()
    s = smooth_probabilities(a, b, 1 / 15, 0.4)
    assert 0.1 < s[1] < 0.2 and s.sum() == pytest.approx(1.0)
    for _ in range(40):
        s = smooth_probabilities(s, b, 1 / 15, 0.4)
    assert s[1] > 0.99


# --------------------------------------------------------------------------- dataset / training
def _rec(n: int = 80) -> tuple[RawRecording, np.ndarray]:
    hands = np.random.default_rng(0).uniform(0.3, 0.7, size=(n, 2, 21, 3)).astype(np.float32)
    pres = np.ones((n, 2), np.float32)
    pres[40:46] = 0.0  # a short dropout: both hands lost for 6 frames
    hands[40:46] = 0.0
    labels = np.array(["palm_to_palm"] * 30 + [IGNORE_LABEL] * 6 + ["thumb_rubbing"] * 44)
    return RawRecording("r", "s", "own", "round1", hands, pres, np.arange(n) / 15.0, labels), labels


def test_window_index_keeps_dropouts_pads_the_start_and_skips_unsettled_labels():
    rec, labels = _rec()
    wi = build_window_index([rec], window=16, stride=1, min_present=8)
    ends = wi.ends.tolist()
    assert min(ends) == 7  # the 8th frame with hands is the first one allowed to answer (no 16-frame warm-up)
    assert not set(ends) & set(range(40, 46))  # no window ends on a frame without hands
    assert 46 in ends and 47 in ends  # ...but the dropout does not reset anything: the next frame answers again
    assert all(labels[e] != IGNORE_LABEL for e in ends) and 36 not in ends and 38 not in ends  # right after a label change: unsettled
    assert set(wi.y.tolist()) == {V2_CLASSES.index("palm_to_palm"), V2_CLASSES.index("thumb_rubbing")}
    steady = RawRecording("r2", "s", "own", "round1", rec.hands, rec.presence, rec.timestamps, np.array(["palm_to_palm"] * 80))
    held = build_window_index([steady], window=16, stride=1, min_present=8, hold_frames=3).ends.tolist()
    assert {40, 41, 42} <= set(held) and not {43, 44, 45} & set(held)  # with a hold, the first frames of a dropout still answer
    raw, pres, t = gather(wi, np.array([ends.index(7), ends.index(47)]), 16)
    assert raw.shape == (2, 16, 2, 21, 3) and (np.diff(t, axis=1) > 0).all()
    assert pres[0, :8].sum() == 0 and pres[0, 8:].all() and not raw[0, :8].any()  # left-padded with empty frames
    assert pres[1, 8:14].sum() == 0 and pres[1, :8].all() and pres[1, 14:].all()  # the dropout sits inside the window
    assert np.allclose(raw[1, -1], rec.hands[47]) and np.allclose(raw[1, 0], rec.hands[32])
    with pytest.raises(ValueError):
        split_groups(wi, {"own:round1"})  # holding out the only group leaves nothing to train on
    with pytest.raises(ValueError):
        build_window_index([RawRecording("x", "s", "own", "g", rec.hands, rec.presence, rec.timestamps, np.array(["bogus"] * 80))], 16)


def test_speed_change_resamples_time_not_just_frames():
    rec, _ = _rec()
    wi = build_window_index([rec], window=16, stride=1)
    sel = np.array([wi.ends.tolist().index(79)])
    raw1, _, t1 = gather(wi, sel, 16)
    raw2, pres2, t2 = gather(wi, sel, 16, np.array([2.0]))  # twice as fast: every second frame, half the time step
    assert np.allclose(raw2[0, -1], raw1[0, -1]) and np.allclose(raw2[0, -2], rec.hands[77]) and np.allclose(raw2[0, 0], rec.hands[49])
    assert np.allclose(np.diff(t2[0]), np.diff(t1[0])) and pres2.all()  # same frame clock, more motion per frame
    raw3, _, t3 = gather(wi, sel, 16, np.array([0.5]))  # half speed: in-between frames are interpolated
    assert np.allclose(raw3[0, -2], 0.5 * (rec.hands[78] + rec.hands[79]), atol=1e-6) and np.allclose(np.diff(t3[0]), np.diff(t1[0]))


def test_named_test_groups_never_reach_training():
    recs = synthetic_raw_recordings(n_groups=8, frames=40)
    wi = build_window_index(recs, 16, 4)
    tr, va, te, split = split_groups(wi, {"synthetic:g3"})
    assert "synthetic:g3" in split["test"] and "synthetic:g3" not in split["train"]
    assert not set(wi.groups[tr]) & set(wi.groups[te]) and not set(wi.groups[tr]) & set(wi.groups[va])


@pytest.fixture(scope="module")
def tiny_artifact(tmp_path_factory):
    out = tmp_path_factory.mktemp("v2") / "art"
    cfg = PairTrainConfig(window=16, stride=2, epochs=20, hidden=32, layers=2, batch_size=64, patience=99, speed_range=None,
                          # the fake classes are defined by where hand B sits around hand A, so (unlike real
                          # washing) they are not symmetric under a mirror or a hand swap: leave those off here
                          augment=PairAugmentConfig(mirror=False, swap=False, tilt_deg=0.0, drop_hand_p=0.0, offset=0.0))
    res = train_pair_model(synthetic_raw_recordings(), out, cfg, log=lambda s: None)
    return out, res


def test_training_learns_and_saves_a_loadable_artifact(tiny_artifact):
    out, res = tiny_artifact
    assert res.metrics["test"]["accuracy"] > 0.7 and res.metrics["val"]["accuracy"] > 0.7
    meta = json.loads((out / "meta.json").read_text())
    assert meta["preprocessing_version"] == "pair-relative-v2" and meta["classes"] == V2_CLASSES and meta["architecture"] == "tcn"
    assert meta["feature_dim"] == FEATURE_DIM_V2 and not set(meta["split"]["train_groups"]) & set(meta["split"]["test_groups"])
    assert (out / "calibrator.json").exists() and (out / "model.pt").exists() and (out / "scaler.npz").exists()


def _tracked(rec: RawRecording, i: int, unassigned: bool = False) -> TrackedHands:
    a = HandObservation.from_array(rec.hands[i, 0].astype(np.float64), track_id=1, side=HandSide.LEFT, handedness_confidence=0.9,
                                   raw_handedness_label="Left", tracking_quality=0.9)
    b = HandObservation.from_array(rec.hands[i, 1].astype(np.float64), track_id=2, side=HandSide.UNKNOWN if unassigned else HandSide.RIGHT,
                                   handedness_confidence=0.9, raw_handedness_label="Right", tracking_quality=0.9)
    if unassigned:
        return TrackedHands(frame_id=i, capture_ts=float(rec.timestamps[i]), left=a, unassigned=[b])
    return TrackedHands(frame_id=i, capture_ts=float(rec.timestamps[i]), left=a, right=b)


@pytest.mark.parametrize("unassigned", [False, True])
def test_adapter_predicts_from_tracked_hands_even_without_a_resolved_side(tiny_artifact, unassigned):
    out, _ = tiny_artifact
    ad = TemporalV2Adapter(TemporalV2Config(artifact_dir=str(out), smooth_s=0.2))
    assert ad.load().available and ad.window_frames == 16
    rec = next(r for r in synthetic_raw_recordings(n_groups=1, frames=60, seed=5) if r.labels[0] == "thumb_rubbing")
    preds = [ad.predict(_tracked(rec, i, unassigned)) for i in range(60)]
    assert all(p.status == PredictionStatus.NO_INPUT for p in preds[:ad.min_present_frames - 1])  # a few frames of evidence first
    assert preds[ad.min_present_frames - 1].status != PredictionStatus.NO_INPUT  # ...but no full-window warm-up
    last = preds[-1]
    assert last.status == PredictionStatus.VALID and last.canonical.technique == "thumb_rubbing" and last.calibrated
    assert not last.canonical.resolved and sum(last.canonical_probabilities.values()) == pytest.approx(1.0, abs=1e-6)
    t_end = float(rec.timestamps[-1])
    assert 0.3 < ad.hold_s < 0.4 and not ad.holding(t_end)
    gone = ad.predict(TrackedHands(frame_id=98, capture_ts=t_end + 0.07))
    assert gone.status == PredictionStatus.VALID and ad.holding(t_end + 0.07)  # a short dropout: still answering from the history
    back = _tracked(rec, 59, unassigned).model_copy(update={"capture_ts": t_end + 0.14, "frame_id": 99})
    assert ad.predict(back).status == PredictionStatus.VALID
    for k in range(1, 9):  # hands stay away: the hold ends after hold_s
        out = ad.predict(TrackedHands(frame_id=99 + k, capture_ts=t_end + 0.14 + k / 15))
    assert out.status == PredictionStatus.NO_INPUT and not ad.holding(t_end + 0.14 + 8 / 15)
    late = _tracked(rec, 59, unassigned).model_copy(update={"capture_ts": t_end + 5.0, "frame_id": 200})
    assert ad.predict(late).status == PredictionStatus.NO_INPUT  # a long break clears the history


def test_adapter_reports_not_washing_as_unknown_with_its_distribution(tiny_artifact):
    out, _ = tiny_artifact
    ad = TemporalV2Adapter(TemporalV2Config(artifact_dir=str(out)))
    ad.load()
    rec = next(r for r in synthetic_raw_recordings(n_groups=1, frames=60, seed=6) if r.labels[0] == "none")
    last = [ad.predict(_tracked(rec, i)) for i in range(60)][-1]
    assert last.status == PredictionStatus.UNKNOWN and last.canonical is None
    assert max(last.canonical_probabilities, key=last.canonical_probabilities.get) == "none"
    fused = FusionEngine(FusionConfig(weights={"temporal_v2": 1.0})).combine({"temporal_v2": last}, last.window_end_ts)
    assert fused.status == PredictionStatus.UNKNOWN and fused.extras["participating"] == ["temporal_v2"]


def test_artifacts_are_not_interchangeable_between_branches(tiny_artifact, tmp_path):
    out, _ = tiny_artifact
    cfg = PipelineConfig.load(None, {"skia": {"temporal_artifact_dir": str(out)}}).skia
    st = SkiaTemporalAdapter(cfg).load()
    assert not st.available and "MODEL_UNAVAILABLE" in st.message
    st = TemporalV2Adapter(TemporalV2Config(artifact_dir=str(tmp_path / "missing"))).load()
    assert not st.available and "MODEL_UNAVAILABLE" in st.message
    assert not TemporalV2Adapter(TemporalV2Config(enabled=False)).load().available


def test_label_registry_maps_v2_classes_and_dev_config_loads():
    reg = LabelRegistry.load(resolve_path("configs/labels.yaml"))
    m = reg.model_map("temporal_v2")
    assert m.native_order == V2_CLASSES and m.canonical_for("none").technique == "none"
    assert m.canonical_for("palm_to_palm").side == HandSide.BOTH and not m.canonical_for("thumb_rubbing").resolved
    dev = PipelineConfig.load(resolve_path("configs/development.yaml"))
    assert dev.temporal_v2.enabled and "temporal_v2" in dev.fusion.weights


def test_unsure_branch_still_votes_in_fusion():
    from tests.conftest import make_pred

    sure = make_pred("skia_temporal", 1.0, "interlaced_fingers", 0.55, dist={"interlaced_fingers": 0.55, "palm_to_palm": 0.45})
    unsure = make_pred("handhygiene", 1.0, None, status=PredictionStatus.UNKNOWN, dist={"palm_to_palm": 0.39, "interlaced_fingers": 0.25, "thumb_rubbing": 0.36})
    eng = FusionEngine(FusionConfig(weights={"skia_temporal": 1.0, "handhygiene": 1.0}))
    fused = eng.combine({"skia_temporal": sure, "handhygiene": unsure}, 1.0)
    assert set(fused.extras["participating"]) == {"skia_temporal", "handhygiene"}
    assert fused.extras["technique_distribution"]["palm_to_palm"] == pytest.approx(0.42)
