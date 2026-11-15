#!/usr/bin/env python
"""Draw the coverage scene's sprite sheets: three germs (jelly, spiky, fuzzy), their burst and a twinkle.

    .venv/bin/python scripts/make_sprites.py            # writes src/convergent/projection/assets/*.png

Each sheet is one row of square frames. The art is stored without colour, so the same sheet works
in full colour and in the projector's green-only light (projection/sprites.py draw_sheet tints it):

    R = body brightness, G = "white" parts (eyes, teeth, highlights), A = coverage; R and G are
    premultiplied by the shape's own coverage.

Around every shape A also carries a soft dark edge (no R, no G). Drawn as a solid sticker on the
laptop it lifts the germ off the skin; as projector light it adds nothing, so one sheet serves both.
Shapes are smooth distance fields drawn at 3x size and scaled down. No bitmaps, no licensed
characters. Re-run after changing the look; the PNGs are committed.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "src" / "convergent" / "projection" / "assets"
SS, TILE, FRAMES = 3, 128, 12
TWO_PI = 2 * math.pi
LIGHT = (-0.45, -0.60, 0.66)
DARK = 0.04  # pupils, brows, mouths: almost no light
GERMS = ("jelly", "spiky", "fuzzy")


def smooth(e0, e1, x):  # type: ignore[no-untyped-def]
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def disc(x, y, cx, cy, r, aa):  # type: ignore[no-untyped-def]
    return 1.0 - smooth(-aa, aa, np.hypot(x - cx, y - cy) - r)


def ell(x, y, cx, cy, rx, ry, aa):  # type: ignore[no-untyped-def]
    return 1.0 - smooth(-aa, aa, (np.hypot((x - cx) / rx, (y - cy) / ry) - 1.0) * min(rx, ry))


def capsule(x, y, ax, ay, bx, by, r, aa):  # type: ignore[no-untyped-def]
    px, py, dx, dy = x - ax, y - ay, bx - ax, by - ay
    h = np.clip((px * dx + py * dy) / (dx * dx + dy * dy), 0, 1)
    return 1.0 - smooth(-aa, aa, np.hypot(px - dx * h, py - dy * h) - r)


def _grid(extent: float, tile: int):  # type: ignore[no-untyped-def]
    n = tile * SS
    a = (np.arange(n) + 0.5) / n * 2 * extent - extent
    x, y = np.meshgrid(a, a)
    return x, y, 2 * extent / n * 1.5


def _frame(body, white, alpha, tile: int, edge: float = 0.6) -> np.ndarray:  # type: ignore[no-untyped-def]
    halo = np.clip(cv2.GaussianBlur(alpha.astype(np.float32), (0, 0), alpha.shape[0] / 36.0) * 1.8, 0, 1) * edge  # soft dark edge
    rgba = np.stack([body * alpha, white * alpha, np.zeros_like(alpha), np.maximum(alpha, halo)], axis=-1).astype(np.float32)
    return np.clip(cv2.resize(rgba, (tile, tile), interpolation=cv2.INTER_AREA) * 255, 0, 255).astype(np.uint8)


def germ(style: str, phase: float, blink: bool = False, scared: float = 0.0, extent: float = 1.3) -> np.ndarray:
    """One frame of a germ. ``phase`` 0..1 of the idle bounce, ``scared`` 0..1 (squashed, wide eyes)."""
    X, Y, aa = _grid(extent, TILE)
    p = TWO_PI * phase
    b = math.sin(p)
    sx, sy = 1 + 0.07 * b + 0.22 * scared, 1 - 0.07 * b - 0.25 * scared
    x, y = X / sx, (Y - 0.9 * (1 - sy)) / sy  # squash and stretch with the feet planted
    r, th = np.hypot(x, y), np.arctan2(y, x)
    extra = np.zeros_like(x)  # appendages, flat shaded
    if style == "jelly":
        rad = 0.80 * (1 + 0.04 * np.sin(2 * th + p) + 0.03 * np.sin(3 * th - p))
        for s in (-1, 1):
            tx, ty = s * (0.42 + 0.05 * b), -1.06
            extra = np.maximum(extra, capsule(x, y, s * 0.28, -0.62, tx, ty, 0.045, aa))
            extra = np.maximum(extra, disc(x, y, tx, ty, 0.11, aa))
        eyes = [(-0.27, -0.12, 0.25), (0.27, -0.12, 0.25)]
    elif style == "spiky":
        k, sway = 9, 0.12 * math.sin(p) + 0.5 * scared * math.sin(3 * p)
        rad = 0.56 * (1 + 0.36 * np.maximum(0.0, np.cos(k * (th + sway))) ** 3)
        for i in range(k):
            c, s = math.cos(TWO_PI * i / k - sway), math.sin(TWO_PI * i / k - sway)
            extra = np.maximum(extra, disc(x, y, 0.90 * c, 0.90 * s, 0.105 + 0.012 * b, aa))
            extra = np.maximum(extra, capsule(x, y, 0.5 * c, 0.5 * s, 0.88 * c, 0.88 * s, 0.04, aa))
        eyes = [(0.0, -0.02, 0.34)]
    else:  # fuzzy
        rad = 0.78 * (1 + 0.045 * np.sin(13 * th + 2 * p) + 0.04 * np.sin(7 * th - p))
        for s in (-1, 1):
            for j in range(6):
                u = j / 5
                extra = np.maximum(extra, disc(x, y, s * (0.34 + 0.16 * u), -0.62 - 0.36 * u, 0.12 * (1 - 0.8 * u), aa))
        eyes = [(-0.33, -0.22, 0.17), (0.33, -0.22, 0.17)]
    inside = 1.0 - smooth(-aa, aa, r - rad)
    nz = np.sqrt(np.clip(1 - (r / rad) ** 2, 0, 1))
    lam = np.clip(x / rad * LIGHT[0] + y / rad * LIGHT[1] + nz * LIGHT[2], 0, 1)
    body = np.where(inside > 0.5, 0.40 + 0.60 * lam + 0.14 * (1 - nz) ** 2, 0.80)  # soft sphere shading, flat appendages
    white = np.zeros_like(x)
    alpha = np.maximum(inside, extra)

    def paint(mask, to_white: bool) -> None:  # type: ignore[no-untyped-def]
        nonlocal body, white
        body = body * (1 - mask) + (0.0 if to_white else DARK) * mask
        white = white * (1 - mask) + (mask if to_white else 0.0)

    look = (0.05 * math.cos(p) * 4, 0.035 * math.sin(p) * 4)
    for ex, ey, er in eyes:
        paint(ell(x, y, ex, ey, er, er * (0.10 if blink else 1.0) * (1 + 0.15 * scared), aa), True)
        if not blink:
            pr = er * (0.46 - 0.22 * scared)
            paint(disc(x, y, ex + look[0] * er, ey + look[1] * er, pr, aa), False)
            paint(disc(x, y, ex + look[0] * er - pr * 0.35, ey + look[1] * er - pr * 0.35, pr * 0.28, aa), True)
    if style == "jelly":  # smile, or a little "o" when scared
        ring = np.clip(disc(x, y, 0, 0.20, 0.25, aa) - disc(x, y, 0, 0.20, 0.19, aa), 0, 1)
        paint(ring * smooth(0.22, 0.27, y) * (1 - scared), False)
        paint(ell(x, y, 0, 0.36, 0.12, 0.12, aa) * scared, False)
    elif style == "spiky":  # grumpy brow (it lifts when scared) and a small mouth
        lift = 0.10 * scared
        paint(capsule(x, y, -0.36, -0.47 + 0.02 * b - lift, 0.30, -0.36 + 0.02 * b - 2 * lift, 0.055, aa), False)
        paint(ell(x, y, 0.0, 0.44, 0.10, 0.05 + 0.06 * scared, aa), False)
    else:  # big mouth with two teeth
        open_ = 0.17 + 0.04 * b + 0.10 * scared
        mouth = ell(x, y, 0, 0.20, 0.38, open_, aa)
        paint(mouth, False)
        for s in (-1, 1):
            paint(ell(x, y, s * 0.13, 0.20 - open_ + 0.07, 0.085, 0.085, aa) * mouth, True)
    white = np.clip(white + np.exp(-((x + 0.30) ** 2 + (y + 0.42) ** 2) / 0.012) * 0.75 * inside, 0, 1)
    return _frame(body, white, alpha, TILE)


def burst(u: float, tile: int = 192, extent: float = 2.6) -> np.ndarray:
    """A popped germ: bubbles and sparkles flying out and fading. u 0..1."""
    x, y, aa = _grid(extent, tile)
    rng = np.random.default_rng(3)
    ease, fade = 1 - (1 - u) ** 3, (1 - u) ** 0.9
    body, white, alpha = np.zeros_like(x), np.zeros_like(x), np.zeros_like(x)
    for i in range(8):
        ang = TWO_PI * i / 8 + rng.uniform(-0.25, 0.25)
        dist = 0.35 + (1.2 + rng.uniform(0, 0.7)) * ease
        cx, cy = dist * math.cos(ang), dist * math.sin(ang) - 0.25 * ease
        br = rng.uniform(0.24, 0.44) * (1 - 0.2 * u)
        ring = np.clip(disc(x, y, cx, cy, br, aa) - disc(x, y, cx, cy, br - 0.09, aa), 0, 1)
        m = np.clip(ring + 0.30 * disc(x, y, cx, cy, br, aa), 0, 1) * fade
        hl = disc(x, y, cx - br * 0.4, cy - br * 0.4, br * 0.2, aa) * fade
        body, white, alpha = np.maximum(body, 0.55 * m), np.maximum(white, np.maximum(0.45 * m, hl)), np.maximum(alpha, np.maximum(m, hl))
    for i in range(6):
        ang = TWO_PI * (i + 0.5) / 6 + rng.uniform(-0.3, 0.3)
        dist = 0.3 + 1.7 * ease
        star = (1.0 - smooth(-aa, aa, (np.sqrt(np.abs(x - dist * math.cos(ang))) + np.sqrt(np.abs(y - dist * math.sin(ang)))) ** 2
                              - (0.42 * (1 - u) + 0.06))) * fade
        white, alpha = np.maximum(white, star), np.maximum(alpha, star)
    safe = np.maximum(alpha, 1e-6)
    return _frame(np.clip(body / safe, 0, 1), np.clip(white / safe, 0, 1), alpha, tile, edge=0.25)


def twinkle(u: float, extent: float = 1.3) -> np.ndarray:
    """A four-point sparkle that swells and fades (clean skin). u 0..1."""
    x, y, aa = _grid(extent, 64)
    s = math.sin(math.pi * u)
    star = 1.0 - smooth(-aa, aa, (np.sqrt(np.abs(x)) + np.sqrt(np.abs(y))) ** 2 - 1.1 * s)
    return _frame(np.zeros_like(x), np.ones_like(x), star * s, 64, edge=0.0)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    sheets = {"burst": [burst((i + 1) / 8) for i in range(8)], "twinkle": [twinkle((i + 0.5) / 6) for i in range(6)]}
    for g in GERMS:
        sheets[g] = [germ(g, i / FRAMES) for i in range(FRAMES)]
        sheets[f"{g}_blink"] = [germ(g, i / FRAMES, blink=True) for i in range(FRAMES)]
        sheets[f"{g}_scared"] = [germ(g, i / FRAMES, scared=0.8) for i in range(FRAMES)]
    for name, frames in sorted(sheets.items()):
        Image.fromarray(np.hstack(frames)).save(OUT / f"{name}.png", optimize=True)
        print(f"{name}.png  {len(frames)} frames of {frames[0].shape[0]} px  {(OUT / f'{name}.png').stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
