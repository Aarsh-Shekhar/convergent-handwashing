"""Structured technical progress state for the future gamification layer.

This is *not* scoring. It is a typed snapshot of what the system has observed: validated
techniques (per side), region evidence (per hand/region), the explicitly defined
``coverage_estimate``, and an honest ``unknown`` list. The game engine decides what to do
with it.

``coverage_estimate`` definition: fraction of the 10 (region x hand) cells whose evidence
status is SUFFICIENT, weighted by evidence confidence. It is an estimate of *observed
technique evidence*, never a measurement of soap contact or microbial cleanliness.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from convergent.common.types import (
    EvidenceStatus,
    GestureEvent,
    HandSide,
    Region,
    RegionEvidence,
    StrictModel,
    ValidationStatus,
)
from convergent.detection import labels as L
from convergent.regions.evidence import EvidenceAccumulator


class TechniqueProgress(StrictModel):
    technique: str
    validated_duration_s: float = 0.0
    event_count: int = 0
    sides_observed: list[HandSide] = Field(default_factory=list)
    side_unresolved_duration_s: float = 0.0
    gesture_detected: bool = False
    gesture_validated: bool = False


class HandProgress(StrictModel):
    side: HandSide
    regions: dict[Region, RegionEvidence]
    sufficient_regions: list[Region]
    unknown_regions: list[Region]


class ProgressState(StrictModel):
    session_id: str
    timestamp: float
    techniques: dict[str, TechniqueProgress]
    hands: dict[HandSide, HandProgress]
    coverage_estimate: float = Field(ge=0.0, le=1.0, description="see module docstring; NOT cleanliness")
    coverage_definition: str = "fraction of (region x hand) cells with SUFFICIENT evidence, confidence-weighted"
    unattributed_evidence: list[dict[str, Any]] = Field(default_factory=list)
    active_candidate: dict[str, Any] | None = None
    procedure_states: dict[str, str] = Field(
        default_factory=lambda: {"wetting": "not_detected", "soap": "not_detected", "rinsing": "not_detected", "drying": "not_detected"},
        description="procedural phases without validated visual detectors stay 'not_detected'",
    )
    schema_version: str = "progress-v1"


class ProgressTracker:
    def __init__(self, session_id: str, accumulator: EvidenceAccumulator) -> None:
        self.session_id = session_id
        self.acc = accumulator
        self._tech: dict[str, TechniqueProgress] = {t: TechniqueProgress(technique=t) for t in L.CORE_TECHNIQUES}
        self._last_ts = 0.0

    def reset(self) -> None:
        self._tech = {t: TechniqueProgress(technique=t) for t in L.CORE_TECHNIQUES}
        self._last_ts = 0.0

    def observe_detection(self, technique: str | None) -> None:
        if technique in self._tech:
            self._tech[technique].gesture_detected = True

    def add_event(self, ev: GestureEvent) -> None:
        self._last_ts = max(self._last_ts, ev.end_ts)
        tp = self._tech.get(ev.technique)
        if tp is None:
            return
        tp.event_count += 1
        tp.gesture_detected = True
        if ev.validation_status == ValidationStatus.VALIDATED:
            tp.gesture_validated = True
            tp.validated_duration_s += ev.validated_duration_s
            if ev.side in (HandSide.LEFT, HandSide.RIGHT, HandSide.BOTH) and ev.side_resolved:
                if ev.side not in tp.sides_observed:
                    tp.sides_observed.append(ev.side)
            else:
                tp.side_unresolved_duration_s += ev.validated_duration_s
        self.acc.add_event(ev)

    def snapshot(self, timestamp: float | None = None, active_candidate: dict[str, Any] | None = None) -> ProgressState:
        evidence = self.acc.evidence()
        hands: dict[HandSide, HandProgress] = {}
        cells = 0
        score = 0.0
        for side in (HandSide.LEFT, HandSide.RIGHT):
            regs = {e.region: e for e in evidence if e.side == side}
            suff = [r for r, e in regs.items() if e.status == EvidenceStatus.SUFFICIENT]
            unk = [r for r, e in regs.items() if e.status == EvidenceStatus.UNKNOWN]
            for e in regs.values():
                cells += 1
                if e.status == EvidenceStatus.SUFFICIENT:
                    score += e.confidence
            hands[side] = HandProgress(side=side, regions=regs, sufficient_regions=suff, unknown_regions=unk)
        return ProgressState(session_id=self.session_id, timestamp=self._last_ts if timestamp is None else timestamp,
                             techniques=dict(self._tech), hands=hands, coverage_estimate=(score / cells) if cells else 0.0,
                             unattributed_evidence=list(self.acc.unattributed), active_candidate=active_candidate)
