"""Family side of the parent app: children and the active one, wash checks, points, rewards, requests, PIN, map."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from starlette.testclient import TestClient

from convergent.backend.app import create_app
from convergent.backend.database import make_engine, run_migrations
from convergent.common.config import Settings
from convergent.scoring import progression as P
from tests.integration.conftest import TOKEN
from tests.integration.test_parent_app import ALL7, H, now, record


@pytest.fixture
def client(tmp_path):
    url = f"sqlite:///{tmp_path / 'family.db'}"
    with TestClient(create_app(Settings(api_token=TOKEN, database_url=url, log_dir="logs"), url)) as c:
        yield c


def post(client, wid: str, ended: datetime | None = None, seconds: dict | None = None, raw: dict | None = None):
    """Send a wash. ``raw`` overwrites fields of the finished record, to build records the station would never send."""
    return client.post("/api/v1/washes", json={**record(wid, ended or now(), seconds or ALL7), **(raw or {})}, headers=H)


def kid(client, name: str) -> int:
    r = client.post("/api/v1/app/children", json={"name": name, "buddy": "scrubby", "age_band": "5-6"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- wash checks
def test_a_wash_with_other_contents_under_the_same_id_is_a_conflict_and_earns_nothing_more(client):
    assert post(client, "w1").status_code == 201
    r = post(client, "w1", seconds={**ALL7, "thumb_rubbing": 0.0})
    assert r.status_code == 409 and r.json()["code"] == "http_409"
    assert client.get("/api/v1/app/family-rewards").json()["points"] == 80
    assert len(client.get("/api/v1/app/washes").json()) == 1


@pytest.mark.parametrize("changes", [
    {"schema_version": "wash-record-v9"},
    {"duration_s": -1.0},
    {"duration_s": 99999.0},
    {"duration_s": 400.0},                       # does not match started/ended (40 s apart)
    {"started_utc": "yesterday"},
    {"seconds": {**ALL7, "nose_rubbing": 3.0}},  # a step the recognizer does not have
    {"seconds": {**ALL7, "palm_to_palm": -2.0}},
    {"seconds": {**ALL7, "palm_to_palm": 500.0}},
])
def test_impossible_wash_records_are_refused(client, changes):
    r = post(client, "bad", raw=changes)
    assert r.status_code == 422, r.text
    assert client.get("/api/v1/app/washes").json() == []


def test_a_wash_from_the_future_is_refused(client):
    assert post(client, "soon", now() + timedelta(hours=2)).status_code == 422


def test_malformed_and_oversized_bodies_are_refused(client):
    assert client.post("/api/v1/washes", content=b"{not json", headers={**H, "Content-Type": "application/json"}).status_code == 422
    assert client.post("/api/v1/washes", json={"wash_id": "x"}, headers=H).status_code == 422
    big = {**record("big", now(), ALL7), "quality": {"pad": "x" * 80_000}}
    assert client.post("/api/v1/washes", json=big, headers=H).status_code == 413
    assert client.post("/api/v1/washes", json=record("w", now(), ALL7), headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_the_same_wash_sent_at_once_from_many_threads_is_saved_and_paid_once(client):
    rec = record("burst", now(), ALL7)
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda _: client.post("/api/v1/washes", json=rec, headers=H).status_code, range(8)))
    assert sorted(codes) == [200] * 7 + [201]
    assert client.get("/api/v1/app/family-rewards").json()["points"] == 80


def test_a_wash_with_nothing_recognized_is_kept_but_earns_nothing(client):
    r = post(client, "empty", seconds=dict.fromkeys(P.STEPS, 0.0))
    assert r.status_code == 201 and r.json()["zaps"] == 0 and r.json()["reward_points"] == 0
    assert client.get("/api/v1/app/home").json()["today"] == 0


# ---- children
def test_new_washes_go_to_the_active_child_and_pages_show_only_that_child(client):
    mia = kid(client, "Mia")
    post(client, "mia-1")
    leo = kid(client, "Leo")          # adding a child makes it the active one
    post(client, "leo-1", seconds={**ALL7, "thumb_rubbing": 0.0})
    assert [w["wash_id"] for w in client.get("/api/v1/app/washes").json()] == ["leo-1"]
    assert client.get("/api/v1/app/washes/mia-1").status_code == 404          # another child's wash is not reachable
    assert client.post("/api/v1/app/washes/mia-1/high-five").status_code == 404
    assert client.post(f"/api/v1/app/children/{mia}/activate").json()["active"] is True
    home = client.get("/api/v1/app/home").json()
    assert home["child"]["name"] == "Mia" and home["latest"]["wash_id"] == "mia-1" and home["points"] == 80
    assert [c["active"] for c in client.get("/api/v1/app/children").json()] == [True, False]
    assert client.post("/api/v1/app/children/999/activate").status_code == 404
    assert leo != mia


def test_the_first_child_takes_over_washes_saved_before_any_child_existed(client):
    post(client, "early")
    assert client.get("/api/v1/app/home").json()["today"] == 1
    kid(client, "Mia")
    assert [w["wash_id"] for w in client.get("/api/v1/app/washes").json()] == ["early"]


def test_removing_a_child_removes_their_washes(client):
    mia = kid(client, "Mia")
    post(client, "mia-1")
    kid(client, "Leo")
    assert client.delete(f"/api/v1/app/children/{mia}").status_code == 200
    assert [c["name"] for c in client.get("/api/v1/app/children").json()] == ["Leo"]
    assert client.post("/api/v1/washes", json=record("mia-1", now(), ALL7), headers=H).status_code == 201  # gone, so it is new again


# ---- points and rewards
def test_points_are_the_score_and_stop_at_the_daily_goal(client):
    client.put("/api/v1/app/settings", json={"daily_goal": 2})
    noon = datetime(2026, 11, 3, 18, tzinfo=UTC)
    got = [post(client, f"w{i}", noon + timedelta(minutes=5 * i)).json()["reward_points"] for i in range(3)]
    assert got == [80, 80, 0]
    page = client.get("/api/v1/app/family-rewards").json()
    assert page["points"] == 160 and page["rule"]["rewarded_washes_per_day"] == 2


def rich(client, washes: int = 5) -> None:
    """Give the active child washes x 80 points, spread over days so the daily goal never caps them."""
    for i in range(washes):
        post(client, f"rich{i}", now() - timedelta(days=i, minutes=1))


def test_asking_for_a_reward_holds_the_points_and_a_repeat_is_not_charged_twice(client):
    reward = client.post("/api/v1/app/family-rewards", json={"title": "Extra bedtime story", "cost": 300, "icon": "book"}).json()
    ask = {"reward_id": reward["id"], "request_id": "req-0001-abcd"}
    r = client.post("/api/v1/app/redemptions", json=ask)
    assert r.status_code == 409 and r.json()["error"] == "not enough points yet"
    rich(client)                                                              # 400 points
    first = client.post("/api/v1/app/redemptions", json=ask).json()
    assert first["points"] == 100 and first["held"] == 300 and first["duplicate"] is False
    again = client.post("/api/v1/app/redemptions", json=ask).json()
    assert again["points"] == 100 and again["duplicate"] is True and len(again["requests"]) == 1
    other = client.post("/api/v1/app/redemptions", json={**ask, "request_id": "req-0002-abcd"})
    assert other.status_code == 409                                           # 100 left, costs 300


def test_exact_balance_can_be_spent_and_the_balance_never_goes_negative(client):
    reward = client.post("/api/v1/app/family-rewards", json={"title": "Sticker", "cost": 80}).json()
    post(client, "one")                                                       # exactly 80 points
    assert client.post("/api/v1/app/redemptions", json={"reward_id": reward["id"], "request_id": "exact-000001"}).json()["points"] == 0
    assert client.post("/api/v1/app/redemptions", json={"reward_id": reward["id"], "request_id": "exact-000002"}).status_code == 409


def test_many_requests_at_once_spend_the_points_only_once(client):
    reward = client.post("/api/v1/app/family-rewards", json={"title": "Movie", "cost": 300}).json()
    rich(client)                                                              # 400 points: enough for one
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda i: client.post("/api/v1/app/redemptions", json={"reward_id": reward["id"], "request_id": f"race-{i:08d}"}).status_code, range(8)))
    assert sorted(codes) == [200] + [409] * 7
    assert client.get("/api/v1/app/family-rewards").json()["points"] == 100


def test_a_parent_decides_once_and_declining_gives_the_points_back(client):
    reward = client.post("/api/v1/app/family-rewards", json={"title": "Movie", "cost": 300}).json()
    rich(client)
    req = client.post("/api/v1/app/redemptions", json={"reward_id": reward["id"], "request_id": "decide-00001"}).json()["request"]
    declined = client.post(f"/api/v1/app/redemptions/{req['id']}/decide", json={"approve": False}).json()
    assert declined["points"] == 400 and declined["request"]["status"] == "declined"
    assert client.post(f"/api/v1/app/redemptions/{req['id']}/decide", json={"approve": True}).status_code == 409
    req2 = client.post("/api/v1/app/redemptions", json={"reward_id": reward["id"], "request_id": "decide-00002"}).json()["request"]
    approved = client.post(f"/api/v1/app/redemptions/{req2['id']}/decide", json={"approve": True}).json()
    assert approved["points"] == 100 and approved["request"]["status"] == "approved"
    client.delete(f"/api/v1/app/family-rewards/{reward['id']}")               # the reward goes, the approved request stays
    assert client.get("/api/v1/app/family-rewards").json()["requests"][0]["title"] == "Movie"


def test_a_switched_off_reward_cannot_be_asked_for_and_bad_rewards_are_refused(client):
    reward = client.post("/api/v1/app/family-rewards", json={"title": "Movie", "cost": 80}).json()
    post(client, "one")
    client.put(f"/api/v1/app/family-rewards/{reward['id']}", json={"enabled": False})
    assert client.post("/api/v1/app/redemptions", json={"reward_id": reward["id"], "request_id": "off-00000001"}).status_code == 409
    assert client.post("/api/v1/app/family-rewards", json={"title": "", "cost": 10}).status_code == 422
    assert client.post("/api/v1/app/family-rewards", json={"title": "Free", "cost": 0}).status_code == 422


def test_deleting_history_resets_points_germs_and_requests_for_that_child_only(client):
    mia = kid(client, "Mia")
    reward = client.post("/api/v1/app/family-rewards", json={"title": "Sticker", "cost": 80}).json()
    post(client, "mia-1")
    client.post("/api/v1/app/redemptions", json={"reward_id": reward["id"], "request_id": "mia-request-1"})
    kid(client, "Leo")
    post(client, "leo-1")
    assert client.delete("/api/v1/app/washes").json() == {"deleted": 1}        # Leo is active
    assert client.get("/api/v1/app/family-rewards").json()["points"] == 0
    client.post(f"/api/v1/app/children/{mia}/activate")
    page = client.get("/api/v1/app/family-rewards").json()
    assert page["earned"] == 80 and page["held"] == 80 and len(page["requests"]) == 1


# ---- high-five
def test_a_high_five_is_saved_once_and_shows_on_the_wash(client):
    post(client, "w1")
    first = client.post("/api/v1/app/washes/w1/high-five").json()
    assert first["duplicate"] is False
    assert client.post("/api/v1/app/washes/w1/high-five").json() == {**first, "duplicate": True}
    detail = client.get("/api/v1/app/washes/w1").json()
    assert detail["high_fived"] == first["high_fived"] and detail["source"] == "station" and detail["session_id"] == "ses_a"


# ---- parent PIN
def test_parent_only_actions_need_the_pin_once_it_is_set(client):
    assert client.get("/api/v1/app/parent").json() == {"pin_set": False, "unlocked": True}
    token = client.put("/api/v1/app/parent/pin", json={"pin": "4821"}).json()["token"]
    assert client.get("/api/v1/app/parent").json() == {"pin_set": True, "unlocked": False}
    for call in (lambda h: client.post("/api/v1/app/family-rewards", json={"title": "Movie", "cost": 300}, headers=h),
                 lambda h: client.delete("/api/v1/app/washes", headers=h),
                 lambda h: client.put("/api/v1/app/parent/pin", json={"pin": "0000"}, headers=h)):
        assert call({}).status_code == 403
        assert call({"X-Parent-Token": "made-up"}).status_code == 403
    assert client.post("/api/v1/app/family-rewards", json={"title": "Movie", "cost": 300}, headers={"X-Parent-Token": token}).status_code == 201
    assert client.post("/api/v1/app/parent/unlock", json={"pin": "1111"}).status_code == 403
    fresh = client.post("/api/v1/app/parent/unlock", json={"pin": "4821"}).json()["token"]
    client.post("/api/v1/app/parent/lock", headers={"X-Parent-Token": fresh})
    assert client.delete("/api/v1/app/washes", headers={"X-Parent-Token": fresh}).status_code == 403
    assert client.get("/api/v1/app/family-rewards").status_code == 200        # reading and asking stay open for the child


def test_pin_guesses_are_slowed_down_and_the_pin_is_not_stored_or_returned(client, tmp_path):
    client.put("/api/v1/app/parent/pin", json={"pin": "4821"})
    codes = [client.post("/api/v1/app/parent/unlock", json={"pin": "0000"}).status_code for _ in range(7)]
    assert codes == [403] * 5 + [429] * 2
    assert "parent_pin_hash" not in client.get("/api/v1/app/settings").json()
    with make_engine(f"sqlite:///{tmp_path / 'family.db'}").connect() as conn:
        stored = conn.execute(sa.text("SELECT parent_pin_hash FROM app_settings")).scalar_one()
    assert stored.startswith("pbkdf2_sha256$") and "4821" not in stored


# ---- map, streak, station
def test_the_map_opens_places_from_rewarded_washes_and_shows_the_way_to_the_next(client):
    start = client.get("/api/v1/app/adventure").json()
    assert [s["unlocked"] for s in start["stages"]] == [True, False, False, False]
    assert start["next"] == {"id": "germ_jungle", "name": "Germ Jungle", "washes_left": 10}
    for i in range(5):
        post(client, f"w{i}", now() - timedelta(days=i, minutes=1))
    half = client.get("/api/v1/app/adventure").json()
    assert half["rewarded_washes"] == 5 and half["stages"][0]["stones_lit"] == 2 and half["next"]["washes_left"] == 5
    assert half["streak"] == {"current": 5, "best": 5}


def test_station_is_online_only_while_live_updates_arrive(live_server):
    import httpx

    base = live_server.http
    assert httpx.get(f"{base}/api/v1/app/station").json()["online"] is False
    httpx.post(f"{base}/api/v1/sessions", json={"session_id": "ses_live", "source_id": "cam", "width": 640, "height": 480, "target_fps": 15,
                                                "device_id": None, "processing_config": {}, "model_versions": {}, "capture_clock": "monotonic"}, headers=H)
    assert httpx.post(f"{base}/api/v1/sessions/ses_live/live", json={"ts": 1.0, "hands": 2}, headers=H).status_code == 202
    st = httpx.get(f"{base}/api/v1/app/station").json()
    assert st["online"] is True and st["last_seen"] is not None and st["rules"] is None
    httpx.post(f"{base}/api/v1/washes", json=record("w1", now(), ALL7), headers=H)
    assert httpx.get(f"{base}/api/v1/app/station").json()["rules"]["scrub_goal_s"] == 20.0


# ---- migration
def test_upgrading_from_the_parent_app_schema_keeps_washes_and_germs(tmp_path):
    from alembic import command
    from alembic.config import Config

    url = f"sqlite:///{tmp_path / 'old.db'}"
    cfg = Config()
    cfg.set_main_option("script_location", "src/convergent/backend/migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0002_parent_app")
    with make_engine(url).begin() as conn:
        conn.execute(sa.text("INSERT INTO children (name, buddy, age_band, created_utc) VALUES ('Mia', 'scrubby', '5-6', '2026-11-20 00:00:00')"))
        conn.execute(sa.text("INSERT INTO washes (wash_id, child_id, session_id, ended_utc, stars, points, finished, steps_done, zaps, seconds, record, created_utc) "
                             "VALUES ('demo-1', NULL, 's', '2026-11-20 12:00:00', 3, 80, 1, 5, 8, '{}', '{}', '2026-11-20 12:00:00')"))
        conn.execute(sa.text("INSERT INTO germ_unlocks (germ, spent, how, created_utc) VALUES ('sneezel', 50, 'bought', '2026-11-20 12:00:00')"))
    assert run_migrations(url) == "0003_family"
    with make_engine(url).connect() as conn:
        assert conn.execute(sa.text("SELECT child_id, source, reward_points FROM washes")).one() == (1, "demo", 0)
        assert conn.execute(sa.text("SELECT child_id, germ, spent FROM child_germs")).one() == (1, "sneezel", 50)
    command.downgrade(cfg, "0002_parent_app")
    with make_engine(url).connect() as conn:
        assert conn.execute(sa.text("SELECT germ, spent FROM germ_unlocks")).one() == ("sneezel", 50)


def test_a_flood_of_washes_is_slowed_down_with_a_retry_hint(client):
    from convergent.backend.routes import app_v1

    codes = [post(client, f"flood-{i}", now() - timedelta(days=i % 300, minutes=i)).status_code for i in range(app_v1.WASH_RATE + 2)]
    assert codes[:app_v1.WASH_RATE] == [201] * app_v1.WASH_RATE and codes[-2:] == [429, 429]
    r = post(client, "one-more")
    assert r.status_code == 429 and r.headers["Retry-After"] == "15"


# ---- parent analytics, score breakdown, sync log
def test_wash_detail_shows_how_the_score_adds_up(client):
    post(client, "w1", seconds={**ALL7, "thumb_rubbing": 0.0})
    d = client.get("/api/v1/app/washes/w1").json()
    assert len(d["steps"]) == 7 and {s["name"] for s in d["steps"]} >= {"Thumbs", "Palm to palm"}
    assert round(sum(s["points"] for s in d["steps"]) + d["time_points"]) == d["points"]
    assert d["lag_s"] >= 0 and d["started"] < d["ended"]


def test_insights_and_the_sync_log_cover_only_the_active_child(client):
    kid(client, "Mia")
    post(client, "mia-1", seconds={**ALL7, "thumb_rubbing": 0.0})
    post(client, "demo-mia-2", now() - timedelta(minutes=30))
    kid(client, "Leo")
    assert client.get("/api/v1/app/insights?days=7").json()["n"] == 0
    assert client.get("/api/v1/app/sync").json() == {"total": 0, "from_station": 0, "from_demo": 0, "log": [], "example": None}
    client.post("/api/v1/app/children/1/activate")
    ins = client.get("/api/v1/app/insights?days=7").json()
    assert ins["n"] == 2 and next(z for z in ins["zones"] if z["zone"] == "thumbs")["missed"] == 1
    sync = client.get("/api/v1/app/sync").json()
    assert (sync["total"], sync["from_station"], sync["from_demo"]) == (2, 1, 1)
    assert sync["log"][0]["wash_id"] == "mia-1" and sync["log"][0]["bytes"] < 4000 and sync["log"][0]["lag_s"] >= 0
    assert sync["example"]["wash_id"] == "mia-1" and "seconds" in sync["example"]["record"]   # the newest wash that came from the sink
    assert client.get("/api/v1/app/insights?days=5").status_code == 422
