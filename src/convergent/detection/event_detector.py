"""Event detector: wraps the temporal validator, merges justified fragments, suppresses
duplicates and exposes the stream of finalized :class:`GestureEvent` objects.

Merging rule: two *validated* events with the same (technique, side) separated by less than
``merge_gap_s`` are merged into one (their supported durations add up; the gap is recorded
in ``tracking_gaps_s``). Duplicate rule: an event whose dedupe key (technique, side, start)
matches one already emitted within ``duplicate_window_s`` is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from convergent.common.config import TemporalConfig
from convergent.common.types import GestureEvent, ModelPrediction, ValidationStatus
from convergent.detection.temporal import Candidate, TemporalValidator


@dataclass
class EventStreamState:
    active: Candidate | None = None
    events: list[GestureEvent] = field(default_factory=list)
    rejected: list[GestureEvent] = field(default_factory=list)
    merged_count: int = 0
    duplicates_dropped: int = 0


class EventDetector:
    def __init__(self, cfg: TemporalConfig | None = None, session_id: str = "") -> None:
        self.cfg = cfg or TemporalConfig()
        self.validator = TemporalValidator(self.cfg, session_id)
        self.state = EventStreamState()
        self._pending: GestureEvent | None = None  # last validated event, held for possible merge
        self._emitted_keys: dict[str, float] = {}

    def reset(self) -> None:
        self.validator.reset()
        self.state = EventStreamState()
        self._pending = None
        self._emitted_keys.clear()

    def update(self, fused: ModelPrediction, tracking_quality: float) -> list[GestureEvent]:
        upd = self.validator.update(fused, tracking_quality)
        self.state.active = upd.active
        out: list[GestureEvent] = []
        for ev in upd.ended:
            out.extend(self._accept(ev))
        # a pending validated event is released once the merge window has passed, unless a
        # candidate for the same (technique, side) that started inside the window is still active
        if self._pending is not None and fused.window_end_ts - self._pending.end_ts > self.cfg.merge_gap_s:
            act = upd.active
            same_active = (act is not None and act.technique == self._pending.technique and act.side == self._pending.side
                           and 0 <= act.start_ts - self._pending.end_ts <= self.cfg.merge_gap_s)
            if not same_active:
                out.extend(self._release())
        return out

    def flush(self, ts: float | None = None) -> list[GestureEvent]:
        out: list[GestureEvent] = []
        for ev in self.validator.flush(ts):
            out.extend(self._accept(ev))
        out.extend(self._release())
        return out

    # ---- internals
    def _accept(self, ev: GestureEvent) -> list[GestureEvent]:
        if ev.validation_status != ValidationStatus.VALIDATED:
            self.state.rejected.append(ev)
            return []
        p = self._pending
        if p is not None and p.technique == ev.technique and p.side == ev.side and 0 <= ev.start_ts - p.end_ts <= self.cfg.merge_gap_s:
            merged = p.model_copy(update={
                "end_ts": ev.end_ts,
                "validated_duration_s": p.validated_duration_s + ev.validated_duration_s,
                "tracking_gaps_s": p.tracking_gaps_s + ev.tracking_gaps_s + (ev.start_ts - p.end_ts),
                "supporting_predictions": (p.supporting_predictions + ev.supporting_predictions)[-50:],
                "confidence": (p.confidence + ev.confidence) / 2.0,
                "quality": (p.quality + ev.quality) / 2.0,
                "side_resolved": p.side_resolved or ev.side_resolved,
                "model_versions": {**p.model_versions, **ev.model_versions},
            })
            self.state.merged_count += 1
            self._pending = merged
            return []
        out = self._release()
        self._pending = ev
        return out

    def _release(self) -> list[GestureEvent]:
        if self._pending is None:
            return []
        ev, self._pending = self._pending, None
        key = ev.dedupe_key
        last = self._emitted_keys.get(f"{ev.technique}|{ev.side.value}")
        if key in self._emitted_keys or (last is not None and abs(ev.start_ts - last) < self.cfg.duplicate_window_s):
            self.state.duplicates_dropped += 1
            return []
        self._emitted_keys[key] = ev.start_ts
        self._emitted_keys[f"{ev.technique}|{ev.side.value}"] = ev.start_ts
        self.state.events.append(ev)
        return [ev]
