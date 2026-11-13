"""Hand-relative ("pair-relative-v2") features for the temporal technique classifier.

Why: the v1 temporal model read raw image coordinates in MediaPipe's left/right slots. That
ties it to where the hands sit in the picture, how large they are, how the camera is rotated,
and to a handedness guess that is unreliable while hands overlap. These features describe the
hands relative to *themselves and each other* instead:

per hand (slot), zeros when the hand is absent
    shape   21 landmarks in the hand's own frame: wrist at the origin, in-plane rotation
            removed (wrist -> middle-finger knuckle is the +y axis), divided by hand size   63
    motion  wrist velocity in the hand's own frame, turn rate, size change (per 1/15 s)      4
    cross   the OTHER hand's wrist, fingertips and middle knuckle in this hand's frame,
            plus the other hand's pointing direction in this hand's frame (both present)    23
global
    distance between the palm centres in hand sizes (both present), presence flag per slot  3

Total ``FEATURE_DIM_V2`` = 2 * 90 + 3 = 183. The representation is invariant to image
translation, uniform scale and in-plane rotation by construction. Slots are filled by
*position continuity* (:class:`HandSlotter`), never by the handedness label; the model is
trained with random slot swaps and evaluated on both orders (:func:`swap_slots`), so which
hand lands in which slot does not matter.

Raw input everywhere in this module: ``raw`` (..., T, 2, 21, 3) MediaPipe-normalised
landmarks (x, y in [0, 1] of image width/height, z relative depth), ``presence`` (..., T, 2),
and the image ``aspect`` = width / height (x and z are multiplied by it so distances are
isotropic, in units of image height).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from convergent.detection.lstm_model import PAIR_PREPROCESSING_VERSION  # noqa: F401  (re-exported)

WRIST, MIDDLE_MCP = 0, 9
PALM_POINTS = (0, 5, 9, 13, 17)
KEY_POINTS = (0, 4, 8, 12, 16, 20, 9)  # wrist, five fingertips, middle knuckle
SHAPE_DIM, MOTION_DIM, CROSS_DIM = 63, 4, 3 * len(KEY_POINTS) + 2
HAND_BLOCK = SHAPE_DIM + MOTION_DIM + CROSS_DIM  # 90
GLOBAL_DIM = 3
FEATURE_DIM_V2 = 2 * HAND_BLOCK + GLOBAL_DIM  # 183
REFERENCE_FPS = 15.0
_MIN_SIZE = 1e-3
_CLIP = 6.0


# --------------------------------------------------------------------------- slotting
class HandSlotter:
    """Keeps each physical hand in the same slot from frame to frame using position continuity.

    The slot index itself carries no meaning (no left/right): the classifier is symmetric in
    the two slots. What matters is that a hand does not jump between slots inside a window.
    """

    def __init__(self, memory_s: float = 1.0, max_jump: float = 0.35) -> None:
        self.memory_s = memory_s
        self.max_jump = max_jump
        self._pos: list[np.ndarray | None] = [None, None]
        self._ts: list[float] = [-1e9, -1e9]

    def reset(self) -> None:
        self._pos = [None, None]
        self._ts = [-1e9, -1e9]

    def assign(self, hands: list[np.ndarray], ts: float) -> tuple[np.ndarray, np.ndarray]:
        """hands: up to two (21,3) landmark arrays. Returns raw (2,21,3) float32 and presence (2,) float32."""
        raw = np.zeros((2, 21, 3), np.float32)
        presence = np.zeros(2, np.float32)
        hands = [np.asarray(h, np.float32) for h in hands[:2]]
        if not hands:
            return raw, presence
        for k in (0, 1):
            if self._pos[k] is not None and ts - self._ts[k] > self.memory_s:
                self._pos[k] = None
        cents = [h[:, :2].mean(axis=0) for h in hands]

        def dist(i: int, k: int) -> float:
            return float(np.linalg.norm(cents[i] - self._pos[k])) if self._pos[k] is not None else np.nan

        if len(hands) == 2:
            known = [self._pos[0] is not None, self._pos[1] is not None]
            if all(known):
                order = (0, 1) if dist(0, 0) + dist(1, 1) <= dist(0, 1) + dist(1, 0) else (1, 0)
            elif known[0]:
                order = (0, 1) if dist(0, 0) <= dist(1, 0) else (1, 0)
            elif known[1]:
                order = (1, 0) if dist(0, 1) <= dist(1, 1) else (0, 1)
            else:
                order = (0, 1) if cents[0][0] <= cents[1][0] else (1, 0)  # deterministic start: left-most first
            slots = {order[0]: 0, order[1]: 1}  # hand index -> slot
        else:
            d0, d1 = dist(0, 0), dist(0, 1)
            if not np.isnan(d0) and not np.isnan(d1):
                slot = 0 if d0 <= d1 else 1
            elif not np.isnan(d0):
                slot = 0 if d0 <= self.max_jump else 1
            elif not np.isnan(d1):
                slot = 1 if d1 <= self.max_jump else 0
            else:
                slot = 0
            slots = {0: slot}
        for i, k in slots.items():
            raw[k] = hands[i]
            presence[k] = 1.0
            self._pos[k] = cents[i]
            self._ts[k] = ts
        return raw, presence


# --------------------------------------------------------------------------- features
def _frames(raw: np.ndarray, aspect: float | np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Isotropic points P (...,2,21,3), wrist w, unit finger direction u (2D), perpendicular v (2D), size s."""
    a = np.asarray(aspect, np.float32)
    if a.ndim:
        a = a.reshape(a.shape + (1,) * (raw.ndim - 1 - a.ndim))
    p = raw.astype(np.float32).copy()
    p[..., 0] = p[..., 0] * a
    p[..., 2] = p[..., 2] * a
    w = p[..., WRIST, :]
    d = p[..., MIDDLE_MCP, :] - w
    s = np.maximum(np.linalg.norm(d, axis=-1), _MIN_SIZE)
    n2 = np.linalg.norm(d[..., :2], axis=-1)
    ok = n2 > 1e-5
    u = np.where(ok[..., None], d[..., :2] / np.maximum(n2, 1e-5)[..., None], np.array([0.0, -1.0], np.float32))
    v = np.stack([-u[..., 1], u[..., 0]], axis=-1)
    return p, w, u.astype(np.float32), v.astype(np.float32), s.astype(np.float32)


