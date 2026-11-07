import json

import cv2
import numpy as np
import pytest

from convergent.common.config import ProjectorConfig, RegionsConfig, SmoothingConfig
from convergent.common.types import (
    AnchorType,
    CalibrationProfile,
    EvidenceStatus,
    GestureEvent,
    HandSide,
    Region,
    ValidationStatus,
    VisibilityState,
)
from convergent.communication.protocol import RenderCommand, RenderItem
from convergent.pi_agent.renderer import ImageRenderer, render_canvas
from convergent.projection.calibration import (
    ManualCorrespondences,
    build_profile,
    calibrate_intrinsics,
    detect_aruco_markers,
    detect_chessboard_corners,
    generate_aruco_grid,
    generate_chessboard,
    generate_dot_grid,
    load_profile,
    save_profile,
)
from convergent.projection.diagnostics import (
    render_command_for_targets,
    render_targets,
    targets_to_items,
)
from convergent.projection.homography import (
    CalibrationError,
    estimate_homography,
    synthetic_homography,
    transform_points,
)
from convergent.projection.mapping import ProjectionMapper
from convergent.projection.smoothing import EMAFilter, OneEuroFilter, TargetSmoother
from convergent.regions.evidence import EvidenceAccumulator
from convergent.regions.foam import FoamProxy
from convergent.regions.geometry import compute_geometry, point_in_polygon, region_anchors
from convergent.regions.progress import ProgressTracker
from convergent.regions.segmentation import LandmarkMaskSegmenter, mask_overlap
from tests.conftest import make_hands, make_obs

TOL = 2.0


def ev(tech, side, start, end, resolved=True, conf=0.9, status=ValidationStatus.VALIDATED):
    return GestureEvent(session_id="s", technique=tech, side=side, start_ts=start, end_ts=end, validated_duration_s=end - start,
                        confidence=conf, validation_status=status, side_resolved=resolved)


# --------------------------------------------------------------------------- regions
def test_geometry_polygons_anchors_and_orientation():
    hand = make_obs(HandSide.RIGHT)
    g = compute_geometry(hand)
    assert set(g.polygons) == set(Region) and g.hand_length > 0
    assert -135 < g.orientation_deg < -45  # fingers point up (image y down)
    anchors = region_anchors(hand)
    for r in Region:
        assert 0 <= anchors[r][0] <= 1 and 0 <= anchors[r][1] <= 1
    assert g.polygons[Region.THUMB].support == 1.0
    assert point_in_polygon(g.palm_center, g.polygons[Region.PALM].points)
    assert not point_in_polygon(np.array([0.99, 0.99]), g.polygons[Region.PALM].points)


def test_left_right_isolation_in_evidence():
    acc = EvidenceAccumulator(RegionsConfig(min_sufficient_duration_s=2.0))
    acc.observe_hands(make_hands(0.0))
    acc.add_event(ev("thumb_rubbing", HandSide.RIGHT, 0, 3))
    by = {(e.region, e.side): e for e in acc.evidence()}
    assert by[(Region.THUMB, HandSide.RIGHT)].status == EvidenceStatus.SUFFICIENT
    assert by[(Region.THUMB, HandSide.LEFT)].status == EvidenceStatus.UNKNOWN
    assert by[(Region.PALM, HandSide.LEFT)].observed_duration_s == 3.0  # acting hand's palm gets weaker evidence
    assert by[(Region.PALM, HandSide.LEFT)].status == EvidenceStatus.INSUFFICIENT


def test_unresolved_side_is_not_attributed_and_durations_accumulate():
    acc = EvidenceAccumulator(RegionsConfig(min_sufficient_duration_s=2.0))
    acc.observe_hands(make_hands(0.0))
    acc.add_event(ev("thumb_rubbing", HandSide.UNRESOLVED, 0, 5, resolved=False))
    assert all(e.status == EvidenceStatus.UNKNOWN for e in acc.evidence())
    assert acc.unattributed and acc.unattributed[0]["reason"] == "side unresolved"
    acc.add_event(ev("palm_to_palm", HandSide.BOTH, 0, 1.5))
    acc.add_event(ev("palm_to_palm", HandSide.BOTH, 2, 3.0))
    palm = {e.side: e for e in acc.evidence() if e.region == Region.PALM}
    assert palm[HandSide.LEFT].observed_duration_s == 2.5 and palm[HandSide.LEFT].status == EvidenceStatus.SUFFICIENT
    assert palm[HandSide.LEFT].first_ts == 0 and palm[HandSide.LEFT].last_ts == 3.0
    acc.add_event(ev("fingertip_rubbing", HandSide.LEFT, 0, 5, status=ValidationStatus.REJECTED))
    assert {e.side: e for e in acc.evidence() if e.region == Region.FINGERTIPS}[HandSide.LEFT].status == EvidenceStatus.UNKNOWN


