"""Removing the projector's green light before hand tracking (vision/projector_light.py)."""

from __future__ import annotations

import numpy as np

from convergent.common.config import PipelineConfig, TrackerConfig, resolve_path
from convergent.pipeline import Pipeline
from convergent.vision.hand_tracker import HandTracker, ScriptedBackend
from convergent.vision.projector_light import (
    DEFAULT_FIT,
    fit_green,
    normalise_light,
    remove_green_light,
)
from tests.conftest import make_frame, synthetic_hand

FIT = (0.42, 0.63, -3.0)
LEAK = (0.10, 0.10)


def natural(seed: int = 0, shape: tuple[int, int] = (60, 80)) -> np.ndarray:
    """A BGR picture whose green follows the fit, like skin and a sink under room light."""
    rng = np.random.default_rng(seed)
    r = rng.uniform(40, 220, shape)
    b = rng.uniform(20, 160, shape)
    g = FIT[0] * r + FIT[1] * b + FIT[2] + rng.normal(0, 2.0, shape)
    return np.clip(np.rint(np.stack([b, g, r], axis=-1)), 0, 255).astype(np.uint8)


def test_natural_picture_is_unchanged():
    img = natural()
    assert np.array_equal(remove_green_light(img, FIT, LEAK), img)


def test_projected_green_is_removed():
    img = natural(1)
    light = np.zeros(img.shape[:2], np.float32)
    light[10:40, 20:60] = 80.0  # a germ
    lit = img.astype(np.float32)
    lit[..., 1] += light
    lit[..., 2] += LEAK[0] * light
    lit[..., 0] += LEAK[1] * light
    lit = np.clip(np.rint(lit), 0, 255).astype(np.uint8)
    out = remove_green_light(lit, FIT, LEAK)
    err = np.abs(out.astype(int) - img.astype(int))
    germ = err[10:40, 20:60]
    assert germ[..., [0, 2]].max() <= 2  # red and blue: leak removed
    assert np.median(germ[..., 1]) <= 2 and germ[..., 1].max() <= 10  # green: back on the fit; what is left is the picture's own noise (sd 2)
    assert err[45:, :].max() == 0  # unlit pixels untouched


def test_clipped_pixels_stay_in_range():
    img = np.full((4, 4, 3), 250, np.uint8)
    img[..., 1] = 255
    out = remove_green_light(img, FIT, LEAK)
    assert out.dtype == np.uint8 and out.shape == img.shape


def test_fit_green_recovers_the_camera_mix():
    a, b, c = fit_green([natural(2), natural(3)])
    assert abs(a - FIT[0]) < 0.02 and abs(b - FIT[1]) < 0.02 and abs(c - FIT[2]) < 1.5


class SpyBackend(ScriptedBackend):
    """Scripted hands, and remembers the picture MediaPipe would have been given (RGB)."""

    def __init__(self, script):  # type: ignore[no-untyped-def]
        super().__init__(script)
        self.seen: list[np.ndarray] = []

    def detect(self, rgb, timestamp_ms):  # type: ignore[no-untyped-def,override]
        self.seen.append(rgb.copy())
        return super().detect(rgb, timestamp_ms)


def test_tracker_filters_its_own_picture_only():
    spy = SpyBackend([])
    tr = HandTracker(TrackerConfig(), spy)
    frame = make_frame()
    tr.image_filter = lambda img: np.zeros_like(img)
    tr.detect(frame)
    assert spy.seen[-1].max() == 0 and frame.image.max() > 0


def pipe_with(graphics: dict) -> tuple[Pipeline, SpyBackend]:
    cfg = PipelineConfig.load(resolve_path("configs/development.yaml"), {"projector": {"graphics": {"enabled": True, "show_ui": False, "mode": "dinos", **graphics}},  # the first scene always draws germs on the test hand
                                                                         "tracker": {"light_fix": False}})  # the test frame is near black: keep the light fix out of these checks
    spy = SpyBackend([[(synthetic_hand(0.5, 0.5, scale=0.3), "Left", 0.95)]])
    return Pipeline(cfg, tracker=HandTracker(cfg.tracker, spy)), spy


