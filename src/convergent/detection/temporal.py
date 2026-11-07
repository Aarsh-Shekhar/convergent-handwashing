"""Temporal validation: turns per-frame fused predictions into stable gesture candidates.

All reasoning is in capture-clock seconds, never frame counts – a 1 s gesture at 10 FPS and
at 30 FPS accumulates the same support. Behaviour (all thresholds in :class:`TemporalConfig`):

* **Hysteresis** – a technique becomes the active candidate when fused confidence is at
  least ``enter_confidence``; it stays active while confidence stays at or above
  ``exit_confidence`` for the same technique.
* **Minimum evidence duration** – a candidate is *validated* once its accumulated supported
  time reaches ``min_duration_s``.
* **Pause/resume** – frames whose fused output is UNKNOWN/NO_INPUT, or whose tracking
  quality is below ``min_tracking_quality``, neither support nor terminate the candidate;
  they are counted as a gap. When the gap exceeds ``max_gap_s`` the candidate ends.
* **Switching** – a different technique reaching ``enter_confidence`` ends the current
  candidate (REJECTED if not yet validated) and starts a new one.
* ``max_event_duration_s`` caps a single event (a stuck classifier cannot create an
  hour-long "palm_to_palm").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from convergent.common.config import TemporalConfig
from convergent.common.types import (
    GestureEvent,
    HandSide,
    ModelPrediction,
    PredictionRef,
    PredictionStatus,
    ValidationStatus,
)


@dataclass
class Candidate:
    technique: str
    side: HandSide
    side_resolved: bool
    start_ts: float
    last_ts: float
    last_support_ts: float
    supported_s: float = 0.0
    gap_s: float = 0.0
    confidences: list[float] = field(default_factory=list)
    qualities: list[float] = field(default_factory=list)
    refs: list[PredictionRef] = field(default_factory=list)
    model_versions: dict[str, str] = field(default_factory=dict)
    validated: bool = False
    validated_at: float | None = None

    @property
    def key(self) -> tuple[str, HandSide]:
        return (self.technique, self.side)


@dataclass
class TemporalUpdate:
    """What happened on this frame."""

    started: Candidate | None = None
    validated: Candidate | None = None
    ended: list[GestureEvent] = field(default_factory=list)
    active: Candidate | None = None


class TemporalValidator:
    def __init__(self, cfg: TemporalConfig | None = None, session_id: str = "") -> None:
        self.cfg = cfg or TemporalConfig()
        self.session_id = session_id
        self.active: Candidate | None = None
        self._last_ts: float | None = None
        self._seq = 0

    def reset(self) -> None:
        self.active = None
        self._last_ts = None

    def update(self, fused: ModelPrediction, tracking_quality: float, ts: float | None = None) -> TemporalUpdate:
        ts = fused.window_end_ts if ts is None else ts
        upd = TemporalUpdate()
        if self._last_ts is not None and ts < self._last_ts:
            raise ValueError(f"timestamps must be non-decreasing ({ts} < {self._last_ts})")
        dt = 0.0 if self._last_ts is None else min(ts - self._last_ts, self.cfg.max_gap_s)
        self._last_ts = ts
        tracking_ok = tracking_quality >= self.cfg.min_tracking_quality
        valid = fused.status == PredictionStatus.VALID and fused.canonical is not None and fused.confidence is not None
        conf = float(fused.confidence or 0.0)
        technique = fused.canonical.technique if valid and fused.canonical else None
        side = fused.canonical.side if valid and fused.canonical else HandSide.UNKNOWN
        side_resolved = bool(fused.canonical.resolved) if valid and fused.canonical else False

        act = self.active
        if act is not None:
            same = valid and technique == act.technique and _side_compatible(side, act.side)
            if same and conf >= self.cfg.exit_confidence and tracking_ok:
                act.supported_s += dt
                act.gap_s = 0.0
                act.last_support_ts = ts
                act.confidences.append(conf)
                act.qualities.append(tracking_quality)
                act.refs.append(_ref(fused))
                _merge_versions(act, fused)
                if not act.side_resolved and side_resolved:
                    act.side, act.side_resolved = side, True
            elif valid and technique != act.technique and conf >= self.cfg.enter_confidence and tracking_ok:
                upd.ended.append(self._finish(act, ts))
                self.active = None
                act = None
            else:
                act.gap_s += dt
                if act.gap_s > self.cfg.max_gap_s:
                    upd.ended.append(self._finish(act, act.last_support_ts))
                    self.active = None
                    act = None
            if act is not None:
                act.last_ts = ts
                if not act.validated and act.supported_s >= self.cfg.min_duration_s:
                    act.validated, act.validated_at = True, ts
                    upd.validated = act
                if ts - act.start_ts >= self.cfg.max_event_duration_s:
                    upd.ended.append(self._finish(act, ts))
                    self.active = None
                    act = None
        if act is None and valid and technique is not None and conf >= self.cfg.enter_confidence and tracking_ok:
            act = Candidate(technique=technique, side=side, side_resolved=side_resolved, start_ts=ts, last_ts=ts,
                            last_support_ts=ts, confidences=[conf], qualities=[tracking_quality], refs=[_ref(fused)])
            _merge_versions(act, fused)
            self.active = act
            upd.started = act
        upd.active = self.active
        return upd

    def flush(self, ts: float | None = None) -> list[GestureEvent]:
        if self.active is None:
            return []
        ev = self._finish(self.active, self.active.last_support_ts if ts is None else ts)
        self.active = None
        return [ev]

    def _finish(self, c: Candidate, end_ts: float) -> GestureEvent:
        end_ts = max(end_ts, c.start_ts)
        self._seq += 1
        status = ValidationStatus.VALIDATED if c.validated else ValidationStatus.REJECTED
        conf = sum(c.confidences) / len(c.confidences) if c.confidences else 0.0
        qual = sum(c.qualities) / len(c.qualities) if c.qualities else 0.0
        return GestureEvent(session_id=self.session_id, technique=c.technique, side=c.side, start_ts=c.start_ts,
                            end_ts=end_ts, validated_duration_s=min(c.supported_s, end_ts - c.start_ts) if c.validated else 0.0,
                            supporting_predictions=c.refs[-50:], model_versions=dict(c.model_versions),
                            confidence=float(min(max(conf, 0.0), 1.0)), quality=float(min(max(qual, 0.0), 1.0)),
                            validation_status=status, side_resolved=c.side_resolved,
                            tracking_gaps_s=max(0.0, (end_ts - c.start_ts) - c.supported_s), sequence_no=self._seq)


def _side_compatible(a: HandSide, b: HandSide) -> bool:
    if a == b:
        return True
    unspecified = (HandSide.UNKNOWN, HandSide.UNRESOLVED)
    return a in unspecified or b in unspecified


def _ref(p: ModelPrediction) -> PredictionRef:
    return PredictionRef(model_id=p.model_id, model_version=p.model_version, window_start_ts=p.window_start_ts,
                         window_end_ts=p.window_end_ts, canonical_key=p.canonical.key if p.canonical else None,
                         confidence=p.confidence)


def _merge_versions(c: Candidate, fused: ModelPrediction) -> None:
    for b in fused.extras.get("branches", []):
        if b.get("status") in ("valid", "unknown"):
            c.model_versions[b["model_id"]] = b.get("model_version", "")
    c.model_versions[fused.model_id] = fused.model_version
