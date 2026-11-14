"""Removing the projector's green light before hand tracking (vision/projector_light.py)."""

from __future__ import annotations

import numpy as np

from convergent.common.config import PipelineConfig, TrackerConfig, resolve_path
from convergent.pipeline import Pipeline
from convergent.vision.hand_tracker import HandTracker, ScriptedBackend
from convergent.vision.projector_light import DEFAULT_FIT, fit_green, remove_green_light
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
    cfg = PipelineConfig.load(resolve_path("configs/development.yaml"), {"projector": {"graphics": {"enabled": True, "show_ui": False, **graphics}}})
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
