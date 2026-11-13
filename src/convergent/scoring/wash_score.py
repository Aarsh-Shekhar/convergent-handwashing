"""Per-step timers and a child-facing wash score.

What is timed: for each scored technique (the six WHO techniques plus wrist rubbing), the
*validated* seconds, summed across tries and across hands. The temporal validator has
already applied the confidence and duration rules (enter/exit confidence, minimum duration,
tracking quality), so this module never looks at raw model confidence.

Live timing. A finished motion only reaches the pipeline as a ``GestureEvent`` roughly
``max_gap_s + merge_gap_s`` after the child stops. To keep the bars moving while the child
rubs, each step's live time is::

    released events  +  the event held for a possible merge  +  the active candidate
                                                                (only once it is validated)

and the displayed value never goes down within a session.

Rules (``ScoringConfig``):

* a step is done when its time reaches ``step_min_s``;
* the wash is finished when ``steps_required`` steps are done AND the summed time of all
  steps reaches ``total_min_s``;
* points: up to ``step_points`` per step (partial credit) plus up to ``time_points`` for total
  time (capped at ``total_min_s``, so scrubbing longer earns nothing extra);
* stars: 0 nothing recognized, 1 some washing, 2 ``two_star_steps`` steps or
  ``two_star_total_s`` seconds, 3 finished, 4 finished with more than ``steps_required``
  steps, 5 finished with every step;
* once finished, the score is frozen. Recognition keeps running, the score stops changing.

This is a score of recognized motion time. It is not a measurement of clean hands, soap
contact or surface coverage.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

from convergent.common.config import ScoringConfig
from convergent.common.types import GestureEvent, StrictModel, ValidationStatus
from convergent.detection.temporal import Candidate

_EPS = 1e-6


class StepTime(StrictModel):
    technique: str
    seconds: float = Field(ge=0)
    done: bool
    points: float = Field(ge=0)


class WashScore(StrictModel):
    session_id: str = ""
    timestamp: float
    steps: list[StepTime]
    steps_done: int = Field(ge=0)
    steps_required: int
    step_min_s: float
    total_s: float = Field(ge=0)
    total_min_s: float
    finished: bool
    finished_at_ts: float | None = None
    next_step: str | None = None
    points: int = Field(ge=0)
    stars: int = Field(ge=0, le=5)
    schema_version: str = "wash-score-v1"


class WashScorer:
    def __init__(self, cfg: ScoringConfig | None = None, session_id: str = "") -> None:
        self.cfg = cfg or ScoringConfig()
        self.session_id = session_id
        self._steps: list[str] = list(self.cfg.steps)
        self.reset()

    def reset(self) -> None:
        """Start a new wash (clears timers and unfreezes the score)."""
        self._released: dict[str, float] = {t: 0.0 for t in self._steps}
        self._shown: dict[str, float] = {t: 0.0 for t in self._steps}
        self._seen: set[str] = set()
        self._frozen: WashScore | None = None
        self._last_end = float("-inf")  # end of the latest credited time
        self._backfilled: set[tuple[str, float]] = set()

    @property
    def finished(self) -> bool:
        return self._frozen is not None

    def add_events(self, events: Iterable[GestureEvent]) -> None:
        """Add released (finalized) events. Rejected events and unscored techniques are ignored."""
        for ev in events:
            if ev.validation_status != ValidationStatus.VALIDATED or ev.technique not in self._released:
                continue
            if ev.event_id in self._seen:
                continue
            self._seen.add(ev.event_id)
            self._released[ev.technique] += ev.validated_duration_s
            self._last_end = max(self._last_end, ev.end_ts)

    def update(self, ts: float, active: Candidate | None = None, pending: GestureEvent | None = None) -> WashScore:
        """Live score for this frame. Returns the frozen score once the wash is finished."""
        if self._frozen is not None:
            return self._frozen
        pend_ok = pending is not None and pending.validation_status == ValidationStatus.VALIDATED and pending.technique in self._released
        act_ok = active is not None and active.validated and active.technique in self._released
        if act_ok and (active.technique, active.start_ts) not in self._backfilled:  # type: ignore[union-attr]
            # once per candidate: credit the recognition lag just before it, but never time already credited
            last_end = max(self._last_end, pending.end_ts) if pend_ok else self._last_end  # type: ignore[union-attr]
            self._backfilled.add((active.technique, active.start_ts))  # type: ignore[union-attr]
            self._released[active.technique] += max(0.0, min(self.cfg.backfill_s, active.start_ts - last_end))  # type: ignore[union-attr]
        live = dict(self._released)
        if pend_ok:
            live[pending.technique] += pending.validated_duration_s  # type: ignore[union-attr]
        if act_ok:
            live[active.technique] += active.supported_s  # type: ignore[union-attr]
        for t in self._steps:
            self._shown[t] = max(self._shown[t], live[t])
        return self._score(ts, self._shown)

    def final(self, ts: float) -> WashScore:
        """Score to save at the end of a run (call after the event detector is flushed).

        If the wash finished, this is the frozen score. Otherwise it is computed from released
        events only, which is the same record the backend stores.
        """
        if self._frozen is not None:
            return self._frozen
        return self._score(ts, self._released)

    # ---- internals
    def _score(self, ts: float, secs: dict[str, float]) -> WashScore:
        c = self.cfg
        steps: list[StepTime] = []
        points = 0.0
        for t in self._steps:
            s = max(0.0, secs[t])
            frac = min(s / c.step_min_s, 1.0) if c.step_min_s > 0 else 1.0
            sp = c.step_points * frac
            points += sp
            steps.append(StepTime(technique=t, seconds=round(s, 3), done=s + _EPS >= c.step_min_s, points=round(sp, 2)))
        total = sum(max(0.0, secs[t]) for t in self._steps)
        points += c.time_points * (min(total / c.total_min_s, 1.0) if c.total_min_s > 0 else 1.0)
        steps_done = sum(1 for st in steps if st.done)
        finished = steps_done >= c.steps_required and total + _EPS >= c.total_min_s
        score = WashScore(
            session_id=self.session_id, timestamp=ts, steps=steps, steps_done=steps_done, steps_required=c.steps_required,
            step_min_s=c.step_min_s, total_s=round(total, 3), total_min_s=c.total_min_s, finished=finished,
            finished_at_ts=ts if finished else None, next_step=next((st.technique for st in steps if not st.done), None),
            points=int(round(points)), stars=self._stars(total, steps_done, finished),
        )
        if finished:
            self._frozen = score
        return score

    def _stars(self, total: float, steps_done: int, finished: bool) -> int:
        c = self.cfg
        if finished:
            if steps_done >= len(self._steps):
                return 5
            return 4 if steps_done > c.steps_required else 3
        if total <= _EPS:
            return 0
        if steps_done >= c.two_star_steps or total + _EPS >= c.two_star_total_s:
            return 2
        return 1
