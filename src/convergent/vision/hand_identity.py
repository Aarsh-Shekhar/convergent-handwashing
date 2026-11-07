"""Stable hand identity across frames.

MediaPipe returns hands in an arbitrary order with a handedness label. The upstream
HandHygiene code assigned right/left purely from that order in the two-hand case, which is
wrong whenever MediaPipe lists the left hand first. This module resolves identity with:

1. **Spatial/temporal association** – detections are matched to existing tracks by
   centroid distance (Hungarian assignment), so a hand keeps its ``track_id`` while it
   moves, including when the hands cross.
2. **Handedness fusion** – each track keeps a running vote of MediaPipe's (swapped, see
   tracker config) anatomical label weighted by its confidence. The track's side is the
   dominant vote, which is robust to single-frame handedness flips.
3. **Uniqueness** – at most one LEFT and one RIGHT per frame. If two detections claim
   the same side, the one with the stronger evidence keeps it; the other takes the opposite
   side only if its own handedness confidence is below ``handedness_trust_threshold``,
   otherwise it is reported as *unassigned* (side UNKNOWN) rather than guessed.

Nothing here infers depth from ``z``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from convergent.common.types import HandSide


@dataclass(eq=False)
class RawHandDetection:
    """Backend-agnostic detection for one frame (before identity resolution)."""

    landmarks: np.ndarray  # (21,3) normalized
    raw_label: str  # MediaPipe label: "Left" | "Right"
    handedness_score: float
    anatomical_side: HandSide  # after configured swap
    world_landmarks: np.ndarray | None = None
    presence_score: float | None = None

    @property
    def centroid(self) -> np.ndarray:
        return self.landmarks[:, :2].mean(axis=0)


@dataclass
class _Track:
    track_id: int
    centroid: np.ndarray
    last_ts: float
    votes: dict[HandSide, float] = field(default_factory=lambda: {HandSide.LEFT: 0.0, HandSide.RIGHT: 0.0})
    hits: int = 0

    @property
    def side(self) -> HandSide:
        l, r = self.votes[HandSide.LEFT], self.votes[HandSide.RIGHT]
        if l == r == 0.0:
            return HandSide.UNKNOWN
        return HandSide.LEFT if l > r else HandSide.RIGHT

    @property
    def side_margin(self) -> float:
        l, r = self.votes[HandSide.LEFT], self.votes[HandSide.RIGHT]
        tot = l + r
        return 0.0 if tot == 0 else abs(l - r) / tot


@dataclass(eq=False)
class ResolvedHand:
    detection: RawHandDetection
    track_id: int
    side: HandSide  # LEFT / RIGHT / UNKNOWN
    side_confidence: float
    track_age: int


class HandIdentityResolver:
    def __init__(
        self,
        max_jump: float = 0.35,
        max_gap_s: float = 0.5,
        handedness_trust_threshold: float = 0.8,
        vote_decay: float = 0.85,
    ) -> None:
        self.max_jump = max_jump
        self.max_gap_s = max_gap_s
        self.trust = handedness_trust_threshold
        self.vote_decay = vote_decay
        self._tracks: dict[int, _Track] = {}
        self._next_id = 0

    def reset(self) -> None:
        self._tracks.clear()

    @property
    def active_tracks(self) -> int:
        return len(self._tracks)

    def update(self, detections: list[RawHandDetection], ts: float) -> list[ResolvedHand]:
        # 1. expire stale tracks
        for tid in [t for t, tr in self._tracks.items() if ts - tr.last_ts > self.max_gap_s]:
            del self._tracks[tid]
        # 2. association
        tracks = list(self._tracks.values())
        assigned: dict[int, _Track] = {}
        if tracks and detections:
            cost = np.zeros((len(detections), len(tracks)), dtype=np.float64)
            for i, det in enumerate(detections):
                for j, tr in enumerate(tracks):
                    d = float(np.linalg.norm(det.centroid - tr.centroid))
                    # handedness disagreement with a confident track adds cost but does not forbid
                    penalty = 0.0
                    if tr.side != HandSide.UNKNOWN and tr.side != det.anatomical_side:
                        penalty = 0.15 * tr.side_margin * det.handedness_score
                    cost[i, j] = d + penalty
            rows, cols = linear_sum_assignment(cost)
            for i, j in zip(rows, cols, strict=True):
                if cost[i, j] <= self.max_jump:
                    assigned[i] = tracks[j]
        # 3. new tracks for unmatched detections
        resolved: list[ResolvedHand] = []
        for i, det in enumerate(detections):
            tr = assigned.get(i)
            if tr is None:
                tr = _Track(track_id=self._next_id, centroid=det.centroid.copy(), last_ts=ts)
                self._next_id += 1
                self._tracks[tr.track_id] = tr
            # vote update (decay + new evidence)
            for k in tr.votes:
                tr.votes[k] *= self.vote_decay
            if det.anatomical_side in (HandSide.LEFT, HandSide.RIGHT):
                tr.votes[det.anatomical_side] += det.handedness_score
            tr.centroid = det.centroid.copy()
            tr.last_ts = ts
            tr.hits += 1
            resolved.append(
                ResolvedHand(
                    detection=det,
                    track_id=tr.track_id,
                    side=tr.side,
                    side_confidence=tr.side_margin,
                    track_age=tr.hits,
                )
            )
        # 4. uniqueness
        return self._enforce_unique_sides(resolved)

    def _enforce_unique_sides(self, hands: list[ResolvedHand]) -> list[ResolvedHand]:
        if len(hands) <= 1:
            return hands
        by_side: dict[HandSide, list[ResolvedHand]] = {}
        for h in hands:
            by_side.setdefault(h.side, []).append(h)
        for side in (HandSide.LEFT, HandSide.RIGHT):
            group = by_side.get(side, [])
            if len(group) <= 1:
                continue
            group.sort(key=lambda h: (h.side_confidence * h.detection.handedness_score, h.track_age), reverse=True)
            winner, losers = group[0], group[1:]
            other = HandSide.RIGHT if side == HandSide.LEFT else HandSide.LEFT
            loser_ids = {id(h) for h in losers}
            other_taken = any(h.side == other for h in hands if h is not winner and id(h) not in loser_ids)
            for loser in losers:
                if not other_taken and loser.detection.handedness_score < self.trust:
                    loser.side = other
                    loser.side_confidence = min(loser.side_confidence, 1.0 - loser.detection.handedness_score)
                    other_taken = True
                else:
                    loser.side = HandSide.UNKNOWN
                    loser.side_confidence = 0.0
        return hands