def _local(rel: np.ndarray, u: np.ndarray, v: np.ndarray, s: np.ndarray) -> np.ndarray:
    """rel (...,K,3) offsets -> hand-frame coordinates (...,K,3): (across, along fingers, depth) / size."""
    x = rel[..., 0] * v[..., None, 0] + rel[..., 1] * v[..., None, 1]
    y = rel[..., 0] * u[..., None, 0] + rel[..., 1] * u[..., None, 1]
    return np.stack([x, y, rel[..., 2]], axis=-1) / s[..., None, None]


def featurize(raw: np.ndarray, presence: np.ndarray, aspect: float | np.ndarray = 4.0 / 3.0,
              timestamps: np.ndarray | None = None) -> np.ndarray:
    """raw (..., T, 2, 21, 3), presence (..., T, 2) -> features (..., T, FEATURE_DIM_V2) float32.

    ``aspect`` is a scalar or an array matching the leading (batch) dimensions. ``timestamps``
    (..., T) makes the motion features frame-rate independent; without it frames are assumed
    to be 1/15 s apart.
    """
    raw = np.asarray(raw, np.float32)
    pres = np.asarray(presence, np.float32) > 0.5
    if raw.shape[-3:] != (2, 21, 3) or pres.shape != raw.shape[:-2]:
        raise ValueError(f"expected raw (...,T,2,21,3) and presence (...,T,2); got {raw.shape} and {pres.shape}")
    p, w, u, v, s = _frames(raw, aspect)
    lead, t = raw.shape[:-4], raw.shape[-4]
    both = (pres[..., 0] & pres[..., 1])[..., None]  # (...,T,1)

    shape = _local(p - w[..., None, :], u, v, s).reshape(lead + (t, 2, SHAPE_DIM))

    # motion: needs the same hand in the previous frame
    motion = np.zeros(lead + (t, 2, MOTION_DIM), np.float32)
    if t > 1:
        if timestamps is None:
            scale = np.ones(lead + (t - 1, 1), np.float32)
        else:
            dt = np.diff(np.asarray(timestamps, np.float64), axis=-1)
            scale = (1.0 / np.maximum(dt * REFERENCE_FPS, 0.25)).astype(np.float32)[..., None]
        dw = w[..., 1:, :, :2] - w[..., :-1, :, :2]
        u1, v1, s1 = u[..., 1:, :, :], v[..., 1:, :, :], s[..., 1:, :]
        u0, s0 = u[..., :-1, :, :], s[..., :-1, :]
        vx = (dw * v1).sum(-1) / s1
        vy = (dw * u1).sum(-1) / s1
        turn = np.arctan2(u0[..., 0] * u1[..., 1] - u0[..., 1] * u1[..., 0], (u0 * u1).sum(-1))
        grow = np.log(s1 / s0)
        m = np.stack([vx, vy, turn, grow], axis=-1) * scale[..., None]
        valid = (pres[..., 1:, :] & pres[..., :-1, :])[..., None]
        motion[..., 1:, :, :] = np.where(valid, m, 0.0)

    # cross: the other hand seen from this hand
    other = p[..., ::-1, :, :][..., KEY_POINTS, :]  # (...,T,2,K,3) other hand's key points
    rel = other - w[..., None, :]
    rel[..., 2] = other[..., 2]  # depth is only meaningful relative to each hand's own wrist
    cross_pts = _local(rel, u, v, s).reshape(lead + (t, 2, 3 * len(KEY_POINTS)))
    uo = u[..., ::-1, :]
    cross_dir = np.stack([(uo * v).sum(-1), (uo * u).sum(-1)], axis=-1)
    cross = np.concatenate([cross_pts, cross_dir], axis=-1)
    cross = np.where(both[..., None], cross, 0.0)

    block = np.concatenate([shape, motion, cross], axis=-1)
    block = np.where(pres[..., None], block, 0.0)
    block = np.clip(block, -_CLIP, _CLIP)

    centre = p[..., PALM_POINTS, :2].mean(axis=-2)  # (...,T,2,2)
    gap = np.linalg.norm(centre[..., 0, :] - centre[..., 1, :], axis=-1) / (0.5 * (s[..., 0] + s[..., 1]))
    gap = np.where(both[..., 0], np.clip(gap, 0.0, _CLIP), 0.0)[..., None]
    out = np.concatenate([block.reshape(lead + (t, 2 * HAND_BLOCK)), gap, pres.astype(np.float32)], axis=-1)
    return np.nan_to_num(out, nan=0.0, posinf=_CLIP, neginf=-_CLIP).astype(np.float32)


