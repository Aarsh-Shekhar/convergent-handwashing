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


def zaps_for(w: Wash, earlier: list[Wash], tz: str, goal: int) -> int:
    """Zaps a new wash earns: 1 per step done, plus a bonus if finished. Nothing once today's goal is already met."""
    day = local_day(w.ended, tz)
    if sum(counts(e) for e in _on(earlier, tz, day, day)) >= goal:
        return 0
    return w.steps_done + (FINISH_BONUS if w.finished else 0)


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
            "steps_done": w.steps_done, "zaps": w.zaps, "seconds_total": round(sum(w.seconds.values()), 1),
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
    return {"today": sum(counts(w) for w in _on(washes, tz, today, today)), "goal": goal, "avg_score": _avg(week),
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
    return {STARTER} | {u["germ"] for u in unlocks}


def rewards(washes: list[Wash], unlocks: list[dict[str, Any]], now: datetime, tz: str) -> dict[str, Any]:
    balance = sum(w.zaps for w in washes) - sum(u.get("spent", 0) for u in unlocks)
    owned = _owned(unlocks)
    germs = [{"id": g, **info, "owned": g in owned, "can_buy": g not in owned and info["price"] is not None and balance >= info["price"]}
             for g, info in GERMS.items()]
    return {"zaps": balance, "germs": germs, "badges": badges(washes), "boss": boss_status(washes, now, tz)}


def germdex(washes: list[Wash], unlocks: list[dict[str, Any]], now: datetime, tz: str) -> dict[str, Any]:
    owned = _owned(unlocks)
    full = {z: sum(coverage(w.seconds)[z] >= 1.0 for w in washes) for z in ZONES}
    germs = [{"id": g, **info, "owned": g in owned, "zapped": full[info["zone"]]} for g, info in GERMS.items()]
    return {"slots": DEX_SLOTS, "owned": len(owned), "germs": germs, "boss": boss_status(washes, now, tz)}


def badges(washes: list[Wash]) -> list[dict[str, Any]]:
    earned = {"first_clean": any(w.finished for w in washes),
              "perfect_10": sum(w.stars >= 5 for w in washes) >= 10,
              "thumb_pro": sum(coverage(w.seconds)["thumbs"] >= 1.0 for w in washes) >= 20}
    return [{"id": b, "name": name, "earned": earned[b]} for b, name in BADGES]
