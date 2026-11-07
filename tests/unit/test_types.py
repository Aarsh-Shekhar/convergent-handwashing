import json

import numpy as np
import pytest
from pydantic import ValidationError

from convergent.common.timestamps import ClockOffsetEstimator, OrderGuard
from convergent.common.types import (
    AnchorType,
    BoundingBox,
    CalibrationProfile,
    CanonicalLabel,
    FramePacket,
    FrameTimestamps,
    GestureEvent,
    HandObservation,
    HandSide,
    ImageTransform,
    ModelPrediction,
    PredictionStatus,
    ProjectionTarget,
    Region,
    RegionEvidence,
    TrackedHands,
    ValidationStatus,
)
from tests.conftest import make_frame, make_obs, synthetic_hand


def test_frame_packet_roundtrip_excludes_image():
    f = make_frame(3, 1.25)
    data = json.loads(f.model_dump_json())
    assert "image" not in data
    back = FramePacket.model_validate(data)
    assert back.frame_id == 3 and back.capture_ts == 1.25 and back.image is None


def test_frame_packet_rejects_dimension_mismatch():
    with pytest.raises(ValidationError):
        FramePacket(frame_id=0, session_id="s", timestamps=FrameTimestamps(capture_ts=0), width=100, height=100, source_id="x",
                    transform=ImageTransform(original_width=100, original_height=100), image=np.zeros((50, 100, 3), np.uint8))


def test_frame_packet_missing_fields_and_extra_forbidden():
    with pytest.raises(ValidationError):
        FramePacket.model_validate({"frame_id": 1})
    with pytest.raises(ValidationError):
        FramePacket.model_validate({**json.loads(make_frame().model_dump_json()), "unexpected": 1})


def test_timestamps_order_validation():
    with pytest.raises(ValidationError):
        FrameTimestamps(capture_ts=1.0, arrival_ts=5.0, processed_ts=4.0)
    ts = FrameTimestamps(capture_ts=1.0, arrival_ts=5.0, processed_ts=5.5)
    assert ts.capture_clock == "source_monotonic"


def test_image_transform_rotation_validation():
    with pytest.raises(ValidationError):
        ImageTransform(original_width=10, original_height=10, rotation_deg=45)
    assert ImageTransform(original_width=10, original_height=10, rotation_deg=450).rotation_deg == 90


def test_hand_observation_requires_21_landmarks():
    with pytest.raises((ValidationError, ValueError)):
        HandObservation.from_array(np.zeros((20, 3)), track_id=0, side=HandSide.LEFT, handedness_confidence=0.5, tracking_quality=0.5)
    obs = make_obs(HandSide.LEFT)
    assert obs.landmark_array().shape == (21, 3)
    with pytest.raises(ValidationError):
        HandObservation.from_array(synthetic_hand(), track_id=0, side=HandSide.BOTH, handedness_confidence=0.5, tracking_quality=0.5)


def test_tracked_hands_slot_sides_enforced():
    with pytest.raises(ValidationError):
        TrackedHands(frame_id=0, capture_ts=0, left=make_obs(HandSide.RIGHT))
    th = TrackedHands(frame_id=0, capture_ts=0, left=make_obs(HandSide.LEFT), right=None)
    assert th.num_hands == 1 and th.get(HandSide.RIGHT) is None and th.by_raw_label("Right") is th.left


def test_bbox_validation():
    with pytest.raises(ValidationError):
        BoundingBox(x_min=0.5, y_min=0.1, x_max=0.2, y_max=0.3)
    b = BoundingBox(x_min=0.1, y_min=0.1, x_max=0.3, y_max=0.5)
    assert b.center == (0.2, 0.3) and abs(b.width - 0.2) < 1e-12


def test_model_prediction_valid_requires_canonical_and_ordered_window():
    with pytest.raises(ValidationError):
        ModelPrediction(model_id="m", model_version="1", window_start_ts=0, window_end_ts=1, status=PredictionStatus.VALID)
    with pytest.raises(ValidationError):
        ModelPrediction(model_id="m", model_version="1", window_start_ts=2, window_end_ts=1, status=PredictionStatus.UNKNOWN)
    p = ModelPrediction(model_id="m", model_version="1", window_start_ts=0, window_end_ts=1, status=PredictionStatus.MODEL_UNAVAILABLE)
    assert not p.is_valid
    assert CanonicalLabel(technique="thumb_rubbing", side=HandSide.LEFT).key == "left_thumb_rubbing"
    assert CanonicalLabel(technique="thumb_rubbing", side=HandSide.UNRESOLVED).key == "thumb_rubbing"


def test_gesture_event_duration_constraints():
    with pytest.raises(ValidationError):
        GestureEvent(session_id="s", technique="palm_to_palm", side=HandSide.BOTH, start_ts=1, end_ts=0.5, validated_duration_s=0,
                     confidence=0.5, validation_status=ValidationStatus.VALIDATED)
    with pytest.raises(ValidationError):
        GestureEvent(session_id="s", technique="palm_to_palm", side=HandSide.BOTH, start_ts=0, end_ts=1, validated_duration_s=2,
                     confidence=0.5, validation_status=ValidationStatus.VALIDATED)
    e = GestureEvent(session_id="s", technique="palm_to_palm", side=HandSide.BOTH, start_ts=0, end_ts=1, validated_duration_s=1,
                     confidence=0.5, validation_status=ValidationStatus.VALIDATED)
    assert e.dedupe_key == e.model_copy().dedupe_key
    assert GestureEvent.model_validate_json(e.model_dump_json()) == e


def test_region_evidence_requires_anatomical_side():
    with pytest.raises(ValidationError):
        RegionEvidence(region=Region.PALM, side=HandSide.BOTH)
    r = RegionEvidence(region=Region.THUMB, side=HandSide.LEFT)
    assert r.status.value == "unknown" and r.observed_duration_s == 0.0


def test_calibration_profile_rejects_singular_and_bad_shape():
    with pytest.raises(ValidationError):
        CalibrationProfile(image_width=640, image_height=480, camera_to_projector=[[1, 0, 0], [0, 1, 0]])
    with pytest.raises(ValidationError):
        CalibrationProfile(image_width=640, image_height=480, camera_to_projector=[[1, 0, 0], [1, 0, 0], [0, 0, 1]])
    p = CalibrationProfile(image_width=640, image_height=480, camera_to_projector=np.eye(3).tolist())
    assert p.projector_width == 854 and p.projector_height == 480 and p.version == 1
    assert CalibrationProfile.model_validate_json(p.model_dump_json()).homography().shape == (3, 3)


def test_projection_target_serialization():
    t = ProjectionTarget(anchor_type=AnchorType.LANDMARK, anchor_id="left:lm8", camera_xy=(1.0, 2.0), projector_xy=None, confidence=0.5,
                         valid=False, reason="outside", timestamp=1.0)
    assert ProjectionTarget.model_validate_json(t.model_dump_json()).valid is False


def test_order_guard_and_clock_offset():
    g = OrderGuard()
    assert g.accept(0, 0.0) and g.accept(1, 0.1)
    assert not g.accept(2, 0.05) and not g.accept(1, 0.2)
    assert g.rejected == 2
    est = ClockOffsetEstimator()
    assert est.offset is None
    for d, a in ((0.0, 10.0), (0.1, 10.15), (0.2, 10.2)):
        est.add(d, a)
    assert abs(est.offset - 10.0) < 1e-9
    assert abs(est.latency_estimate(0.1, 10.15) - 0.05) < 1e-9
