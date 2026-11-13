"""End-to-end pipeline tests that do not need MediaPipe: a scripted landmark backend drives the
real adapters/fusion/temporal/regions/projection/backend path."""

from __future__ import annotations

import json

import numpy as np
import pytest

from convergent.backend.client import inprocess_client
from convergent.common.config import PipelineConfig, ProjectorConfig, SmoothingConfig
from convergent.common.types import HandSide, PredictionStatus
from convergent.detection.numpy_forest import NumpyForestPipeline
from convergent.detection.training import synthetic_recordings, train_temporal_model
from convergent.pipeline import Pipeline
from convergent.projection.calibration import build_profile
from convergent.projection.homography import synthetic_homography, transform_points
from convergent.vision.hand_tracker import HandTracker, ScriptedBackend
from tests.conftest import synthetic_hand

TOKEN = "e2e-token"


def two_hand_script(n: int, drift: float = 0.0):
    out = []
    for i in range(n):
        a = synthetic_hand(0.35 + drift * i, 0.5, seed=i)
        b = synthetic_hand(0.65, 0.5, seed=1000 + i, mirror=True)
        out.append([(a, "Right", 0.95), (b, "Left", 0.95)])
    return out


def constant_forest(tmp_path, native_class: float = 1.0):
    """A forest whose every tree votes the same class -> deterministic VALID predictions."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline as SkPipe
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 126))
    y = np.full(200, native_class)
    # the adapter requires all 10 upstream classes; put the others far away in feature space
    for k, cls in enumerate(c for c in range(1, 11) if float(c) != native_class):
        y[k * 10:(k + 1) * 10] = float(cls)
        x[k * 10:(k + 1) * 10] += 50 * (k + 1)
    pipe = SkPipe([("scaler", StandardScaler()), ("classifier", RandomForestClassifier(n_estimators=3, random_state=0))]).fit(x, y)
    path = tmp_path / "const.npz"
    NumpyForestPipeline.from_sklearn(pipe).save(path)
    return path


def base_config(tmp_path, max_frames=60, forest=True, temporal=None):
    cfg = PipelineConfig.load(None, {
        "source": {"kind": "synthetic", "max_frames": max_frames, "target_fps": 15},
        "tracker": {"backend": "null"},
        "handhygiene": {"enabled": forest, "model_path": str(constant_forest(tmp_path)) if forest else str(tmp_path / "none.npz"), "unknown_threshold": 0.3},
        "skia": {"enabled": temporal is not None, "temporal_artifact_dir": str(temporal) if temporal else str(tmp_path / "no_art")},
        "yolo": {"enabled": False},
        "temporal_v2": {"enabled": False},  # these tests script the v1 branches; the trained v2 artifact must not vote
        "temporal": {"min_duration_s": 1.0, "max_gap_s": 0.5},
        "projector": {"profile_path": None},
        "results_dir": str(tmp_path / "runs"),
    })
    return cfg


def test_model_unavailable_mode_produces_no_fake_detections(tmp_path):
    cfg = base_config(tmp_path, forest=False)
    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(two_hand_script(60))), deterministic=True)
    status = pipe.load_models()
    assert not any(s.available for s in status.values())
    summary = pipe.run()
    assert summary.frames == 60 and summary.events == []
    assert set(summary.fused_counts) == {"no_input"} and summary.progress["coverage_estimate"] == 0.0
    assert all("MODEL_UNAVAILABLE" in v["message"] or "disabled" in v["message"] for v in summary.model_status.values())


def test_deterministic_replay_produces_identical_events_and_persists_to_backend(tmp_path):
    cfg = base_config(tmp_path, max_frames=90)
    runs = []
    for i in range(2):
        pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(two_hand_script(90))), deterministic=True, save_results=True)
        pipe.load_models()
        summary = pipe.run()
        runs.append([(e.technique, e.side.value, round(e.start_ts, 6), round(e.end_ts, 6), round(e.validated_duration_s, 6)) for e in summary.events])
    assert runs[0] == runs[1] and runs[0], runs
    assert runs[0][0][0] == "palm_to_palm" and runs[0][0][1] == "both"
    assert (tmp_path / "runs" / summary.session_id / "frames.jsonl").exists()
    recs = [json.loads(line) for line in (tmp_path / "runs" / summary.session_id / "frames.jsonl").read_text().splitlines()]
    assert len(recs) == 90 and recs[-1]["fused"]["participating"] == ["handhygiene"]
    from convergent.detection.pair_training import RawRecording

    land = RawRecording.load(tmp_path / "runs" / summary.session_id / "landmarks.npz")  # hand points for replay / labelling
    assert land.hands.shape == (90, 2, 21, 3) and float(land.presence.min(axis=1).mean()) > 0.9
    assert "v2_top" in recs[-1]
    assert summary.progress["hands"]["left"]["regions"]["palm"]["status"] in ("sufficient", "partial")
    assert summary.progress["hands"]["left"]["regions"]["thumb"]["status"] == "unknown"

    client, app = inprocess_client(TOKEN, f"sqlite:///{tmp_path / 'e2e.db'}")
    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(two_hand_script(90))), backend_client=client, deterministic=True)
    pipe.load_models()
    summary = pipe.run()
    events = client.get_events(summary.session_id)
    assert len(events) == len(summary.events) >= 1 and events[0]["technique"] == "palm_to_palm"
    regions = client.get_regions(summary.session_id)
    by = {(r["region"], r["side"]): r for r in regions}
    assert by[("palm", "left")]["observed_duration_s"] > 0 and by[("thumb", "right")]["status"] == "unknown"
    session = client._req("GET", f"/api/v1/sessions/{summary.session_id}")
    assert session["ended_utc"] is not None and session["stats"]["frames"] == 90
    assert session["model_versions"]["handhygiene"]["available"] is True and session["model_versions"]["yolo"]["available"] is False
    assert client.stats.predictions_sent > 0 and client.stats.failures == 0
    client.close()


def test_wash_score_live_final_and_saved_to_backend(tmp_path):
    cfg = base_config(tmp_path, max_frames=90)  # 6 s of constant palm-to-palm
    client, app = inprocess_client(TOKEN, f"sqlite:///{tmp_path / 'score.db'}")
    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(two_hand_script(90))), backend_client=client, deterministic=True)
    pipe.load_models()
    results = []
    pipe.on_frame = results.append
    summary = pipe.run()
    assert all(r.score is not None for r in results)
    live_palm = [r.score.steps[0].seconds for r in results]
    assert all(b >= a for a, b in zip(live_palm, live_palm[1:], strict=False)) and live_palm[-1] > 3.0
    sc = summary.score
    assert sc["steps"][0]["technique"] == "palm_to_palm" and sc["steps"][0]["done"]
    assert sc["steps_done"] == 1 and not sc["finished"] and sc["stars"] == 1 and sc["next_step"] == "back_of_hand"
    assert sc["steps"][0]["seconds"] == pytest.approx(sum(e.validated_duration_s for e in summary.events), abs=1e-3)
    session = client._req("GET", f"/api/v1/sessions/{summary.session_id}")
    assert session["stats"]["wash_score"] == sc
    client.close()


def test_stop_and_ctrl_c_still_return_summary_with_score(tmp_path):
    cfg = base_config(tmp_path, max_frames=90)
    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(two_hand_script(90))), deterministic=True, save_results=True)
    pipe.load_models()
    seen = []

    def stop_at_45(r):
        seen.append(r)
        if len(seen) == 45:
            pipe.stop()

    pipe.on_frame = stop_at_45
    summary = pipe.run()
    assert summary.frames == 45 and summary.score is not None and summary.score["steps"][0]["seconds"] > 0
    assert (tmp_path / "runs" / summary.session_id / "summary.json").exists()

    pipe2 = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(two_hand_script(90))), deterministic=True)
    pipe2.load_models()
    count = [0]

    def ctrl_c_at_45(r):
        count[0] += 1
        if count[0] == 45:
            raise KeyboardInterrupt

    pipe2.on_frame = ctrl_c_at_45
    summary2 = pipe2.run()
    assert summary2.score is not None and summary2.events and summary2.score["steps"][0]["seconds"] > 0


def test_backend_failure_does_not_corrupt_session_progress(tmp_path):
    from convergent.backend.client import BackendClient

    cfg = base_config(tmp_path, max_frames=45)
    client = BackendClient("http://127.0.0.1:9", TOKEN, timeout_s=0.2)  # nothing listens here
    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(two_hand_script(45))), backend_client=client, deterministic=True)
    pipe.load_models()
    summary = pipe.run()
    assert summary.frames == 45 and summary.events and client.stats.failures > 0


def test_calibration_targets_reach_the_renderer(tmp_path):
    from convergent.communication.protocol import RenderCommand
    from convergent.pi_agent.renderer import ImageRenderer

    H = synthetic_homography(0)
    cam = np.array([[50, 50], [600, 40], [620, 440], [30, 450], [320, 240], [100, 300]], float)
    prof, _ = build_profile(cam, transform_points(H, cam), (640, 480))
    cfg = base_config(tmp_path, max_frames=20)
    cfg = cfg.model_copy(update={"projector": ProjectorConfig(profile_path=None, anchors=["hand_centroid", "fingertips"], smoothing=SmoothingConfig(method="ema"))})
    renderer = ImageRenderer()
    sent: list[RenderCommand] = []

    class FakeGateway:
        _seq = 0

        def next_render_seq(self):
            self._seq += 1
            return self._seq

        def send_render(self, cmd):
            sent.append(cmd)
            renderer.render(RenderCommand.from_message(json.loads(cmd.to_message())))
            return True

    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(two_hand_script(20, drift=0.005))), gateway=FakeGateway(), deterministic=True, calibration=prof)
    pipe.load_models()
    summary = pipe.run()
    assert summary.frames == 20 and len(sent) == 20
    assert sent[-1].calibration_profile_id == prof.profile_id and sent[-1].canvas_width == 854
    assert renderer.rendered == 20 and renderer.last.any()
    valid_items = [it for it in sent[-1].items if it.shape == "crosshair"]
    assert len(valid_items) == 2 and {it.anchor_id for it in valid_items} == {"left:hand_centroid", "right:hand_centroid"}


@pytest.mark.slow
def test_temporal_branch_participates_in_fusion_when_artifact_present(tmp_path):
    art = tmp_path / "art"
    train_temporal_model(synthetic_recordings(n_subjects=4, per_subject=1, frames=40, seed=2), art, window=6, stride=3, epochs=1, hidden=8, layers=1)
    cfg = base_config(tmp_path, max_frames=40, temporal=art)
    cfg = cfg.model_copy(update={"skia": cfg.skia.model_copy(update={"unknown_threshold": 0.0})})
    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(two_hand_script(40))), deterministic=True)
    status = pipe.load_models()
    assert status["skia_temporal"].available and status["handhygiene"].available
    results = []
    pipe.on_frame = results.append
    pipe.run()
    participating = [r.fused.extras.get("participating", []) for r in results]
    assert participating[0] == ["handhygiene"]  # window not full yet
    assert any("skia_temporal" in p for p in participating[6:])
    assert all(r.branch_predictions["skia_temporal"].status in (PredictionStatus.NO_INPUT, PredictionStatus.VALID, PredictionStatus.UNKNOWN) for r in results)
    assert results[-1].branch_predictions["skia_temporal"].window_end_ts - results[-1].branch_predictions["skia_temporal"].window_start_ts == pytest.approx(5 / 15)


def test_pipeline_one_hand_only_and_sides(tmp_path):
    cfg = base_config(tmp_path, max_frames=30)
    script = [[(synthetic_hand(0.5, 0.5, seed=i), "Left", 0.95)] for i in range(30)]
    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend(script)), deterministic=True)
    pipe.load_models()
    res = []
    pipe.on_frame = res.append
    pipe.run()
    assert all(r.hands.right is not None and r.hands.left is None for r in res)  # raw "Left" -> anatomical RIGHT (swap)
    assert all(r.hands.right.side == HandSide.RIGHT for r in res)
