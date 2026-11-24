"""Parent app storage: washes saved one by one, settings, the child, germ unlocks.

The numbers shown in the app are worked out in ``scoring/progression.py``; this module only loads and saves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
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


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite hands back naive datetimes


def settings(db: DbSession) -> m.AppSettings:
    row = db.get(m.AppSettings, 1)
    if row is None:
        row = m.AppSettings(id=1, parent_name="", timezone="America/Chicago", daily_goal=6, routines=DEFAULT_ROUTINES,
                            toggles=DEFAULT_TOGGLES, onboarded=False, updated_utc=utc_now())
        db.add(row)
        db.commit()
    return row


def update_settings(db: DbSession, changes: dict[str, Any]) -> m.AppSettings:
    row = settings(db)
    for k, v in changes.items():
        setattr(row, k, v)
    row.updated_utc = utc_now()
    db.commit()
    return row


def child(db: DbSession) -> m.Child | None:
    return db.scalars(select(m.Child).order_by(m.Child.id)).first()


def set_child(db: DbSession, name: str, buddy: str, age_band: str) -> m.Child:
    row = child(db)
    if row is None:
        row = m.Child(name=name, buddy=buddy, age_band=age_band, created_utc=utc_now())
        db.add(row)
    else:
        row.name, row.buddy, row.age_band = name, buddy, age_band
    db.commit()
    return row


def _wash(r: m.WashRow) -> P.Wash:
    return P.Wash(wash_id=r.wash_id, ended=_utc(r.ended_utc), seconds=r.seconds, stars=r.stars, points=r.points,
                  finished=r.finished, steps_done=r.steps_done, zaps=r.zaps)


def washes(db: DbSession) -> list[P.Wash]:
    return [_wash(r) for r in db.scalars(select(m.WashRow).order_by(m.WashRow.ended_utc)).all()]


def wash_row(db: DbSession, wash_id: str) -> m.WashRow | None:
    return db.get(m.WashRow, wash_id)


def unlocks(db: DbSession) -> list[dict[str, Any]]:
    return [{"germ": u.germ, "spent": u.spent, "how": u.how} for u in db.scalars(select(m.GermUnlock)).all()]


def add_wash(db: DbSession, rec: WashRecord) -> tuple[P.Wash, bool]:
    """Save a wash once (same wash_id again changes nothing). Works out its zaps and a boss win when it arrives."""
    old = db.get(m.WashRow, rec.wash_id)
    if old is not None:
        return _wash(old), False
    s = settings(db)
    ended = datetime.fromisoformat(rec.ended_utc.replace("Z", "+00:00"))
    w = P.Wash(wash_id=rec.wash_id, ended=ended, seconds=rec.seconds, stars=rec.score.stars, points=rec.score.points,
               finished=rec.score.finished, steps_done=rec.score.steps_done)
    before = [e for e in washes(db) if e.ended <= ended]
    w.zaps = P.zaps_for(w, before, s.timezone, s.daily_goal)
    kid = child(db)
    db.add(m.WashRow(wash_id=w.wash_id, child_id=None if kid is None else kid.id, session_id=rec.session_id, ended_utc=ended,
                     stars=w.stars, points=w.points, finished=w.finished, steps_done=w.steps_done, zaps=w.zaps,
                     seconds=dict(rec.seconds), record=rec.model_dump(mode="json"), created_utc=utc_now()))
    db.commit()
    boss = P.boss_status(washes(db), ended, s.timezone)
    if boss["won"] and db.get(m.GermUnlock, boss["germ"]) is None:
        db.add(m.GermUnlock(germ=boss["germ"], spent=0, how="boss", created_utc=utc_now()))
        db.commit()
    return w, True


def buy(db: DbSession, germ: str, now: datetime) -> None:
    info = P.GERMS.get(germ)
    if info is None:
        raise Refused("unknown germ")
    if germ == P.STARTER or db.get(m.GermUnlock, germ) is not None:
        raise Refused("already owned")
    if info["price"] is None:
        raise Refused("this germ is won, not bought")
    if P.rewards(washes(db), unlocks(db), now, settings(db).timezone)["zaps"] < info["price"]:
        raise Refused("not enough zaps")
    db.add(m.GermUnlock(germ=germ, spent=info["price"], how="bought", created_utc=utc_now()))
    db.commit()


def delete_history(db: DbSession) -> int:
    """Delete every wash and the germs bought or won with them. Settings and the child stay."""
    n = len(washes(db))
    db.execute(delete(m.WashRow))
    db.execute(delete(m.GermUnlock))
    db.commit()
    return n
