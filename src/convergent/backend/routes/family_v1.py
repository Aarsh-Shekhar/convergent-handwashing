"""Family routes of the parent app: children, family rewards, reward requests, high-fives, parent PIN, map.

Like the other /api/v1/app/ routes these have no account login: the backend listens on this laptop only by
default. Parent-only actions additionally need the parent PIN once one is set (header ``X-Parent-Token``
from ``POST /api/v1/app/parent/unlock``).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from convergent.backend import models as m
from convergent.backend.auth import require_write
from convergent.backend.routes.api_v1 import get_db
from convergent.backend.routes.app_v1 import ChildIn, _now, require_parent
from convergent.backend.services import family as F
from convergent.backend.services import parent_app as A
from convergent.scoring import progression as P

router = APIRouter(prefix="/api/v1/app")


class RewardIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    cost: int = Field(ge=1, le=100_000)
    icon: Literal["gift", "book", "movie", "park", "treat", "game"] = "gift"


class RewardEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    cost: int | None = Field(default=None, ge=1, le=100_000)
    icon: Literal["gift", "book", "movie", "park", "treat", "game"] | None = None
    enabled: bool | None = None


class RedeemIn(BaseModel):
    reward_id: int
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class DecideIn(BaseModel):
    approve: bool


class PinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=8, pattern=r"^[0-9]+$")


def _sessions(request: Request) -> F.ParentSessions:
    return request.app.state.parents


def _refuse(exc: Exception, code: int = status.HTTP_409_CONFLICT) -> HTTPException:
    return HTTPException(code, detail=str(exc))


def _child(c: m.Child, active: int | None) -> dict[str, Any]:
    return {"id": c.id, "name": c.name, "buddy": c.buddy, "age_band": c.age_band, "active": c.id == active}


def _reward(r: m.FamilyReward) -> dict[str, Any]:
    return {"id": r.id, "title": r.title, "cost": r.cost, "icon": r.icon, "enabled": r.enabled}


def _redemption(r: m.Redemption) -> dict[str, Any]:
    return {"id": r.id, "request_id": r.request_id, "reward_id": r.reward_id, "title": r.title, "cost": r.cost, "status": r.status,
            "requested": A._utc(r.requested_utc).isoformat(), "decided": None if r.decided_utc is None else A._utc(r.decided_utc).isoformat()}


def _rewards_page(db: DbSession) -> dict[str, Any]:
    kid = A.scope(db)
    bal = F.balance(db, kid)
    offered = [_reward(r) | {"affordable": r.enabled and bal >= r.cost, "to_go": max(r.cost - bal, 0)} for r in F.rewards(db)]
    nxt = next((r for r in offered if r["enabled"] and not r["affordable"]), None)
    s = A.settings(db)
    return {"points": bal, "earned": F.earned(db, kid), "held": F.held(db, kid), "rewards": offered,
            "next": None if nxt is None else {"id": nxt["id"], "title": nxt["title"], "to_go": nxt["to_go"]},
            "requests": [_redemption(r) for r in F.redemptions(db, kid)], "badges": P.badges(A.washes(db), s.timezone),
            "rule": {"per_wash": "score", "max_per_wash": 100, "rewarded_washes_per_day": s.daily_goal}}


# ---- children
@router.get("/children")
def list_children(db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    active = A.scope(db)
    return [_child(c, active) for c in A.children(db)]


@router.post("/children", status_code=status.HTTP_201_CREATED)
def add_child(body: ChildIn, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    c = A.add_child(db, body.name.strip(), body.buddy, body.age_band)
    return _child(c, A.scope(db))


@router.put("/children/{child_id}")
def edit_child(child_id: int, body: ChildIn, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    try:
        c = A.edit_child(db, child_id, body.name.strip(), body.buddy, body.age_band)
    except A.Refused as exc:
        raise _refuse(exc, status.HTTP_404_NOT_FOUND) from None
    return _child(c, A.scope(db))


@router.post("/children/{child_id}/activate")
def activate_child(child_id: int, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    """Pick whose washes the app shows. New washes from the station go to this child from now on."""
    try:
        c = A.activate_child(db, child_id)
    except A.Refused as exc:
        raise _refuse(exc, status.HTTP_404_NOT_FOUND) from None
    return _child(c, c.id)


@router.delete("/children/{child_id}", dependencies=[Depends(require_parent)])
def remove_child(child_id: int, db: DbSession = Depends(get_db)) -> dict[str, bool]:
    try:
        A.remove_child(db, child_id)
    except A.Refused as exc:
        raise _refuse(exc, status.HTTP_404_NOT_FOUND) from None
    return {"removed": True}


# ---- family rewards
@router.get("/family-rewards")
def family_rewards(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    return _rewards_page(db)


@router.post("/family-rewards", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_parent)])
def add_reward(body: RewardIn, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    return _reward(F.add_reward(db, body.title, body.cost, body.icon))


@router.put("/family-rewards/{reward_id}", dependencies=[Depends(require_parent)])
def edit_reward(reward_id: int, body: RewardEdit, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return _reward(F.edit_reward(db, reward_id, body.model_dump(exclude_none=True)))
    except A.Refused as exc:
        raise _refuse(exc, status.HTTP_404_NOT_FOUND) from None


@router.delete("/family-rewards/{reward_id}", dependencies=[Depends(require_parent)])
def remove_reward(reward_id: int, db: DbSession = Depends(get_db)) -> dict[str, bool]:
    try:
        F.remove_reward(db, reward_id)
    except A.Refused as exc:
        raise _refuse(exc, status.HTTP_404_NOT_FOUND) from None
    return {"removed": True}


@router.post("/redemptions")
def request_reward(body: RedeemIn, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    """The child asks for a reward. The points are held until a parent approves or declines."""
    try:
        row, created = F.request_reward(db, body.reward_id, body.request_id)
    except A.Refused as exc:
        raise _refuse(exc) from None
    return {**_rewards_page(db), "request": _redemption(row), "duplicate": not created}


@router.post("/redemptions/{redemption_id}/decide", dependencies=[Depends(require_parent)])
def decide(redemption_id: int, body: DecideIn, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    try:
        row = F.decide(db, redemption_id, body.approve)
    except A.Refused as exc:
        raise _refuse(exc) from None
    return {**_rewards_page(db), "request": _redemption(row)}


# ---- high-five
@router.post("/washes/{wash_id}/high-five")
def high_five(wash_id: str, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    """Save a parent's high-five on a wash. It lives in the app; nothing is sent to the station."""
    try:
        row, created = F.high_five(db, wash_id)
    except A.Refused as exc:
        raise _refuse(exc, status.HTTP_404_NOT_FOUND) from None
    return {"wash_id": wash_id, "high_fived": A._utc(row.created_utc).isoformat(), "duplicate": not created}


