"""Parent app routes: the pipeline saves each wash (token), the web app reads progress and edits settings.

App routes under /api/v1/app/ have no login yet: the backend listens on this laptop only by default.
Real parent accounts come later (see docs/PARENT_APP.md).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from convergent.backend import models as m
from convergent.backend.auth import require_write
from convergent.backend.routes.api_v1 import API_VERSION, get_db
from convergent.backend.services import parent_app as A
from convergent.communication.protocol import make_message
from convergent.scoring import progression as P
from convergent.scoring.wash_session import WashRecord

router = APIRouter()


class SettingsIn(BaseModel):
    parent_name: str | None = Field(default=None, max_length=64)
    timezone: str | None = None
    daily_goal: int | None = Field(default=None, ge=1, le=12)
    routines: list[dict[str, Any]] | None = None
    toggles: dict[str, bool] | None = None
    onboarded: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("unknown timezone") from None
        return v


class ChildIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    buddy: str = Field(default="scrubby", max_length=32)
    age_band: Literal["3-4", "5-6", "7-8", "9+"] = "5-6"


class BuyIn(BaseModel):
    germ: str


def _now() -> datetime:
    return datetime.now(UTC)


def _settings_out(s: m.AppSettings) -> dict[str, Any]:
    return {"parent_name": s.parent_name, "timezone": s.timezone, "daily_goal": s.daily_goal, "routines": s.routines,
            "toggles": s.toggles, "onboarded": s.onboarded}


def _child_out(c: m.Child | None) -> dict[str, Any] | None:
    return None if c is None else {"name": c.name, "buddy": c.buddy, "age_band": c.age_band}


def _view(w: P.Wash, s: m.AppSettings) -> dict[str, Any]:
    local = w.ended.astimezone(ZoneInfo(s.timezone))
    return {**P.wash_view(w), "day": local.date().isoformat(), "time": local.strftime("%H:%M"), "label": P.label(local, s.routines)}


# ---- written by the pipeline
@router.post("/api/v1/washes", dependencies=[Depends(require_write)])
async def post_wash(rec: WashRecord, request: Request, response: Response, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    w, created = A.add_wash(db, rec)
    view = _view(w, A.settings(db))
    if created:
        response.status_code = status.HTTP_201_CREATED
        await request.app.state.hub.broadcast("observations", make_message("wash_saved", 0, wash=view))
    return {**view, "duplicate": not created}


# ---- read by the web app
@router.get("/api/v1/app/home")
def home(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    s = A.settings(db)
    h = P.home(A.washes(db), _now(), s.timezone, s.daily_goal)
    if h["latest"]:
        h["latest"] = _view(next(w for w in A.washes(db) if w.wash_id == h["latest"]["wash_id"]), s)
    return {**h, "parent_name": s.parent_name, "child": _child_out(A.child(db))}


@router.get("/api/v1/app/washes")
def list_washes(db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    s = A.settings(db)
    return [_view(w, s) for w in reversed(A.washes(db))]


@router.get("/api/v1/app/washes/{wash_id}")
def wash_detail(wash_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    row = A.wash_row(db, wash_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="wash not found")
    w = next(x for x in A.washes(db) if x.wash_id == wash_id)
    rec = row.record
    return {**_view(w, A.settings(db)), "seconds": rec["seconds"], "duration_s": rec["duration_s"], "soap_seen": rec.get("soap_seen"),
            "step_min_s": rec["score"]["step_min_s"], "total_min_s": rec["score"]["total_min_s"]}


@router.delete("/api/v1/app/washes")
def delete_washes(db: DbSession = Depends(get_db)) -> dict[str, int]:
    return {"deleted": A.delete_history(db)}


@router.get("/api/v1/app/progress")
def progress(period: Literal["day", "week", "month"] = "week", db: DbSession = Depends(get_db)) -> dict[str, Any]:
    s = A.settings(db)
    return P.progress(A.washes(db), _now(), s.timezone, s.daily_goal, period)


@router.get("/api/v1/app/rewards")
def rewards(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    return P.rewards(A.washes(db), A.unlocks(db), _now(), A.settings(db).timezone)


@router.post("/api/v1/app/rewards/buy")
def buy(body: BuyIn, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    try:
        A.buy(db, body.germ, _now())
    except A.Refused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return P.rewards(A.washes(db), A.unlocks(db), _now(), A.settings(db).timezone)


@router.get("/api/v1/app/germdex")
def germdex(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    return P.germdex(A.washes(db), A.unlocks(db), _now(), A.settings(db).timezone)


@router.get("/api/v1/app/settings")
def get_settings(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    return _settings_out(A.settings(db))


@router.put("/api/v1/app/settings")
def put_settings(body: SettingsIn, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    return _settings_out(A.update_settings(db, body.model_dump(exclude_none=True)))


@router.get("/api/v1/app/child")
def get_child(db: DbSession = Depends(get_db)) -> dict[str, Any] | None:
    return _child_out(A.child(db))


@router.put("/api/v1/app/child")
def put_child(body: ChildIn, db: DbSession = Depends(get_db)) -> dict[str, Any] | None:
    return _child_out(A.set_child(db, body.name, body.buddy, body.age_band))


@router.get("/api/v1/app/station")
def station(request: Request, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    devices = [{"device_id": d.device_id, "status": d.status, "last_seen": None if d.last_seen_utc is None else d.last_seen_utc.isoformat()}
               for d in db.scalars(select(m.Device).order_by(m.Device.device_id)).all()]
    last = max(A.washes(db), key=lambda w: w.ended, default=None)
    return {"backend": "ok", "version": API_VERSION, "devices": devices, "watching": request.app.state.hub.counts().get("observations", 0),
            "last_wash": None if last is None else last.ended.isoformat()}
