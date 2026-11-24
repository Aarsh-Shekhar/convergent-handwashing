"""Progress rules of the parent app (scoring/progression.py): zones, zaps, days, trouble spots, boss, badges."""

from datetime import UTC, date, datetime, timedelta

from convergent.scoring import progression as P

TZ = "America/Chicago"
ALL7 = {t: 4.0 for t in P.STEPS}
NONE = dict.fromkeys(P.STEPS, 0.0)


def wash(ended: datetime, seconds: dict[str, float] | None = None, stars: int = 3, points: int = 80, zaps: int = 0, wid: str = "") -> P.Wash:
    s = {**NONE, **(seconds or {})}
    done = sum(v >= 3.0 for v in s.values())
    return P.Wash(wash_id=wid or f"w{ended.timestamp()}", ended=ended, seconds=s, stars=stars, points=points,
                  finished=stars >= 3, steps_done=done, zaps=zaps)


def at(day: int, hour: int = 18) -> datetime:
    """A time in November 2026, given in UTC. 18:00 UTC is 12:00 in Chicago."""
    return datetime(2026, 11, day, hour, tzinfo=UTC)


# ---- zones
def test_zone_coverage_caps_at_full_and_backs_is_the_mean_of_its_two_steps():
    cov = P.coverage({**NONE, "palm_to_palm": 6.0, "back_of_hand": 3.0, "backs_of_fingers": 0.0, "thumb_rubbing": 1.5})
    assert cov["palms"] == 1.0
    assert cov["backs"] == 0.5
    assert cov["thumbs"] == 0.5
    assert cov["wrists"] == 0.0


def test_missed_zones_are_the_ones_under_full():
    assert P.missed({**ALL7, "thumb_rubbing": 2.9}) == ["thumbs"]
    assert P.missed(ALL7) == []


# ---- zaps
def test_zaps_are_steps_done_plus_a_bonus_for_a_finished_wash():
    finished = wash(at(3), {**NONE, **{t: 4.0 for t in P.STEPS[:5]}}, stars=3)
    assert P.zaps_for(finished, [], TZ, goal=6) == 5 + P.FINISH_BONUS
    half = wash(at(3), {"palm_to_palm": 4.0, "back_of_hand": 4.0}, stars=1)
    assert P.zaps_for(half, [], TZ, goal=6) == 2


def test_no_zaps_once_the_daily_goal_is_reached():
    earlier = [wash(at(3, 14 + i)) for i in range(2)]
    w = wash(at(3, 20), ALL7, stars=5)
    assert P.zaps_for(w, earlier, TZ, goal=2) == 0
    assert P.zaps_for(w, earlier, TZ, goal=3) == 7 + P.FINISH_BONUS


def test_washes_with_no_stars_do_not_use_up_the_daily_goal():
    earlier = [wash(at(3, 14), stars=0), wash(at(3, 15), stars=0)]
    assert P.zaps_for(wash(at(3, 20), ALL7, stars=5), earlier, TZ, goal=1) == 7 + P.FINISH_BONUS


def test_the_daily_cap_resets_at_local_midnight_not_utc_midnight():
    # 04:00 UTC on Nov 4 is 22:00 on Nov 3 in Chicago: the same local day as the earlier wash
    earlier = [wash(at(3, 20))]
    assert P.zaps_for(wash(at(4, 4), ALL7, stars=5), earlier, TZ, goal=1) == 0
    # 07:00 UTC on Nov 4 is 01:00 on Nov 4 in Chicago: a new day
    assert P.zaps_for(wash(at(4, 7), ALL7, stars=5), earlier, TZ, goal=1) == 7 + P.FINISH_BONUS


# ---- days and weeks
def test_local_day_and_monday_week_start():
    assert P.local_day(at(4, 4), TZ) == date(2026, 11, 3)
    assert P.week_start(date(2026, 11, 22)) == date(2026, 11, 16)  # a Sunday belongs to the week starting Monday 16th


# ---- home
def test_home_counts_today_against_the_goal_and_clean_washes_never_reset():
    now = at(10, 23)
    washes = [wash(at(1), ALL7, stars=5, points=100), wash(at(10, 15), stars=1, points=30), wash(at(10, 16), stars=3, points=80),
              wash(at(10, 17), stars=0, points=0)]
    h = P.home(washes, now, TZ, goal=6)
    assert h["today"] == 2           # the 0-star wash does not count
    assert h["goal"] == 6
    assert h["clean_washes"] == 2    # finished washes, all time
    assert h["latest"]["wash_id"] == washes[-1].wash_id
    # no washes today: the clean count stays where it was
    assert P.home(washes, at(20), TZ, goal=6)["clean_washes"] == 2


def test_tip_names_the_most_missed_zone_only_after_three_washes_this_week():
    thumbs_missed = {**ALL7, "thumb_rubbing": 0.0}
    two = [wash(at(10, 14 + i), thumbs_missed) for i in range(2)]
    assert P.home(two, at(10, 23), TZ, 6)["tip"] is None
    three = [*two, wash(at(10, 17), {**ALL7, "wrist_rubbing": 0.0})]
    assert P.home(three, at(10, 23), TZ, 6)["tip"]["zone"] == "thumbs"


