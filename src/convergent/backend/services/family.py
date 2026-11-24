"""Family rewards, reward requests, high-fives and the parent PIN.

Points are never stored as a running total. A child's balance is always worked out from the washes
(``washes.reward_points``, fixed when each wash arrived) minus the reward requests that are waiting or
approved, so it cannot drift and deleting history resets it cleanly.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from convergent.backend import models as m
from convergent.backend.services import parent_app as A
from convergent.backend.services.parent_app import Refused
from convergent.common.timestamps import utc_now

DEFAULT_REWARDS = [("Extra bedtime story", 300, "book"), ("Pick Friday movie", 800, "movie"), ("Trip to the park", 1500, "park")]
ICONS = ("gift", "book", "movie", "park", "treat", "game")
HOLDING = ("requested", "approved")  # request states that hold points

# One writer at a time for anything that checks a balance and then spends it. SQLite already allows a
# single writer; the lock makes the check and the insert one step for the whole process.
_spend_lock = threading.Lock()


class NotAllowed(PermissionError):
    pass


# ---- points
def earned(db: DbSession, child_id: int | None) -> int:
    q = select(func.coalesce(func.sum(m.WashRow.reward_points), 0)).where(A._owned_by(m.WashRow.child_id, child_id))
    return int(db.scalar(q) or 0)


def held(db: DbSession, child_id: int | None) -> int:
    q = select(func.coalesce(func.sum(m.Redemption.cost), 0)).where(A._owned_by(m.Redemption.child_id, child_id),
                                                                     m.Redemption.status.in_(HOLDING))
    return int(db.scalar(q) or 0)


def balance(db: DbSession, child_id: int | None) -> int:
    return earned(db, child_id) - held(db, child_id)


# ---- rewards the parent offers
def rewards(db: DbSession) -> list[m.FamilyReward]:
    return list(db.scalars(select(m.FamilyReward).order_by(m.FamilyReward.cost, m.FamilyReward.id)).all())


def seed_default_rewards(db: DbSession) -> None:
    """The three example rewards from the design, for a family that has none yet."""
    if rewards(db):
        return
    for title, cost, icon in DEFAULT_REWARDS:
        db.add(m.FamilyReward(title=title, cost=cost, icon=icon, enabled=True, created_utc=utc_now()))
    db.commit()


def add_reward(db: DbSession, title: str, cost: int, icon: str) -> m.FamilyReward:
    row = m.FamilyReward(title=title.strip(), cost=cost, icon=icon, enabled=True, created_utc=utc_now())
    db.add(row)
    db.commit()
    return row


def edit_reward(db: DbSession, reward_id: int, changes: dict[str, Any]) -> m.FamilyReward:
    row = db.get(m.FamilyReward, reward_id)
    if row is None:
        raise Refused("unknown reward")
    for k, v in changes.items():
        setattr(row, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return row


def remove_reward(db: DbSession, reward_id: int) -> None:
    row = db.get(m.FamilyReward, reward_id)
    if row is None:
        raise Refused("unknown reward")
    db.delete(row)  # earlier requests keep their own title and cost
    db.commit()


# ---- reward requests
def redemptions(db: DbSession, child_id: int | None) -> list[m.Redemption]:
    q = select(m.Redemption).where(A._owned_by(m.Redemption.child_id, child_id)).order_by(m.Redemption.requested_utc.desc(), m.Redemption.id.desc())
    return list(db.scalars(q).all())


def request_reward(db: DbSession, reward_id: int, request_id: str) -> tuple[m.Redemption, bool]:
    """The active child asks for a reward. Holds the points at once so they cannot be spent twice.

    The same ``request_id`` again returns the first request unchanged."""
    with _spend_lock:
        again = db.scalars(select(m.Redemption).where(m.Redemption.request_id == request_id)).first()
        if again is not None:
            return again, False
        reward = db.get(m.FamilyReward, reward_id)
        if reward is None or not reward.enabled:
            raise Refused("this reward is not available")
        kid = A.scope(db)
        if balance(db, kid) < reward.cost:
            raise Refused("not enough points yet")
        row = m.Redemption(request_id=request_id, child_id=kid, reward_id=reward.id, title=reward.title, cost=reward.cost,
                           status="requested", requested_utc=utc_now())
        db.add(row)
        try:
            db.commit()
        except IntegrityError:  # the same request_id from another worker
            db.rollback()
            return db.scalars(select(m.Redemption).where(m.Redemption.request_id == request_id)).one(), False
        return row, True


def decide(db: DbSession, redemption_id: int, approve: bool) -> m.Redemption:
    """A parent approves (points stay spent) or declines (points come back). A decision is made once."""
    with _spend_lock:
        row = db.get(m.Redemption, redemption_id)
        if row is None:
            raise Refused("unknown request")
        want = "approved" if approve else "declined"
        if row.status == want:
            return row
        if row.status != "requested":
            raise Refused(f"this request was already {row.status}")
        row.status, row.decided_utc = want, utc_now()
        db.commit()
        return row


# ---- high-fives
def high_five(db: DbSession, wash_id: str) -> tuple[m.Encouragement, bool]:
    if A.wash_in_scope(db, wash_id) is None:
        raise Refused("unknown wash")
    old = db.scalars(select(m.Encouragement).where(m.Encouragement.wash_id == wash_id, m.Encouragement.kind == "high_five")).first()
    if old is not None:
        return old, False
    row = m.Encouragement(wash_id=wash_id, kind="high_five", created_utc=utc_now())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalars(select(m.Encouragement).where(m.Encouragement.wash_id == wash_id)).one(), False
    return row, True


def high_fived(db: DbSession, wash_id: str) -> datetime | None:
    row = db.scalars(select(m.Encouragement).where(m.Encouragement.wash_id == wash_id, m.Encouragement.kind == "high_five")).first()
    return None if row is None else A._utc(row.created_utc)


def reset_app_data(db: DbSession) -> None:
    """Remove every parent-app row (children, washes, germs, rewards, requests, settings). Demo backends only."""
    for table in (m.Encouragement, m.Redemption, m.GermUnlock, m.WashRow, m.FamilyReward, m.Child, m.AppSettings):
        db.execute(delete(table))
    db.commit()


# ---- parent PIN
# Parent-only actions (managing rewards, deciding requests, deleting history, removing a child) need the PIN
# once one is set. Until then the app is open, as it is on a fresh install. This keeps a child out of the
# parent screens on a shared tablet; it is not account security (see docs/SCRUBBLE_APP.md).
PIN_ITERATIONS = 200_000
UNLOCK_S = 15 * 60
MAX_TRIES, TRY_WINDOW_S = 5, 60.0


def _hash(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PIN_ITERATIONS).hex()


def set_pin(db: DbSession, pin: str) -> None:
    salt = secrets.token_bytes(16)
    A.settings(db).parent_pin_hash = f"pbkdf2_sha256${PIN_ITERATIONS}${salt.hex()}${_hash(pin, salt)}"
    db.commit()


def clear_pin(db: DbSession) -> None:
    A.settings(db).parent_pin_hash = None
    db.commit()


def pin_ok(db: DbSession, pin: str) -> bool:
    stored = A.settings(db).parent_pin_hash
    if not stored:
        return False
    _, _, salt, digest = stored.split("$")
    return hmac.compare_digest(_hash(pin, bytes.fromhex(salt)), digest)


class ParentSessions:
    """Short-lived unlock tokens, kept in memory (a backend restart locks the parent screens again)."""

    def __init__(self) -> None:
        self._tokens: dict[str, float] = {}
        self._tries: list[float] = []
        self._lock = threading.Lock()

    def note_try(self) -> bool:
        """Count a PIN attempt. False when there were too many in the last minute."""
        now = time.monotonic()
        with self._lock:
            self._tries = [t for t in self._tries if now - t < TRY_WINDOW_S]
            if len(self._tries) >= MAX_TRIES:
                return False
            self._tries.append(now)
            return True

    def open(self) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[token] = time.monotonic() + UNLOCK_S
        return token

    def valid(self, token: str | None) -> bool:
        now = time.monotonic()
        with self._lock:
            self._tokens = {t: exp for t, exp in self._tokens.items() if exp > now}
            return token is not None and token in self._tokens

    def close(self, token: str | None) -> None:
        with self._lock:
            self._tokens.pop(token or "", None)

    def close_all(self) -> None:
        with self._lock:
            self._tokens.clear()
