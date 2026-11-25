"""Fill the parent app with made-up washes so its pages have something to show.

Run with the backend up (it needs CONVERGENT_API_TOKEN from .env, like a camera run):
    .venv/bin/python scripts/seed_demo_washes.py --days 14
Remove them in the app (Settings, Delete wash history). Washes are made up: thumbs and wrists are
missed more often, like on real data. Ids start with "demo-".
"""

from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime, timedelta

from convergent.backend.client import BackendClient
from convergent.common.config import PipelineConfig, ScoringConfig, load_settings, resolve_path
from convergent.scoring.wash_score import StepTime, WashScore
from convergent.scoring.wash_session import WashRecord

MISS = {"palm_to_palm": 0.05, "back_of_hand": 0.2, "interlaced_fingers": 0.25, "backs_of_fingers": 0.3,
        "thumb_rubbing": 0.55, "fingertip_rubbing": 0.35, "wrist_rubbing": 0.6}
HOURS = [7.5, 12.2, 15.5, 18.1, 19.6, 20.5]


def fake_score(seconds: dict[str, float], c: ScoringConfig) -> WashScore:
    steps = [StepTime(technique=t, seconds=s, done=s >= c.step_min_s, points=round(c.step_points * min(s / c.step_min_s, 1), 2))
             for t, s in seconds.items()]
    done, total = sum(st.done for st in steps), sum(seconds.values())
    finished = done >= c.steps_required and total >= c.total_min_s
    stars = (5 if done == 7 else 4 if done > c.steps_required else 3) if finished else (2 if done >= 3 or total >= 10 else 1 if total else 0)
    points = round(sum(st.points for st in steps) + c.time_points * min(total / c.total_min_s, 1))
    return WashScore(timestamp=total, steps=steps, steps_done=done, steps_required=c.steps_required, step_min_s=c.step_min_s,
                     total_s=round(total, 2), total_min_s=c.total_min_s, finished=finished, finished_at_ts=total if finished else None,
                     next_step=next((st.technique for st in steps if not st.done), None), points=points, stars=stars)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--url", default=None, help="backend address (default: backend.base_url in configs/development.yaml)")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    cfg = PipelineConfig.load(resolve_path("configs/development.yaml"))
    url = args.url or cfg.backend.base_url
    client = BackendClient(url, load_settings().api_token)
    now = datetime.now(UTC)
    sent = 0
    for d in range(args.days, -1, -1):
        day = (now - timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
        for h in rng.sample(HOURS, rng.randint(2, 6)):
            ended = day + timedelta(hours=h + 6 + rng.uniform(-0.3, 0.3))  # ~US Central local time
            if ended > now:
                continue
            seconds = {t: 0.0 if rng.random() < p else round(rng.uniform(2.5, 6.0), 1) for t, p in MISS.items()}
            rec = WashRecord(wash_id=f"demo-{ended:%Y%m%d%H%M%S}", session_id="demo", started_utc=(ended - timedelta(seconds=45)).isoformat(),
                             ended_utc=ended.isoformat(), duration_s=45.0, seconds=seconds, score=fake_score(seconds, cfg.scoring),
                             soap_seen=rng.random() < 0.8, quality={"demo": True}, models={})
            client.post_wash(rec.model_dump(mode="json"))
            sent += 1
    client.close()
    print(f"sent {sent} demo washes to {url}")


if __name__ == "__main__":
    main()