def test_partial_visibility_and_extension_techniques():
    acc = EvidenceAccumulator(RegionsConfig(min_sufficient_duration_s=2.0, partial_visibility_weight=0.5))
    hands = make_hands(0.0)
    hands.left.visibility = VisibilityState.PARTIAL
    acc.observe_hands(hands)
    acc.add_event(ev("palm_to_palm", HandSide.BOTH, 0, 2.2, conf=1.0))
    palm = {e.side: e for e in acc.evidence() if e.region == Region.PALM}
    assert palm[HandSide.RIGHT].status == EvidenceStatus.SUFFICIENT
    assert palm[HandSide.LEFT].status == EvidenceStatus.INSUFFICIENT  # halved weight
    acc.add_event(ev("wrist_rubbing", HandSide.LEFT, 0, 10))  # extension: no core region mapping
    assert {e.side: e for e in acc.evidence() if e.region == Region.PALM}[HandSide.LEFT].observed_duration_s == 2.2


def test_progress_snapshot_structure_and_coverage_definition():
    acc = EvidenceAccumulator(RegionsConfig(min_sufficient_duration_s=1.0))
    acc.observe_hands(make_hands(0.0))
    pt = ProgressTracker("s", acc)
    pt.observe_detection("thumb_rubbing")
    pt.add_event(ev("palm_to_palm", HandSide.BOTH, 0, 2, conf=1.0))
    snap = pt.snapshot(2.0, {"technique": "x"})
    assert snap.techniques["palm_to_palm"].gesture_validated and snap.techniques["thumb_rubbing"].gesture_detected
    assert not snap.techniques["thumb_rubbing"].gesture_validated
    assert Region.PALM in snap.hands[HandSide.LEFT].sufficient_regions and Region.THUMB in snap.hands[HandSide.LEFT].unknown_regions
    assert snap.coverage_estimate == pytest.approx(2 / 10)
    assert "not cleanliness" in snap.model_fields["coverage_estimate"].description.lower() or "NOT" in snap.model_fields["coverage_estimate"].description
    assert snap.procedure_states["soap"] == "not_detected"
    json.loads(snap.model_dump_json())


def test_segmentation_masks_and_foam_proxy_flags():
    hand = make_obs(HandSide.LEFT)
    masks = LandmarkMaskSegmenter().masks((120, 160), hand)
    assert set(masks) == set(Region) and masks[Region.PALM].sum() > 0
    assert 0 <= mask_overlap(masks[Region.PALM], masks[Region.BACK_OF_HAND]) <= 1
    img = np.full((120, 160, 3), 250, np.uint8)  # bright white everywhere
    obs = FoamProxy().observe(img, hand)
    assert obs.lather_proxy > 0.9 and obs.validated is False and "unvalidated" in obs.limitations


# --------------------------------------------------------------------------- projection
def test_known_homography_recovery_and_inverse():
    H = synthetic_homography(0)
    rng = np.random.default_rng(0)
    cam = np.column_stack([rng.uniform(20, 620, 30), rng.uniform(20, 460, 30)])
    prj = transform_points(H, cam)
    res = estimate_homography(cam, prj)
    assert res.rmse < TOL and res.max_error < TOL and res.inlier_count == 30
    assert np.allclose(res.H / res.H[2, 2], H / H[2, 2], atol=1e-6)
    back = transform_points(res.inverse(), prj)
    assert np.abs(back - cam).max() < TOL
    noisy = estimate_homography(cam, prj + rng.normal(0, 0.5, prj.shape))
    assert noisy.rmse < TOL


def test_degenerate_correspondences_rejected():
    with pytest.raises(CalibrationError):
        estimate_homography(np.array([[0, 0], [1, 1], [2, 2]]), np.array([[0, 0], [1, 1], [2, 2]]))
    with pytest.raises(CalibrationError):
        estimate_homography(np.array([[0, 0], [1, 1], [2, 2], [3, 3]]), np.array([[0, 0], [1, 1], [2, 2], [3, 3]]))  # collinear
    with pytest.raises(CalibrationError):
        estimate_homography(np.array([[0, 0], [0, 0], [10, 0], [0, 10]]), np.array([[0, 0], [0, 0], [10, 0], [0, 10]]))  # duplicate
    with pytest.raises(CalibrationError):
        estimate_homography(np.array([[0, 0], [1, 0], [0, 1], [1, 1]]), np.array([[0, 0], [1, 0], [0, 1]]))
    with pytest.raises(CalibrationError):
        estimate_homography(np.array([[0, 0], [1, 0], [0, 1], [np.nan, 1]]), np.array([[0, 0], [1, 0], [0, 1], [1, 1]]))


