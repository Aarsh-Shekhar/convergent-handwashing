"""The wash upload queue: nothing lost when the backend is away, nothing counted twice when it comes back."""

import sqlite3
import time
from datetime import timedelta

import httpx
import pytest

from convergent.backend.client import BackendClient, BackendError
from convergent.backend.outbox import MAX_WAITING, WashOutbox, backoff_s
from tests.integration.conftest import TOKEN, LiveServer, free_port
from tests.integration.test_parent_app import ALL7, now, record


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def rec(wid: str) -> dict:
    return record(wid, now() - timedelta(seconds=5), ALL7)


def fail(status: int | None, retry_after: float | None = None):
    def send(_):
        raise BackendError("nope", status, retry_after)
    return send


# ---- rules, with a fake backend and a fake clock (no thread)
def test_backoff_doubles_up_to_the_cap_with_jitter():
    assert [backoff_s(n, 2.0, 300.0, rng=lambda: 1.0) for n in (1, 2, 3, 4, 20)] == [2.0, 4.0, 8.0, 16.0, 300.0]
    assert backoff_s(3, 2.0, 300.0, rng=lambda: 0.0) == 4.0   # jitter: between half and all of the wait


def test_a_wash_is_removed_from_waiting_only_after_the_backend_acknowledged_it(tmp_path):
    got: list[str] = []
    box = WashOutbox(tmp_path / "q.sqlite3", lambda r: got.append(r["wash_id"]), start=False)
    assert box.put(rec("w1")) is True
    assert box.put(rec("w1")) is False                         # the same wash queued twice is one wash
    assert box.counts() == {"waiting": 1, "sent": 0, "dead": 0}
    assert box.drain_once() == 1 and got == ["w1"]
    assert box.counts() == {"waiting": 0, "sent": 1, "dead": 0}
    assert box.drain_once() == 0 and got == ["w1"]             # never sent again


@pytest.mark.parametrize("status", [None, 500, 503, 408, 429])
def test_trouble_that_can_pass_is_retried_later_and_keeps_the_order(tmp_path, status):
    clock = Clock()
    box = WashOutbox(tmp_path / "q.sqlite3", fail(status), start=False, clock=clock)
    box.put(rec("w1"))
    box.put(rec("w2"))
    assert box.drain_once() == 0
    assert box.counts()["waiting"] == 2 and box.parked() == []
    assert box.drain_once() == 0                               # not due yet: no second try, w2 not tried before w1
    tries = sqlite3.connect(tmp_path / "q.sqlite3").execute("SELECT wash_id, attempts FROM washes ORDER BY wash_id").fetchall()
    assert tries == [("w1", 1), ("w2", 0)]
    got: list[str] = []
    box._send = lambda r: got.append(r["wash_id"])
    clock.t += 301
    assert box.drain_once() == 2 and got == ["w1", "w2"]


def test_retry_after_from_the_backend_is_respected(tmp_path):
    clock = Clock()
    box = WashOutbox(tmp_path / "q.sqlite3", fail(429, retry_after=120), start=False, clock=clock)
    box.put(rec("w1"))
    box.drain_once()
    box._send = lambda r: None
    clock.t += 100
    assert box.drain_once() == 0
    clock.t += 21
    assert box.drain_once() == 1


@pytest.mark.parametrize("status", [401, 403, 409, 413, 422])
def test_an_answer_that_will_not_change_parks_the_wash_and_lets_the_next_one_through(tmp_path, status):
    def send(r):
        if r["wash_id"] == "bad":
            raise BackendError("refused", status)
    box = WashOutbox(tmp_path / "q.sqlite3", send, start=False)
    box.put(rec("bad"))
    box.put(rec("good"))
    assert box.drain_once() == 1
    assert box.counts() == {"waiting": 0, "sent": 1, "dead": 1}
    assert box.parked()[0]["wash_id"] == "bad" and "refused" in box.parked()[0]["error"]
    box._send = lambda r: None
    assert box.retry_dead() == 1 and box.drain_once() == 1     # after the cause is fixed


def test_a_full_queue_parks_the_oldest_wash_instead_of_growing_forever(tmp_path):
    box = WashOutbox(tmp_path / "q.sqlite3", fail(None), start=False)
    for i in range(MAX_WAITING + 2):
        box.put({"wash_id": f"w{i:05d}"})
    assert box.counts()["waiting"] == MAX_WAITING
    assert [p["wash_id"] for p in box.parked()] == ["w00000", "w00001"]


def test_only_the_wash_record_is_stored(tmp_path):
    box = WashOutbox(tmp_path / "q.sqlite3", fail(None), start=False)
    box.put(rec("w1"))
    cols = [c[1] for c in sqlite3.connect(tmp_path / "q.sqlite3").execute("PRAGMA table_info(washes)")]
    assert cols == ["wash_id", "body", "state", "attempts", "next_try", "last_error", "queued", "done"]


# ---- against the real backend
def _client(url: str, token: str = TOKEN) -> BackendClient:
    return BackendClient(url, token, timeout_s=0.5)


def _points(url: str) -> int:
    return httpx.get(f"{url}/api/v1/app/family-rewards").json()["points"]


