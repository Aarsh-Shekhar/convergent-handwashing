"""The live window (cli._attach_show_window): the old score panel on the right goes away while the projection is on."""

from __future__ import annotations

import cv2

from convergent import cli
from convergent.common.config import PipelineConfig, resolve_path
from convergent.pipeline import Pipeline
from convergent.vision import overlays
from convergent.vision.hand_tracker import HandTracker, ScriptedBackend
from tests.conftest import make_frame


def panels_drawn(monkeypatch, projection: bool, toggle: bool = False) -> int:  # type: ignore[no-untyped-def]
    calls: list[int] = []
    monkeypatch.setattr(overlays, "draw_score_panel", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(cv2, "imshow", lambda *a: None)
    monkeypatch.setattr(cv2, "waitKey", lambda *a: ord("p") if toggle else 0)
    cfg = PipelineConfig.load(resolve_path("configs/development.yaml"))
    pipe = Pipeline(cfg, tracker=HandTracker(cfg.tracker, ScriptedBackend([])))
    cli._attach_show_window(pipe, projection=projection)
    pipe.process_frame(make_frame(0, 0.0))
    pipe.process_frame(make_frame(1, 1 / 15))
    return len(calls)


def test_projection_on_hides_the_score_panel(monkeypatch):  # type: ignore[no-untyped-def]
    assert panels_drawn(monkeypatch, projection=True) == 0


def test_projection_off_keeps_the_score_panel(monkeypatch):  # type: ignore[no-untyped-def]
    assert panels_drawn(monkeypatch, projection=False) == 2


def test_pressing_p_switches_it(monkeypatch):  # type: ignore[no-untyped-def]
    assert panels_drawn(monkeypatch, projection=False, toggle=True) == 1  # first frame off (panel), then P turns projection on


def test_the_projection_button_sits_top_left_and_covers_no_text():
    from tests.unit.test_projection_graphics import tracked

    x0, y0, x1, y1 = overlays.ProjectionPreview.BUTTON
    assert x0 <= 10 and y0 <= 10  # top-left corner
    img = overlays.render_overlay(make_frame(0, 0.0), tracked(0.0, []), ["a" * 60] * 3)
    assert (img[y0 : y1 + 1, x0 : x1 + 1] == 30).all()  # no debug text under the button
