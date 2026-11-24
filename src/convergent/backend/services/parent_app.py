"""Parent app storage: washes saved one by one, settings, the children, germ unlocks.

The numbers shown in the app are worked out in ``scoring/progression.py``; this module only loads and saves.

Everything a page shows belongs to the *active child*: the one the parent picked in the app. The station
never recognizes a child, so a new wash goes to whoever is active when it arrives. Before the first child is
added, washes are kept unassigned and handed to that first child when it is created.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from convergent.backend import models as m
from convergent.common.timestamps import utc_now
from convergent.scoring import progression as P
from convergent.scoring.wash_session import WashRecord

DEFAULT_ROUTINES = [  # from the design's Routines screen
    {"id": "after_bathroom", "name": "After bathroom", "detail": "Auto, camera detects", "time": None, "on": True},
    {"id": "before_breakfast", "name": "Before breakfast", "detail": "Daily", "time": "07:30", "on": True},
    {"id": "before_lunch", "name": "Before lunch", "detail": "School days", "time": "12:00", "on": True},
    {"id": "after_outside", "name": "After playing outside", "detail": "Manual start", "time": None, "on": False},
    {"id": "before_dinner", "name": "Before dinner", "detail": "Daily", "time": "18:00", "on": True},
]
DEFAULT_TOGGLES = {"station_reminder": True, "skipped_alert": True, "sounds": True}


class Refused(ValueError):
    pass


class Conflict(ValueError):
    """The same wash_id arrived again with different contents."""


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite hands back naive datetimes


def settings(db: DbSession) -> m.AppSettings:
    row = db.get(m.AppSettings, 1)
    if row is None:
        row = m.AppSettings(id=1, parent_name="", timezone="America/Chicago", daily_goal=6, routines=DEFAULT_ROUTINES,
                            toggles=DEFAULT_TOGGLES, onboarded=False, updated_utc=utc_now())
        db.add(row)
        try:
            db.commit()
        except IntegrityError:  # two first requests at once: the other one created it
            db.rollback()
            row = db.get(m.AppSettings, 1)
    return row  # type: ignore[return-value]


def update_settings(db: DbSession, changes: dict[str, Any]) -> m.AppSettings:
    row = settings(db)
    for k, v in changes.items():
        setattr(row, k, v)
    row.updated_utc = utc_now()
    db.commit()
    return row


def children(db: DbSession) -> list[m.Child]:
    return list(db.scalars(select(m.Child).order_by(m.Child.id)).all())


def child(db: DbSession) -> m.Child | None:
    """The active child: the one the parent picked, else the first one."""
    kids = children(db)
    active = settings(db).active_child_id
    return next((k for k in kids if k.id == active), kids[0] if kids else None)


def scope(db: DbSession) -> int | None:
    kid = child(db)
    return None if kid is None else kid.id


def _owned_by(col: Any, child_id: int | None) -> Any:
    return col.is_(None) if child_id is None else col == child_id


def add_child(db: DbSession, name: str, buddy: str, age_band: str) -> m.Child:
    """Add a child and make it the active one. The first child takes over anything saved before it existed."""
    first = not children(db)
    row = m.Child(name=name, buddy=buddy, age_band=age_band, created_utc=utc_now())
    db.add(row)
    db.flush()
    if first:
        for table in (m.WashRow, m.GermUnlock, m.Redemption):
            db.execute(update(table).where(table.child_id.is_(None)).values(child_id=row.id))
    settings(db).active_child_id = row.id
    db.commit()
    return row


def edit_child(db: DbSession, child_id: int, name: str, buddy: str, age_band: str) -> m.Child:
    row = db.get(m.Child, child_id)
    if row is None:
        raise Refused("unknown child")
    row.name, row.buddy, row.age_band = name, buddy, age_band
    db.commit()
    return row


def activate_child(db: DbSession, child_id: int) -> m.Child:
    row = db.get(m.Child, child_id)
    if row is None:
        raise Refused("unknown child")
    settings(db).active_child_id = child_id
    db.commit()
    return row


def remove_child(db: DbSession, child_id: int) -> None:
    """Remove a child with their washes, germs and reward requests (nothing of theirs is kept)."""
    row = db.get(m.Child, child_id)
    if row is None:
        raise Refused("unknown child")
    db.execute(delete(m.WashRow).where(m.WashRow.child_id == child_id))
    db.delete(row)  # germs and reward requests go with the child (ON DELETE CASCADE)
    s = settings(db)
    if s.active_child_id == child_id:
        s.active_child_id = None
    db.commit()


def set_child(db: DbSession, name: str, buddy: str, age_band: str) -> m.Child:
    """Create the first child, or rename the active one."""
    row = child(db)
    return add_child(db, name, buddy, age_band) if row is None else edit_child(db, row.id, name, buddy, age_band)


def _wash(r: m.WashRow) -> P.Wash:
    return P.Wash(wash_id=r.wash_id, ended=_utc(r.ended_utc), seconds=r.seconds, stars=r.stars, points=r.points,
                  finished=r.finished, steps_done=r.steps_done, zaps=r.zaps, reward_points=r.reward_points)


def washes(db: DbSession) -> list[P.Wash]:
    """The active child's washes, oldest first."""
    q = select(m.WashRow).where(_owned_by(m.WashRow.child_id, scope(db))).order_by(m.WashRow.ended_utc)
    return [_wash(r) for r in db.scalars(q).all()]


def wash_row(db: DbSession, wash_id: str) -> m.WashRow | None:
    return db.get(m.WashRow, wash_id)


def wash_in_scope(db: DbSession, wash_id: str) -> m.WashRow | None:
    row = db.get(m.WashRow, wash_id)
    return row if row is not None and row.child_id == scope(db) else None


