"""Parent app API: washes saved one by one, progress across sessions, rewards, settings, live `wash_saved`."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from convergent.backend.app import create_app
from convergent.common.config import Settings
from convergent.scoring import progression as P
from tests.integration.conftest import TOKEN

H = {"Authorization": f"Bearer {TOKEN}"}
ALL7 = {t: 4.0 for t in P.STEPS}


def record(wid: str, ended: datetime, seconds: dict[str, float], session: str = "ses_a") -> dict:
    s = {t: seconds.get(t, 0.0) for t in P.STEPS}
    done = sum(v >= 3.0 for v in s.values())
    total = sum(s.values())
    finished = done >= 5 and total >= 20
    stars = (5 if done == 7 else 4 if done == 6 else 3) if finished else (2 if done >= 3 or total >= 10 else 1 if total else 0)
    score = {"session_id": session, "timestamp": 30.0, "steps": [{"technique": t, "seconds": v, "done": v >= 3, "points": min(v / 3, 1) * 10}
                                                                   for t, v in s.items()],
             "steps_done": done, "steps_required": 5, "step_min_s": 3.0, "total_s": total, "total_min_s": 20.0, "finished": finished,
             "finished_at_ts": 20.0 if finished else None, "next_step": None, "points": 80 if finished else 30, "stars": stars}
    stamp = lambda t: t.isoformat().replace("+00:00", "Z")  # noqa: E731
    return {"wash_id": wid, "session_id": session, "started_utc": stamp(ended - timedelta(seconds=40)), "ended_utc": stamp(ended),
            "duration_s": 40.0, "seconds": s, "score": score, "soap_seen": True, "quality": {"frames": 600}, "models": {}}


@pytest.fixture
def client(tmp_path):
    url = f"sqlite:///{tmp_path / 'app.db'}"
    with TestClient(create_app(Settings(api_token=TOKEN, database_url=url, log_dir="logs"), url)) as c:
        yield c


def now() -> datetime:
    return datetime.now(UTC)


def test_a_wash_is_saved_once_and_earns_zaps(client):
    r = client.post("/api/v1/washes", json=record("w1", now(), ALL7), headers=H)
    assert r.status_code == 201, r.text
    assert r.json()["zaps"] == 7 + P.FINISH_BONUS
    again = client.post("/api/v1/washes", json=record("w1", now(), ALL7), headers=H)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert len(client.get("/api/v1/app/washes").json()) == 1
    assert client.get("/api/v1/app/rewards").json()["zaps"] == 7 + P.FINISH_BONUS


def test_saving_a_wash_needs_the_token(client):
    assert client.post("/api/v1/washes", json=record("w1", now(), ALL7)).status_code == 401


def test_progress_adds_up_across_sessions(client):
    client.post("/api/v1/washes", json=record("a-w001", now() - timedelta(minutes=30), ALL7, "ses_a"), headers=H)
    client.post("/api/v1/washes", json=record("b-w001", now(), {**ALL7, "thumb_rubbing": 0.0}, "ses_b"), headers=H)
    home = client.get("/api/v1/app/home").json()
    assert home["today"] == 2 and home["clean_washes"] == 2
    assert home["latest"]["wash_id"] == "b-w001" and home["latest"]["missed"] == ["thumbs"]
    week = client.get("/api/v1/app/progress", params={"period": "week"}).json()
    assert week["washes"] == 2 and week["trouble_spots"][0]["zone"] == "thumbs"
    detail = client.get("/api/v1/app/washes/b-w001").json()
    assert detail["seconds"]["thumb_rubbing"] == 0.0 and detail["coverage"]["thumbs"] == 0.0


def test_daily_goal_from_settings_caps_zaps(client):
    assert client.put("/api/v1/app/settings", json={"daily_goal": 1}).status_code == 200
    noon = datetime(2026, 11, 3, 18, tzinfo=UTC)  # a fixed day, so the test never straddles midnight
    client.post("/api/v1/washes", json=record("w1", noon, ALL7), headers=H)
    assert client.post("/api/v1/washes", json=record("w2", noon + timedelta(minutes=5), ALL7), headers=H).json()["zaps"] == 0


def test_buying_a_germ(client):
    assert client.post("/api/v1/app/rewards/buy", json={"germ": "sneezel"}).status_code == 409   # 0 zaps
    for i in range(5):
        client.post("/api/v1/washes", json=record(f"w{i}", now() - timedelta(minutes=i), ALL7), headers=H)  # 5 x 10 zaps
    r = client.post("/api/v1/app/rewards/buy", json={"germ": "sneezel"})
    assert r.status_code == 200, r.text
    rewards = client.get("/api/v1/app/rewards").json()
    assert rewards["zaps"] == 0
    assert {g["id"] for g in rewards["germs"] if g["owned"]} == {"gunky", "sneezel"}
    assert client.post("/api/v1/app/rewards/buy", json={"germ": "sneezel"}).status_code == 409  # already owned
    assert client.post("/api/v1/app/rewards/buy", json={"germ": "king_prickle"}).status_code == 409  # boss prize, not for sale


def test_beating_the_boss_unlocks_it_for_free(client):
    boss = P.boss_of_week(P.local_day(now(), "America/Chicago"))
    zone_steps = P.ZONES[P.GERMS[boss]["zone"]]
    start = P.week_start(P.local_day(now(), "America/Chicago"))
    for i in range(P.BOSS_TARGET):
        when = max(now() - timedelta(minutes=i), datetime.combine(start, datetime.min.time(), tzinfo=UTC) + timedelta(hours=8))
        client.post("/api/v1/washes", json=record(f"w{i}", when - timedelta(seconds=i), {t: 4.0 for t in zone_steps}), headers=H)
    dex = client.get("/api/v1/app/germdex").json()
    assert dex["boss"]["won"] is True
    assert next(g for g in dex["germs"] if g["id"] == boss)["owned"] is True


def test_settings_child_and_delete_history(client):
    s = client.get("/api/v1/app/settings").json()
    assert s["daily_goal"] == 6 and s["onboarded"] is False and len(s["routines"]) == 5
    client.put("/api/v1/app/settings", json={"parent_name": "Sam", "timezone": "America/New_York", "onboarded": True})
    s = client.get("/api/v1/app/settings").json()
    assert s["parent_name"] == "Sam" and s["timezone"] == "America/New_York" and s["onboarded"] is True
    assert client.put("/api/v1/app/settings", json={"timezone": "Mars/Base"}).status_code == 422
    assert client.get("/api/v1/app/child").json() is None
    client.put("/api/v1/app/child", json={"name": "Mia", "buddy": "scrubby", "age_band": "5-6"})
    assert client.get("/api/v1/app/child").json()["name"] == "Mia"
    client.post("/api/v1/washes", json=record("w1", now(), ALL7), headers=H)
    assert client.delete("/api/v1/app/washes").status_code == 200
    assert client.get("/api/v1/app/washes").json() == []
    assert client.get("/api/v1/app/rewards").json()["zaps"] == 0


def test_saved_wash_reaches_the_live_feed(live_server):
    import httpx
    from websockets.sync.client import connect

    with connect(f"{live_server.ws}/ws/v1/observations") as sub:
        r = httpx.post(f"{live_server.http}/api/v1/washes", json=record("w1", now(), ALL7), headers=H)
        assert r.status_code == 201
        msg = json.loads(sub.recv(timeout=5))
    assert msg["type"] == "wash_saved" and msg["wash"]["wash_id"] == "w1" and msg["wash"]["zaps"] == 10
