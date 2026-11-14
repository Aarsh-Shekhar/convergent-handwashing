import json
import time

import numpy as np
import pytest
from starlette.testclient import TestClient

from convergent.backend.app import create_app
from convergent.backend.database import current_revision, run_migrations
from convergent.common.config import Settings
from convergent.common.types import (
    CalibrationProfile,
    CanonicalLabel,
    GestureEvent,
    HandSide,
    ModelPrediction,
    Region,
    RegionEvidence,
    ValidationStatus,
)
from tests.integration.conftest import TOKEN

H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'api.db'}"


@pytest.fixture
def client(db_url):
    app = create_app(Settings(api_token=TOKEN, database_url=db_url, log_dir="logs"), db_url)
    with TestClient(app) as c:
        yield c


def new_session(c, **kw):
    r = c.post("/api/v1/sessions", json={"source_id": "synthetic", "width": 640, "height": 480, "target_fps": 15, **kw}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def test_migrations_applied_and_health(client, db_url):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["migration_revision"] == "0001_initial" and h["database"] == "ok"
    assert current_revision(db_url) == "0001_initial"
    assert run_migrations(db_url) == "0001_initial"  # idempotent


def test_auth_required_for_writes_and_fail_closed_without_token(client, db_url):
    r = client.post("/api/v1/sessions", json={"source_id": "x", "width": 1, "height": 1, "target_fps": 1})
    assert r.status_code == 401 and r.json()["code"] == "http_401"
    r = client.post("/api/v1/sessions", json={"source_id": "x", "width": 1, "height": 1, "target_fps": 1}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    app = create_app(Settings(api_token="", database_url=db_url, log_dir="logs"), db_url)
    with TestClient(app) as c:
        r = c.post("/api/v1/sessions", json={"source_id": "x", "width": 1, "height": 1, "target_fps": 1}, headers=H)
        assert r.status_code == 503
        assert c.get("/api/v1/devices").status_code == 200  # reads still allowed on the dev LAN
    strict = create_app(Settings(api_token=TOKEN, database_url=db_url, allow_unauthenticated_reads=False, log_dir="logs"), db_url)
    with TestClient(strict) as c:
        assert c.get("/api/v1/devices").status_code == 401
        assert c.get("/api/v1/devices", headers=H).status_code == 200


def test_invalid_requests_get_consistent_errors(client):
    r = client.post("/api/v1/sessions", json={"source_id": "x", "width": -1, "height": 1, "target_fps": 1}, headers=H)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    r = client.post("/api/v1/sessions", json={"source_id": "x", "width": 1, "height": 1, "target_fps": 1, "bogus": 1}, headers=H)
    assert r.status_code == 422
    assert client.get("/api/v1/sessions/none").status_code == 404
    sid = new_session(client)
    r = client.post(f"/api/v1/sessions/{sid}/predictions", json={"predictions": []}, headers=H)
    assert r.status_code == 422
    r = client.post("/api/v1/sessions", json={"session_id": sid, "source_id": "x", "width": 1, "height": 1, "target_fps": 1}, headers=H)
    assert r.status_code == 409


def test_session_lifecycle_predictions_events_regions_and_duplicates(client):
    sid = new_session(client, device_id="pi-01", model_versions={"handhygiene": "v"})
    assert client.get("/api/v1/devices").json()[0]["device_id"] == "pi-01"
    p = ModelPrediction(model_id="handhygiene", model_version="v", window_start_ts=0.1, window_end_ts=0.1, frame_ids=[1],
                        canonical=CanonicalLabel(technique="palm_to_palm", side=HandSide.BOTH), confidence=0.9, canonical_probabilities={"palm_to_palm": 0.9})
    body = {"predictions": [p.model_dump(mode="json"), p.model_dump(mode="json")]}
    r = client.post(f"/api/v1/sessions/{sid}/predictions", json=body, headers=H).json()
    assert r == {"accepted": 1, "duplicates": 1, "rejected": 0, "errors": []}
    assert client.post(f"/api/v1/sessions/{sid}/predictions", json=body, headers=H).json()["accepted"] == 0
    ev = GestureEvent(session_id=sid, technique="thumb_rubbing", side=HandSide.LEFT, start_ts=0, end_ts=2, validated_duration_s=1.8,
                      confidence=0.8, validation_status=ValidationStatus.VALIDATED)
    r = client.post(f"/api/v1/sessions/{sid}/events", json={"events": [ev.model_dump(mode="json")]}, headers=H).json()
    assert r["accepted"] == 1
    again = ev.model_copy(update={"event_id": "evt_other"})  # same dedupe key, different id
    assert client.post(f"/api/v1/sessions/{sid}/events", json={"events": [again.model_dump(mode="json")]}, headers=H).json()["duplicates"] == 1
    wrong = ev.model_copy(update={"session_id": "ses_other", "event_id": "evt_x"})
    assert client.post(f"/api/v1/sessions/{sid}/events", json={"events": [wrong.model_dump(mode="json")]}, headers=H).json()["rejected"] == 1
    events = client.get(f"/api/v1/sessions/{sid}/events").json()
    assert len(events) == 1 and events[0]["technique"] == "thumb_rubbing" and events[0]["side"] == "left"
    reg = [RegionEvidence(region=Region.THUMB, side=HandSide.LEFT, observed_duration_s=1.8, confidence=0.6, status="partial", supporting_events=[ev.event_id])]
    assert client.post(f"/api/v1/sessions/{sid}/regions", json={"snapshot_ts": 2.0, "evidence": [e.model_dump(mode="json") for e in reg]}, headers=H).json()["accepted"] == 1
    stale = [RegionEvidence(region=Region.THUMB, side=HandSide.LEFT, observed_duration_s=0.1, confidence=0.1)]
    assert client.post(f"/api/v1/sessions/{sid}/regions", json={"snapshot_ts": 1.0, "evidence": [e.model_dump(mode="json") for e in stale]}, headers=H).json()["accepted"] == 0
    regions = client.get(f"/api/v1/sessions/{sid}/regions").json()
    assert regions[0]["observed_duration_s"] == 1.8 and regions[0]["status"] == "partial"
    ended = client.patch(f"/api/v1/sessions/{sid}", json={"ended": True, "stats": {"frames": 10}}, headers=H).json()
    assert ended["ended_utc"] is not None and ended["stats"]["frames"] == 10
    assert client.get("/health").json()["sessions_open"] == 0


def test_persistence_survives_app_restart(db_url):
    app = create_app(Settings(api_token=TOKEN, database_url=db_url, log_dir="logs"), db_url)
    with TestClient(app) as c:
        sid = new_session(c)
    app2 = create_app(Settings(api_token=TOKEN, database_url=db_url, log_dir="logs"), db_url)
    with TestClient(app2) as c:
        assert c.get(f"/api/v1/sessions/{sid}").status_code == 200


def test_calibrations_models_evaluations_annotations(client):
    prof = CalibrationProfile(image_width=640, image_height=480, camera_to_projector=np.eye(3).tolist(), reprojection_rmse_px=0.5, inlier_count=8)
    r = client.post("/api/v1/calibrations", json={"profile": prof.model_dump(mode="json"), "device_id": "pi-01", "activate": True}, headers=H)
    assert r.status_code == 201 and r.json()["active"] is True
    pid = r.json()["profile_id"]
    assert client.get("/api/v1/calibrations/active").json()["profile_id"] == pid
    v2 = prof.model_copy(update={"profile_id": "cal_v2", "version": 2})
    client.post("/api/v1/calibrations", json={"profile": v2.model_dump(mode="json"), "activate": True}, headers=H)
    assert client.get("/api/v1/calibrations/active").json()["profile_id"] == "cal_v2"
    assert client.get(f"/api/v1/calibrations/{pid}").json()["active"] is False
    inv = client.post("/api/v1/calibrations/cal_v2/invalidate", json={"reason": "camera moved"}, headers=H).json()
    assert inv["valid"] is False and inv["profile"]["valid"] is False and inv["profile"]["invalidation_reason"] == "camera moved"
    assert client.get("/api/v1/calibrations/active").json() is None
    assert client.post("/api/v1/calibrations", json={"profile": v2.model_dump(mode="json")}, headers=H).status_code == 409
    m = client.post("/api/v1/models", json={"model_id": "handhygiene", "version": "rf_10102024", "available": True, "artifact_hash": "abc"}, headers=H)
    assert m.status_code == 200
    models = client.get("/api/v1/models").json()
    assert models["registered"][0]["model_id"] == "handhygiene" and any(d["model_key"] == "yolo" for d in models["discovered"])
    e = client.post("/api/v1/evaluations", json={"dataset": "sample", "metrics": {"f1": 0.5}, "model_config": {"branches": ["a"]}}, headers=H)
    assert e.status_code == 201
    got = client.get(f"/api/v1/evaluations/{e.json()['run_id']}").json()
    assert got["metrics"]["f1"] == 0.5 and got["model_config"]["branches"] == ["a"]
    sid = new_session(client)
    a = client.post("/api/v1/annotations", json={"session_id": sid, "technique": "palm_to_palm", "start_ts": 0, "end_ts": 1, "annotator": "qa"}, headers=H)
    assert a.status_code == 201 and a.json()["kind"] == "reference"
    assert client.post("/api/v1/annotations", json={"session_id": "nope", "technique": "x", "start_ts": 0, "end_ts": 1}, headers=H).status_code == 404


def test_websocket_pubsub_device_status_and_reconnect(live_server):
    import httpx
    from websockets.sync.client import connect

    base = live_server.ws
    with connect(f"{base}/ws/v1/observations?token={TOKEN}") as pub, connect(f"{base}/ws/v1/observations") as sub:
        pub.send(json.dumps({"type": "live", "seq": 1, "fused": "palm_to_palm"}))
        assert json.loads(pub.recv(timeout=5))["type"] == "ack"
        assert json.loads(sub.recv(timeout=5))["fused"] == "palm_to_palm"
        sub.send(json.dumps({"type": "live", "seq": 2}))
        assert "requires the API token" in json.loads(sub.recv(timeout=5))["message"]
        sub.send("not json")
        assert json.loads(sub.recv(timeout=5))["type"] == "error"
    with connect(f"{base}/ws/v1/render?token={TOKEN}") as r1, connect(f"{base}/ws/v1/render") as r2:
        r1.send(json.dumps({"type": "render", "seq": 1, "command": "clear", "canvas_width": 854, "canvas_height": 480}))
        assert json.loads(r2.recv(timeout=5))["command"] == "clear"
    for _ in range(2):  # connect, report, disconnect, reconnect
        with connect(f"{base}/ws/v1/device?token={TOKEN}") as dev:
            dev.send(json.dumps({"type": "hello", "seq": 1, "device_id": "pi-02", "software_version": "a", "hardware": {"cam": "B0176"}}))
            assert json.loads(dev.recv(timeout=5))["type"] == "hello_ack"
            dev.send(json.dumps({"type": "status", "seq": 2, "device_id": "pi-02", "monotonic_ns": 1, "frames_captured": 5, "frames_sent": 4,
                                 "frames_dropped": 1, "queue_depth": 0, "cpu_temp_c": 50.0}))
            dev.send(json.dumps({"type": "ping", "seq": 3}))
            assert json.loads(dev.recv(timeout=5))["type"] == "pong"
            dev.send(b"\x00" * 10)
            assert "binary" in json.loads(dev.recv(timeout=5))["message"]
            devs = {d["device_id"]: d for d in httpx.get(f"{live_server.http}/api/v1/devices").json()}
            assert devs["pi-02"]["status"] == "connected" and devs["pi-02"]["last_status"]["frames_sent"] == 4
        time.sleep(0.2)
        devs = {d["device_id"]: d for d in httpx.get(f"{live_server.http}/api/v1/devices").json()}
        assert devs["pi-02"]["status"] == "disconnected"
    with pytest.raises(Exception):
        with connect(f"{base}/ws/v1/device?token=wrong") as dev:
            dev.recv(timeout=5)


def test_live_endpoint_fans_out_to_observation_subscribers(live_server):
    """The game layer's feed: POST .../live (write token) -> `live` message on /ws/v1/observations, nothing stored."""
    import httpx
    from websockets.sync.client import connect

    sid = "ses_live_test"
    r = httpx.post(f"{live_server.http}/api/v1/sessions", headers={"Authorization": f"Bearer {TOKEN}"},
                   json={"session_id": sid, "source_id": "test", "width": 640, "height": 480, "target_fps": 15,
                         "processing_config": {}, "model_versions": {}, "capture_clock": "monotonic"})
    assert r.status_code == 201
    body = {"ts": 12.5, "frame_id": 187, "hands": 2, "fused": {"status": "valid", "technique": "thumb_rubbing", "side": "left", "confidence": 0.91},
            "active": {"technique": "thumb_rubbing", "side": "left", "start_ts": 10.0, "supported_s": 2.4, "validated": True},
            "score": {"stars": 2, "points": 55, "steps_done": 3, "finished": False}, "progress": None}
    with connect(f"{live_server.ws}/ws/v1/observations") as sub:
        assert httpx.post(f"{live_server.http}/api/v1/sessions/{sid}/live", json=body, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 202
        msg = json.loads(sub.recv(timeout=5))
    assert msg["type"] == "live" and msg["session_id"] == sid and msg["fused"]["technique"] == "thumb_rubbing"
    assert msg["score"]["stars"] == 2 and msg["active"]["supported_s"] == 2.4
    # write token required; unknown fields rejected; nothing persisted on the session
    assert httpx.post(f"{live_server.http}/api/v1/sessions/{sid}/live", json=body).status_code in (401, 403)
    assert httpx.post(f"{live_server.http}/api/v1/sessions/{sid}/live", json=body | {"bogus": 1}, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 422
    assert httpx.get(f"{live_server.http}/api/v1/sessions/{sid}/events").json() == []