# ---- adventure map
@router.get("/adventure")
def adventure(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    s = A.settings(db)
    washes = A.washes(db)
    return {**P.adventure(washes), "streak": P.streak(washes, _now(), s.timezone), "boss": P.boss_status(washes, _now(), s.timezone)}


# ---- parent analytics and the sync log
@router.get("/insights")
def insights(days: int = 14, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    if days not in (7, 14, 30, 90):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="days must be 7, 14, 30 or 90")
    s = A.settings(db)
    return P.insights(A.washes(db), _now(), s.timezone, s.daily_goal, days)


@router.get("/sync")
def sync_log(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    """How the active child's washes reached the app: where each came from, when it happened and when it arrived."""
    rows = A.wash_rows(db)
    log = [{"wash_id": r.wash_id, "session_id": r.session_id, "source": r.source, "ended": A._utc(r.ended_utc).isoformat(),
            "received": A._utc(r.created_utc).isoformat(), "lag_s": round((A._utc(r.created_utc) - A._utc(r.ended_utc)).total_seconds(), 1),
            "points": r.points, "bytes": len(json.dumps(r.record, separators=(",", ":")))} for r in rows[:25]]
    newest = next((r for r in rows if r.source == "station"), rows[0] if rows else None)
    return {"total": len(rows), "from_station": sum(r.source == "station" for r in rows), "from_demo": sum(r.source == "demo" for r in rows),
            "log": log, "example": None if newest is None else {"wash_id": newest.wash_id, "source": newest.source, "record": newest.record}}


# ---- parent PIN
@router.get("/parent")
def parent_state(request: Request, db: DbSession = Depends(get_db), x_parent_token: str | None = Header(default=None)) -> dict[str, bool]:
    has_pin = bool(A.settings(db).parent_pin_hash)
    return {"pin_set": has_pin, "unlocked": not has_pin or _sessions(request).valid(x_parent_token)}


@router.post("/parent/unlock")
def unlock(body: PinIn, request: Request, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    sessions = _sessions(request)
    if not sessions.note_try():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="too many tries, wait a minute", headers={"Retry-After": "60"})
    if not F.pin_ok(db, body.pin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="wrong PIN")
    return {"token": sessions.open(), "expires_in_s": F.UNLOCK_S}


@router.post("/parent/lock")
def lock(request: Request, x_parent_token: str | None = Header(default=None)) -> dict[str, bool]:
    _sessions(request).close(x_parent_token)
    return {"locked": True}


@router.put("/parent/pin", dependencies=[Depends(require_parent)])
def set_pin(body: PinIn, request: Request, db: DbSession = Depends(get_db)) -> dict[str, Any]:
    """Set or change the PIN (changing it needs the old one unlocked). Returns a fresh unlock token."""
    F.set_pin(db, body.pin)
    _sessions(request).close_all()
    return {"pin_set": True, "token": _sessions(request).open(), "expires_in_s": F.UNLOCK_S}


@router.delete("/parent/pin", dependencies=[Depends(require_parent)])
def clear_pin(request: Request, db: DbSession = Depends(get_db)) -> dict[str, bool]:
    F.clear_pin(db)
    _sessions(request).close_all()
    return {"pin_set": False}


# ---- demo family
@router.post("/demo/reset", dependencies=[Depends(require_write)])
def demo_reset(request: Request, db: DbSession = Depends(get_db)) -> dict[str, bool]:
    """Empty the parent app's tables so the demo family can be seeded again. Refused unless the backend runs
    with CONVERGENT_DEMO_MODE=true, so it can never clear a real family's data."""
    if not request.app.state.settings.demo_mode:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="not a demo backend")
    F.reset_app_data(db)
    _sessions(request).close_all()
    return {"reset": True}