def swap_slots(features: np.ndarray) -> np.ndarray:
    """The feature vector of the same frames with the two hand slots exchanged."""
    f = np.asarray(features)
    a, b = f[..., :HAND_BLOCK], f[..., HAND_BLOCK:2 * HAND_BLOCK]
    g = f[..., 2 * HAND_BLOCK:]
    return np.concatenate([b, a, g[..., :1], g[..., 2:3], g[..., 1:2]], axis=-1)


# --------------------------------------------------------------------------- augmentation (training only)
@dataclass
class PairAugmentConfig:
    """Augmentation of RAW landmark windows (applied before :func:`featurize`).

    In-plane rotation, translation and uniform scale are not listed: the features are invariant
    to them already.
    """

    swap: bool = True            # exchange the two slots
    mirror: bool = True          # horizontal flip (labels have no side, so they are unchanged)
    tilt_deg: float = 30.0       # out-of-plane camera tilt about the x and y axes
    stretch: float = 0.10        # anisotropic x stretch (aspect / lens error)
    hand_scale: float = 0.10     # one hand larger/smaller than the other
    offset: float = 0.05         # shift of one hand relative to the other, in image-height units
    jitter: float = 0.0025       # per-landmark noise, image-height units
    drop_hand_p: float = 0.35    # hide one hand for part of the window (when the other is visible)
    drop_all_p: float = 0.10     # of those, hide it for the whole window

    def to_dict(self) -> dict[str, float | bool]:
        return dict(self.__dict__)


