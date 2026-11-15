"""Projected game graphics: germ-dinosaurs on the hands that wash away, a glow under the active
hand, and a basin-anchored step strip. Produces RenderItems in projector pixels, so the Pi draws
exactly what the laptop previews.

Design rules (from Casper DPM, SIGGRAPH Asia 2024, adapted to a 60 Hz projector and a Wi-Fi
camera): hand-attached content is small and soft (sprites, a blurred glow, no crisp outline on
the skin); positions are extrapolated by ``lead_ms`` to hide pipeline latency; everything with
detail (prompt, step bars, stars) is drawn in a fixed strip where nothing moves.

Germs: ``germs_per_region`` per (hand, region) cell, placed at fixed offsets in the hand's own
frame (wrist->middle-MCP axis), so they ride along with the hand. A cell's germs disappear as
its region evidence grows (``observed_duration_s / min_sufficient_duration_s``); each
disappearance plays a short "pop". Nothing here changes the score or the evidence.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from convergent.common.types import HandObservation, HandSide, Region, TrackedHands
from convergent.communication.protocol import RenderItem
from convergent.regions.geometry import compute_geometry

STEP_ORDER = ["palm_to_palm", "back_of_hand", "interlaced_fingers", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing", "wrist_rubbing"]
PROMPTS = {
    "palm_to_palm": "Rub your palms together!",
    "back_of_hand": "Rub the back of each hand!",
    "interlaced_fingers": "Lace your fingers and rub!",
    "backs_of_fingers": "Rub the backs of your fingers!",
    "thumb_rubbing": "Twist around each thumb!",
    "fingertip_rubbing": "Scrub your fingertips in your palm!",
    "wrist_rubbing": "Rub each wrist!",
}
SHORT = {"palm_to_palm": "palms", "back_of_hand": "backs", "interlaced_fingers": "lace", "backs_of_fingers": "knuckles",
         "thumb_rubbing": "thumbs", "fingertip_rubbing": "tips", "wrist_rubbing": "wrists"}
GERM_COLOR = (90, 220, 90)
GLOW_ACTIVE = (255, 220, 60)
GLOW_DONE = (80, 200, 80)
REGIONS = [Region.PALM, Region.BACK_OF_HAND, Region.THUMB, Region.FINGERS, Region.FINGERTIPS]

ToProjector = Callable[[float, float], tuple[float, float] | None]


@dataclass
class GraphicsConfig:
    enabled: bool = False
    germs_per_region: int = 3
    germ_size_px: float = 20.0
    lead_ms: float = 0.0          # extrapolate hand-attached graphics by this much (measure the real latency first)
    show_ui: bool = True
    ui_height_px: int = 96
    pop_s: float = 0.5
    sprite: str = "dino"
    green_only: bool = False      # hand graphics in the projector's green light only (projection-proof tracking)
    # coverage scene (projection/coverage.py)
    hold_s: float = 0.4           # keep a lost hand's graphics this long, fading out
    flip_facing: bool = False     # palm/back come out reversed when the tracker's left/right is reversed


@dataclass
class _Germ:
    offset: np.ndarray  # (2,) in hand-length units, hand frame
    angle: float
    popped_at: float | None = None
    last_xy: tuple[float, float] | None = None


@dataclass
class _HandTrack:
    centroid: np.ndarray
    ts: float
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2))


class GermScene:
    def __init__(self, cfg: GraphicsConfig, min_sufficient_s: float = 3.0, canvas: tuple[int, int] = (854, 480), seed: int = 7) -> None:
        self.cfg = cfg
        self.enabled = cfg.enabled
        self.min_sufficient_s = max(min_sufficient_s, 1e-3)
        self.canvas = canvas
        rng = np.random.default_rng(seed)
        self._germs: dict[tuple[HandSide, Region], list[_Germ]] = {}
        for side in (HandSide.LEFT, HandSide.RIGHT, HandSide.UNKNOWN):
            for region in REGIONS:
                self._germs[(side, region)] = [_Germ(rng.uniform(-0.12, 0.12, size=2), float(rng.uniform(0, 360))) for _ in range(cfg.germs_per_region)]
        self._tracks: dict[int, _HandTrack] = {}
        self.germs_alive = 0
        self.germs_total = 0

    # ---- evidence -> how many germs stay
    def _fraction(self, progress: object | None, side: HandSide, region: Region) -> float:
        """0 = nothing seen on that cell, 1 = sufficient evidence."""
        if progress is None:
            return 0.0
        hands = getattr(progress, "hands", {}) or {}
        sides = [HandSide.LEFT, HandSide.RIGHT] if side not in (HandSide.LEFT, HandSide.RIGHT) else [side]
        fr = []
        for s in sides:
            hp = hands.get(s) or hands.get(s.value)
            if hp is None:
                continue
            ev = hp.regions.get(region) if isinstance(hp.regions, dict) else None
            if ev is None:
                ev = hp.regions.get(region.value) if isinstance(hp.regions, dict) else None
            if ev is None:
                fr.append(0.0)
                continue
            status = getattr(ev, "status", None)
            status = getattr(status, "value", status)
            if status == "sufficient":
                fr.append(1.0)
            else:
                fr.append(min(1.0, float(getattr(ev, "observed_duration_s", 0.0)) / self.min_sufficient_s))
        return max(fr) if fr else 0.0

    # ---- per hand
    def _lead(self, hand: HandObservation, centroid: np.ndarray, ts: float) -> np.ndarray:
        tr = self._tracks.get(hand.track_id)
        if tr is not None and ts > tr.ts:
            v = (centroid - tr.centroid) / (ts - tr.ts)
            tr.velocity = 0.6 * tr.velocity + 0.4 * v
            tr.centroid, tr.ts = centroid, ts
        else:
            tr = self._tracks[hand.track_id] = _HandTrack(centroid, ts)
        return tr.velocity * (self.cfg.lead_ms / 1000.0)

    def _col(self, color: tuple[int, int, int] | list[int]) -> list[int]:
        """Hand graphics colour. With green_only: pure green at the same brightness, so the camera's red and blue stay clean."""
        return [0, max(color), 0] if self.cfg.green_only else list(color)

    def _hand_items(self, hand: HandObservation, progress: object | None, ts: float, to_proj: ToProjector, active: bool) -> list[RenderItem]:
        geo = compute_geometry(hand)
        lm = hand.landmark_array()[:, :2]
        wrist, mcp = lm[0], lm[9]
        axis = mcp - wrist
        n = np.linalg.norm(axis)
        if n < 1e-6:
            return []
        u = axis / n
        v = np.array([-u[1], u[0]])
        shift = self._lead(hand, geo.hand_centroid, ts)
        angle = math.degrees(math.atan2(u[1], u[0]))
        items: list[RenderItem] = []
        # glow under the hand (soft, tolerant of misalignment)
        c = geo.hand_centroid + shift
        p = to_proj(float(c[0]), float(c[1]))
        if p is not None:
            items.append(RenderItem("sprite", x=p[0], y=p[1], radius=self.cfg.germ_size_px * 3.2, sprite="blob",
                                    color=self._col(GLOW_ACTIVE if active else GLOW_DONE), alpha=0.45 if active else 0.25))
        side = hand.side if hand.side in (HandSide.LEFT, HandSide.RIGHT) else HandSide.UNKNOWN
        for region in REGIONS:
            poly = geo.polygons.get(region)
            if poly is None or poly.support < 0.3:
                continue
            frac = self._fraction(progress, side, region)
            germs = self._germs[(side, region)]
            alive_n = int(math.ceil(len(germs) * (1.0 - frac) - 1e-6))
            for i, g in enumerate(germs):
                pos = poly.anchor + (g.offset[0] * u + g.offset[1] * v) * geo.hand_length + shift
                p = to_proj(float(pos[0]), float(pos[1]))
                if p is None:
                    continue
                g.last_xy = p
                self.germs_total += 1
                if i < alive_n:
                    g.popped_at = None
                    self.germs_alive += 1
                    wiggle = 12.0 * math.sin(ts * 6.0 + i * 1.7)
                    items.append(RenderItem("sprite", x=p[0], y=p[1], radius=self.cfg.germ_size_px, sprite=self.cfg.sprite,
                                            angle=angle + wiggle, color=self._col(GERM_COLOR), anchor_id=f"{side.value}:{region.value}:{i}"))
                else:
                    if g.popped_at is None:
                        g.popped_at = ts
                    age = ts - g.popped_at
                    if age < self.cfg.pop_s:
                        items.append(RenderItem("sprite", x=p[0], y=p[1], radius=self.cfg.germ_size_px, sprite="pop", progress=age / self.cfg.pop_s,
                                                color=self._col([255, 240, 120])))
        return items

    # ---- fixed strip
    def _ui_items(self, score: object | None, soap: object | None, active_technique: str | None) -> list[RenderItem]:
        w, h = self.canvas
        top = h - self.cfg.ui_height_px
        items: list[RenderItem] = [RenderItem("filled_polygon", points=[[0, top], [w, top], [w, h], [0, h]], color=[0, 0, 0], alpha=0.55)]
        if score is None:
            items.append(RenderItem("text", x=16, y=top + 10, label="Show me your hands!", size=28, color=[255, 255, 255]))
            return items
        steps = {st.technique: st for st in score.steps}
        nxt = score.next_step
        prompt = "All done! Great washing!" if score.finished and score.steps_done >= 7 else PROMPTS.get(active_technique or nxt or "", "Keep washing!")
        if active_technique and steps.get(active_technique) is not None and not steps[active_technique].done:
            prompt = "Keep going: " + PROMPTS.get(active_technique, "")
        items.append(RenderItem("text", x=16, y=top + 8, label=prompt, size=26, color=[255, 255, 255]))
        # 7 step bars
        bw, gap, x0, y0 = (w - 32 - 6 * 8) / 7.0, 8.0, 16.0, top + 48.0
        for i, t in enumerate(STEP_ORDER):
            st = steps.get(t)
            frac = 0.0 if st is None else min(1.0, st.seconds / max(score.step_min_s, 1e-6))
            col = GLOW_DONE if (st is not None and st.done) else (GLOW_ACTIVE if t in (active_technique, nxt) else (160, 160, 160))
            x = x0 + i * (bw + gap)
            items.append(RenderItem("bar", x=x, y=y0, size=bw, radius=14, progress=frac, color=list(col), alpha=0.9))
            items.append(RenderItem("text", x=x + 2, y=y0 + 16, label=SHORT[t], size=13, color=list(col)))
        # stars + soap
        for i in range(5):
            items.append(RenderItem("text", x=w - 150 + i * 24, y=top + 6, label="*", size=30, color=[255, 215, 0] if i < score.stars else [90, 90, 90]))
        if soap is not None and getattr(soap, "seen", False):
            items.append(RenderItem("text", x=w - 150, y=top + 40 - 8, label="soap ok", size=14, color=[90, 220, 90]))
        return items

    def build(self, hands: TrackedHands, progress: object | None, score: object | None, soap: object | None, ts: float,
              to_proj: ToProjector, active_technique: str | None = None) -> list[RenderItem]:
        self.germs_alive = self.germs_total = 0
        items: list[RenderItem] = []
        for hand in hands.hands + hands.unassigned:
            items += self._hand_items(hand, progress, ts, to_proj, active=active_technique is not None)
        if self.cfg.show_ui:
            items += self._ui_items(score, soap, active_technique)
        return items

    def reset(self) -> None:
        for germs in self._germs.values():
            for g in germs:
                g.popped_at = None
        self._tracks.clear()