def test_profile_build_save_load_and_mapping_validity(tmp_path):
    H = synthetic_homography(2)
    cam = np.array([[50, 50], [600, 40], [620, 440], [30, 450], [320, 240], [100, 300], [500, 120]], float)
    prj = transform_points(H, cam)
    prof, res = build_profile(cam, prj, (640, 480), max_rmse_px=TOL)
    assert prof.valid and prof.inlier_count == 7 and prof.projector_width == 854
    p = save_profile(prof, tmp_path / "p.json")
    loaded = load_profile(p)
    assert loaded.camera_to_projector == prof.camera_to_projector
    m = ProjectionMapper(loaded, ProjectorConfig(smoothing=SmoothingConfig(method="none")))
    fwd = m.camera_to_projector(320, 240)
    assert fwd.valid
    back = m.projector_to_camera(fwd.x, fwd.y)
    assert back.valid and abs(back.x - 320) < TOL and abs(back.y - 240) < TOL
    assert not m.camera_to_projector(320, 240, image_size=(1280, 720)).valid  # resolution change
    assert not m.camera_to_projector(float("nan"), 1).valid
    far = m.camera_to_projector(-5000, -5000)
    assert not far.valid and far.reason == "outside projector canvas"
    m.invalidate("camera moved")
    assert not m.ready and "invalid" in m.camera_to_projector(1, 1).reason
    assert not ProjectionMapper(None).camera_to_projector(1, 1).valid


def test_map_hands_targets_onto_projector_canvas():
    H = synthetic_homography(0)
    cam = np.array([[50, 50], [600, 40], [620, 440], [30, 450], [320, 240], [100, 300]], float)
    prof, _ = build_profile(cam, transform_points(H, cam), (640, 480))
    m = ProjectionMapper(prof, ProjectorConfig(anchors=["hand_centroid", "fingertips", "regions"]))
    targets = m.map_hands(make_hands(1.0), (640, 480))
    assert len(targets) == 2 * (1 + 5 + 5)
    valid = [t for t in targets if t.valid]
    assert valid and all(0 <= t.projector_xy[0] < 854 and 0 <= t.projector_xy[1] < 480 for t in valid)
    assert {t.anchor_type for t in targets} == {AnchorType.HAND_CENTROID, AnchorType.LANDMARK, AnchorType.REGION_CENTROID}
    assert all(t.calibration_profile_id == prof.profile_id for t in targets)
    canvas = render_targets(valid)
    assert canvas.shape == (480, 854, 3) and canvas.any()
    cmd = render_command_for_targets(1, targets, prof)
    assert cmd.command == "draw" and len(cmd.items) == len(valid) and cmd.calibration_version == 1
    rendered = render_canvas(RenderCommand.from_message(json.loads(cmd.to_message())))
    assert rendered.any()
    missing = m.map_hands(make_hands(1.1, left=False), (640, 480))
    assert all(t.side == HandSide.RIGHT for t in missing)


def test_smoothing_filters_reduce_jitter_reset_and_bounded_prediction():
    rng = np.random.default_rng(0)
    ts = np.arange(100) / 30.0
    truth = np.column_stack([100 + 50 * ts, 200 + 0 * ts])
    noisy = truth + rng.normal(0, 3, truth.shape)
    for f in (EMAFilter(0.3), OneEuroFilter(1.0, 0.01, 1.0)):
        out = np.array([f.update(p, t) for p, t in zip(noisy, ts, strict=True)])
        assert np.std(np.diff(out[20:, 1])) < np.std(np.diff(noisy[20:, 1]))
        assert np.abs(out[-1] - truth[-1]).max() < 15  # no excessive lag
    sm = TargetSmoother(SmoothingConfig(method="one_euro", reset_gap_s=0.5, max_prediction_horizon_s=0.1))
    sm.update("a", (0, 0), 0.0)
    sm.update("a", (10, 0), 0.1)
    pred = sm.predict("a", 0.15)
    assert pred is not None and 10 < pred[0] < 20
    assert sm.predict("a", 0.15 + 0.5) is None  # beyond horizon/gap -> no extrapolation
    assert sm.update("a", (1000, 0), 5.0) == (1000.0, 0.0)  # gap -> filter reset, no interpolation
    sm.invalidate("a")
    assert sm.predict("a", 5.1) is None
    with pytest.raises(ValueError):
        EMAFilter(0)