def test_queueing_never_waits_for_a_backend_that_is_down(tmp_path):
    dead_url = f"http://127.0.0.1:{free_port()}"               # nothing listens here
    c = _client(dead_url)
    box = WashOutbox(tmp_path / "q.sqlite3", lambda r: c.post_wash(r, retries=0), base_s=0.05)
    t0 = time.perf_counter()
    for i in range(5):
        box.put(rec(f"w{i}"))
    assert time.perf_counter() - t0 < 0.5                      # 5 washes on disk; the camera loop was not held up
    time.sleep(0.3)
    assert box.counts()["waiting"] == 5
    box.close(flush_s=0)
    c.close()


def test_washes_queued_offline_survive_a_restart_and_are_counted_once_when_the_backend_is_back(tmp_path):
    q = tmp_path / "q.sqlite3"
    dead = _client(f"http://127.0.0.1:{free_port()}")
    box = WashOutbox(q, lambda r: dead.post_wash(r, retries=0), base_s=0.05, cap_s=0.2)
    box.put(rec("offline-1"))
    box.put(rec("offline-2"))
    time.sleep(0.3)
    box.close(flush_s=0)                                       # the wash software stops (or the laptop loses power)
    dead.close()

    with LiveServer(f"sqlite:///{tmp_path / 'live.db'}") as server:
        live = _client(server.http)
        box = WashOutbox(q, lambda r: live.post_wash(r, retries=0), base_s=0.05, cap_s=0.2)   # next run, backend reachable
        for _ in range(100):
            if box.counts()["sent"] == 2:
                break
            time.sleep(0.05)
        assert box.counts() == {"waiting": 0, "sent": 2, "dead": 0}
        assert [w["wash_id"] for w in httpx.get(f"{server.http}/api/v1/app/washes").json()] == ["offline-2", "offline-1"]
        assert _points(server.http) == 160
        # the acknowledgement of an upload is lost and the wash is sent again: still one wash, one award
        sqlite3.connect(q).execute("UPDATE washes SET state = 'waiting', next_try = 0").connection.commit()
        box._wake.set()
        for _ in range(100):
            if box.counts()["sent"] == 2:
                break
            time.sleep(0.05)
        assert _points(server.http) == 160 and len(httpx.get(f"{server.http}/api/v1/app/washes").json()) == 2
        box.close()
        live.close()


def test_a_wrong_token_parks_the_wash_with_the_reason(tmp_path):
    with LiveServer(f"sqlite:///{tmp_path / 'live.db'}") as server:
        c = _client(server.http, token="not-the-token")
        box = WashOutbox(tmp_path / "q.sqlite3", lambda r: c.post_wash(r, retries=0), start=False)
        box.put(rec("w1"))
        assert box.drain_once() == 0
        assert box.parked()[0]["wash_id"] == "w1" and "401" in box.parked()[0]["error"]
        assert "not-the-token" not in box.parked()[0]["error"]
        box.close(flush_s=0)
        c.close()


# ---- through the real pipeline (scripted hands, no camera)
def _wash_pipeline(tmp_path, url: str, hands_frames: int = 75):
    from convergent.common.config import PipelineConfig, resolve_path
    from convergent.pipeline import Pipeline
    from convergent.vision.hand_tracker import HandTracker, ScriptedBackend
    from tests.unit.test_wash_session import HAND

    cfg = PipelineConfig.load(resolve_path("configs/development.yaml"),
                              {"wash_sessions": {"enabled": True}, "source": {"kind": "synthetic", "max_frames": hands_frames + 75, "target_fps": 15.0},
                               "live_status_every_s": 0, "results_dir": str(tmp_path / "runs"), "backend": {"live_hz": 0}})
    client = BackendClient(url, TOKEN, timeout_s=0.3)
    return Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend([HAND] * hands_frames + [[]] * 75)), backend_client=client)


def test_the_pipeline_keeps_its_pace_with_the_backend_down_and_the_wash_arrives_on_the_next_run(tmp_path):
    down = _wash_pipeline(tmp_path, f"http://127.0.0.1:{free_port()}")
    assert down.outbox is not None
    t0 = time.perf_counter()
    summary = down.run()
    down.close()
    assert len(summary.washes) == 1
    assert sqlite3.connect(tmp_path / "runs" / "wash_outbox.sqlite3").execute("SELECT wash_id, state FROM washes").fetchall() == [(summary.washes[0]["wash_id"], "waiting")]
    took_down = time.perf_counter() - t0

    with LiveServer(f"sqlite:///{tmp_path / 'live.db'}") as server:
        up = _wash_pipeline(tmp_path, server.http)   # the next run of the wash software: the queued wash goes first
        for _ in range(100):
            if up.outbox.counts()["sent"] == 1:
                break
            time.sleep(0.05)
        saved = httpx.get(f"{server.http}/api/v1/app/washes").json()
        assert [w["wash_id"] for w in saved] == [summary.washes[0]["wash_id"]]
        second = up.run()
        up.close()
        assert len(httpx.get(f"{server.http}/api/v1/app/washes").json()) == 1 + len(second.washes)
    assert took_down < 60   # 150 frames; every other backend call fails fast and none of them is the wash upload
