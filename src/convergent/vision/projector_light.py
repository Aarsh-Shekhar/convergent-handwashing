"""Remove the projector's green light from the camera picture before hand tracking.

With ``projector.graphics.green_only`` the hand graphics use only the projector's green light, so
the camera's red and blue channels stay almost clean. Under room light, green is close to a fixed
mix of red and blue (``G = a*R + b*B + c``, fitted per camera with ``scripts/fit_green.py``), so a
pixel whose green is clearly above that mix is lit by the projector. Only those pixels are
repaired: the extra green is removed, plus the small part of it that leaks into red and blue.
Every other pixel keeps its real colour, so the tracker still sees the colour picture it was
trained on (red-only tracking lost about 15 points of frame accuracy for that reason).
"""

from __future__ import annotations

from collections.abc import Iterable

import cv2
import numpy as np

DEFAULT_FIT = (0.416, 0.633, -3.2)  # Mac webcam, own round down1 (2026-11-14); refit for the Arducam
DEFAULT_LEAK = (0.10, 0.10)  # projector green seen by the camera's red / blue; measure on hardware day
_ON, _RAMP = 10.0, 15.0  # extra green below _ON counts as noise; full repair from _ON + _RAMP
# light fix gates, from 61 videos of 5 sources (2026-11-14). Normal footage: lowest channel p99 >= 180,
# p99 spread <= 31 (a few Kaggle sinks 72), smallest channel range >= 160, grain <= 6.
_DARK, _TINT, _FLAT, _GRAIN = 150.0, 50.0, 120.0, 12.0


def remove_green_light(bgr: np.ndarray, fit: Iterable[float] = DEFAULT_FIT, leak: Iterable[float] = DEFAULT_LEAK) -> np.ndarray:
    """BGR uint8 in, BGR uint8 out (same shape). Pixels without projector light come back unchanged."""
    a, b, c = fit
    lr, lb = leak
    f = bgr.astype(np.float32)
    bl, g, r = f[..., 0], f[..., 1], f[..., 2]
    # camera sees R = R0 + lr*L, B = B0 + lb*L, G = G0 + L with G0 = a*R0 + b*B0 + c
    light = np.maximum(0.0, (g - a * r - b * bl - c) / (1.0 - a * lr - b * lb))
    light *= np.clip((light - _ON) / _RAMP, 0.0, 1.0)
    out = np.stack([bl - lb * light, g - light, r - lr * light], axis=-1)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def fit_green(frames: Iterable[np.ndarray]) -> tuple[float, float, float]:
    """Least-squares ``G = a*R + b*B + c`` over BGR frames taken with the projector off."""
    px = np.concatenate([np.asarray(f).reshape(-1, 3) for f in frames]).astype(np.float32)
    ok = (px.max(axis=1) < 250) & (px.min(axis=1) > 5)  # clipped pixels do not follow the mix
    px = px[ok]
    coef, *_ = np.linalg.lstsq(np.column_stack([px[:, 2], px[:, 0], np.ones(len(px))]), px[:, 1], rcond=None)
    return float(coef[0]), float(coef[1]), float(coef[2])


def normalise_light(bgr: np.ndarray) -> np.ndarray:
    """Clean-up of the TRACKER's picture in bad light (BGR uint8 in and out). A well-lit picture comes back
    as the same object. Grainy: 5x5 blur. Dark, tinted or flat: each colour channel's 1st..99th percentile is
    stretched to 0..255. MediaPipe loses hands in such pictures (held-out METC frame accuracy 48 to 58%
    instead of 78%); with this it is 75 to 76%. Always on it costs 2.7 points in normal light, hence the gates."""
    out = bgr
    if np.median(np.abs(cv2.Laplacian(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), cv2.CV_32F))) > _GRAIN:
        out = cv2.GaussianBlur(bgr, (5, 5), 0)
    sub = out[::4, ::4].reshape(-1, 3).astype(np.float32)
    lo, hi = np.percentile(sub, 1, axis=0), np.percentile(sub, 99, axis=0)
    span = hi - lo
    if span.min() >= 8 and (hi.min() < _DARK or hi.max() - hi.min() > _TINT or span.min() < _FLAT):  # under 8: no picture to stretch
        out = np.clip((out.astype(np.float32) - lo) * (255.0 / span), 0, 255).astype(np.uint8)
    return out
