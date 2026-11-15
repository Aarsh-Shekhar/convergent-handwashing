"""Auto wash sessions: split one long camera run into washes, and the record kept of each.

A wash starts when a hand has been tracked for ``start_after_s`` and ends once no hand was seen for
``end_after_s`` (a child stepping back, the next child arriving). The pipeline then saves one
:class:`WashRecord`, the data the parents' app shows: how long each part of the hands was washed.
Seconds are recognized washing-motion time, not proof of clean hands. No names, no pictures.
"""

from __future__ import annotations

from typing import Any

from convergent.common.types import StrictModel
from convergent.scoring.wash_score import WashScore


class WashRecord(StrictModel):
    wash_id: str                 # "<run session id>-w001"
    session_id: str              # the camera run it belongs to
    started_utc: str
    ended_utc: str               # when the hands were last seen
    duration_s: float
    seconds: dict[str, float]    # wash step -> validated seconds (same numbers as score.steps)
    score: WashScore
    soap_seen: bool | None = None  # unvalidated lather heuristic (None = check switched off)
    quality: dict[str, Any]      # frames, fps, no_hand_share, two_hand_share, light_fix, green_only: lets the app skip bad sessions
    models: dict[str, Any]       # recognizer version and hash
    schema_version: str = "wash-record-v1"


class WashSessions:
    def __init__(self, start_after_s: float = 0.5, end_after_s: float = 4.0) -> None:
        self.start_after_s, self.end_after_s = start_after_s, end_after_s
        self.washing = False
        self.started_ts = self.ended_ts = 0.0
        self.seen_since: float | None = None  # first frame of the hands now in view (None = nobody there)

    def update(self, ts: float, hands_present: bool) -> str | None:
        """Call once per frame. Returns "start" or "end" on the frame a wash starts or ends, else None."""
        if hands_present:
            if self.seen_since is None:
                self.seen_since = ts
            self.ended_ts = ts  # last time a hand was seen
            if not self.washing and ts - self.seen_since >= self.start_after_s:
                self.washing, self.started_ts = True, self.seen_since
                return "start"
        elif self.washing:
            if ts - self.ended_ts >= self.end_after_s:
                return self.close()
        else:
            self.seen_since = None
        return None

    def close(self) -> str:
        """End the wash now (the run is stopping). ``ended_ts`` stays at the last time a hand was seen."""
        self.washing, self.seen_since = False, None
        return "end"
