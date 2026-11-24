"""Durable upload queue for finished washes.

A finished wash is worth keeping even when the backend or the Wi-Fi is down, and the camera loop must never
wait for the network. So the pipeline only writes the wash to a small SQLite file (``put``, a few
milliseconds) and a background thread uploads it:

* a wash stays in the file until the backend has acknowledged it, so it survives a crash or a restart;
* network trouble, 5xx, 408 and 429 are retried with growing, jittered waits (``Retry-After`` is respected);
* an answer that will never change (bad record, wrong token, conflict) parks the wash as ``dead`` with the
  reason, instead of retrying forever. ``convergent wash-queue --retry-dead`` sends parked washes again
  once the cause is fixed;
* the backend stores a wash_id once, so an upload repeated after a lost answer is harmless.

Only wash records are stored: seconds per step, score, quality numbers. No frames, no hand points.
"""

from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from convergent.backend.client import BackendError
from convergent.common.logging import get_logger

log = get_logger(__name__)

RETRYABLE = {408, 425, 429}   # plus every 5xx and every failure without an HTTP answer
KEEP_DONE = 200               # acknowledged washes kept as a local receipt
MAX_WAITING = 2000            # about a year of washes for one sink; beyond it the oldest waiting wash is parked

_SCHEMA = """
CREATE TABLE IF NOT EXISTS washes (
    wash_id TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'waiting',      -- waiting | sent | dead
    attempts INTEGER NOT NULL DEFAULT 0,
    next_try REAL NOT NULL DEFAULT 0,           -- unix time
    last_error TEXT NOT NULL DEFAULT '',
    queued REAL NOT NULL,
    done REAL
)
"""


def backoff_s(attempts: int, base_s: float = 2.0, cap_s: float = 300.0, rng: Callable[[], float] = random.random) -> float:
    """Wait before try number ``attempts + 1``: doubles each time up to ``cap_s``, with 50 to 100% jitter."""
    return min(cap_s, base_s * 2 ** max(attempts - 1, 0)) * (0.5 + 0.5 * rng())


class WashOutbox:
    def __init__(self, path: Path | str, send: Callable[[dict[str, Any]], Any], base_s: float = 2.0, cap_s: float = 300.0,
                 start: bool = True, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._send, self._base_s, self._cap_s, self._clock = send, base_s, cap_s, clock
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = False
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")  # a queued wash must survive a power cut
        self._db.execute(_SCHEMA)
        self._db.commit()
        self._thread: threading.Thread | None = None
        if start:
            self._thread = threading.Thread(target=self._run, name="wash-outbox", daemon=True)
            self._thread.start()

    # ---- called from the camera loop
    def put(self, record: dict[str, Any]) -> bool:
        """Queue a wash. Returns False if this wash_id is already in the queue. Never touches the network."""
        with self._lock:
            cur = self._db.execute("INSERT OR IGNORE INTO washes (wash_id, body, queued) VALUES (?, ?, ?)",
                                   (record["wash_id"], json.dumps(record, default=str), self._clock()))
            over = self._db.execute("SELECT COUNT(*) FROM washes WHERE state = 'waiting'").fetchone()[0] - MAX_WAITING
            if over > 0:
                self._db.execute("UPDATE washes SET state = 'dead', last_error = 'queue full', done = ? WHERE wash_id IN "
                                 "(SELECT wash_id FROM washes WHERE state = 'waiting' ORDER BY queued LIMIT ?)", (self._clock(), over))
            self._db.commit()
        self._wake.set()
        return cur.rowcount == 1

    # ---- upload
    def drain_once(self) -> int:
        """Upload waiting washes, oldest first. Returns how many were acknowledged.

        While the oldest wash is waiting out a retry delay the ones behind it wait too: they would fail the
        same way, and washes should reach the backend in the order they happened."""
        with self._lock:
            waiting = self._db.execute("SELECT wash_id, body, attempts, next_try FROM washes WHERE state = 'waiting' ORDER BY queued, rowid").fetchall()
        sent = 0
        for wash_id, body, attempts, next_try in waiting:
            if self._stop or next_try > self._clock():
                break
            try:
                self._send(json.loads(body))
            except BackendError as exc:
                status = getattr(exc, "status", None)
                if status is not None and status < 500 and status not in RETRYABLE:
                    log.error("wash %s refused by the backend (%s), parked: %s", wash_id, status, exc)
                    self._mark(wash_id, "dead", attempts + 1, 0.0, str(exc)[:300])
                    continue
                wait = max(backoff_s(attempts + 1, self._base_s, self._cap_s), float(getattr(exc, "retry_after", None) or 0.0))
                log.warning("wash %s not uploaded yet (try %d, next in %.0f s): %s", wash_id, attempts + 1, wait, exc)
                self._mark(wash_id, "waiting", attempts + 1, self._clock() + wait, str(exc)[:300])
                break  # the backend is unreachable or busy: later washes would fail the same way, keep their order
            else:
                self._mark(wash_id, "sent", attempts + 1, 0.0, "")
                sent += 1
        return sent

    def _mark(self, wash_id: str, state: str, attempts: int, next_try: float, error: str) -> None:
        with self._lock:
            self._db.execute("UPDATE washes SET state = ?, attempts = ?, next_try = ?, last_error = ?, done = ? WHERE wash_id = ?",
                             (state, attempts, next_try, error, None if state == "waiting" else self._clock(), wash_id))
            if state == "sent":
                self._db.execute("DELETE FROM washes WHERE state = 'sent' AND wash_id NOT IN "
                                 "(SELECT wash_id FROM washes WHERE state = 'sent' ORDER BY done DESC LIMIT ?)", (KEEP_DONE,))
            self._db.commit()

    def _run(self) -> None:
        while not self._stop:
            try:
                self.drain_once()
            except Exception as exc:  # noqa: BLE001 - the uploader must outlive any surprise
                log.exception("wash outbox: %s", exc)
            self._wake.clear()
            self._wake.wait(timeout=self._next_wait())

    def _next_wait(self) -> float:
        with self._lock:
            row = self._db.execute("SELECT MIN(next_try) FROM washes WHERE state = 'waiting'").fetchone()
        return 30.0 if row[0] is None else min(max(row[0] - self._clock(), 0.2), 30.0)

    # ---- inspection and shutdown
    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = dict(self._db.execute("SELECT state, COUNT(*) FROM washes GROUP BY state").fetchall())
        return {s: int(rows.get(s, 0)) for s in ("waiting", "sent", "dead")}

    def parked(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT wash_id, attempts, last_error FROM washes WHERE state = 'dead' ORDER BY queued").fetchall()
        return [{"wash_id": w, "attempts": a, "error": e} for w, a, e in rows]

    def retry_dead(self) -> int:
        with self._lock:
            n = self._db.execute("UPDATE washes SET state = 'waiting', next_try = 0, done = NULL WHERE state = 'dead'").rowcount
            self._db.commit()
        self._wake.set()
        return n

    def close(self, flush_s: float = 3.0) -> None:
        """Give waiting washes ``flush_s`` to upload, then stop. Whatever is left stays in the file for the next run."""
        deadline = time.monotonic() + flush_s
        while self._thread is not None and time.monotonic() < deadline:
            with self._lock:
                head = self._db.execute("SELECT next_try FROM washes WHERE state = 'waiting' ORDER BY queued, rowid LIMIT 1").fetchone()
                due = head is not None and head[0] <= self._clock()
            if not due:
                break
            self._wake.set()
            time.sleep(0.05)
        self._stop = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=6.0)
        with self._lock:
            self._db.close()
