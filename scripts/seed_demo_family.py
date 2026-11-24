"""Fill a DEMO backend with a made-up family so every screen of the app has something to show.

    CONVERGENT_DEMO_MODE=true CONVERGENT_DATABASE_URL=sqlite:///./scrubble_demo.db .venv/bin/python -m convergent.cli backend --port 8010
    .venv/bin/python scripts/seed_demo_family.py --url http://127.0.0.1:8010 --reset

The family is the one in the design: Sam with Mia and Leo. Every wash is made up (ids start with "demo-", the app
marks them "Demo data"). The script only talks to a backend that reports demo mode, and --reset empties that
backend's app tables first, so it cannot touch a real family's data. The same day and seed give the same family.

Mia ends one rewarded wash short of opening Soap Canyon on the map, so the next real wash from the station
visibly moves the app without anything being staged in the UI.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from convergent.common.config import PipelineConfig, ScoringConfig, load_settings, resolve_path
from convergent.scoring.wash_score import StepTime, WashScore
from convergent.scoring.wash_session import WashRecord

STEPS = ["palm_to_palm", "back_of_hand", "interlaced_fingers", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing", "wrist_rubbing"]
# chance that a step is skipped, per child: Mia rushes her thumbs, Leo his fingertips
SKIP = {
    "Mia": {"palm_to_palm": 0.03, "back_of_hand": 0.12, "interlaced_fingers": 0.15, "backs_of_fingers": 0.18, "thumb_rubbing": 0.62,
            "fingertip_rubbing": 0.4, "wrist_rubbing": 0.3},
    "Leo": {"palm_to_palm": 0.05, "back_of_hand": 0.2, "interlaced_fingers": 0.1, "backs_of_fingers": 0.25, "thumb_rubbing": 0.2,
            "fingertip_rubbing": 0.6, "wrist_rubbing": 0.45},
}
ROUTINE_HOURS = [7.6, 12.1, 15.4, 18.05, 19.5]   # around the default routines, local time
# washes per day, oldest first, ending today. Mia: 24 in all, so wash 25 opens Soap Canyon.
PLAN = {"Mia": [2, 3, 2, 4, 3, 2, 3, 3, 2], "Leo": [1, 2, 0, 2, 3, 1, 2]}   # a day holds at most 5 (one per routine time)


def score_for(seconds: dict[str, float], c: ScoringConfig) -> WashScore:
    """The score the station would give these step times (same rules as scoring/wash_score.py)."""
    steps = [StepTime(technique=t, seconds=s, done=s >= c.step_min_s, points=round(c.step_points * min(s / c.step_min_s, 1), 2))
             for t, s in seconds.items()]
    done, total = sum(st.done for st in steps), sum(seconds.values())
    finished = done >= c.steps_required and total >= c.total_min_s
    stars = (5 if done == 7 else 4 if done > c.steps_required else 3) if finished else (2 if done >= 3 or total >= 10 else 1 if total else 0)
    points = round(sum(st.points for st in steps) + c.time_points * min(total / c.total_min_s, 1))
    return WashScore(timestamp=total, steps=steps, steps_done=done, steps_required=c.steps_required, step_min_s=c.step_min_s,
                     total_s=round(total, 2), total_min_s=c.total_min_s, finished=finished, finished_at_ts=total if finished else None,
                     next_step=next((st.technique for st in steps if not st.done), None), points=points, stars=stars)


def washes_for(kid: str, tz: ZoneInfo, now: datetime, rng: random.Random, cfg: ScoringConfig) -> list[WashRecord]:
    plan = list(PLAN[kid])
    local_now = now.astimezone(tz)
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    # today only gets the routine times that have already passed; the rest of today's share moves to the first day
    passed = [h for h in ROUTINE_HOURS if h + 0.4 < local_now.hour + local_now.minute / 60]
    moved = max(plan[-1] - len(passed), 0)
    plan[-1] -= moved
    plan[0] += moved
    out: list[WashRecord] = []
    for back, count in zip(range(len(plan) - 1, -1, -1), plan, strict=True):
        day = today - timedelta(days=back)
        hours = sorted(rng.sample(passed if back == 0 else ROUTINE_HOURS, count))
        for h in hours:
            ended = (day + timedelta(hours=h, minutes=rng.randint(0, 9))).astimezone(UTC)
            seconds = {t: 0.0 if rng.random() < SKIP[kid][t] else round(rng.uniform(3.0, 5.5), 1) for t in STEPS}
            if sum(seconds.values()) == 0:
                seconds["palm_to_palm"] = 3.4
            took = round(sum(seconds.values()) + rng.uniform(6, 14), 1)   # hands in view: scrubbing plus rinsing
            stamp = lambda t: t.isoformat(timespec="milliseconds").replace("+00:00", "Z")  # noqa: E731
            out.append(WashRecord(
                wash_id=f"demo-{kid.lower()}-{len(out) + 1:03d}", session_id=f"demo-{kid.lower()}",
                started_utc=stamp(ended - timedelta(seconds=took)), ended_utc=stamp(ended), duration_s=took, seconds=seconds,
                score=score_for(seconds, cfg), soap_seen=rng.random() < 0.85, quality={"demo": True, "frames": int(took * 15), "fps": 15.0},
                models={"temporal_v2": {"version": "demo"}}))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8010", help="the demo backend")
    ap.add_argument("--timezone", default="America/Chicago")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--reset", action="store_true", help="empty the demo backend's app tables first")
    args = ap.parse_args()

    token = load_settings().api_token
    if not token:
        print("CONVERGENT_API_TOKEN is not set (see .env.example)", file=sys.stderr)
        return 2
    cfg = PipelineConfig.load(resolve_path("configs/development.yaml")).scoring
    tz, rng, now = ZoneInfo(args.timezone), random.Random(args.seed), datetime.now(UTC)
    with httpx.Client(base_url=args.url, timeout=10, headers={"Authorization": f"Bearer {token}"}) as c:
        def call(method: str, path: str, body: dict | None = None, ok: tuple[int, ...] = (200, 201)) -> dict:
            r = c.request(method, path, json=body)
            if r.status_code == 429:  # the backend's flood guard: wait as asked, once
                time.sleep(float(r.headers.get("Retry-After", "15")))
                r = c.request(method, path, json=body)
            if r.status_code not in ok:
                raise SystemExit(f"{method} {path}: {r.status_code} {r.text[:200]}")
            return r.json()

        if not call("GET", "/api/v1/app/station").get("demo_mode"):
            print(f"{args.url} is not a demo backend (start it with CONVERGENT_DEMO_MODE=true). Nothing was changed.", file=sys.stderr)
            return 2
        if args.reset:
            call("POST", "/api/v1/app/demo/reset")
        elif call("GET", "/api/v1/app/children"):
            print("this demo backend already has a family: run again with --reset to start over", file=sys.stderr)
            return 2

        call("PUT", "/api/v1/app/settings", {"parent_name": "Sam", "timezone": args.timezone, "daily_goal": 6, "onboarded": True})
        rewards = [call("POST", "/api/v1/app/family-rewards", {"title": t, "cost": cost, "icon": icon})
                   for t, cost, icon in (("Extra bedtime story", 300, "book"), ("Pick Friday movie", 800, "movie"), ("Trip to the park", 1500, "park"))]
        sent = {}
        for kid, buddy, age in (("Leo", "minty", "7-8"), ("Mia", "scrubby", "5-6")):   # Mia last, so she is the active child
            call("POST", "/api/v1/app/children", {"name": kid, "buddy": buddy, "age_band": age})
            records = sorted(washes_for(kid, tz, now, rng, cfg), key=lambda r: r.ended_utc)
            for rec in records:
                call("POST", "/api/v1/washes", rec.model_dump(mode="json"))
            sent[kid] = len(records)
        # Mia already traded points for a movie night, and bought her first germ with zaps
        asked = call("POST", "/api/v1/app/redemptions", {"reward_id": rewards[1]["id"], "request_id": "demo-movie-night-1"})
        call("POST", f"/api/v1/app/redemptions/{asked['request']['id']}/decide", {"approve": True})
        call("POST", "/api/v1/app/rewards/buy", {"germ": "sneezel"})
        latest = call("GET", "/api/v1/app/home")["latest"]
        call("POST", f"/api/v1/app/washes/{latest['wash_id']}/high-five")
        home, trip = call("GET", "/api/v1/app/home"), call("GET", "/api/v1/app/adventure")
    print(f"seeded {args.url}: Mia {sent['Mia']} washes, Leo {sent['Leo']} washes (all made up)")
    print(f"Mia: {home['points']} points, {home['zaps']} zaps, {home['streak']}-day streak, next on the map: "
          f"{trip['next']['name']} in {trip['next']['washes_left']} wash(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
