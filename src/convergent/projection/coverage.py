"""Coverage scene: germs all over the hands that go down as each part is washed. No guide, any order.

Every germ sits on one spot of the hand and belongs to the wash step that cleans that spot. The palm
side and the back side are two different sets (the palm's germs go with "palm to palm", the same
spots on the back go with "back of hand"), and the side facing the camera is the one drawn. As a
step's timer fills toward ``step_min_s`` its germs pop one by one, so what is left on the hands is
what has not been washed long enough. That is the same record the wash score gives the parents' app.

A spot is a fixed mix of the 21 hand points (weights sum to 1), so a germ moves, turns, scales and
bends with the hand. Smoothness: every hand's points go through a One Euro filter, a hand the
tracker loses is held for ``hold_s`` and faded out, and the shown progress rises at most ``_RATE``
per second. The slim bar at the top (germs left, a ring per part with its seconds, stars) keeps clear of the hands.

"Popped" means the recognized step ran long enough. It is not contact detection, and both hands
clear together. Nothing here changes score or evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from convergent.common.types import TrackedHands
from convergent.communication.protocol import RenderItem
from convergent.projection.scene import GermScene, GraphicsConfig, ToProjector
from convergent.projection.smoothing import OneEuroFilter
from convergent.projection.sprites import GERMS
from convergent.regions.geometry import palm_facing_camera

PALM, BACK = 0, 1
STEPS = ["palm_to_palm", "back_of_hand", "interlaced_fingers", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing", "wrist_rubbing"]
P2P, BOH, INT, BOF, THB, TIP, WRI = STEPS
# (weights over the 21 hand points, germ radius in hand lengths, the step that cleans it on the palm side, on the back side)
SPOTS: list[tuple[dict[int, float], float, str, str]] = [
    ({0: .2, 5: .2, 9: .2, 13: .2, 17: .2}, .17, P2P, BOH), ({5: .55, 0: .45}, .13, P2P, BOH), ({17: .55, 0: .45}, .13, P2P, BOH), ({9: .7, 13: .3}, .11, P2P, BOH),
    ({5: .45, 6: .55}, .10, INT, BOF), ({9: .45, 10: .55}, .10, INT, BOF), ({13: .45, 14: .55}, .10, INT, BOF), ({17: .45, 18: .55}, .09, INT, BOF),
    ({6: .3, 7: .7}, .09, INT, BOF), ({10: .3, 11: .7}, .09, INT, BOF), ({14: .3, 15: .7}, .09, INT, BOF),
    ({2: .5, 3: .5}, .12, THB, THB), ({3: .35, 4: .65}, .10, THB, THB),
    ({8: 1.}, .085, TIP, TIP), ({12: 1.}, .085, TIP, TIP), ({16: 1.}, .085, TIP, TIP), ({20: 1.}, .08, TIP, TIP),
    ({0: 1.3, 9: -.3}, .13, WRI, WRI), ({0: 1.2, 5: -.2}, .10, WRI, WRI), ({0: 1.2, 17: -.2}, .10, WRI, WRI),
]
COLOURS = {"jelly": (120, 235, 95), "spiky": (215, 120, 255), "fuzzy": (255, 170, 60)}
_rng = np.random.default_rng(4)
KIND = [GERMS[i % len(GERMS)] for i in _rng.permutation(len(SPOTS))]  # which germ lives on each spot
POP_AT: dict[tuple[int, int], float] = {}  # (side, spot) -> the step progress at which that germ pops
for _side in (PALM, BACK):
    for _step in STEPS:
        _idx = [i for i, s in enumerate(SPOTS) if s[2 + _side] == _step]
        for _rank, _i in enumerate(_rng.permutation(_idx)):
            POP_AT[(_side, int(_i))] = 0.15 + 0.85 * (_rank + 1) / len(_idx)

_REF = 640.0      # the filter works in pixels of a 640 px wide picture
# One Euro settings, measured on 6 saved live runs (8,275 frames, palm centre): slow-hand jitter x0.63 of raw, lag while moving
# 1.8 px median / 4.2 px p90. beta 0.05: x0.72 and 0.8 px. beta 0.01: x0.57 and 3.1 px.
_MIN_CUTOFF, _BETA = 0.25, 0.02
_RATE = 1.0       # shown progress per second at most, so germs never all pop in one frame
_FACE_FRAMES = 3  # palm/back flips after this many agreeing frames
_EDGE_ON = 0.15   # hand seen edge-on below this (knuckle triangle area / palm length^2): keep the current side
_POP_S = 0.6


@dataclass
class _Hand:
    filt: OneEuroFilter
    xy: np.ndarray  # (21, 2) filtered points, in _REF units
    ts: float
    face: int | None = None
    pending: int = 0


class CoverageScene(GermScene):
    def __init__(self, cfg: GraphicsConfig, min_sufficient_s: float = 3.0, canvas: tuple[int, int] = (854, 480), seed: int = 7) -> None:
        super().__init__(cfg, min_sufficient_s, canvas, seed)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._hands: dict[int, _Hand] = {}
        self._shown = dict.fromkeys(STEPS, 0.0)            # rate-limited copy of each step's progress
        self._popped: dict[tuple[int, int, int], float] = {}  # (track, side, spot) -> when its burst started
        self._last_ts: float | None = None

    @property
    def germs_left(self) -> int:
        """Germs not washed off yet on two hands, both sides (does not depend on what the camera sees right now)."""
        return 2 * sum(self._shown[SPOTS[i][2 + side]] < at for (side, i), at in POP_AT.items())

    # ---- tracking: filter, hold, palm/back
    def _facing(self, lm: np.ndarray, side: object) -> int | None:
        w, i, p = lm[0, :2], lm[5, :2], lm[17, :2]
        cross = (i[0] - w[0]) * (p[1] - w[1]) - (i[1] - w[1]) * (p[0] - w[0])
        if abs(cross) < _EDGE_ON * float(np.sum((lm[9, :2] - w) ** 2)):
            return None
        f = palm_facing_camera(lm, side)  # type: ignore[arg-type]
        return None if f is None else (PALM if f != self.cfg.flip_facing else BACK)

    def _track(self, hands: TrackedHands, ts: float) -> None:
        for h in hands.hands + hands.unassigned:
            tr = self._hands.get(h.track_id)
            if tr is None or ts - tr.ts > self.cfg.hold_s:  # new hand or long gap: start the filter fresh
                tr = self._hands[h.track_id] = _Hand(OneEuroFilter(_MIN_CUTOFF, _BETA), np.zeros((21, 2)), ts, tr.face if tr else None)
            lm = h.landmark_array()
            tr.xy, tr.ts = tr.filt.update(lm[:, :2] * _REF, ts), ts
            f = self._facing(lm, h.side)
            if f is None or f == tr.face:
                tr.pending = 0
            elif tr.face is None or tr.pending + 1 >= _FACE_FRAMES:
                tr.face, tr.pending = f, 0
            else:
                tr.pending += 1
        for tid in [t for t, tr in self._hands.items() if ts - tr.ts > self.cfg.hold_s]:
            del self._hands[tid]
            self._popped = {k: v for k, v in self._popped.items() if k[0] != tid}

    # ---- drawing
    def _hand_items(self, tid: int, tr: _Hand, ts: float, to_proj: ToProjector, washing: str | None) -> list[RenderItem]:  # type: ignore[override]
        def proj(pt: np.ndarray) -> np.ndarray | None:
            p = to_proj(float(pt[0] / _REF), float(pt[1] / _REF))
            return None if p is None else np.array(p)

        lo, hi = proj(np.clip(tr.xy.min(axis=0), 0, _REF - 1)), proj(np.clip(tr.xy.max(axis=0), 0, _REF - 1))
        if lo is None or hi is None:
            return []
        # 0.32 x the larger side of the hand's outline box: about wrist-to-knuckle for an open hand, and it does not
        # collapse when the hand is seen end-on (palms together in front of the camera)
        length = 0.32 * float(np.abs(hi - lo).max())
        fade = 1.0 - (ts - tr.ts) / self.cfg.hold_s
        face = PALM if tr.face is None else tr.face
        items: list[RenderItem] = []
        for i, (wts, frac, *by) in enumerate(SPOTS):
            step, kind = by[face], KIND[i]
            pos = proj(sum(tr.xy[j] * w for j, w in wts.items()))
            if pos is None or length < 4:
                continue
            col = [0, 150, 0] if self.cfg.green_only else list(COLOURS[kind])  # dimmer body in green: the eye still stands out
            radius = frac * length
            self.germs_total += 1
            if self._shown[step] < POP_AT[(face, i)]:
                self.germs_alive += 1
                scared = washing == step
                drift = 0.035 * length * np.array([math.sin(1.7 * ts + i), math.cos(2.1 * ts + 1.3 * i)])  # the colony looks alive
                shake = 0.02 * length * np.array([math.sin(31 * ts + i), math.cos(27 * ts + i)]) if scared else 0.0
                sprite = f"{kind}_scared" if scared else (f"{kind}_blink" if (ts + 0.9 * i) % 2.8 < 0.13 else kind)
                x, y = pos + drift + shake
                items.append(RenderItem("sprite", x=float(x), y=float(y), radius=radius, sprite=sprite, color=col, alpha=fade,
                                        progress=(ts * 1.25 + 0.31 * i) % 1.0, anchor_id=f"{tid}:{step}:{i}"))
                continue
            age = ts - self._popped.setdefault((tid, face, i), ts)
            if age < _POP_S:
                items.append(RenderItem("sprite", x=float(pos[0]), y=float(pos[1]), radius=radius, sprite="burst", color=col, alpha=fade, progress=age / _POP_S))
            elif (tw := (0.35 * ts + 0.37 * i) % 1.0) < 0.18:  # clean skin twinkles now and then
                items.append(RenderItem("sprite", x=float(pos[0]), y=float(pos[1]), radius=0.6 * radius, sprite="twinkle",
                                        color=self._col((255, 255, 255)), alpha=fade, progress=tw / 0.18))
        return items

    def _bar(self, score: object) -> RenderItem:
        w, _h = self.canvas
        width = min(w - 40.0, max(0.58 * w, 560.0))
        steps = {s.technique: s for s in score.steps}  # type: ignore[attr-defined]
        return RenderItem("hud", x=(w - width) / 2, y=0.02 * w, size=width, label=str(self.germs_left), progress=score.stars / 5,  # type: ignore[attr-defined]
                          points=[[round(min(1.0, steps[s].seconds / max(score.step_min_s, 1e-6)), 3), round(steps[s].seconds, 1)] for s in STEPS],  # type: ignore[attr-defined]
                          color=self._col((120, 240, 170)))

    def build(self, hands: TrackedHands, progress: object | None, score: object | None, soap: object | None, ts: float,  # noqa: ARG002
              to_proj: ToProjector, active_technique: str | None = None) -> list[RenderItem]:
        self.germs_alive = self.germs_total = 0
        dt = 0.0 if self._last_ts is None else max(0.0, ts - self._last_ts)
        self._last_ts = ts
        if score is not None:
            for st in score.steps:  # type: ignore[attr-defined]
                if st.technique in self._shown:
                    cur = self._shown[st.technique]
                    self._shown[st.technique] = max(cur, min(st.seconds / max(score.step_min_s, 1e-6), cur + _RATE * dt, 1.0))  # type: ignore[attr-defined]
        self._track(hands, ts)
        items: list[RenderItem] = []
        for tid, tr in self._hands.items():
            items += self._hand_items(tid, tr, ts, to_proj, active_technique)
        if self.cfg.show_ui and score is not None:
            items.append(self._bar(score))
        return items
