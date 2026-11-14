"""Side resolver: which hand RECEIVES a sided technique (back_of_hand, backs_of_fingers,
thumb_rubbing, fingertip_rubbing, wrist_rubbing).

Why this exists
---------------
``temporal_v2`` predicts the technique but not the side, and MediaPipe's own left/right label is
close to a coin flip when one hand covers the other (measured on the Kaggle clips: 8-62 % per
technique). Without a side, sided events stay ``unresolved`` and produce no region evidence, so
coverage topped out at ~0.4.

What it does
------------
A small MLP reads label-free hand geometry (the visible hands sorted by image x, each expressed
relative to its own wrist and hand size, plus the offset between the two wrists when both are
visible, plus the technique) and predicts P(receiving hand = right). The pipeline averages that
probability over the frames of a validated event and sets ``GestureEvent.side`` when the
average is far enough from 0.5. Convention (verified by looking at the Kaggle Step_*_Left/Right
frames, see configs/labels.yaml): the receiving hand is the *static* one – the hand whose back,
thumb or wrist is being rubbed, or whose palm hosts the other hand's fingertips.

Trained by ``scripts/train_side_resolver.py`` on the Kaggle landmark sequences; held-out-session
accuracy is in the artifact's ``meta.json`` (96.5 % per frame, 96-100 % per clip). The camera
convention is "overhead, person at the bottom of the frame" (image-left = person's left); set
``mirrored: true`` when the camera faces the user.

Artifact (``models/side_resolver/current``): ``meta.json`` (plain JSON), ``model.pt``
(``state_dict`` only, loaded with ``weights_only=True``), ``scaler.npz``.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from convergent.common.types import GestureEvent, HandSide, TrackedHands

FEATURE_VERSION = "side-v1"
SIDED_ORDER = ["back_of_hand", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing", "wrist_rubbing"]
SIDED_INDEX = {t: i for i, t in enumerate(SIDED_ORDER)}
PER_HAND = 66  # 63 relative landmarks + 2 reserved + presence flag
N_FEATURES = 2 * PER_HAND + 3 + len(SIDED_ORDER)  # + wrist offset (2) + hand count (1) + technique one-hot


def side_features(hands: list[np.ndarray], technique: str, mirrored: bool = False) -> np.ndarray:
    """Label-free geometry of up to two visible hands.

    ``hands``: list of (21, 3) normalized landmark arrays (any order, no left/right meaning).
    Returns a float32 vector of length N_FEATURES. Identical input always gives identical output,
    whichever hand MediaPipe called left or right.
    """
    if technique not in SIDED_INDEX:
        raise ValueError(f"not a sided technique: {technique}")
    out = np.zeros(N_FEATURES, np.float32)
    hs = []
    for h in hands:
        a = np.asarray(h, dtype=np.float64).reshape(21, 3).copy()
        if mirrored:
            a[:, 0] = 1.0 - a[:, 0]
        hs.append(a)
    hs.sort(key=lambda a: a[0, 0])  # image-left first
    hs = hs[:2]
    for k, a in enumerate(hs):
        rel = a - a[0]
        scale = float(np.linalg.norm(a[9, :2] - a[0, :2])) + 1e-6  # wrist -> middle-finger MCP
        out[k * PER_HAND : k * PER_HAND + 63] = (rel / scale).ravel()
        out[k * PER_HAND + 65] = 1.0
    if len(hs) == 2:
        s = float(np.linalg.norm(hs[0][9, :2] - hs[0][0, :2])) + 1e-6
        out[2 * PER_HAND : 2 * PER_HAND + 2] = (hs[1][0, :2] - hs[0][0, :2]) / s
    out[2 * PER_HAND + 2] = float(len(hs))
    out[2 * PER_HAND + 3 + SIDED_INDEX[technique]] = 1.0
    return out


def build_model(input_dim: int, hidden: tuple[int, ...] = (128, 64)):
    from torch import nn

    layers: list[Any] = []
    d = input_dim
    for i, h in enumerate(hidden):
        layers += [nn.Linear(d, h), nn.ReLU()]
        if i == 0:
            layers.append(nn.Dropout(0.2))
        d = h
    layers.append(nn.Linear(d, 2))
    return nn.Sequential(*layers)


@dataclass
class SideResolverArtifact:
    meta: dict[str, Any]
    mu: np.ndarray
    sd: np.ndarray
    model: Any
    path: Path

    @classmethod
    def load(cls, path: Path) -> SideResolverArtifact:
        import torch

        path = Path(path)
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        if meta.get("feature_version") != FEATURE_VERSION:
            raise ValueError(f"side resolver feature version {meta.get('feature_version')!r} != {FEATURE_VERSION!r}")
        if meta.get("classes") != ["left", "right"] or meta.get("techniques") != SIDED_ORDER:
            raise ValueError("side resolver artifact has an unexpected class/technique layout")
        sc = np.load(path / "scaler.npz")
        model = build_model(int(meta["input_dim"]), tuple(meta["hidden"]))
        state = torch.load(path / "model.pt", map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        model.eval()
        return cls(meta, sc["mu"].astype(np.float32), sc["sd"].astype(np.float32), model, path)

    def prob_right(self, feats: np.ndarray) -> np.ndarray:
        import torch

        x = (np.atleast_2d(feats).astype(np.float32) - self.mu) / self.sd
        with torch.no_grad():
            logits = self.model(torch.from_numpy(x))
            return torch.softmax(logits, dim=1)[:, 1].numpy()


@dataclass
class SideObservation:
    ts: float
    technique: str
    prob_right: float


@dataclass
class SideResolver:
    """Per-frame side probabilities + per-event resolution."""

    artifact: SideResolverArtifact | None
    mirrored: bool = False
    min_frames: int = 6
    margin: float = 0.15
    history_s: float = 180.0
    _obs: deque[SideObservation] = field(default_factory=deque)
    frames_scored: int = 0

    @classmethod
    def from_config(cls, cfg: Any) -> SideResolver:
        art = None
        if getattr(cfg, "enabled", True):
            p = Path(cfg.artifact_dir)
            if p.is_dir():
                art = SideResolverArtifact.load(p)
        return cls(art, mirrored=bool(cfg.mirrored), min_frames=int(cfg.min_frames), margin=float(cfg.margin))

    @property
    def available(self) -> bool:
        return self.artifact is not None

    def status(self) -> Any:
        import hashlib

        from convergent.detection.base import ArtifactStatus

        if self.artifact is None:
            return ArtifactStatus("side_resolver", False, None, "", None, "no side resolver artifact (sided events stay unresolved); train with scripts/train_side_resolver.py", FEATURE_VERSION)
        p = self.artifact.path / "model.pt"
        cv = (self.artifact.meta.get("metrics") or {}).get("cv") or {}
        acc = cv.get("frame_accuracy")
        msg = f"loaded (v{self.version}, held-out frame accuracy {acc:.3f}, mirrored={self.mirrored})" if acc is not None else f"loaded (v{self.version})"
        return ArtifactStatus("side_resolver", True, str(self.artifact.path), self.version, hashlib.sha256(p.read_bytes()).hexdigest(), msg, FEATURE_VERSION)

    @property
    def version(self) -> str:
        return str(self.artifact.meta.get("model_version", "?")) if self.artifact else "unavailable"

    def observe(self, hands: TrackedHands, technique: str | None, ts: float) -> float | None:
        """Score one frame. Returns P(receiving = right) or None when not applicable."""
        if self.artifact is None or technique not in SIDED_INDEX:
            return None
        seen = [h.landmark_array() for h in (hands.hands + hands.unassigned)]
        if not seen:
            return None
        p = float(self.artifact.prob_right(side_features(seen, technique, self.mirrored))[0])
        self._obs.append(SideObservation(ts, technique, p))
        self.frames_scored += 1
        cutoff = ts - self.history_s
        while self._obs and self._obs[0].ts < cutoff:
            self._obs.popleft()
        return p

    def resolve(self, ev: GestureEvent) -> GestureEvent:
        """Return the event with its side set from the frames inside [start_ts, end_ts], or unchanged."""
        if self.artifact is None or ev.technique not in SIDED_INDEX or ev.side in (HandSide.LEFT, HandSide.RIGHT):
            return ev
        probs = [o.prob_right for o in self._obs if o.technique == ev.technique and ev.start_ts - 1e-6 <= o.ts <= ev.end_ts + 1e-6]
        if len(probs) < self.min_frames:
            return ev
        p = float(np.mean(probs))
        if abs(p - 0.5) < self.margin:
            return ev
        side = HandSide.RIGHT if p > 0.5 else HandSide.LEFT
        return ev.model_copy(update={"side": side, "side_resolved": True})

    def resolve_all(self, events: list[GestureEvent]) -> list[GestureEvent]:
        return [self.resolve(e) for e in events]

    def reset(self) -> None:
        self._obs.clear()
