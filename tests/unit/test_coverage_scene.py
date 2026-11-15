"""The coverage scene (projection/coverage.py): germs over the whole hand that go down as each part is washed,
its sprite sheets and top bar (projection/sprites.py), and the solid "sticker" look of the game window."""

from __future__ import annotations

from collections import Counter

import numpy as np
from PIL import Image

from convergent.common.types import HandObservation, HandSide, VisibilityState
from convergent.communication.protocol import RenderCommand
from convergent.pi_agent.renderer import render_canvas
from convergent.projection.coverage import SPOTS, CoverageScene
from convergent.projection.scene import GraphicsConfig
from convergent.projection.sprites import GERMS, SHEETS, draw_sprite
from convergent.scoring.wash_score import StepTime, WashScore
from tests.unit.test_projection_graphics import IDENTITY, hand, tracked

STEPS = ["palm_to_palm", "back_of_hand", "interlaced_fingers", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing", "wrist_rubbing"]
DT = 1 / 15
# the test hand (side RIGHT, fingers up) shows its back to the camera, so its palm spots belong to "back_of_hand"
BACK_PARTS = {"back_of_hand", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing", "wrist_rubbing"}


def score(secs: dict[str, float], step_min: float = 3.0) -> WashScore:
    steps = [StepTime(technique=t, seconds=secs.get(t, 0.0), done=secs.get(t, 0.0) >= step_min, points=0.0) for t in STEPS]
    return WashScore(timestamp=0.0, steps=steps, steps_done=sum(s.done for s in steps), steps_required=5, step_min_s=step_min,
                     total_s=sum(secs.values()), total_min_s=20.0, finished=False, points=0, stars=2)


def scene(**kw) -> CoverageScene:  # type: ignore[no-untyped-def]
    return CoverageScene(GraphicsConfig(enabled=True, **{"show_ui": False, **kw}))


def play(sc: CoverageScene, seconds: float, hands_at, secs: dict[str, float] | None = None, t0: float = 0.0, active: str | None = None):  # type: ignore[no-untyped-def]
    """Build frames for ``seconds``; ``hands_at(t)`` gives that frame's hands. Returns (end time, last items)."""
    t, items = t0, []
    while t < t0 + seconds - 1e-9:
        t += DT
        items = sc.build(tracked(t, hands_at(t)), None, score(secs or {}), None, t, IDENTITY, active_technique=active)
    return t, items


def germs(items):  # type: ignore[no-untyped-def]
    return [i for i in items if i.sprite.split("_")[0] in GERMS]


def parts(items) -> Counter:  # type: ignore[no-untyped-def]
    return Counter(i.anchor_id.split(":")[1] for i in germs(items))


def layer_of(kind: str, color=(0, 150, 0), progress: float = 0.0, xy=(100, 100), size: float = 30.0) -> np.ndarray:  # type: ignore[no-untyped-def]
    layer = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw_sprite(layer, kind, xy[0], xy[1], size, 0.0, color, 1.0, progress)
    return np.asarray(layer)


STILL = lambda t: [hand(0.5, 0.7)]  # noqa: E731


# ---------------------------------------------------------------- sprite sheets
def test_every_sheet_draws_and_a_green_tint_stays_pure_green():
    assert all(f"{g}{suffix}" in SHEETS for g in GERMS for suffix in ("", "_blink", "_scared"))
    for kind in SHEETS:
        px = layer_of(kind, progress=0.5 if kind == "twinkle" else 0.0)  # the twinkle peaks half way, the burst starts full
        assert px[..., 3].max() > 200, kind
        assert px[..., 0].max() == 0 and px[..., 2].max() == 0, kind  # no red or blue light from a green germ, eyes included
    purple = layer_of("spiky", color=(215, 120, 255))
    assert (purple[..., :3].min(axis=-1) > 240).any()  # in colour the eye is white


def test_sheets_carry_a_dark_edge_that_adds_no_light():
    px = layer_of("jelly", color=(120, 235, 95))
    edge = (px[..., 3] > 40) & (px[..., :3].max(axis=-1) < 30)  # covered but dark: the sticker's soft outline
    assert edge.sum() > 50


def test_germs_loop_and_the_burst_and_twinkle_play_once():
    assert not np.array_equal(layer_of("fuzzy", progress=0.0), layer_of("fuzzy", progress=0.5))
    assert np.array_equal(layer_of("fuzzy", progress=0.0), layer_of("fuzzy", progress=1.0))
    for kind in ("burst", "twinkle"):
        mid, end = layer_of(kind, progress=0.3, size=20), layer_of(kind, progress=1.0, size=20)
        assert int(end[..., 3].astype(int).sum()) < 0.35 * int(mid[..., 3].astype(int).sum()), kind


def test_sprites_may_hang_over_the_canvas_edge():
    for kind in ("spiky", "burst", "blob"):
        for xy in ((2, 2), (198, 199), (-30, 100)):
            layer_of(kind, xy=xy)  # must not raise


# ---------------------------------------------------------------- coverage
def test_germs_cover_every_part_of_the_visible_side_and_ride_with_the_hand():
    sc = scene()
    _, a = play(sc, 0.5, lambda t: [hand(0.4, 0.7)])
    assert len(germs(a)) == len(SPOTS) and set(parts(a)) == BACK_PARTS
    ys = [g.y for g in germs(a)]
    assert max(ys) - min(ys) > 0.3 * 480  # from the wrist to the fingertips, not one clump
    assert len({g.sprite for g in germs(a)} & set(GERMS)) == 3  # all three kinds
    _, b = play(sc, 1.0, lambda t: [hand(0.6, 0.7)], t0=0.5)
    assert abs(np.mean([g.x for g in germs(b)]) - np.mean([g.x for g in germs(a)]) - 0.2 * 854) < 8


def test_a_parts_germs_pop_as_its_seconds_fill_and_the_other_parts_stay():
    sc = scene()
    t, before = play(sc, 0.5, STILL)
    n = parts(before)["back_of_hand"]
    t, items = play(sc, 0.2, STILL, {"back_of_hand": 3.0}, t0=t)
    assert parts(items)["back_of_hand"] == n  # the shown progress rises at most 1.0 per second: no mass pop in one frame
    t, items = play(sc, 0.4, STILL, {"back_of_hand": 3.0}, t0=t)
    assert 0 < parts(items)["back_of_hand"] < n and any(i.sprite == "burst" for i in items)
    t, items = play(sc, 1.5, STILL, {"back_of_hand": 3.0}, t0=t)
    assert parts(items)["back_of_hand"] == 0
    assert all(parts(items)[p] == parts(before)[p] for p in BACK_PARTS - {"back_of_hand"})  # nothing else was washed


def test_palm_and_back_carry_different_parts():
    for flip, expect in ((False, BACK_PARTS), (True, {"palm_to_palm", "interlaced_fingers", "thumb_rubbing", "fingertip_rubbing", "wrist_rubbing"})):
        _, items = play(scene(flip_facing=flip), 0.5, STILL)
        assert set(parts(items)) == expect, flip


def test_germs_of_the_part_being_washed_look_scared():
    _, items = play(scene(), 0.5, STILL, active="thumb_rubbing")
    scared = {i.anchor_id.split(":")[1] for i in germs(items) if i.sprite.endswith("_scared")}
    assert scared == {"thumb_rubbing"}


def test_clean_skin_twinkles_now_and_then():
    sc = scene()
    t, _ = play(sc, 2.0, STILL, {"back_of_hand": 3.0})
    seen = 0
    for _ in range(60):
        t, items = play(sc, DT, STILL, {"back_of_hand": 3.0}, t0=t)
        seen += sum(i.sprite == "twinkle" for i in items)
    assert seen > 0


def test_a_short_tracking_dropout_does_not_blink_the_germs():
    sc = scene()
    t, items = play(sc, 0.5, STILL)
    full = germs(items)[0].alpha
    t, items = play(sc, 0.2, lambda t: [], t0=t)  # tracker lost the hand for 0.2 s
    assert len(germs(items)) == len(SPOTS) and 0.2 < germs(items)[0].alpha < full  # held and fading
    t, items = play(sc, 0.4, lambda t: [], t0=t)
    assert not germs(items)  # gone after hold_s (0.4 s)


def test_germ_positions_are_smoother_than_the_raw_hand():
    rng = np.random.default_rng(0)
    sc, xs, t = scene(), [], 0.0
    for _ in range(60):
        t += DT
        jx = float(rng.normal(0, 0.001))  # tracker jitter on a still hand (about 0.9 canvas px)
        items = sc.build(tracked(t, [hand(0.5 + jx, 0.7)]), None, score({}), None, t, IDENTITY)
        palm = next(g for g in germs(items) if g.anchor_id.endswith(":0"))
        xs.append(palm.x - 0.035 * 0)  # the germ's own slow drift is far below the jitter band measured here
    assert np.std(np.diff(xs[15:])) < 0.7 * np.sqrt(2) * 0.001 * 854


def test_hands_seen_end_on_still_get_full_size_germs():
    lm = hand(0.5, 0.7).landmark_array()
    lm[:, 1] = 0.7 + (lm[:, 1] - 0.7) * 0.2  # fingers pointing at the camera: the outline is short but still wide
    flat = HandObservation.from_array(lm, side=HandSide.RIGHT, visibility=VisibilityState.VISIBLE, tracking_quality=0.9, track_id=1, handedness_confidence=0.8)
    _, items = play(scene(), 0.5, lambda t: [flat])
    assert max(g.radius for g in germs(items)) > 10


# ---------------------------------------------------------------- top bar, colour, renderer
def test_top_bar_shows_each_parts_progress_and_the_germs_left_and_stays_off_the_hands():
    sc = scene(show_ui=True)
    _, items = play(sc, 0.5, lambda t: [])
    bar = [i for i in items if i.shape == "hud"]
    assert len(bar) == 1 and bar[0].y < 0.1 * 480 and bar[0].label == str(4 * len(SPOTS))  # two hands, two sides each
    _, items = play(sc, 1.5, lambda t: [], {"palm_to_palm": 3.0, "thumb_rubbing": 1.5}, t0=0.5)
    bar = next(i for i in items if i.shape == "hud")
    assert [p[0] for p in bar.points] == [1.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0] and bar.progress == 2 / 5  # 2 stars
    assert [p[1] for p in bar.points] == [3.0, 0.0, 0.0, 0.0, 1.5, 0.0, 0.0]  # and the seconds washed, shown in each ring
    assert int(bar.label) < 4 * len(SPOTS)
    assert not any(i.shape == "hud" for i in play(scene(), 0.2, lambda t: [])[1])  # show_ui off: no bar


def test_green_only_hand_graphics_use_no_red_or_blue_light():
    sc = scene(green_only=True)
    _, items = play(sc, 2.5, STILL, {"back_of_hand": 3.0}, active="thumb_rubbing")
    assert items and all(i.color[0] == 0 and i.color[2] == 0 for i in items)
    canvas = render_canvas(RenderCommand(seq=1, command="draw", calibration_profile_id=None, calibration_version=None, canvas_width=854, canvas_height=480, items=items))
    assert canvas[..., 1].max() > 100 and canvas[..., 0].max() == 0 and canvas[..., 2].max() == 0


def test_canvas_renders_as_light_or_as_see_through_stickers():
    _, items = play(scene(show_ui=True), 0.5, STILL)
    cmd = RenderCommand(seq=1, command="draw", calibration_profile_id=None, calibration_version=None, canvas_width=854, canvas_height=480, items=items)
    light = render_canvas(cmd)
    assert light.shape == (480, 854, 3) and light[60:].max() > 150  # germs as light on black
    layer = render_canvas(cmd, transparent=True)
    assert layer.shape == (480, 854, 4) and layer[..., 3].min() == 0 and layer[60:, :, 3].max() == 255  # see-through except where a germ is
    assert layer[:60, 200:650, 3].max() > 100  # the top bar is drawn too


def _pipe(mode: str):  # type: ignore[no-untyped-def]
    from convergent.common.config import PipelineConfig, resolve_path
    from convergent.pipeline import Pipeline
    from convergent.vision.hand_tracker import HandTracker, ScriptedBackend

    cfg = PipelineConfig.load(resolve_path("configs/development.yaml"), {"projector": {"graphics": {"enabled": True, "mode": mode}}})
    return Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend([])))