def augment_raw(raw: np.ndarray, presence: np.ndarray, aspect: np.ndarray, cfg: PairAugmentConfig, rng: np.random.Generator
                ) -> tuple[np.ndarray, np.ndarray]:
    """raw (B,T,2,21,3), presence (B,T,2), aspect (B,). Returns augmented copies (same shapes)."""
    raw = np.asarray(raw, np.float32).copy()
    pres = np.asarray(presence, np.float32).copy()
    b, t = raw.shape[:2]
    a = np.asarray(aspect, np.float32).reshape(b, 1, 1, 1)
    on = (pres > 0.5)[..., None, None]  # (B,T,2,1,1)
    # work in isotropic coordinates (image-height units)
    raw[..., 0] *= a
    raw[..., 2] *= a
    if cfg.mirror:
        flip = rng.random(b) < 0.5
        raw[flip, ..., 0] = a[flip] - raw[flip, ..., 0]
    if cfg.stretch > 0:
        raw[..., 0] *= rng.uniform(1 - cfg.stretch, 1 + cfg.stretch, size=(b, 1, 1, 1)).astype(np.float32)
    if cfg.hand_scale > 0:
        k = rng.uniform(1 - cfg.hand_scale, 1 + cfg.hand_scale, size=(b, 1, 1, 1)).astype(np.float32)
        wrist = raw[:, :, 1:2, WRIST:WRIST + 1, :]
        raw[:, :, 1:2] = (raw[:, :, 1:2] - wrist) * k[..., None] + wrist
    if cfg.offset > 0:
        raw[:, :, 1, :, :2] += rng.normal(0.0, cfg.offset, size=(b, 1, 1, 2)).astype(np.float32)
    if cfg.tilt_deg > 0:
        cnt = np.maximum(on.sum(axis=(1, 2, 3, 4), keepdims=True), 1) * 21
        centre = (raw * on).sum(axis=(1, 2, 3), keepdims=True) / cnt  # (B,1,1,1,3)
        ax, ay = np.deg2rad(rng.uniform(-cfg.tilt_deg, cfg.tilt_deg, size=(2, b))).astype(np.float32)
        cx, sx, cy, sy = np.cos(ax), np.sin(ax), np.cos(ay), np.sin(ay)
        rot = np.zeros((b, 3, 3), np.float32)  # R = Ry @ Rx
        rot[:, 0, 0], rot[:, 0, 1], rot[:, 0, 2] = cy, sy * sx, sy * cx
        rot[:, 1, 0], rot[:, 1, 1], rot[:, 1, 2] = 0.0, cx, -sx
        rot[:, 2, 0], rot[:, 2, 1], rot[:, 2, 2] = -sy, cy * sx, cy * cx
        q = raw - centre
        q[..., 2] = raw[..., 2]  # each hand's depth is relative to its own wrist
        q = np.einsum("bij,btkmj->btkmi", rot, q)
        wz = q[..., WRIST:WRIST + 1, 2:3]  # keep the wrist at depth 0 (MediaPipe convention)
        raw = np.concatenate([q[..., :2] + centre[..., :2], q[..., 2:3] - wz], axis=-1)
    if cfg.jitter > 0:
        raw += rng.normal(0.0, cfg.jitter, size=raw.shape).astype(np.float32)
    if cfg.drop_hand_p > 0:
        for i in np.where(rng.random(b) < cfg.drop_hand_p)[0]:
            k = int(rng.integers(0, 2))
            if rng.random() < cfg.drop_all_p:
                lo, hi = 0, t
            else:
                n = int(rng.integers(max(2, t // 4), t + 1))
                lo = int(rng.integers(0, t - n + 1))
                hi = lo + n
            keep = pres[i, lo:hi, 1 - k] > 0.5  # only where the other hand stays visible
            pres[i, lo:hi, k] = np.where(keep, 0.0, pres[i, lo:hi, k])
    if cfg.swap:
        sw = rng.random(b) < 0.5
        raw[sw] = raw[sw][:, :, ::-1]
        pres[sw] = pres[sw][:, :, ::-1]
    raw[..., 0] /= a
    raw[..., 2] /= a
    raw *= (pres > 0.5)[..., None, None]
    return raw.astype(np.float32), pres.astype(np.float32)


def smooth_probabilities(prev: np.ndarray | None, new: np.ndarray, dt: float, tau_s: float) -> np.ndarray:
    """Exponential smoothing of a probability vector with time constant ``tau_s`` (0 = off)."""
    if prev is None or tau_s <= 0 or dt <= 0:
        return np.asarray(new, np.float64)
    alpha = 1.0 - float(np.exp(-dt / tau_s))
    out = (1.0 - alpha) * np.asarray(prev, np.float64) + alpha * np.asarray(new, np.float64)
    return out / max(out.sum(), 1e-12)
