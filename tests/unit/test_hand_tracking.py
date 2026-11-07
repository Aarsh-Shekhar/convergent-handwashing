import numpy as np

from convergent.common.config import TrackerConfig
from convergent.common.types import HandSide, VisibilityState
from convergent.vision.hand_identity import HandIdentityResolver, RawHandDetection
from convergent.vision.hand_tracker import (
    HandTracker,
    NullBackend,
    ScriptedBackend,
    label_to_side,
    swap_label,
)
from convergent.vision.overlays import render_overlay
from tests.conftest import make_frame, synthetic_hand


def det(lm, label, score=0.95, swap=True):
    anat = label_to_side(swap_label(label) if swap else label)
    return RawHandDetection(lm, label, score, anat)


def test_single_hand_and_missing_hand_explicit():
    r = HandIdentityResolver()
    out = r.update([det(synthetic_hand(0.3, 0.5), "Right")], 0.0)
    assert len(out) == 1 and out[0].side == HandSide.LEFT  # swapped: non-mirrored image
    assert r.update([], 0.1) == []  # nothing fabricated for absence


def test_two_hands_order_independent():
    r = HandIdentityResolver()
    a, b = synthetic_hand(0.3, 0.5), synthetic_hand(0.7, 0.5, mirror=True)
    first = r.update([det(a, "Right"), det(b, "Left")], 0.0)
    second = r.update([det(b, "Left"), det(a, "Right")], 0.05)  # MediaPipe lists them the other way round
    ids1 = {h.side: h.track_id for h in first}
    ids2 = {h.side: h.track_id for h in second}
    assert ids1 == ids2 and set(ids1) == {HandSide.LEFT, HandSide.RIGHT}


def test_handedness_flip_is_outvoted_by_track_history():
    r = HandIdentityResolver()
    lm = synthetic_hand(0.3, 0.5)
    for i in range(6):
        out = r.update([det(lm, "Right", 0.95)], i * 0.05)
    assert out[0].side == HandSide.LEFT
    out = r.update([det(lm, "Left", 0.55)], 0.35)  # single low-confidence flip
    assert out[0].side == HandSide.LEFT and out[0].track_id == 0


def test_crossing_hands_keep_track_ids():
    r = HandIdentityResolver(max_jump=0.4)
    la = synthetic_hand(0.3, 0.5)
    rb = synthetic_hand(0.7, 0.5, mirror=True)
    r.update([det(la, "Right"), det(rb, "Left")], 0.0)
    ids = {h.side: h.track_id for h in r.update([det(la, "Right"), det(rb, "Left")], 0.05)}
    # move them towards each other and past, with a momentary handedness confusion on both
    for k, x in enumerate(np.linspace(0.3, 0.7, 9)):
        a = synthetic_hand(x, 0.5)
        b = synthetic_hand(1.0 - x, 0.5, mirror=True)
        labels = ("Left", "Right") if 0.45 < x < 0.55 else ("Right", "Left")
        out = r.update([det(a, labels[0], 0.6), det(b, labels[1], 0.6)], 0.1 + k * 0.05)
    by_id = {h.track_id: h for h in out}
    assert set(by_id) == set(ids.values())
    assert by_id[ids[HandSide.LEFT]].side == HandSide.LEFT


def test_two_detections_same_side_are_made_unique():
    r = HandIdentityResolver(handedness_trust_threshold=0.8)
    out = r.update([det(synthetic_hand(0.3, 0.5), "Right", 0.9), det(synthetic_hand(0.7, 0.5), "Right", 0.6)], 0.0)
    sides = sorted(h.side.value for h in out)
    assert sides == ["left", "right"]  # low-confidence duplicate takes the free side
    r2 = HandIdentityResolver(handedness_trust_threshold=0.8)
    out2 = r2.update([det(synthetic_hand(0.3, 0.5), "Right", 0.95), det(synthetic_hand(0.7, 0.5), "Right", 0.95)], 0.0)
    assert sorted(h.side.value for h in out2) == ["left", "unknown"]  # confident duplicate is NOT guessed


def test_tracking_gap_expires_tracks():
    r = HandIdentityResolver(max_gap_s=0.3)
    first = r.update([det(synthetic_hand(), "Right")], 0.0)[0].track_id
    later = r.update([det(synthetic_hand(), "Right")], 1.0)[0].track_id
    assert later != first and r.active_tracks == 1


def test_tracker_with_scripted_backend_sets_visibility_and_raw_labels():
    lm = synthetic_hand(0.5, 0.5)
    partial = synthetic_hand(0.98, 0.5)  # mostly outside the frame
    backend = ScriptedBackend([[(lm, "Right", 0.9)], [(partial, "Right", 0.9)]])
    tr = HandTracker(TrackerConfig(swap_handedness=True), backend)
    th = tr.detect(make_frame(0, 0.0))
    assert th.left is not None and th.left.raw_handedness_label == "Right" and th.right is None
    assert th.left.visibility == VisibilityState.VISIBLE
    th2 = tr.detect(make_frame(1, 0.05))
    assert th2.left is not None and th2.left.visibility == VisibilityState.PARTIAL
    tr2 = HandTracker(TrackerConfig(swap_handedness=False), ScriptedBackend([[(lm, "Right", 0.9)]]))
    assert tr2.detect(make_frame(0, 0.0)).right is not None  # no swap -> raw label is anatomical


def test_null_backend_and_overlay():
    tr = HandTracker(TrackerConfig(backend="null"), NullBackend())
    frame = make_frame()
    th = tr.detect(frame)
    assert th.num_hands == 0 and th.left is None and th.right is None
    img = render_overlay(frame, th, ["extra"])
    assert img.shape == frame.image.shape and img.any()
    lm = synthetic_hand()
    th2 = HandTracker(TrackerConfig(), ScriptedBackend([[(lm, "Left", 0.9), (synthetic_hand(0.8, 0.5, mirror=True), "Right", 0.9)]])).detect(frame)
    assert render_overlay(frame, th2).sum() != img.sum()


def test_malformed_landmarks_are_skipped():
    backend = ScriptedBackend([[(np.zeros((20, 3)), "Left", 0.9)]])
    th = HandTracker(TrackerConfig(), backend).detect(make_frame())
    assert th.num_hands == 0
