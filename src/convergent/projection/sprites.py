"""Projector sprites drawn from primitives (PIL only, so the Pi renders exactly what the laptop
previews). Original cartoon shapes, no licensed characters.

Shapes: ``dino`` (a tiny germ-dinosaur), ``blob`` (soft glow), ``pop`` (burst when a germ is
washed away). Every sprite is drawn into an RGBA layer and alpha-composited, so overlapping
sprites and fades work the same on both ends of the wire.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Sprite sheets drawn by scripts/make_sprites.py: name -> (frames, tile half-width in sprite radii).
# Stored without colour (R = body brightness, G = white parts, premultiplied; A = coverage incl. a soft dark edge) and tinted here.
GERMS = ("jelly", "spiky", "fuzzy")
SHEETS = {**{f"{g}{state}": (12, 1.3) for g in GERMS for state in ("", "_blink", "_scared")}, "burst": (8, 2.6), "twinkle": (6, 1.3)}
_ONE_SHOT = {"burst", "twinkle"}  # played once (progress 0..1); the others loop
_ASSETS = Path(__file__).parent / "assets"
SPRITES = ("dino", "blob", "pop", *SHEETS)


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
    # eye + pupil: white/near-black, but only in the body's own channels (a pure-green dino stays pure green)
    ex, ey = _rot([(0.72, -0.33)], angle_deg, x, y, s)[0]
    r = 0.11 * s
    d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(*(255 if ch > 0 else 0 for ch in color), a))
    r2 = 0.05 * s
    d.ellipse([ex - r2, ey - r2, ex + r2, ey + r2], fill=(*(20 if ch > 0 else 0 for ch in color), a))


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
    _paste(layer, tile, x, y)


def draw_pop(layer: Image.Image, x: float, y: float, size: float, progress: float, color: tuple[int, int, int] = (255, 240, 120)) -> None:
    """Burst when a germ is washed away: an expanding, fading ring of 8 rays. ``progress`` 0..1."""
    d = ImageDraw.Draw(layer, "RGBA")
    p = max(0.0, min(1.0, progress))
    a = int(255 * (1.0 - p))
    r0, r1 = size * (0.4 + 1.2 * p), size * (0.9 + 1.6 * p)
    for i in range(8):
        ang = i * math.pi / 4
        d.line([(x + r0 * math.cos(ang), y + r0 * math.sin(ang)), (x + r1 * math.cos(ang), y + r1 * math.sin(ang))], fill=(*color, a), width=max(1, int(size / 8)))


def _paste(layer: Image.Image, tile: Image.Image, x: float, y: float) -> None:
    """Alpha-composite ``tile`` centred on (x, y); the part outside the layer is cut off."""
    dx, dy = int(round(x - tile.width / 2)), int(round(y - tile.height / 2))
    sx, sy = max(0, -dx), max(0, -dy)
    if sx < tile.width and sy < tile.height and dx < layer.width and dy < layer.height:
        layer.alpha_composite(tile, (max(dx, 0), max(dy, 0)), (sx, sy))


_STRIPS: dict[str, np.ndarray] = {}
_TILES: dict[tuple[str, int, int, tuple[int, ...], int], Image.Image] = {}


def draw_sheet(layer: Image.Image, kind: str, x: float, y: float, size: float, color: tuple[int, int, int] = (215, 120, 255),
               alpha: float = 1.0, progress: float = 0.0) -> None:
    """One frame of a sprite sheet, ``size`` = sprite radius in px. The body takes ``color``; eyes and highlights
    are white in the body's own channels only, so a pure-green germ stays pure green (projection-proof tracking).
    Tinted, scaled tiles are cached: a frame costs one paste."""
    n, extent = SHEETS[kind]
    frame = min(n - 1, int(progress * n)) if kind in _ONE_SHOT else int(progress * n) % n
    px = max(4, int(round(2 * size * extent / 4)) * 4)  # sizes in steps of 4 px keep the cache small
    a8 = int(round(max(0.0, min(1.0, alpha)) * 8))
    key = (kind, frame, px, tuple(color), a8)
    tile = _TILES.get(key)
    if tile is None:
        strip = _STRIPS.get(kind)
        if strip is None:
            strip = _STRIPS[kind] = np.asarray(Image.open(_ASSETS / f"{kind}.png").convert("RGBA"), np.float32) / 255.0
        h = strip.shape[0]
        f = strip[:, frame * h:(frame + 1) * h]
        body = np.asarray(color, np.float32)
        cov = f[..., 3:4]
        rgb = (f[..., 0:1] * body + f[..., 1:2] * np.where(body > 0, 255.0, 0.0)) / np.maximum(cov, 1e-3)  # un-premultiply for PIL
        rgba = np.concatenate([np.clip(rgb, 0, 255), cov * 255.0 * a8 / 8], axis=-1).astype(np.uint8)
        tile = Image.fromarray(rgba).resize((px, px), Image.BILINEAR)
        if len(_TILES) > 600:
            _TILES.clear()
        _TILES[key] = tile
    _paste(layer, tile, x, y)


_PARTS = ("palms", "backs", "fingers", "knuckles", "thumbs", "tips", "wrists")  # the seven wash steps, in WHO order
_FONTS = ("/System/Library/Fonts/SFNSRounded.ttf", "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf")
_BARS: dict[tuple, Image.Image] = {}


def _font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONTS:
        try:
            f = ImageFont.truetype(path, px)
        except OSError:
            continue
        try:
            f.set_variation_by_name("Bold")
        except (OSError, AttributeError, ValueError):
            pass
        return f
    return ImageFont.load_default()


def draw_hud(layer: Image.Image, x: float, y: float, width: float, fractions: list[float], seconds: list[float], left: str, stars: int,
             accent: tuple[int, int, int] = (120, 240, 170)) -> None:
    """The coverage scene's slim bar: germs left, one ring per wash step that fills with its seconds and shows them
    (filled when the step is done), five stars. Drawn at 2x and scaled down for smooth edges; cached until a number changes."""
    key = (round(width), tuple(round(f * 24) for f in fractions), tuple(round(s, 1) for s in seconds), left, stars, tuple(accent))
    bar = _BARS.get(key)
    if bar is None:
        u = 2 * width / 620.0  # the layout below is in units of a 620 x 82 bar
        im = Image.new("RGBA", (int(620 * u), int(82 * u)), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=im.height // 2, fill=(16, 20, 30, 165))
        small, big, num = _font(max(6, int(11 * u))), _font(max(8, int(22 * u))), _font(max(6, int(14.5 * u)))
        d.text((26 * u, 15 * u), left, font=big, fill=(255, 255, 255, 255))
        d.text((26 * u, 48 * u), "germs left", font=small, fill=(255, 255, 255, 170))
        for i, (frac, sec) in enumerate(zip(fractions[:len(_PARTS)], seconds, strict=False)):
            cx, cy, r, wd = (150 + i * 52) * u, 31 * u, 21 * u, max(2, int(3.5 * u))
            box = [cx - r, cy - r, cx + r, cy + r]
            done = frac >= 1.0
            d.ellipse(box, fill=(*accent, 255) if done else None, outline=(255, 255, 255, 70), width=wd)
            if 0 < frac < 1.0:
                d.arc(box, -90, -90 + 360 * frac, fill=(*accent, 255), width=wd)
            txt = f"{sec:.0f}s" if sec >= 9.95 else f"{sec:.1f}"  # seconds washed, also after the step is done
            if sec > 0:
                d.text((cx - d.textlength(txt, font=num) / 2, cy - 0.62 * num.size), txt, font=num, fill=(16, 20, 30, 255) if done else (255, 255, 255, 240))
            d.text((cx - d.textlength(_PARTS[i], font=small) / 2, 58 * u), _PARTS[i], font=small, fill=(255, 255, 255, 235 if frac > 0 else 150))
        for k in range(5):
            cx, cy, r = (512 + k * 21) * u, 41 * u, 9 * u
            pts = [(cx + (r if j % 2 == 0 else 0.45 * r) * math.sin(j * math.pi / 5), cy - (r if j % 2 == 0 else 0.45 * r) * math.cos(j * math.pi / 5)) for j in range(10)]
            d.polygon(pts, fill=(255, 210, 70, 255) if k < stars else (255, 255, 255, 60))
        bar = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
        if len(_BARS) > 64:
            _BARS.clear()
        _BARS[key] = bar
    layer.alpha_composite(bar, (max(0, int(x)), max(0, int(y))))


def draw_sprite(layer: Image.Image, kind: str, x: float, y: float, size: float, angle_deg: float = 0.0,
                color: tuple[int, int, int] = (90, 220, 90), alpha: float = 1.0, progress: float = 0.0) -> None:
    if kind == "dino":
        draw_dino(layer, x, y, size, angle_deg, color, alpha)
    elif kind == "blob":
        draw_blob(layer, x, y, size, color, alpha)
    elif kind == "pop":
        draw_pop(layer, x, y, size, progress, color)
    elif kind in SHEETS:
        draw_sheet(layer, kind, x, y, size, color, alpha, progress)
    else:
        raise ValueError(f"unknown sprite {kind!r} (one of {SPRITES})")
