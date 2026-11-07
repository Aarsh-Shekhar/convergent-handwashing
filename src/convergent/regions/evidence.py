"""Gesture-to-region evidence accumulation.

The camera observes *movements*; this module turns validated technique events into evidence
that an anatomical region was addressed. It never claims soap coverage or cleanliness –
``RegionEvidence.status`` is about observed evidence only (``coverage_estimate`` in
``progress.py`` is explicitly defined on top of it).

Mapping (WHO technique -> regions it is intended to address). For sided techniques the
side is the hand RECEIVING the action; the acting hand's palm also gets (weaker) evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from convergent.common.config import RegionsConfig
from convergent.common.types import (
    EvidenceStatus,
    GestureEvent,
    HandSide,
    Region,
    RegionEvidence,
    TrackedHands,
    ValidationStatus,
    VisibilityState,
)
from convergent.detection import labels as L

# (technique) -> list of (target: "self"|"other"|"both", region, weight)
# "self" = the side carried by the event (hand receiving the action), "other" = the acting hand.
TECHNIQUE_REGIONS: dict[str, list[tuple[str, Region, float]]] = {
    L.PALM_TO_PALM: [("both", Region.PALM, 1.0)],
    L.BACK_OF_HAND: [("self", Region.BACK_OF_HAND, 1.0), ("other", Region.PALM, 0.5), ("both", Region.FINGERS, 0.5)],
    L.INTERLACED_FINGERS: [("both", Region.FINGERS, 1.0), ("both", Region.PALM, 0.5)],
    L.BACKS_OF_FINGERS: [("both", Region.FINGERS, 1.0)],
    L.THUMB_RUBBING: [("self", Region.THUMB, 1.0), ("other", Region.PALM, 0.3)],
    L.FINGERTIP_RUBBING: [("self", Region.FINGERTIPS, 1.0), ("other", Region.PALM, 0.5)],
}


def _other(side: HandSide) -> HandSide:
    return HandSide.RIGHT if side == HandSide.LEFT else HandSide.LEFT


@dataclass
class _Acc:
    duration: float = 0.0
    weighted: float = 0.0
    conf_sum: float = 0.0
    n: int = 0
    events: list[str] = field(default_factory=list)
    techniques: list[str] = field(default_factory=list)
    first_ts: float | None = None
    last_ts: float | None = None
    visibility: VisibilityState = VisibilityState.MISSING
    uncertain_duration: float = 0.0  # evidence attributable to an unresolved side


class EvidenceAccumulator:
    """Accumulates evidence per (region, side) from validated events."""

    def __init__(self, cfg: RegionsConfig | None = None) -> None:
        self.cfg = cfg or RegionsConfig()
        self._acc: dict[tuple[Region, HandSide], _Acc] = {
            (r, s): _Acc() for r in Region for s in (HandSide.LEFT, HandSide.RIGHT)
        }
        self._last_visibility: dict[HandSide, VisibilityState] = {HandSide.LEFT: VisibilityState.MISSING, HandSide.RIGHT: VisibilityState.MISSING}
        self.unattributed: list[dict[str, object]] = []

    def reset(self) -> None:
        self.__init__(self.cfg)  # type: ignore[misc]

    def observe_hands(self, hands: TrackedHands) -> None:
        for side in (HandSide.LEFT, HandSide.RIGHT):
            h = hands.get(side)
            self._last_visibility[side] = h.visibility if h is not None else VisibilityState.MISSING

    def add_event(self, ev: GestureEvent) -> None:
        if ev.validation_status != ValidationStatus.VALIDATED:
            return
        spec = TECHNIQUE_REGIONS.get(ev.technique)
        if spec is None:
            return  # extensions (e.g. wrist_rubbing) have no core-region mapping
        for target, region, w in spec:
            sides: list[tuple[HandSide, float]] = []
            if target == "both":
                sides = [(HandSide.LEFT, w), (HandSide.RIGHT, w)]
            elif ev.side in (HandSide.LEFT, HandSide.RIGHT) and ev.side_resolved:
                sides = [(ev.side if target == "self" else _other(ev.side), w)]
            else:
                # side unknown/unresolved: cannot attribute to a hand
                if self.cfg.use_unresolved_side_evidence:
                    sides = [(HandSide.LEFT, w * 0.5), (HandSide.RIGHT, w * 0.5)]
                    for s, _w in sides:
                        self._acc[(region, s)].uncertain_duration += ev.validated_duration_s * 0.5
                else:
                    self.unattributed.append({"event_id": ev.event_id, "technique": ev.technique, "region": region.value,
                                              "duration_s": ev.validated_duration_s, "reason": "side unresolved"})
                    continue
            for side, weight in sides:
                a = self._acc[(region, side)]
                vis = self._last_visibility[side]
                vis_w = 1.0 if vis == VisibilityState.VISIBLE else (self.cfg.partial_visibility_weight if vis == VisibilityState.PARTIAL else 0.25)
                a.duration += ev.validated_duration_s
                a.weighted += ev.validated_duration_s * weight * vis_w * ev.confidence
                a.conf_sum += ev.confidence
                a.n += 1
                a.events.append(ev.event_id)
                if ev.technique not in a.techniques:
                    a.techniques.append(ev.technique)
                a.first_ts = ev.start_ts if a.first_ts is None else min(a.first_ts, ev.start_ts)
                a.last_ts = ev.end_ts if a.last_ts is None else max(a.last_ts, ev.end_ts)
                a.visibility = vis if a.visibility == VisibilityState.MISSING or vis == VisibilityState.VISIBLE else a.visibility

    def evidence(self) -> list[RegionEvidence]:
        out = []
        for (region, side), a in self._acc.items():
            if a.n == 0:
                status = EvidenceStatus.UNKNOWN
                conf = 0.0
            else:
                conf = min(1.0, a.weighted / max(self.cfg.min_sufficient_duration_s, 1e-9))
                if a.weighted >= self.cfg.min_sufficient_duration_s:
                    status = EvidenceStatus.PARTIAL if a.visibility != VisibilityState.VISIBLE or a.uncertain_duration > 0 else EvidenceStatus.SUFFICIENT
                else:
                    status = EvidenceStatus.INSUFFICIENT
            out.append(RegionEvidence(region=region, side=side, supporting_events=list(a.events), supporting_techniques=list(a.techniques),
                                      visibility=a.visibility, observed_duration_s=a.duration, confidence=float(conf), status=status,
                                      first_ts=a.first_ts, last_ts=a.last_ts))
        return out

    def for_side(self, side: HandSide) -> list[RegionEvidence]:
        return [e for e in self.evidence() if e.side == side]