def test_patterns_generate_and_detect_in_simulated_camera_view():
    H = np.linalg.inv(synthetic_homography(1))  # projector -> camera
    cb = generate_chessboard()
    assert cb.image.shape == (480, 854, 3) and len(cb.points) == 54
    cam = cv2.warpPerspective(cb.image, H, (640, 480), borderValue=(255, 255, 255))
    corners = detect_chessboard_corners(cam, cb.meta["cols"], cb.meta["rows"])
    assert corners is not None and len(corners) == 54
    ar = generate_aruco_grid()
    found = detect_aruco_markers(cv2.warpPerspective(ar.image, H, (640, 480), borderValue=(255, 255, 255)))
    assert len(found) >= 8
    cam_pts = np.array([found[i] for i in ar.ids if i in found])
    prj_pts = np.array([ar.points[ar.ids.index(i)] for i in ar.ids if i in found])
    prof, res = build_profile(cam_pts, prj_pts, (640, 480))
    assert res.rmse < TOL and prof.valid
    dg = generate_dot_grid()
    assert len(dg.points) == 40 and dg.image.max() == 255


def test_manual_correspondences_fallback(tmp_path):
    H = synthetic_homography(3)
    cam = np.array([[10, 10], [600, 20], [610, 460], [20, 470], [300, 200]], float)
    mc = ManualCorrespondences(cam, transform_points(H, cam))
    mc.save(tmp_path / "pairs.json")
    loaded = ManualCorrespondences.load(tmp_path / "pairs.json")
    prof, res = build_profile(loaded.camera, loaded.projector, (640, 480))
    assert res.rmse < TOL
    (tmp_path / "short.json").write_text(json.dumps({"pairs": [{"camera": [0, 0], "projector": [0, 0]}]}))
    with pytest.raises(CalibrationError):
        ManualCorrespondences.load(tmp_path / "short.json")


def test_intrinsics_from_synthetic_chessboard_views():
    cols, rows, sq = 9, 6, 40
    board = np.full(((rows + 1) * sq + 2 * sq, (cols + 1) * sq + 2 * sq), 255, np.uint8)
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                board[sq + r * sq:sq + (r + 1) * sq, sq + c * sq:sq + (c + 1) * sq] = 0
    K = np.array([[600, 0, 320], [0, 600, 240], [0, 0, 1]], float)
    views = []
    for i in range(6):
        rvec = np.array([0.15 * np.sin(i), 0.2 * np.cos(i * 1.3), 0.05 * i])
        R, _ = cv2.Rodrigues(rvec)
        t = np.array([[-200 + 15 * i], [-150 + 10 * i], [900 + 40 * i]], float)
        Hv = K @ np.column_stack([R[:, 0], R[:, 1], t.ravel()])
        img = cv2.warpPerspective(board, Hv, (640, 480), borderValue=255)
        views.append(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    intr = calibrate_intrinsics(views, (cols, rows), square_size=1.0)
    assert abs(intr.fx - 600) / 600 < 0.1 and abs(intr.cx - 320) < 30
    assert intr.rms_reprojection_error is not None and intr.rms_reprojection_error < 1.0
    with pytest.raises(CalibrationError):
        calibrate_intrinsics(views[:2], (cols, rows))


def test_render_commands_and_renderer_expiry():
    cmd = RenderCommand(seq=5, command="draw", calibration_profile_id="cal_x", calibration_version=2, canvas_width=854, canvas_height=480,
                        items=[RenderItem(shape="crosshair", x=100, y=100, radius=10, color=[255, 0, 0], label="L"), RenderItem(shape="text", x=5, y=5, label="hi")],
                        text="debug", valid_until_ns=10)
    r = ImageRenderer()
    canvas = r.render(cmd)
    assert canvas[100, 100].tolist() == [255, 0, 0] and r.last_seq == 5
    r.tick(now_ns=20)
    assert r.last is not None and not r.last.any() and r.expired_at is not None
    chess = r.render(RenderCommand(seq=6, command="pattern", calibration_profile_id=None, calibration_version=None, canvas_width=854, canvas_height=480,
                                   items=[RenderItem(shape="chessboard")]))
    assert chess.min() == 0 and chess.max() == 255
    cleared = r.render(RenderCommand(seq=7, command="clear", calibration_profile_id=None, calibration_version=None, canvas_width=854, canvas_height=480))
    assert not cleared.any()
    with pytest.raises(Exception):
        RenderItem(shape="triangle")
    with pytest.raises(Exception):
        RenderCommand.from_message({"type": "render", "seq": 1, "command": "explode", "canvas_width": 10, "canvas_height": 10})
    assert targets_to_items([]) == []
    assert CalibrationProfile.model_validate_json(json.dumps(json.loads(CalibrationProfile(image_width=1, image_height=1, camera_to_projector=np.eye(3).tolist()).model_dump_json())))
