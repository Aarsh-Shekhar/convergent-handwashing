"""Projector sprites drawn from primitives (PIL only, so the Pi renders exactly what the laptop
previews). Original cartoon shapes, no licensed characters.

Shapes: ``dino`` (a tiny germ-dinosaur), ``blob`` (soft glow), ``pop`` (burst when a germ is
washed away). Every sprite is drawn into an RGBA layer and alpha-composited, so overlapping
sprites and fades work the same on both ends of the wire.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

SPRITES = ("dino", "blob", "pop")


def _rot(points: list[tuple[float, float]], angle_deg: float, cx: float, cy: float, s: float) -> list[tuple[float, float]]:
    a = math.radians(angle_deg)
    c, si = math.cos(a), math.sin(a)
    return [(cx + s * (x * c - y * si), cy + s * (x * si + y * c)) for x, y in points]


def draw_dino(layer: Image.Image, x: float, y: float, size: float, angle_deg: float = 0.0, color: tuple[int, int, int] = (90, 220, 90),
              alpha: float = 1.0) -> None:
    """A germ-dinosaur in a unit box (-1..1), ``size`` = half-width in px, facing +x before rotation."""
    d = ImageDraw.Draw(layer, "RGBA")
    a = int(255 * max(0.0, min(1.0, alpha)))
    body = (*color, a)
    dark = (max(0, color[0] - 60), max(0, color[1] - 60), max(0, color[2] - 60), a)
    s = size
    # body (fat ellipse) as a polygon so it can rotate
    n = 18
    ell = [(0.55 * math.cos(2 * math.pi * i / n), 0.42 * math.sin(2 * math.pi * i / n)) for i in range(n)]
    d.polygon(_rot(ell, angle_deg, x, y, s), fill=body)
    # tail, head, legs, back spikes
    d.polygon(_rot([(-0.5, -0.1), (-1.0, 0.25), (-0.45, 0.25)], angle_deg, x, y, s), fill=body)
    d.polygon(_rot([(0.35, -0.55), (0.95, -0.5), (1.0, -0.1), (0.5, 0.05)], angle_deg, x, y, s), fill=body)
    for lx in (-0.15, 0.25):
        d.polygon(_rot([(lx, 0.3), (lx + 0.2, 0.3), (lx + 0.2, 0.75), (lx - 0.02, 0.75)], angle_deg, x, y, s), fill=dark)
    for i, sx in enumerate((-0.35, -0.05, 0.25)):
        d.polygon(_rot([(sx, -0.38), (sx + 0.15, -0.72 + 0.05 * i), (sx + 0.3, -0.38)], angle_deg, x, y, s), fill=dark)
    # eye + pupil
    ex, ey = _rot([(0.72, -0.33)], angle_deg, x, y, s)[0]
    r = 0.11 * s
    d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(255, 255, 255, a))
    r2 = 0.05 * s
    d.ellipse([ex - r2, ey - r2, ex + r2, ey + r2], fill=(20, 20, 20, a))


_BLOB_CACHE: dict[tuple[int, tuple[int, int, int], int], Image.Image] = {}


def draw_blob(layer: Image.Image, x: float, y: float, size: float, color: tuple[int, int, int] = (255, 220, 60), alpha: float = 0.6) -> None:
    """Soft glow: a blurred disc (cached per size/colour). Tolerates tracking misalignment."""
    r = int(size)
    pad = r
    a = int(255 * max(0.0, min(1.0, alpha)))
    key = (r, tuple(color), a)
    tile = _BLOB_CACHE.get(key)
    if tile is None:
        tile = Image.new("RGBA", (2 * (r + pad), 2 * (r + pad)), (0, 0, 0, 0))
        ImageDraw.Draw(tile).ellipse([pad, pad, pad + 2 * r, pad + 2 * r], fill=(*color, a))
        tile = tile.filter(ImageFilter.GaussianBlur(max(1, r // 2)))
        if len(_BLOB_CACHE) > 64:
            _BLOB_CACHE.clear()
        _BLOB_CACHE[key] = tile
    layer.alpha_composite(tile, (int(x) - r - pad, int(y) - r - pad))


def draw_pop(layer: Image.Image, x: float, y: float, size: float, progress: float, color: tuple[int, int, int] = (255, 240, 120)) -> None:
    """Burst when a germ is washed away: an expanding, fading ring of 8 rays. ``progress`` 0..1."""
    d = ImageDraw.Draw(layer, "RGBA")
    p = max(0.0, min(1.0, progress))
    a = int(255 * (1.0 - p))
    r0, r1 = size * (0.4 + 1.2 * p), size * (0.9 + 1.6 * p)
    for i in range(8):
        ang = i * math.pi / 4
        d.line([(x + r0 * math.cos(ang), y + r0 * math.sin(ang)), (x + r1 * math.cos(ang), y + r1 * math.sin(ang))], fill=(*color, a), width=max(1, int(size / 8)))


def draw_sprite(layer: Image.Image, kind: str, x: float, y: float, size: float, angle_deg: float = 0.0,
                color: tuple[int, int, int] = (90, 220, 90), alpha: float = 1.0, progress: float = 0.0) -> None:
    if kind == "dino":
        draw_dino(layer, x, y, size, angle_deg, color, alpha)
    elif kind == "blob":
        draw_blob(layer, x, y, size, color, alpha)
    elif kind == "pop":
        draw_pop(layer, x, y, size, progress, color)
    else:
        raise ValueError(f"unknown sprite {kind!r} (one of {SPRITES})")