def _unlock(db: DbSession, germ: str) -> m.GermUnlock | None:
    return db.scalars(select(m.GermUnlock).where(_owned_by(m.GermUnlock.child_id, scope(db)), m.GermUnlock.germ == germ)).first()


def unlocks(db: DbSession) -> list[dict[str, Any]]:
    q = select(m.GermUnlock).where(_owned_by(m.GermUnlock.child_id, scope(db)))
    return [{"germ": u.germ, "spent": u.spent, "how": u.how} for u in db.scalars(q).all()]


MAX_WASH_S = 3600.0        # a "wash" longer than an hour is a stuck camera, not a wash
CLOCK_SLACK_S = 600.0      # how far in the future a station clock may be


def check_record(rec: WashRecord, now: datetime) -> tuple[datetime, datetime]:
    """Refuse a wash record that cannot be true. Returns (started, ended) as aware UTC datetimes."""
    if rec.schema_version != "wash-record-v1":
        raise Refused(f"unsupported schema_version {rec.schema_version!r}")
    try:
        started = _utc(datetime.fromisoformat(rec.started_utc.replace("Z", "+00:00")))
        ended = _utc(datetime.fromisoformat(rec.ended_utc.replace("Z", "+00:00")))
    except ValueError:
        raise Refused("started_utc and ended_utc must be ISO 8601 timestamps") from None
    if ended < started:
        raise Refused("ended_utc is before started_utc")
    if not 0 <= rec.duration_s <= MAX_WASH_S:
        raise Refused("duration_s is out of range")
    if abs((ended - started).total_seconds() - rec.duration_s) > 5.0:
        raise Refused("duration_s does not match started_utc and ended_utc")
    if (ended - now).total_seconds() > CLOCK_SLACK_S:
        raise Refused("ended_utc is in the future")
    unknown = set(rec.seconds) - set(P.STEPS)
    if unknown:
        raise Refused(f"unknown wash step {sorted(unknown)[0]!r}")
    if any(v < 0 or v > rec.duration_s + 5.0 for v in rec.seconds.values()):
        raise Refused("a step's seconds are negative or longer than the wash")
    if not (0 <= rec.score.points <= 100 and 0 <= rec.score.stars <= 5 and 0 <= rec.score.steps_done <= len(P.STEPS)):
        raise Refused("score is out of range")
    return started, ended


def add_wash(db: DbSession, rec: WashRecord, now: datetime | None = None) -> tuple[P.Wash, bool]:
    """Save a wash once and work out what it earned (zaps, points, a boss win) when it arrives.

    The same record again changes nothing; the same wash_id with other contents is a :class:`Conflict`."""
    _, ended = check_record(rec, now or utc_now())
    body = rec.model_dump(mode="json")
    old = db.get(m.WashRow, rec.wash_id)
    if old is not None:
        if old.record != body:
            raise Conflict(f"wash {rec.wash_id} was already saved with different contents")
        return _wash(old), False
    s = settings(db)
    w = P.Wash(wash_id=rec.wash_id, ended=ended, seconds=rec.seconds, stars=rec.score.stars, points=rec.score.points,
               finished=rec.score.finished, steps_done=rec.score.steps_done)
    before = [e for e in washes(db) if e.ended <= ended]
    w.zaps = P.zaps_for(w, before, s.timezone, s.daily_goal)
    w.reward_points = P.points_for(w, before, s.timezone, s.daily_goal)
    kid = scope(db)
    source = "demo" if rec.quality.get("demo") or rec.wash_id.startswith("demo-") else "station"
    db.add(m.WashRow(wash_id=w.wash_id, child_id=kid, session_id=rec.session_id, ended_utc=ended,
                     stars=w.stars, points=w.points, finished=w.finished, steps_done=w.steps_done, zaps=w.zaps,
                     reward_points=w.reward_points, source=source, seconds=dict(rec.seconds), record=body, created_utc=utc_now()))
    try:
        db.commit()
    except IntegrityError:  # the same wash arrived twice at once: the other request saved it
        db.rollback()
        return _wash(db.get(m.WashRow, rec.wash_id)), False  # type: ignore[arg-type]
    boss = P.boss_status(washes(db), ended, s.timezone)
    if boss["won"] and _unlock(db, boss["germ"]) is None:
        db.add(m.GermUnlock(child_id=kid, germ=boss["germ"], spent=0, how="boss", created_utc=utc_now()))
        db.commit()
    return w, True


def buy(db: DbSession, germ: str, now: datetime) -> None:
    info = P.GERMS.get(germ)
    if info is None:
        raise Refused("unknown germ")
    if germ == P.STARTER or _unlock(db, germ) is not None:
        raise Refused("already owned")
    if info["price"] is None:
        raise Refused("this germ is won, not bought")
    if P.rewards(washes(db), unlocks(db), now, settings(db).timezone)["zaps"] < info["price"]:
        raise Refused("not enough zaps")
    db.add(m.GermUnlock(child_id=scope(db), germ=germ, spent=info["price"], how="bought", created_utc=utc_now()))
    db.commit()


def delete_history(db: DbSession) -> int:
    """Delete the active child's washes and everything earned with them: germs, points and reward requests.

    Points and zaps are sums over washes, so they return to zero. Settings, rewards and the child stay."""
    kid = scope(db)
    n = len(washes(db))
    db.execute(delete(m.WashRow).where(_owned_by(m.WashRow.child_id, kid)))  # high-fives go with their wash
    db.execute(delete(m.GermUnlock).where(_owned_by(m.GermUnlock.child_id, kid)))
    db.execute(delete(m.Redemption).where(_owned_by(m.Redemption.child_id, kid)))
    db.commit()
    return n
