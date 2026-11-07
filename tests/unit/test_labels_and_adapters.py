from pathlib import Path

import numpy as np
import pytest

from convergent.common.config import HandHygieneConfig, SkiaConfig, YoloConfig, resolve_path
from convergent.common.types import HandSide, PredictionStatus
from convergent.detection.handhygiene_adapter import (
    HANDHYGIENE_NUM_FEATURES,
    HandHygieneAdapter,
    centroid_normalize,
    handhygiene_feature_vector,
    select_hands,
)
from convergent.detection.labels import LabelMappingError, LabelRegistry, default_registry
from convergent.detection.lstm_model import (
    FeatureScaler,
    TemporalArtifact,
    TemporalArtifactMeta,
    build_model,
)
from convergent.detection.numpy_forest import NumpyForestPipeline
from convergent.detection.sequence_buffer import SequenceBuffer, windows_from_sequence
from convergent.detection.skia_adapter import (
    SKIA_STEP_NAMES,
    SkiaLegacyAdapter,
    SkiaTemporalAdapter,
    legacy_normalize,
    skia_feature_vector,
    skia_observation,
)
from convergent.detection.training import synthetic_recordings, train_temporal_model
from convergent.detection.yolo_adapter import (
    YOLO_NATIVE_NAMES,
    YoloAdapter,
    decode_predictions,
    detections_to_distribution,
    letterbox,
    nms,
    scale_boxes,
    to_model_input,
)
from tests.conftest import make_frame, make_hands, synthetic_hand

REG = default_registry()