def excess_green(rgb: np.ndarray) -> float:
    """Strongest projector green left in any pixel (green above the camera's natural mix)."""
    r, g, b = (rgb[..., i].astype(np.float32) for i in range(3))
    return float(np.maximum(0, g - DEFAULT_FIT[0] * r - DEFAULT_FIT[1] * b - DEFAULT_FIT[2]).max())


def test_pipeline_leaves_the_tracker_alone_by_default():
    pipe, _ = pipe_with({})
    assert pipe.tracker.image_filter is None


def test_simulated_projection_reaches_the_tracker_and_green_only_removes_it():
    for green_only in (False, True):
        pipe, spy = pipe_with({"simulate_feedback": 1.0, "green_only": green_only})
        frames = [make_frame(i, i / 15) for i in range(3)]
        for f in frames:
            pipe.process_frame(f)
        assert np.array_equal(spy.seen[0], frames[0].image[..., ::-1])  # nothing projected yet on the first frame
        assert frames[2].image.max() == 30  # the frame itself (saved, previewed) never gets the projection
        if green_only:
            assert excess_green(spy.seen[2]) < 12  # only faint light is left (below what the filter can tell from skin)
        else:
            assert excess_green(spy.seen[2]) > 100  # germs from the previous render are on the hand in the tracker's picture


# ---------------------------------------------------------------- light fix (tracker picture in bad light)
def lit_scene(shape: tuple[int, int] = (120, 160)) -> np.ndarray:
    """A smooth, well-exposed BGR picture: every channel spans about 20..235."""
    h, w = shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    b = 20 + 215 * x / (w - 1)
    g = 20 + 215 * y / (h - 1)
    r = 20 + 215 * (x / (w - 1) + y / (h - 1)) / 2
    return np.rint(np.stack([b, g, r], axis=-1)).astype(np.uint8)


def _bad_light(kind: str) -> np.ndarray:
    f = lit_scene().astype(np.float32)
    if kind == "dark":
        f *= 0.25
    elif kind == "tinted":
        f *= np.array([1.2, 1.0, 0.7], np.float32)
    elif kind == "flat":
        f = 128 + (f - 128) * 0.4
    return np.clip(np.rint(f), 0, 255).astype(np.uint8)


def test_light_fix_returns_a_good_picture_untouched():
    img = lit_scene()
    assert normalise_light(img) is img


def test_light_fix_restores_the_full_range_in_dark_tinted_and_flat_light():
    for kind in ("dark", "tinted", "flat"):
        out = normalise_light(_bad_light(kind))
        px = out.reshape(-1, 3)
        assert np.percentile(px, 99, axis=0).min() >= 235, kind
        assert np.percentile(px, 1, axis=0).max() <= 20, kind
        assert normalise_light(out) is out, kind  # a second pass has nothing left to fix


def test_light_fix_blurs_a_grainy_picture():
    import cv2

    def grain(im: np.ndarray) -> float:
        return float(np.median(np.abs(cv2.Laplacian(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), cv2.CV_32F))))

    noisy = np.clip(lit_scene().astype(np.float32) + np.random.default_rng(0).normal(0, 15, (120, 160, 3)), 0, 255).astype(np.uint8)
    out = normalise_light(noisy)
    assert grain(noisy) > 20 and grain(out) < 12


def test_tracker_applies_the_light_fix_only_when_switched_on():
    for on in (False, True):
        frame = make_frame(w=160, h=120)
        frame.image[:] = _bad_light("dark")
        spy = SpyBackend([])
        HandTracker(TrackerConfig(light_fix=on), spy).detect(frame)
        assert (spy.seen[-1].max() > 200) == on and frame.image.max() < 70  # the frame itself stays dark


def test_light_fix_leaves_a_picture_without_any_contrast_alone():
    blank = np.full((120, 160, 3), 30, np.uint8)  # lens covered: nothing to stretch
    assert normalise_light(blank) is blank