def test_pipeline_picks_the_scene_by_mode():
    from convergent.projection.scene import GermScene

    assert type(_pipe("coverage").scene) is CoverageScene and type(_pipe("dinos").scene) is GermScene


def test_game_window_draws_solid_stickers_not_light():
    from convergent.vision.overlays import ProjectionPreview

    _, items = play(scene(), 0.5, STILL)
    cmd = RenderCommand(seq=1, command="draw", calibration_profile_id=None, calibration_version=None, canvas_width=854, canvas_height=480, items=items)
    white = np.full((480, 854, 3), 255, np.uint8)  # on a white picture added light is invisible; a sticker is not
    out = ProjectionPreview(_pipe("coverage")).compose(white.copy(), cmd, clean=True)
    assert (out < 200).any() and out.shape == white.shape


def test_top_bar_writes_the_seconds_into_each_ring():
    from convergent.projection.sprites import draw_hud

    def bar(seconds: list[float]) -> np.ndarray:
        layer = Image.new("RGBA", (700, 90), (0, 0, 0, 0))
        draw_hud(layer, 10, 5, 620, [min(1.0, s / 3) for s in seconds], seconds, "40", 2)
        return np.asarray(layer)

    a, b = bar([0, 0, 0, 0, 0, 0, 0]), bar([0, 0, 0, 0, 0, 0, 0.1])
    ring7 = slice(435, 480)  # x range of the last ring (150 + 6 * 52 = 462 in bar units, plus the bar's x of 10)
    assert not np.array_equal(a[:, ring7], b[:, ring7]) and np.array_equal(a[:, :400], b[:, :400])  # only that ring changed
    bar([12.3, 45.6, 3.0, 0.4, 100.0, 7.7, 2.9])  # long times must fit without raising


def test_the_seconds_in_a_ring_are_big_enough_to_read():
    from convergent.projection.sprites import draw_hud

    def bar(seconds: list[float]) -> np.ndarray:
        layer = Image.new("RGBA", (700, 100), (0, 0, 0, 0))
        draw_hud(layer, 10, 5, 620, [1.0] * 7, seconds, "40", 2)  # all rings full, so only the numbers differ
        return np.asarray(layer).astype(int)

    ys, xs = np.nonzero(np.abs(bar([19.0] + [0.0] * 6) - bar([0.0] * 7)).sum(axis=2) > 60)
    assert np.ptp(ys) + 1 >= 10 and np.ptp(xs) + 1 >= 22  # "19s": digits at least 10 px tall on a 620 px bar


def test_top_bar_is_bigger_in_the_game_window_and_unchanged_on_the_projector():
    def width(canvas: tuple[int, int]) -> float:
        sc = CoverageScene(GraphicsConfig(enabled=True, show_ui=True), canvas=canvas)
        return next(i for i in play(sc, 0.2, lambda t: [])[1] if i.shape == "hud").size

    assert width((1280, 854)) >= 0.57 * 1280  # the 2x game window
    assert width((854, 480)) == 560  # the projector's own canvas