# ---- progress
def test_week_progress_washes_per_day_average_and_trouble_spots():
    week = [wash(at(16), {**ALL7, "thumb_rubbing": 0.0}, points=60), wash(at(16, 20), ALL7, points=100),
            wash(at(18), {**ALL7, "thumb_rubbing": 1.0, "wrist_rubbing": 0.0}, points=80)]
    last_week = [wash(at(10), points=50)]
    p = P.progress([*last_week, *week], at(19, 23), TZ, goal=6, period="week")
    assert p["per_day"][:4] == [2, 0, 1, 0]          # Mon 16 .. Thu 19
    assert len(p["per_day"]) == 7
    assert p["washes"] == 3
    assert p["avg_score"] == 80
    assert p["avg_change"] == 30                     # 80 this week vs 50 last week
    spots = {s["zone"]: s["missed"] for s in p["trouble_spots"]}
    assert spots["thumbs"] == round(2 / 3, 3)
    assert spots["wrists"] == round(1 / 3, 3)
    assert "palms" not in spots                      # never missed: not a trouble spot
    assert [s["zone"] for s in p["trouble_spots"]] == ["thumbs", "wrists"]


def test_month_progress_has_one_ring_per_day():
    p = P.progress([wash(at(3)), wash(at(3, 20)), wash(at(17))], at(20), TZ, goal=4, period="month")
    assert len(p["days"]) == 30
    assert p["days"][2] == {"day": 3, "washes": 2, "fill": 0.5}
    assert p["days"][16]["washes"] == 1


def test_day_progress_shows_mean_zone_coverage_today():
    today = [wash(at(10, 15), ALL7), wash(at(10, 16), {**ALL7, "thumb_rubbing": 0.0})]
    p = P.progress(today, at(10, 23), TZ, goal=6, period="day")
    assert p["washes"] == 2
    assert p["zones"]["thumbs"] == 0.5
    assert p["zones"]["palms"] == 1.0


# ---- rewards, boss, badges
def test_zap_balance_is_earned_minus_spent_and_gunky_is_owned_from_the_start():
    r = P.rewards([wash(at(3), zaps=40), wash(at(4), zaps=30)], [{"germ": "sneezel", "spent": 50}], at(5), TZ)
    assert r["zaps"] == 20
    owned = {g["id"] for g in r["germs"] if g["owned"]}
    assert owned == {"gunky", "sneezel"}
    prickle = next(g for g in r["germs"] if g["id"] == "prickle")
    assert prickle["can_buy"] is False               # costs 50, balance 20


def test_boss_of_the_week_is_won_by_washing_its_zone_fully_enough_times():
    now = at(18)
    boss = P.boss_of_week(P.local_day(now, TZ))
    zone = P.GERMS[boss]["zone"]
    step = P.ZONES[zone][0]
    hits = [wash(at(16, 14) + timedelta(minutes=i), {**NONE, **{t: 4.0 for t in P.ZONES[zone]}}) for i in range(P.BOSS_TARGET - 1)]
    assert P.boss_status(hits, now, TZ)["won"] is False
    last_week = [wash(at(10), {step: 4.0} | {t: 4.0 for t in P.ZONES[zone]})]
    assert P.boss_status([*last_week, *hits], now, TZ)["done"] == P.BOSS_TARGET - 1  # last week's wash does not count
    st = P.boss_status([*hits, wash(at(17), {**NONE, **{t: 4.0 for t in P.ZONES[zone]}})], now, TZ)
    assert st == {"germ": boss, "zone": zone, "done": P.BOSS_TARGET, "target": P.BOSS_TARGET, "won": True}


def test_badges():
    five = [wash(at(1, 10 + i), ALL7, stars=5) for i in range(10)]
    b = {x["id"]: x["earned"] for x in P.badges(five)}
    assert b == {"first_clean": True, "perfect_10": True, "thumb_pro": False}
    assert {x["id"]: x["earned"] for x in P.badges(five[:9])}["perfect_10"] is False
    assert {x["id"]: x["earned"] for x in P.badges([])}["first_clean"] is False
    thumbs = [wash(at(2, 10) + timedelta(minutes=i), {"thumb_rubbing": 3.0}, stars=1) for i in range(20)]
    assert {x["id"]: x["earned"] for x in P.badges(thumbs)}["thumb_pro"] is True


def test_germdex_counts_how_often_each_germ_zone_was_fully_washed():
    d = P.germdex([wash(at(3), ALL7), wash(at(4), {**ALL7, "palm_to_palm": 0.0})], [], at(5), TZ)
    by = {g["id"]: g for g in d["germs"]}
    assert by["gunky"]["zapped"] == 1 and by["gunky"]["owned"] is True   # Gunky lives on palms
    assert by["sneezel"]["zapped"] == 2 and by["sneezel"]["owned"] is False
    assert d["slots"] == 12 and d["owned"] == 1


def test_a_wash_is_named_after_the_routine_closest_in_time():
    routines = [{"name": "Before breakfast", "time": "07:30", "on": True}, {"name": "Before lunch", "time": "12:00", "on": True},
                {"name": "Before dinner", "time": "18:00", "on": False}]
    assert P.label(datetime(2026, 11, 3, 12, 40), routines) == "Before lunch"
    assert P.label(datetime(2026, 11, 3, 15, 0), routines) == "Wash"           # nothing within an hour
    assert P.label(datetime(2026, 11, 3, 18, 0), routines) == "Wash"           # routine switched off