# --------------------------------------------------------------------------- labels
def test_registry_core_and_mappings_resolved_flags():
    assert REG.core == ["palm_to_palm", "back_of_hand", "interlaced_fingers", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing"]
    hh = REG.model_map("handhygiene")
    assert hh.canonical_for("1").technique == "palm_to_palm" and hh.canonical_for("1").side == HandSide.BOTH
    assert hh.canonical_for("5.1").technique == "thumb_rubbing" and not hh.canonical_for("5.1").resolved
    assert hh.canonical_for_index(9).technique == "fingertip_rubbing"
    sk = REG.model_map("skia")
    assert sk.canonical_for("7lt").technique == "wrist_rubbing" and not REG.is_core("wrist_rubbing")
    yo = REG.model_map("yolo")
    assert yo.canonical_for("Step4").technique == "backs_of_fingers" and yo.canonical_for("Step4").side == HandSide.UNKNOWN
    with pytest.raises(LabelMappingError):
        hh.canonical_for("99")
    with pytest.raises(LabelMappingError):
        REG.model_map("nope")
    assert "left_thumb_rubbing" in REG.canonical_keys() and "none" in REG.canonical_keys()
    assert REG.technique_of_key("right_back_of_hand") == "back_of_hand" and REG.side_of_key("left_x") == HandSide.LEFT


def test_registry_side_resolution_override_and_invalid_config():
    import yaml

    data = yaml.safe_load(Path(resolve_path("configs/labels.yaml")).read_text(encoding="utf-8"))
    data["side_resolution"] = {"skia:5lt": "left"}
    reg = LabelRegistry.from_dict(data)
    lab = reg.model_map("skia").canonical_for("5lt")
    assert lab.resolved and lab.side == HandSide.LEFT
    bad = dict(data)
    bad["models"] = {"x": {"native_order": ["a"], "map": {"a": {"technique": "not_a_technique"}}}}
    with pytest.raises(LabelMappingError):
        LabelRegistry.from_dict(bad)
    bad2 = dict(data)
    bad2["models"] = {"x": {"native_order": ["a", "b"], "map": {"a": {"technique": "palm_to_palm"}}}}
    with pytest.raises(LabelMappingError):
        LabelRegistry.from_dict(bad2)


# --------------------------------------------------------------------------- HandHygiene
def test_handhygiene_feature_ordering_right_then_left_centroid_normalized():
    right = synthetic_hand(0.7, 0.5, seed=1)
    left = synthetic_hand(0.3, 0.5, seed=2, mirror=True)
    x = handhygiene_feature_vector(right, left)
    assert x.shape == (HANDHYGIENE_NUM_FEATURES,)
    assert np.allclose(x[:63].reshape(21, 3), right - right.mean(axis=0))
    assert np.allclose(x[63:].reshape(21, 3), left - left.mean(axis=0))
    assert np.allclose(x[:63].reshape(21, 3).mean(axis=0), 0)  # centroid removed
    assert np.allclose(x[0:3], centroid_normalize(right)[0])  # row-major x,y,z per landmark


def test_handhygiene_missing_hand_is_zero_block_and_requires_one_hand():
    right = synthetic_hand()
    x = handhygiene_feature_vector(right, None)
    assert np.all(x[63:] == 0) and np.any(x[:63] != 0)
    with pytest.raises(ValueError):
        handhygiene_feature_vector(None, None)


def test_select_hands_raw_label_vs_anatomical():
    hands = make_hands(0.0)  # left has raw "Right", right has raw "Left" (swapped convention)
    r, lft = select_hands(hands, "raw_label")
    assert r is hands.left and lft is hands.right
    r2, l2 = select_hands(hands, "anatomical")
    assert r2 is hands.right and l2 is hands.left


def test_handhygiene_missing_artifact_reports_unavailable_and_never_predicts(tmp_path):
    a = HandHygieneAdapter(HandHygieneConfig(model_path=str(tmp_path / "missing.pkl")))
    st = a.load()
    assert not st.available and "MODEL_UNAVAILABLE" in st.message
    p = a.predict(make_hands(0.0))
    assert p.status == PredictionStatus.MODEL_UNAVAILABLE and p.canonical is None


def test_handhygiene_rejects_unsupported_checkpoint(tmp_path):
    import pickle

    from sklearn.linear_model import LogisticRegression

    clf = LogisticRegression().fit(np.random.default_rng(0).random((20, 10)), np.arange(20) % 2)
    bad = tmp_path / "bad.pkl"
    bad.write_bytes(pickle.dumps(clf))
    a = HandHygieneAdapter(HandHygieneConfig(model_path=str(bad)))
    st = a.load()
    assert not st.available and "features" in st.message


def test_handhygiene_dangerous_pickle_refused(tmp_path):
    import pickle

    class Evil:
        def __reduce__(self):
            return (__import__("os").system, ("echo pwned",))

    bad = tmp_path / "evil.pkl"
    bad.write_bytes(pickle.dumps(Evil()))
    a = HandHygieneAdapter(HandHygieneConfig(model_path=str(bad)))
    st = a.load()
    assert not st.available


def test_numpy_forest_matches_sklearn_pipeline(tmp_path):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(0)
    x = rng.normal(size=(300, 126))
    y = (rng.integers(1, 11, size=300)).astype(float)
    pipe = Pipeline([("scaler", StandardScaler()), ("classifier", RandomForestClassifier(n_estimators=5, random_state=0))]).fit(x, y)
    exported = NumpyForestPipeline.from_sklearn(pipe)
    assert np.allclose(exported.predict_proba(x[:50]), pipe.predict_proba(x[:50]))
    exported.save(tmp_path / "f.npz")
    loaded = NumpyForestPipeline.load(tmp_path / "f.npz")
    assert np.allclose(loaded.predict_proba(x[:20]), pipe.predict_proba(x[:20]))
    assert loaded.n_features_in_ == 126 and list(loaded.classes_) == sorted(set(y))
    a = HandHygieneAdapter(HandHygieneConfig(model_path=str(tmp_path / "f.npz")))
    assert a.load().available
    p = a.predict(make_hands(0.0))
    assert p.status in (PredictionStatus.VALID, PredictionStatus.UNKNOWN)
    assert p.probabilities is not None and abs(sum(p.probabilities.values()) - 1) < 1e-6
    assert set(p.probabilities) == set(REG.model_map("handhygiene").native_order)


@pytest.mark.skipif(not resolve_path("models/handhygiene/rf_10102024.numpy-forest.npz").exists(), reason="converted artifact absent")
def test_handhygiene_real_artifact_loads_and_predicts_distribution():
    a = HandHygieneAdapter()
    st = a.load()
    assert st.available and st.details["conversion"]["validation"]["argmax_agreement"] == 1.0
    p = a.predict(make_hands(0.0))
    assert p.status in (PredictionStatus.VALID, PredictionStatus.UNKNOWN)
    assert p.probabilities and len(p.probabilities) == 10
    if p.status == PredictionStatus.VALID:
        assert p.canonical is not None and REG.is_known(p.canonical.technique)
        assert p.confidence >= 0.4


def test_handhygiene_threshold_yields_unknown(tmp_path):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(1)
    x = rng.normal(size=(200, 126))
    y = (np.arange(200) % 10 + 1).astype(float)
    pipe = Pipeline([("scaler", StandardScaler()), ("classifier", RandomForestClassifier(n_estimators=10, random_state=0))]).fit(x, y)
    NumpyForestPipeline.from_sklearn(pipe).save(tmp_path / "f.npz")
    a = HandHygieneAdapter(HandHygieneConfig(model_path=str(tmp_path / "f.npz"), unknown_threshold=1.01))
    a.load()
    assert a.predict(make_hands(0.0)).status == PredictionStatus.UNKNOWN
    assert a.predict(make_hands(0.0, left=False, right=False)).status == PredictionStatus.NO_INPUT


# --------------------------------------------------------------------------- S-Kia
def test_skia_feature_ordering_left_then_right_raw_landmarks():
    left = synthetic_hand(0.3, 0.5, mirror=True)
    right = synthetic_hand(0.7, 0.5)
    x = skia_feature_vector(left, right)
    assert x.shape == (126,)
    assert np.allclose(x[:63], left.reshape(63)) and np.allclose(x[63:], right.reshape(63))
    assert np.all(skia_feature_vector(None, right)[:63] == 0)
    with pytest.raises(ValueError):
        skia_feature_vector(None, None)
    hands = make_hands(0.0, right=False)
    obs = skia_observation(hands, "anatomical")
    assert obs is not None and list(obs[1]) == [1.0, 0.0]


def test_skia_legacy_normalization_and_adapter_unavailable_without_tf(tmp_path):
    x = np.arange(126, dtype=float)
    out = legacy_normalize(x, np.zeros(126), np.ones(126))
    assert np.allclose(out, x / (1 + 1e-8))
    a = SkiaLegacyAdapter(SkiaConfig(mode="legacy", legacy_model_path=str(tmp_path / "m.keras"), legacy_stats_path=str(tmp_path / "s.npz")))
    assert not a.load().available
    assert a.predict(make_hands(0.0)).status == PredictionStatus.MODEL_UNAVAILABLE


def test_sequence_buffer_windows_gaps_and_stride():
    buf = SequenceBuffer(window_frames=4, max_gap_s=0.2, stride_frames=2)
    out = []
    for i in range(8):
        out.append(buf.push(i * 0.1, i, np.full(126, i, np.float32), np.ones(2), 0.9))
    emitted = [o for o in out if o is not None]
    assert len(emitted) == 3 and emitted[0].frame_ids == [0, 1, 2, 3] and emitted[1].frame_ids == [2, 3, 4, 5]
    assert emitted[0].features.shape == (4, 126) and emitted[0].start_ts == 0.0 and emitted[0].end_ts == pytest.approx(0.3)
    assert buf.push(5.0, 99, np.zeros(126), np.ones(2), 0.9) is None  # gap resets
    assert buf.gaps_detected == 1 and len(buf) == 1
    with pytest.raises(ValueError):
        buf.push(4.0, 100, np.zeros(126), np.ones(2), 0.9)  # non-increasing
    with pytest.raises(ValueError):
        SequenceBuffer(window_frames=1)


def test_windows_from_sequence_respects_gaps_and_order():
    ts = np.array([0.0, 0.1, 0.2, 0.3, 1.0, 1.1, 1.2, 1.3, 1.4])
    feats = np.zeros((9, 126))
    w = windows_from_sequence(feats, ts, window=3, stride=1, max_gap_s=0.2)
    assert w == [(0, 3), (1, 4), (4, 7), (5, 8), (6, 9)]
    assert windows_from_sequence(feats, np.array([0, 0.1, 0.05, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]), 3, 1, 0.2)[0] == (2, 5)  # backwards ts starts a new segment


def test_temporal_model_requires_more_than_one_step_and_scaler_roundtrip(tmp_path):
    import torch

    meta = TemporalArtifactMeta(classes=SKIA_STEP_NAMES, window_frames=4, hidden_size=8, num_layers=1)
    m = build_model(meta)
    with pytest.raises(ValueError):
        m(torch.zeros(1, 1, meta.input_dim))
    assert m(torch.zeros(2, 4, meta.input_dim)).shape == (2, 12)
    sc = FeatureScaler.fit(np.random.default_rng(0).normal(2, 3, size=(10, 4, 126)))
    sc.save(tmp_path / "s.npz")
    sc2 = FeatureScaler.load(tmp_path / "s.npz")
    x = np.ones((4, 126))
    assert np.allclose(sc.transform(x), sc2.transform(x))
    with pytest.raises(ValueError):
        sc.transform(np.ones((4, 10)))


@pytest.mark.slow
def test_train_temporal_model_grouped_split_and_adapter_inference(tmp_path):
    recs = synthetic_recordings(n_subjects=5, per_subject=1, frames=60, seed=1)
    res = train_temporal_model(recs, tmp_path / "art", window=8, stride=4, epochs=2, batch_size=16, hidden=16, layers=1)
    meta = res.artifact.meta
    assert meta.window_frames == 8 and meta.preprocessing_version == "skia-sequence-v1"
    assert not (set(meta.split["train_groups"]) & set(meta.split["test_groups"]))  # no subject leakage
    assert (tmp_path / "art" / "scaler.npz").exists() and (tmp_path / "art" / "meta.json").exists()
    art = TemporalArtifact.load(tmp_path / "art")
    probs = art.predict_proba(recs[0].features[:8], recs[0].presence[:8])
    assert probs.shape == (12,) and abs(probs.sum() - 1) < 1e-5
    a = SkiaTemporalAdapter(SkiaConfig(temporal_artifact_dir=str(tmp_path / "art"), unknown_threshold=0.0))
    assert a.load().available and a.window_frames == 8
    statuses = [a.predict(make_hands(i / 15, i, seed=i)).status for i in range(10)]
    assert statuses[:7] == [PredictionStatus.NO_INPUT] * 7 and statuses[7] == PredictionStatus.VALID
    p = a.predict(make_hands(10 / 15, 10))
    assert p.window_end_ts - p.window_start_ts == pytest.approx(7 / 15) and len(p.frame_ids) == 8
    assert a.predict(make_hands(0.0, 11)).status == PredictionStatus.ERROR  # timestamp goes backwards -> explicit error


def test_temporal_artifact_rejects_one_step_or_bad_preprocessing(tmp_path):
    meta = TemporalArtifactMeta(classes=SKIA_STEP_NAMES, window_frames=1)
    d = tmp_path / "bad"
    d.mkdir()
    (d / "meta.json").write_text(meta.to_json())
    (d / "model.pt").write_bytes(b"")
    (d / "scaler.npz").write_bytes(b"")
    with pytest.raises(ValueError):
        TemporalArtifact.load(d)
    a = SkiaTemporalAdapter(SkiaConfig(temporal_artifact_dir=str(d)))
    assert not a.load().available


# --------------------------------------------------------------------------- YOLO
def test_letterbox_and_model_input_geometry():
    img = np.zeros((480, 720, 3), np.uint8)
    img[:, :, 0] = 255  # pure blue in BGR
    lb, r, pad = letterbox(img, 640)
    assert lb.shape[0] % 32 == 0 and lb.shape[1] == 640 and r == pytest.approx(640 / 720)
    x, r2, pad2 = to_model_input(img, 640)
    assert x.shape == (1, 3, lb.shape[0], 640) and x.dtype == np.float32 and x.min() >= 0 and x.max() <= 1
    cy, cx = x.shape[2] // 2, x.shape[3] // 2
    assert x[0, 2, cy, cx] == 1.0 and x[0, 0, cy, cx] == 0.0  # BGR -> RGB: blue ends in channel 2
    boxes = np.array([[pad2[0], pad2[1], pad2[0] + 72 * r2, pad2[1] + 48 * r2]])
    back = scale_boxes(boxes, r2, pad2, (480, 720))
    assert np.allclose(back, [[0, 0, 72, 48]], atol=1e-6)


def test_decode_predictions_nms_and_distribution():
    raw = np.zeros((4, 12))
    raw[0] = [100, 100, 50, 50, 0.9, 0, 0, 0, 0, 0.95, 0, 0]  # Step5 conf .855
    raw[1] = [102, 101, 50, 50, 0.8, 0, 0, 0, 0, 0.9, 0, 0]  # overlaps -> suppressed
    raw[2] = [300, 300, 40, 40, 0.7, 0.9, 0, 0, 0, 0, 0, 0]  # Step1 conf .63
    raw[3] = [10, 10, 5, 5, 0.1, 1, 0, 0, 0, 0, 0, 0]  # below threshold
    dets = decode_predictions(raw, 0.25, 0.45)
    assert dets.shape == (2, 6) and int(dets[0, 5]) == 4 and int(dets[1, 5]) == 0
    assert np.allclose(dets[0, :4], [75, 75, 125, 125])
    dist = detections_to_distribution(dets, YOLO_NATIVE_NAMES)
    assert dist["Step5"] == pytest.approx(0.855) and dist["Step1"] == pytest.approx(0.63) and dist["Step7"] == 0.0
    assert nms(np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]]), np.array([0.9, 0.8, 0.7]), 0.5) == [0, 2]
    with pytest.raises(ValueError):
        decode_predictions(np.zeros((3, 4)), 0.25, 0.45)


