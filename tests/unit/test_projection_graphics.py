"""Projected game graphics: sprites through the render protocol, germ scene behaviour, preview compose."""

from __future__ import annotations

import json

import numpy as np
from PIL import Image

from convergent.common.types import HandObservation, HandSide, TrackedHands, VisibilityState
from convergent.communication.protocol import RenderCommand, RenderItem
from convergent.pi_agent.renderer import render_canvas
from convergent.projection.scene import GermScene, GraphicsConfig
from convergent.projection.sprites import draw_sprite


def hand(cx: float, cy: float, track_id: int = 1, side: HandSide = HandSide.RIGHT) -> HandObservation:
    # an open hand: wrist at the bottom, fingers up, roughly 0.3 image units tall
    rng = np.random.default_rng(track_id)
    base = np.array([[0.0, 0.0], [-0.08, -0.05], [-0.13, -0.11], [-0.16, -0.16], [-0.18, -0.2],
                     [-0.05, -0.17], [-0.06, -0.24], [-0.06, -0.29], [-0.06, -0.33],
                     [0.0, -0.18], [0.0, -0.26], [0.0, -0.31], [0.0, -0.35],
                     [0.05, -0.17], [0.06, -0.24], [0.06, -0.29], [0.06, -0.32],
                     [0.1, -0.15], [0.12, -0.2], [0.13, -0.24], [0.14, -0.27]])
    pts = np.c_[base + [cx, cy] + rng.normal(0, 0.002, base.shape), np.zeros(21)]
    return HandObservation.from_array(pts, side=side, visibility=VisibilityState.VISIBLE, tracking_quality=0.9, track_id=track_id, handedness_confidence=0.8)


def tracked(ts: float, hands: list[HandObservation]) -> TrackedHands:
    return TrackedHands(frame_id=int(ts * 15), capture_ts=ts, unassigned=hands, processing_time_ms=1.0)


IDENTITY = lambda xn, yn: (xn * 854, yn * 480)  # noqa: E731


def test_sprite_items_survive_the_wire_and_render():
    items = [RenderItem("sprite", x=100, y=100, radius=20, sprite="dino", angle=30, alpha=0.8),
             RenderItem("sprite", x=300, y=200, radius=50, sprite="blob", alpha=0.5),
             RenderItem("sprite", x=500, y=100, radius=20, sprite="pop", progress=0.3),
             RenderItem("bar", x=10, y=400, size=200, radius=12, progress=0.5), RenderItem("text", x=10, y=10, label="hi", size=24),
             RenderItem("filled_polygon", points=[[0, 380], [854, 380], [854, 480], [0, 480]], alpha=0.5)]
    cmd = RenderCommand(seq=1, command="draw", calibration_profile_id=None, calibration_version=None, canvas_width=854, canvas_height=480, items=items)
    back = RenderCommand.from_message(json.loads(cmd.to_message()))
    assert [i.sprite for i in back.items][:3] == ["dino", "blob", "pop"] and back.items[0].angle == 30
    img = render_canvas(back)
    assert img.shape == (480, 854, 3) and img[100, 100].sum() > 0 and img[200, 300].sum() > 0


def test_unknown_sprite_is_rejected():
    import pytest

    from convergent.communication.protocol import ProtocolError

    with pytest.raises(ProtocolError):
        RenderItem("sprite", x=1, y=1, sprite="mouse")
    with pytest.raises(ValueError):
        draw_sprite(Image.new("RGBA", (10, 10)), "mouse", 5, 5, 3)


def test_germs_ride_with_the_hand_and_die_with_evidence():
    from convergent.common.types import EvidenceStatus, Region, RegionEvidence
    from convergent.regions.progress import HandProgress, ProgressState

    scene = GermScene(GraphicsConfig(enabled=True, germs_per_region=3, show_ui=False), min_sufficient_s=3.0)
    items0 = scene.build(tracked(0.0, [hand(0.5, 0.7)]), None, None, None, 0.0, IDENTITY)
    germs0 = [i for i in items0 if i.sprite == "dino"]
    assert len(germs0) == 15 and scene.germs_alive == 15  # 5 regions x 3, nothing washed yet
    # the hand moves right by 0.1: every germ moves with it
    items1 = scene.build(tracked(0.1, [hand(0.6, 0.7)]), None, None, None, 0.1, IDENTITY)
    germs1 = {i.anchor_id: i for i in items1 if i.sprite == "dino"}
    for g in germs0:
        assert abs(germs1[g.anchor_id].x - g.x - 0.1 * 854) < 2.0 and abs(germs1[g.anchor_id].y - g.y) < 2.0
    # palm sufficient, thumb half-way: palm germs gone (pop plays), thumb loses half
    ev = {Region.PALM: RegionEvidence(region=Region.PALM, side=HandSide.RIGHT, observed_duration_s=5.0, confidence=1.0, status=EvidenceStatus.SUFFICIENT),
          Region.THUMB: RegionEvidence(region=Region.THUMB, side=HandSide.RIGHT, observed_duration_s=1.5, confidence=1.0, status=EvidenceStatus.INSUFFICIENT)}
    prog = ProgressState(session_id="s", timestamp=0.2, hands={HandSide.RIGHT: HandProgress(side=HandSide.RIGHT, regions=ev, sufficient_regions=[Region.PALM], unknown_regions=[])},
                         coverage_estimate=0.1, techniques={})
    items2 = scene.build(tracked(0.2, [hand(0.6, 0.7)]), prog, None, None, 0.2, IDENTITY)
    alive = [i.anchor_id for i in items2 if i.sprite == "dino"]
    assert not any(a.startswith("right:palm") for a in alive)
    assert sum(a.startswith("right:thumb") for a in alive) == 2
    assert sum(i.sprite == "pop" for i in items2) == 3 + 1  # 3 palm germs + 1 thumb germ popping
    items3 = scene.build(tracked(1.0, [hand(0.6, 0.7)]), prog, None, None, 1.0, IDENTITY)
    assert not any(i.sprite == "pop" for i in items3)  # pop is over after pop_s


def test_lead_time_extrapolates_along_the_motion():
    cfg = GraphicsConfig(enabled=True, germs_per_region=1, show_ui=False, lead_ms=200)
    a, b = GermScene(cfg), GermScene(GraphicsConfig(enabled=True, germs_per_region=1, show_ui=False, lead_ms=0))
    for t in range(5):  # hand moving right at 0.5 image/s
        ia = a.build(tracked(t / 10, [hand(0.3 + 0.05 * t, 0.7)]), None, None, None, t / 10, IDENTITY)
        ib = b.build(tracked(t / 10, [hand(0.3 + 0.05 * t, 0.7)]), None, None, None, t / 10, IDENTITY)
    ga = next(i for i in ia if i.sprite == "dino")
    gb = next(i for i in ib if i.sprite == "dino")
    assert ga.x > gb.x + 20  # led forward by ~0.5 * 0.2 * 854 ~ 85 px (velocity is smoothed)


def test_ui_strip_reflects_the_score():
    from convergent.scoring.wash_score import WashScorer

    sc = WashScorer()
    score = sc.update(0.0)
    scene = GermScene(GraphicsConfig(enabled=True, show_ui=True))
    items = scene.build(tracked(0.0, []), None, score, None, 0.0, IDENTITY)
    labels = [i.label for i in items if i.shape == "text"]
    assert any("palms" in lb.lower() for lb in labels)  # first WHO step prompt
    assert sum(i.shape == "bar" for i in items) == 7
