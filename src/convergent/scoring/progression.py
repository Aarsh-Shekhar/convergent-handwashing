"""Progress across washes for the parent app: zones, zaps, days, trouble spots, rewards, boss, badges.

Pure functions over saved washes, so the backend is the one place these numbers are worked out and
the web app only draws them. Days and weeks use the family's own timezone; weeks start on Monday.

What a wash is worth is fixed when it arrives (``zaps_for``, stored on the wash), so changing a rule
later never rewrites history. Seconds are recognized washing-motion time, not proof of clean hands.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# ---- rules (first guesses, tune on real washes)
STEP_MIN_S = 3.0      # a step or zone is fully washed at this many seconds (same as scoring.step_min_s)
FINISH_BONUS = 3      # extra zaps for a finished wash
BOSS_TARGET = 20      # times the boss's zone must be fully washed in one week
TIP_MIN_WASHES = 3    # washes this week before the home tip names a zone
STEPS = ["palm_to_palm", "back_of_hand", "interlaced_fingers", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing", "wrist_rubbing"]
ZONES: dict[str, list[str]] = {
    "palms": ["palm_to_palm"], "between_fingers": ["interlaced_fingers"], "thumbs": ["thumb_rubbing"],
    "nails": ["fingertip_rubbing"], "backs": ["back_of_hand", "backs_of_fingers"], "wrists": ["wrist_rubbing"],
}
ZONE_NAMES = {"palms": "Palms", "between_fingers": "Between fingers", "thumbs": "Thumbs", "nails": "Nails & tips",
              "backs": "Backs", "wrists": "Wrists"}
# germs named in the design; each lives on one zone. price None = not for sale (owned from the start, or a boss prize)
GERMS: dict[str, dict[str, Any]] = {
    "gunky":           {"name": "Gunky", "rarity": "common", "price": None, "zone": "palms"},
    "sneezel":         {"name": "Sneezel", "rarity": "common", "price": 50, "zone": "between_fingers"},
    "prickle":         {"name": "Prickle", "rarity": "common", "price": 50, "zone": "thumbs"},
    "smudge":          {"name": "Smudge", "rarity": "common", "price": 50, "zone": "nails"},
    "king_sneeze":     {"name": "King Sneeze", "rarity": "rare", "price": 80, "zone": "between_fingers"},
    "king_gunk":       {"name": "King Gunk", "rarity": "rare", "price": 80, "zone": "palms"},
    "rainbow_sneezel": {"name": "Rainbow Sneezel", "rarity": "legendary", "price": 100, "zone": "backs"},
    "king_prickle":    {"name": "King Prickle", "rarity": "boss", "price": None, "zone": "thumbs"},
}
STARTER = "gunky"
KINGS = ["king_prickle", "king_sneeze", "king_gunk"]  # boss of the week rotates through these
DEX_SLOTS = 12
BADGES = [("first_clean", "First clean wash"), ("perfect_10", "Perfect 10"), ("thumb_pro", "Thumb pro")]
STREAK_BADGE_DAYS = 5  # the "5-day streak" badge
# Adventure map: places open as rewarded washes add up (a product choice, not a measurement). A wash past the
# daily goal earns nothing and does not move the map, so washing extra times is never the way forward.
MAP_STAGES = [("bubble_bay", "Bubble Bay", 0), ("germ_jungle", "Germ Jungle", 10), ("soap_canyon", "Soap Canyon", 25),
              ("bacteria_castle", "Bacteria Castle", 50)]
MAP_STONES = 4  # stepping stones drawn between two places


@dataclass
class Wash:
    wash_id: str
    ended: datetime          # timezone-aware
    seconds: dict[str, float]
    stars: int
    points: int
    finished: bool
    steps_done: int
    zaps: int = 0
    reward_points: int = 0   # family-reward points this wash earned (fixed when it arrived)


# ---- single wash
def coverage(seconds: dict[str, float]) -> dict[str, float]:
    """Share of each zone washed long enough (0..1). A zone with two steps is their mean."""
    return {z: round(sum(min(seconds.get(t, 0.0) / STEP_MIN_S, 1.0) for t in ts) / len(ts), 3) for z, ts in ZONES.items()}


def missed(seconds: dict[str, float]) -> list[str]:
    return [z for z, c in coverage(seconds).items() if c < 1.0]


def counts(w: Wash) -> bool:
    """Counts toward the daily goal: at least some washing was recognized."""
    return w.stars >= 1


# ---- days
def local_day(dt: datetime, tz: str) -> date:
    return dt.astimezone(ZoneInfo(tz)).date()


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _on(washes: list[Wash], tz: str, first: date, last: date) -> list[Wash]:
    return [w for w in washes if first <= local_day(w.ended, tz) <= last]


def worth(w: Wash) -> int:
    """Zaps a wash is worth before the daily limit: 1 per step done, plus a bonus if finished."""
    return w.steps_done + (FINISH_BONUS if w.finished else 0)


def zaps_for(w: Wash, earlier: list[Wash], tz: str, goal: int) -> int:
    """Zaps a new wash earns: its worth, or nothing once ``goal`` washes today already earned zaps."""
    day = local_day(w.ended, tz)
    if sum(e.zaps > 0 for e in _on(earlier, tz, day, day)) >= goal:
        return 0
    return worth(w)


def points_for(w: Wash, earlier: list[Wash], tz: str, goal: int) -> int:
    """Family-reward points a new wash earns: its score (0 to 100), under the same daily cap as zaps.

    A wash with no step done earns nothing, and so does any wash once ``goal`` washes today already earned."""
    day = local_day(w.ended, tz)
    if worth(w) == 0 or sum(e.zaps > 0 for e in _on(earlier, tz, day, day)) >= goal:
        return 0
    return max(0, min(int(w.points), 100))


def wash_days(washes: list[Wash], tz: str) -> list[date]:
    """Local days with at least one counted wash, oldest first."""
    return sorted({local_day(w.ended, tz) for w in washes if counts(w)})


def _runs(days: list[date]) -> tuple[int, int, date | None]:
    """(longest run, latest run, last day) of consecutive days."""
    best = run = 0
    prev: date | None = None
    for d in days:
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    return best, run, prev


def streak(washes: list[Wash], now: datetime, tz: str) -> dict[str, int]:
    """Days in a row with a counted wash. Today not washed yet does not break it; a missed day starts a new one."""
    best, run, last = _runs(wash_days(washes, tz))
    current = run if last is not None and local_day(now, tz) - last <= timedelta(days=1) else 0
    return {"current": current, "best": best}


def adventure(washes: list[Wash]) -> dict[str, Any]:
    """The adventure map: which places are open and how far along the path to the next one."""
    done = sum(1 for w in washes if w.zaps > 0 or w.reward_points > 0)
    stages = []
    for i, (key, name, need) in enumerate(MAP_STAGES):
        nxt = MAP_STAGES[i + 1][2] if i + 1 < len(MAP_STAGES) else None
        span = None if nxt is None else nxt - need
        stones = MAP_STONES if span is None or done >= nxt else max(0, min(MAP_STONES, (done - need) * MAP_STONES // span))
        stages.append({"id": key, "name": name, "unlock_at": need, "unlocked": done >= need, "stones_lit": stones if done >= need else 0})
    upcoming = next((st for st in stages if not st["unlocked"]), None)
    return {"rewarded_washes": done, "stones": MAP_STONES, "stages": stages,
            "next": None if upcoming is None else {"id": upcoming["id"], "name": upcoming["name"], "washes_left": upcoming["unlock_at"] - done}}


def _avg(ws: list[Wash]) -> int | None:
    ws = [w for w in ws if counts(w)]
    return round(sum(w.points for w in ws) / len(ws)) if ws else None


def trouble_spots(ws: list[Wash]) -> list[dict[str, Any]]:
    """Zones missed in some of these washes, most missed first."""
    ws = [w for w in ws if counts(w)]
    if not ws:
        return []
    share = {z: round(sum(z in missed(w.seconds) for w in ws) / len(ws), 3) for z in ZONES}
    return [{"zone": z, "name": ZONE_NAMES[z], "missed": s} for z, s in sorted(share.items(), key=lambda kv: -kv[1]) if s > 0]


def label(local: datetime, routines: list[dict[str, Any]], window_min: int = 60) -> str:
    """Name a wash after the switched-on routine closest in time (within ``window_min``), else by time of day."""
    best = "Morning wash" if local.hour < 12 else "Afternoon wash" if local.hour < 17 else "Evening wash"
    gap = window_min + 1
    for r in routines:
        if r.get("on") and r.get("time"):
            h, mi = map(int, r["time"].split(":"))
            d = abs(local.hour * 60 + local.minute - (h * 60 + mi))
            if d <= window_min and d < gap:
                best, gap = r["name"], d
    return best


def wash_view(w: Wash) -> dict[str, Any]:
    return {"wash_id": w.wash_id, "ended": w.ended.isoformat(), "stars": w.stars, "points": w.points, "finished": w.finished,
            "steps_done": w.steps_done, "zaps": w.zaps, "reward_points": w.reward_points, "capped": w.zaps == 0 and worth(w) > 0,
            "seconds_total": round(sum(w.seconds.values()), 1),
            "coverage": coverage(w.seconds), "missed": missed(w.seconds)}


# ---- pages
def home(washes: list[Wash], now: datetime, tz: str, goal: int) -> dict[str, Any]:
    today = local_day(now, tz)
    week = _on(washes, tz, week_start(today), today)
    spots = trouble_spots(week)
    tip = None
    if len([w for w in week if counts(w)]) >= TIP_MIN_WASHES and spots:
        tip = {"zone": spots[0]["zone"], "name": spots[0]["name"], "missed": spots[0]["missed"]}
    latest = max(washes, key=lambda w: w.ended, default=None)
    todays = _on(washes, tz, today, today)
    return {"today": sum(counts(w) for w in todays), "zap_washes_today": sum(w.zaps > 0 for w in todays), "goal": goal, "avg_score": _avg(week),
            "clean_washes": sum(w.finished for w in washes), "latest": None if latest is None else wash_view(latest), "tip": tip}


def progress(washes: list[Wash], now: datetime, tz: str, goal: int, period: str) -> dict[str, Any]:
    today = local_day(now, tz)
    if period == "day":
        ws = [w for w in _on(washes, tz, today, today) if counts(w)]
        zones = {z: round(sum(coverage(w.seconds)[z] for w in ws) / len(ws), 3) if ws else 0.0 for z in ZONES}
        return {"period": "day", "date": today.isoformat(), "washes": len(ws), "goal": goal, "avg_score": _avg(ws), "zones": zones}
    if period == "week":
        start = week_start(today)
        ws = _on(washes, tz, start, start + timedelta(days=6))
        prev = _avg(_on(washes, tz, start - timedelta(days=7), start - timedelta(days=1)))
        avg = _avg(ws)
        per_day = [sum(counts(w) for w in ws if local_day(w.ended, tz) == start + timedelta(days=i)) for i in range(7)]
        return {"period": "week", "start": start.isoformat(), "washes": sum(per_day), "per_day": per_day, "goal": goal,
                "avg_score": avg, "avg_change": None if avg is None or prev is None else avg - prev,
                "clean_washes": sum(w.finished for w in washes), "trouble_spots": trouble_spots(ws)}
    n = calendar.monthrange(today.year, today.month)[1]
    first = today.replace(day=1)
    ws = _on(washes, tz, first, first.replace(day=n))
    days = []
    for d in range(1, n + 1):
        k = sum(counts(w) for w in ws if local_day(w.ended, tz).day == d)
        days.append({"day": d, "washes": k, "fill": round(min(k / goal, 1.0), 3) if goal else 0.0})
    return {"period": "month", "year": today.year, "month": today.month, "first_weekday": first.weekday(),
            "washes": sum(x["washes"] for x in days), "goal": goal, "days": days}


def boss_of_week(day: date) -> str:
    return KINGS[day.isocalendar()[1] % len(KINGS)]


def boss_status(washes: list[Wash], now: datetime, tz: str) -> dict[str, Any]:
    today = local_day(now, tz)
    boss = boss_of_week(today)
    zone = GERMS[boss]["zone"]
    done = sum(coverage(w.seconds)[zone] >= 1.0 for w in _on(washes, tz, week_start(today), today))
    return {"germ": boss, "zone": zone, "done": min(done, BOSS_TARGET), "target": BOSS_TARGET, "won": done >= BOSS_TARGET}


def _owned(unlocks: list[dict[str, Any]]) -> set[str]:
    return {STARTER} | {u["germ"] for u in unlocks if u["germ"] in GERMS}  # "_gift" rows are test zaps, not germs


def rewards(washes: list[Wash], unlocks: list[dict[str, Any]], now: datetime, tz: str) -> dict[str, Any]:
    balance = sum(w.zaps for w in washes) - sum(u.get("spent", 0) for u in unlocks)
    owned = _owned(unlocks)
    germs = [{"id": g, **info, "owned": g in owned, "can_buy": g not in owned and info["price"] is not None and balance >= info["price"]}
             for g, info in GERMS.items()]
    return {"zaps": balance, "germs": germs, "badges": badges(washes, tz), "boss": boss_status(washes, now, tz)}


def germdex(washes: list[Wash], unlocks: list[dict[str, Any]], now: datetime, tz: str) -> dict[str, Any]:
    owned = _owned(unlocks)
    full = {z: sum(coverage(w.seconds)[z] >= 1.0 for w in washes) for z in ZONES}
    germs = [{"id": g, **info, "owned": g in owned, "zapped": full[info["zone"]]} for g, info in GERMS.items()]
    return {"slots": DEX_SLOTS, "owned": len(owned), "germs": germs, "boss": boss_status(washes, now, tz)}


def badges(washes: list[Wash], tz: str | None = None) -> list[dict[str, Any]]:
    """Badges earned so far. With ``tz`` the streak badge is included (days are counted in the family's timezone)."""
    perfect = sum(w.stars >= 5 for w in washes)
    thumbs = sum(coverage(w.seconds)["thumbs"] >= 1.0 for w in washes)
    rows = [{"id": "first_clean", "name": "First clean wash", "earned": any(w.finished for w in washes), "have": min(sum(w.finished for w in washes), 1), "need": 1},
            {"id": "perfect_10", "name": "Perfect 10", "earned": perfect >= 10, "have": min(perfect, 10), "need": 10},
            {"id": "thumb_pro", "name": "Thumb pro", "earned": thumbs >= 20, "have": min(thumbs, 20), "need": 20}]
    if tz is None:
        return [{"id": r["id"], "name": r["name"], "earned": r["earned"]} for r in rows]
    best = _runs(wash_days(washes, tz))[0]
    rows.insert(0, {"id": "streak_5", "name": f"{STREAK_BADGE_DAYS}-day streak", "earned": best >= STREAK_BADGE_DAYS,
                    "have": min(best, STREAK_BADGE_DAYS), "need": STREAK_BADGE_DAYS})
    return rows


# ---- parent analytics
DAY_BLOCKS = [("Morning", 5, 11), ("Midday", 11, 14), ("Afternoon", 14, 18), ("Evening", 18, 22)]  # local hours; the rest is "Night"
STEP_NAMES = {"palm_to_palm": "Palm to palm", "back_of_hand": "Back of hand", "interlaced_fingers": "Fingers interlaced",
              "backs_of_fingers": "Backs of fingers", "thumb_rubbing": "Thumbs", "fingertip_rubbing": "Fingertips", "wrist_rubbing": "Wrists"}


def _mean(xs: list[float]) -> float | None:
    return None if not xs else sum(xs) / len(xs)


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    ys, mid = sorted(xs), len(xs) // 2
    return ys[mid] if len(ys) % 2 else (ys[mid - 1] + ys[mid]) / 2


def insights(washes: list[Wash], now: datetime, tz: str, goal: int, days: int = 14, scrub_goal_s: float = 20.0) -> dict[str, Any]:
    """Numbers for the parent view over the last ``days`` local days (today included).

    Only washes where something was recognized are measured (``n``). Every figure is a plain mean, share or
    count over those washes, so a parent can check it against the wash list."""
    today = local_day(now, tz)
    first = today - timedelta(days=days - 1)
    span = _on(washes, tz, first, today)
    ws = [w for w in span if counts(w)]
    prev = [w for w in _on(washes, tz, first - timedelta(days=days), first - timedelta(days=1)) if counts(w)]
    n = len(ws)
    scores = [float(w.points) for w in ws]
    scrub = [sum(w.seconds.values()) for w in ws]
    covers = [coverage(w.seconds) for w in ws]
    per_day = []
    for i in range(days):
        d = first + timedelta(days=i)
        day = [w for w in ws if local_day(w.ended, tz) == d]
        m = _mean([float(w.points) for w in day])
        per_day.append({"date": d.isoformat(), "washes": len(day), "avg_score": None if m is None else round(m, 1)})
    zones = []
    for z in ZONES:
        vals = [c[z] for c in covers]
        m = _mean(vals)
        zones.append({"zone": z, "name": ZONE_NAMES[z], "coverage": None if m is None else round(m, 3),
                      "full": sum(v >= 1.0 for v in vals), "partial": sum(0 < v < 1.0 for v in vals), "missed": sum(v == 0 for v in vals), "n": n})
    techniques = []
    for t in STEPS:
        secs = [w.seconds.get(t, 0.0) for w in ws]
        m = _mean(secs)
        techniques.append({"technique": t, "name": STEP_NAMES[t], "mean_s": None if m is None else round(m, 2),
                           "done": sum(v >= STEP_MIN_S for v in secs), "n": n})
    blocks = []
    for name, lo, hi in [*DAY_BLOCKS, ("Night", 22, 29)]:
        hit = [w for w in ws if lo <= (w.ended.astimezone(ZoneInfo(tz)).hour + (24 if w.ended.astimezone(ZoneInfo(tz)).hour < 5 else 0)) < hi]
        m = _mean([float(w.points) for w in hit])
        blocks.append({"block": name, "from_hour": lo % 24, "to_hour": hi % 24, "washes": len(hit), "avg_score": None if m is None else round(m, 1)})
    mean, before = _mean(scores), _mean([float(w.points) for w in prev])
    scrub_mean = _mean(scrub)
    return {
        "days": days, "from": first.isoformat(), "to": today.isoformat(), "n": n, "not_recognized": len(span) - n, "goal": goal,
        "score": {"mean": None if mean is None else round(mean, 1), "median": _median(scores), "best": max(scores, default=None),
                  "previous_mean": None if before is None else round(before, 1), "previous_n": len(prev),
                  "change": None if mean is None or before is None else round(mean - before, 1)},
        "scrub": {"mean_s": None if scrub_mean is None else round(scrub_mean, 1), "goal_s": scrub_goal_s, "reached_goal": sum(s >= scrub_goal_s for s in scrub)},
        "finished": sum(w.finished for w in ws), "perfect": sum(all(v >= 1.0 for v in c.values()) for c in covers),
        "days_with_wash": sum(1 for d in per_day if d["washes"]), "days_goal_met": sum(1 for d in per_day if d["washes"] >= goal),
        "per_day": per_day, "zones": zones, "techniques": techniques, "by_time": blocks,
    }
