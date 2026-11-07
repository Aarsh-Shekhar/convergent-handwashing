"""Temporal smoothing and bounded latency compensation for projected target positions."""

from __future__ import annotations

import math

import numpy as np

from convergent.common.config import SmoothingConfig


class EMAFilter:
    def __init__(self, alpha: float = 0.4) -> None:
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0,1]")
        self.alpha = alpha
        self._v: np.ndarray | None = None

    def reset(self) -> None:
        self._v = None

    def update(self, x: np.ndarray, ts: float) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        self._v = x.copy() if self._v is None else self.alpha * x + (1 - self.alpha) * self._v
        return self._v.copy()


class OneEuroFilter:
    """Casiez et al. One Euro filter: low jitter at rest, low lag when moving."""

    def __init__(self, min_cutoff: float = 1.5, beta: float = 0.05, d_cutoff: float = 1.0) -> None:
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self._x: np.ndarray | None = None
        self._dx: np.ndarray | None = None
        self._t: float | None = None

    def reset(self) -> None:
        self._x = self._dx = None
        self._t = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def update(self, x: np.ndarray, ts: float) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        if self._x is None or self._t is None:
            self._x, self._dx, self._t = x.copy(), np.zeros_like(x), ts
            return x.copy()
        dt = max(ts - self._t, 1e-6)
        self._t = ts
        dx = (x - self._x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self._dx = a_d * dx + (1 - a_d) * self._dx
        cutoff = self.min_cutoff + self.beta * float(np.linalg.norm(self._dx))
        a = self._alpha(cutoff, dt)
        self._x = a * x + (1 - a) * self._x
        return self._x.copy()


class NoFilter:
    def reset(self) -> None:
        pass

    def update(self, x: np.ndarray, ts: float) -> np.ndarray:
        return np.asarray(x, dtype=np.float64).copy()


class TargetSmoother:
    """Per-anchor smoothing with gap-based reset and bounded linear prediction.

    * if the gap since the last valid update exceeds ``reset_gap_s`` the filter restarts
      (no interpolation across tracking loss);
    * :meth:`predict` extrapolates at most ``max_prediction_horizon_s`` ahead using the last
      velocity estimate and returns ``None`` if the target has gone invalid.
    """

    def __init__(self, cfg: SmoothingConfig | None = None) -> None:
        self.cfg = cfg or SmoothingConfig()
        self._filters: dict[str, EMAFilter | OneEuroFilter | NoFilter] = {}
        self._last: dict[str, tuple[np.ndarray, float, np.ndarray]] = {}  # anchor -> (pos, ts, velocity)

    def _make(self) -> EMAFilter | OneEuroFilter | NoFilter:
        if self.cfg.method == "ema":
            return EMAFilter(self.cfg.ema_alpha)
        if self.cfg.method == "one_euro":
            return OneEuroFilter(self.cfg.one_euro_min_cutoff, self.cfg.one_euro_beta, self.cfg.one_euro_d_cutoff)
        return NoFilter()

    def reset(self, anchor_id: str | None = None) -> None:
        if anchor_id is None:
            self._filters.clear()
            self._last.clear()
        else:
            self._filters.pop(anchor_id, None)
            self._last.pop(anchor_id, None)

    def update(self, anchor_id: str, xy: tuple[float, float], ts: float) -> tuple[float, float]:
        f = self._filters.get(anchor_id)
        prev = self._last.get(anchor_id)
        if f is None or prev is None or ts - prev[1] > self.cfg.reset_gap_s or ts < prev[1]:
            f = self._make()
            self._filters[anchor_id] = f
            prev = None
        out = f.update(np.asarray(xy, dtype=np.float64), ts)
        vel = np.zeros(2) if prev is None else (out - prev[0]) / max(ts - prev[1], 1e-6)
        self._last[anchor_id] = (out, ts, vel)
        return float(out[0]), float(out[1])

    def invalidate(self, anchor_id: str) -> None:
        self.reset(anchor_id)

    def predict(self, anchor_id: str, ts: float) -> tuple[float, float] | None:
        prev = self._last.get(anchor_id)
        if prev is None:
            return None
        pos, t0, vel = prev
        dt = ts - t0
        if dt < 0 or dt > self.cfg.reset_gap_s:
            return None
        dt = min(dt, self.cfg.max_prediction_horizon_s)
        p = pos + vel * dt
        return float(p[0]), float(p[1])
