"""Send one SIMULATED wash to a demo backend through the same API the station uses (POST /api/v1/washes).

    .venv/bin/python scripts/send_test_wash.py --url http://127.0.0.1:8010 --miss thumbs

For rehearsing the app without the camera: the wash shows up live in the open app, marked "Demo data".
It only talks to a backend that reports demo mode, so it cannot add made-up washes to a real family.
A real wash comes from `convergent camera --auto-wash --backend http`.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from convergent.common.config import PipelineConfig, load_settings, resolve_path
from convergent.scoring import progression as P
from convergent.scoring.wash_session import WashRecord

sys.path.insert(0, str(resolve_path("scripts")))
from seed_demo_family import score_for  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--miss", nargs="*", default=["thumbs"], choices=list(P.ZONES), help="zones to leave unwashed")
    ap.add_argument("--seconds", type=float, default=4.0, help="scrub time for each washed step")
    args = ap.parse_args()
    token = load_settings().api_token
    cfg = PipelineConfig.load(resolve_path("configs/development.yaml")).scoring
    skipped = {step for zone in args.miss for step in P.ZONES[zone]}
    seconds = {t: 0.0 if t in skipped else args.seconds for t in P.STEPS}
    took = round(sum(seconds.values()) + 9.0, 1)
    ended = datetime.now(UTC)
    stamp = lambda t: t.isoformat(timespec="milliseconds").replace("+00:00", "Z")  # noqa: E731
    rec = WashRecord(wash_id=f"demo-sim-{uuid.uuid4().hex[:10]}", session_id="demo-sim", started_utc=stamp(ended - timedelta(seconds=took)),
                     ended_utc=stamp(ended), duration_s=took, seconds=seconds, score=score_for(seconds, cfg), soap_seen=None,
                     quality={"demo": True, "simulated": True}, models={"temporal_v2": {"version": "demo"}})
    with httpx.Client(base_url=args.url, timeout=10, headers={"Authorization": f"Bearer {token}"}) as c:
        if not c.get("/api/v1/app/station").json().get("demo_mode"):
            print(f"{args.url} is not a demo backend (CONVERGENT_DEMO_MODE=true). Nothing was sent.", file=sys.stderr)
            return 2
        r = c.post("/api/v1/washes", json=rec.model_dump(mode="json"))
    print(r.status_code, r.json().get("wash_id"), f"score {rec.score.points}", f"+{r.json().get('reward_points')} points")
    return 0 if r.status_code == 201 else 1


if __name__ == "__main__":
    raise SystemExit(main())