def test_yolo_missing_weights_and_untrusted_hash(tmp_path):
    a = YoloAdapter(YoloConfig(weights_path=str(tmp_path / "none.pt")))
    st = a.load()
    assert not st.available and "MODEL_UNAVAILABLE" in st.message
    assert a.predict(make_frame()).status == PredictionStatus.MODEL_UNAVAILABLE
    fake = tmp_path / "fake.pt"
    fake.write_bytes(b"not a checkpoint")
    b = YoloAdapter(YoloConfig(weights_path=str(fake)))
    st = b.load()
    assert not st.available and "not registered as trusted" in st.message


def test_yolo_prediction_from_detections_maps_labels_and_timestamps():
    a = YoloAdapter(YoloConfig())
    dets = np.array([[10, 10, 50, 50, 0.8, 6], [60, 60, 90, 90, 0.4, 0]])
    p = a.prediction_from_detections(dets, ts=3.5, frame_id=7, ms=12.0)
    assert p.status == PredictionStatus.VALID and p.native_label == "Step7" and p.canonical.technique == "wrist_rubbing"
    assert p.window_start_ts == p.window_end_ts == 3.5 and p.frame_ids == [7] and len(p.extras["boxes"]) == 2
    assert p.canonical_probabilities["palm_to_palm"] == pytest.approx(0.4) and not p.calibrated
    empty = a.prediction_from_detections(np.zeros((0, 6)), 1.0, 1, 1.0)
    assert empty.status == PredictionStatus.UNKNOWN
    assert a.should_run(0) and not a.should_run(1) and a.should_run(3)
