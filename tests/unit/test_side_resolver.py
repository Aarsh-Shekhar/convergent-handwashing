"""Side resolver: label-free features, mirror handling, event-level resolution, artifact loading."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from convergent.common.config import SideResolverConfig
from convergent.common.types import (
    GestureEvent,
    HandObservation,
    HandSide,
    TrackedHands,
    ValidationStatus,
    VisibilityState,
)
from convergent.detection.side_resolver import (
    N_FEATURES,
    SIDED_ORDER,
    SideResolver,
    SideResolverArtifact,
    side_features,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "models" / "side_resolver" / "current"


def hand(cx: float, cy: float, scale: float = 0.1, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    pts = rng.uniform(-1, 1, size=(21, 3)) * scale
    pts[0] = 0.0
    pts[9] = [0.0, -1.0 * scale, 0.0]  # middle-finger MCP straight "up" from the wrist: hand scale = `scale`
    pts[:, 0] += cx
    pts[:, 1] += cy
    return pts


def test_features_do_not_depend_on_hand_order_or_mediapipe_label():
    a, b = hand(0.3, 0.5, seed=1), hand(0.6, 0.5, seed=2)
    f1 = side_features([a, b], "thumb_rubbing")
    f2 = side_features([b, a], "thumb_rubbing")
    assert f1.shape == (N_FEATURES,) and np.allclose(f1, f2)
    assert f1[-len(SIDED_ORDER):].tolist() == [0.0, 0.0, 1.0, 0.0, 0.0]  # technique one-hot
    assert f1[2 * 66 + 2] == 2.0  # hand count


def test_features_are_translation_and_scale_invariant_per_hand():
    a = hand(0.3, 0.5, scale=0.1, seed=3)
    moved = a.copy()
    moved[:, :2] += [0.2, -0.1]
    bigger = (a - a[0]) * 2.0 + a[0]
    for other in (moved, bigger):
        f0, f1 = side_features([a], "back_of_hand"), side_features([other], "back_of_hand")
        assert np.allclose(f0[:63], f1[:63], atol=1e-6)


def test_mirroring_flips_x_before_features():
    a, b = hand(0.3, 0.5, seed=4), hand(0.6, 0.5, seed=5)
    mirrored_hands = []
    for h in (a, b):
        m = h.copy()
        m[:, 0] = 1.0 - m[:, 0]
        mirrored_hands.append(m)
    assert np.allclose(side_features(mirrored_hands, "wrist_rubbing"), side_features([a, b], "wrist_rubbing", mirrored=True))


def test_rejects_unsided_technique():
    with pytest.raises(ValueError):
        side_features([hand(0.5, 0.5)], "palm_to_palm")


def tracked(ts: float, arrays: list[np.ndarray]) -> TrackedHands:
    obs = [HandObservation.from_array(arr, side=HandSide.UNKNOWN, visibility=VisibilityState.VISIBLE, tracking_quality=0.9, track_id=i + 1, handedness_confidence=0.5) for i, arr in enumerate(arrays)]
    return TrackedHands(frame_id=int(ts * 15), capture_ts=ts, unassigned=obs, processing_time_ms=1.0)


def event(tech: str, start: float, end: float, side: HandSide = HandSide.UNRESOLVED) -> GestureEvent:
    return GestureEvent(session_id="s", technique=tech, side=side, start_ts=start, end_ts=end, validated_duration_s=end - start,
                        confidence=0.9, validation_status=ValidationStatus.VALIDATED, side_resolved=False)


class _FakeArtifact:
    """Returns P(right) from the x position of the first (image-left) hand: left of centre -> left receives."""

    meta = {"model_version": "fake"}
    path = Path("/nonexistent")

    def prob_right(self, feats: np.ndarray) -> np.ndarray:
        feats = np.atleast_2d(feats)
        return np.array([0.9 if f[2 * 66] > 0 else 0.1 for f in feats])  # wrist offset dx>0 means a second hand to the right


def test_event_resolution_needs_enough_frames_and_a_margin():
    res = SideResolver(_FakeArtifact(), min_frames=3, margin=0.15)
    for i in range(5):  # two hands, second to the right -> prob 0.9 -> right receives
        res.observe(tracked(i / 15.0, [hand(0.3, 0.5), hand(0.6, 0.5)]), "back_of_hand", i / 15.0)
    ev = res.resolve(event("back_of_hand", 0.0, 0.3))
    assert ev.side == HandSide.RIGHT and ev.side_resolved
    # too few frames inside the event span: unchanged
    ev2 = res.resolve(event("back_of_hand", 0.2, 0.25))
    assert ev2.side == HandSide.UNRESOLVED and not ev2.side_resolved
    # non-sided technique and already-sided events are left alone
    assert res.resolve(event("palm_to_palm", 0.0, 0.3, HandSide.BOTH)).side == HandSide.BOTH
    assert res.observe(tracked(1.0, [hand(0.3, 0.5)]), "palm_to_palm", 1.0) is None
    # frames of another technique never count
    assert res.resolve(event("thumb_rubbing", 0.0, 0.3)).side == HandSide.UNRESOLVED


def test_unavailable_resolver_is_a_no_op():
    res = SideResolver.from_config(SideResolverConfig(artifact_dir="/nonexistent/dir"))
    assert not res.available and res.status().available is False
    assert res.observe(tracked(0.0, [hand(0.5, 0.5)]), "thumb_rubbing", 0.0) is None
    ev = event("thumb_rubbing", 0.0, 1.0)
    assert res.resolve(ev) is ev


@pytest.mark.skipif(not ARTIFACT.is_dir(), reason="trained side resolver artifact not present")
def test_installed_artifact_loads_and_is_consistent():
    art = SideResolverArtifact.load(ARTIFACT)
    assert art.meta["classes"] == ["left", "right"] and art.meta["techniques"] == SIDED_ORDER
    assert art.meta["metrics"]["cv"]["frame_accuracy"] > 0.9
    p = art.prob_right(side_features([hand(0.4, 0.5), hand(0.6, 0.5)], "thumb_rubbing"))
    assert p.shape == (1,) and 0.0 <= p[0] <= 1.0
    res = SideResolver.from_config(SideResolverConfig(artifact_dir=str(ARTIFACT)))
    st = res.status()
    assert st.available and st.sha256 and "0.9" in st.message
