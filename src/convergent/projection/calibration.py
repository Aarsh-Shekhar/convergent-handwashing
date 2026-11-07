"""Camera intrinsics, calibration pattern generation, correspondence collection and
profile construction/persistence.

* :func:`calibrate_intrinsics` – OpenCV chessboard calibration from images (when available).
* :func:`generate_chessboard` / :func:`generate_dot_grid` / :func:`generate_aruco_grid` – patterns
  rendered on the 854x480 projector canvas; the projector shows them, the camera sees them,
  and detected pattern points give camera<->projector correspondences.
* :func:`detect_chessboard_corners` / :func:`detect_aruco_markers` – automated correspondence detection.
* :class:`ManualCorrespondences` – JSON/YAML fallback when automated detection is unreliable.
* :func:`build_profile` – homography + validation -> :class:`CalibrationProfile`;
  :func:`save_profile` / :func:`load_profile` – JSON persistence (the backend stores the same model).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from convergent.common.timestamps import utc_now_iso
from convergent.common.types import (
    PROJECTOR_LOGICAL_HEIGHT,
    PROJECTOR_LOGICAL_WIDTH,
    CalibrationProfile,
    CameraIntrinsics,
)
from convergent.projection.homography import CalibrationError, HomographyResult, estimate_homography


# --------------------------------------------------------------------------- intrinsics
def calibrate_intrinsics(images: list[np.ndarray], pattern_size: tuple[int, int] = (9, 6), square_size: float = 1.0) -> CameraIntrinsics:
    """Chessboard intrinsics (cv2.calibrateCamera). ``pattern_size`` = inner corners (cols, rows)."""
    if len(images) < 3:
        raise CalibrationError("need at least 3 calibration images")
    objp = np.zeros((pattern_size[0] * pattern_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern_size[0], 0:pattern_size[1]].T.reshape(-1, 2) * square_size
    obj_pts, img_pts = [], []
    shape = None
    for img in images:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        shape = gray.shape[::-1]
        ok, corners = cv2.findChessboardCorners(gray, pattern_size, None)
        if not ok:
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
        obj_pts.append(objp)
        img_pts.append(corners)
    if len(obj_pts) < 3:
        raise CalibrationError(f"chessboard found in only {len(obj_pts)} images (need >= 3)")
    rms, K, dist, _r, _t = cv2.calibrateCamera(obj_pts, img_pts, shape, None, None)
    return CameraIntrinsics(fx=float(K[0, 0]), fy=float(K[1, 1]), cx=float(K[0, 2]), cy=float(K[1, 2]),
                            distortion=[float(d) for d in np.ravel(dist)], image_width=int(shape[0]), image_height=int(shape[1]),
                            rms_reprojection_error=float(rms))


def undistort_points(pts: np.ndarray, intr: CameraIntrinsics) -> np.ndarray:
    arr = np.asarray(pts, dtype=np.float64).reshape(-1, 1, 2)
    K = intr.matrix()
    out = cv2.undistortPoints(arr, K, np.asarray(intr.distortion, dtype=np.float64), P=K)
    return out.reshape(-1, 2)


# --------------------------------------------------------------------------- patterns
@dataclass
class Pattern:
    kind: str
    image: np.ndarray  # projector canvas (H, W, 3) BGR
    points: np.ndarray  # (N,2) projector-space reference points
    ids: list[int] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def generate_chessboard(cols: int = 9, rows: int = 6, width: int = PROJECTOR_LOGICAL_WIDTH, height: int = PROJECTOR_LOGICAL_HEIGHT,
                        margin: int = 40) -> Pattern:
    """Chessboard with ``cols x rows`` INNER corners, returned with their projector coordinates."""
    sq_w = (width - 2 * margin) / (cols + 1)
    sq_h = (height - 2 * margin) / (rows + 1)
    sq = int(min(sq_w, sq_h))
    bw, bh = sq * (cols + 1), sq * (rows + 1)
    x0, y0 = (width - bw) // 2, (height - bh) // 2
    img = np.full((height, width, 3), 255, dtype=np.uint8)
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                cv2.rectangle(img, (x0 + c * sq, y0 + r * sq), (x0 + (c + 1) * sq - 1, y0 + (r + 1) * sq - 1), (0, 0, 0), -1)
    pts = np.array([[x0 + (c + 1) * sq, y0 + (r + 1) * sq] for r in range(rows) for c in range(cols)], dtype=np.float64)
    return Pattern("chessboard", img, pts, meta={"cols": cols, "rows": rows, "square": sq, "origin": [x0, y0]})


def generate_dot_grid(cols: int = 8, rows: int = 5, width: int = PROJECTOR_LOGICAL_WIDTH, height: int = PROJECTOR_LOGICAL_HEIGHT,
                      margin: int = 60, radius: int = 8) -> Pattern:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    xs = np.linspace(margin, width - margin, cols)
    ys = np.linspace(margin, height - margin, rows)
    pts = []
    for y in ys:
        for x in xs:
            cv2.circle(img, (int(round(x)), int(round(y))), radius, (255, 255, 255), -1)
            pts.append([x, y])
    return Pattern("dot_grid", img, np.array(pts, dtype=np.float64), meta={"cols": cols, "rows": rows, "radius": radius})


def generate_aruco_grid(cols: int = 5, rows: int = 3, width: int = PROJECTOR_LOGICAL_WIDTH, height: int = PROJECTOR_LOGICAL_HEIGHT,
                        marker_px: int = 90, margin: int = 30) -> Pattern:
    """Uniquely identified ArUco markers; points are marker centers keyed by id (robust to partial views)."""
    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    img = np.full((height, width, 3), 255, dtype=np.uint8)
    xs = np.linspace(margin, width - margin - marker_px, cols)
    ys = np.linspace(margin, height - margin - marker_px, rows)
    pts, ids = [], []
    mid = 0
    for y in ys:
        for x in xs:
            marker = aruco.generateImageMarker(dictionary, mid, marker_px)
            xi, yi = int(round(x)), int(round(y))
            img[yi:yi + marker_px, xi:xi + marker_px] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
            pts.append([xi + marker_px / 2.0, yi + marker_px / 2.0])
            ids.append(mid)
            mid += 1
    return Pattern("aruco_grid", img, np.array(pts, dtype=np.float64), ids, {"dict": "DICT_4X4_50", "marker_px": marker_px})


def detect_chessboard_corners(camera_image: np.ndarray, cols: int, rows: int) -> np.ndarray | None:
    gray = cv2.cvtColor(camera_image, cv2.COLOR_BGR2GRAY) if camera_image.ndim == 3 else camera_image
    ok, corners = cv2.findChessboardCorners(gray, (cols, rows), None)
    if not ok:
        return None
    corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
    return corners.reshape(-1, 2).astype(np.float64)


def detect_aruco_markers(camera_image: np.ndarray) -> dict[int, np.ndarray]:
    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    detector = aruco.ArucoDetector(dictionary, aruco.DetectorParameters())
    gray = cv2.cvtColor(camera_image, cv2.COLOR_BGR2GRAY) if camera_image.ndim == 3 else camera_image
    corners, ids, _ = detector.detectMarkers(gray)
    out: dict[int, np.ndarray] = {}
    if ids is None:
        return out
    for c, i in zip(corners, ids.ravel(), strict=True):
        out[int(i)] = c.reshape(-1, 2).mean(axis=0).astype(np.float64)
    return out


# --------------------------------------------------------------------------- manual fallback
@dataclass
class ManualCorrespondences:
    """Fallback: a human clicks/measures camera pixels for known projector points.

    File format (JSON): ``{"pairs": [{"camera": [x, y], "projector": [u, v]}, ...]}``
    """

    camera: np.ndarray
    projector: np.ndarray

    @classmethod
    def load(cls, path: str | Path) -> ManualCorrespondences:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        pairs = data.get("pairs", [])
        if len(pairs) < 4:
            raise CalibrationError("manual correspondences need at least 4 pairs")
        cam = np.array([p["camera"] for p in pairs], dtype=np.float64)
        prj = np.array([p["projector"] for p in pairs], dtype=np.float64)
        return cls(cam, prj)

    def save(self, path: str | Path) -> None:
        pairs = [{"camera": [float(a), float(b)], "projector": [float(c), float(d)]} for (a, b), (c, d) in zip(self.camera, self.projector, strict=True)]
        Path(path).write_text(json.dumps({"pairs": pairs}, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- profiles
def build_profile(camera_pts: np.ndarray, projector_pts: np.ndarray, image_size: tuple[int, int],
                  projector_size: tuple[int, int] = (PROJECTOR_LOGICAL_WIDTH, PROJECTOR_LOGICAL_HEIGHT),
                  intrinsics: CameraIntrinsics | None = None, plane_id: str = "sink_plane", rotation_deg: int = 0,
                  mirrored: bool = False, crop: tuple[int, int, int, int] | None = None, version: int = 1,
                  max_rmse_px: float | None = None, notes: str = "") -> tuple[CalibrationProfile, HomographyResult]:
    cam = np.asarray(camera_pts, dtype=np.float64)
    if intrinsics is not None and intrinsics.distortion:
        cam = undistort_points(cam, intrinsics)
    res = estimate_homography(cam, projector_pts)
    valid = True
    reason = ""
    if max_rmse_px is not None and res.rmse > max_rmse_px:
        valid, reason = False, f"rmse {res.rmse:.2f}px > {max_rmse_px}px"
    prof = CalibrationProfile(version=version, image_width=image_size[0], image_height=image_size[1], image_rotation_deg=rotation_deg,
                              image_mirrored=mirrored, crop=crop, projector_width=projector_size[0], projector_height=projector_size[1],
                              intrinsics=intrinsics, camera_to_projector=res.H.tolist(), calibration_plane_id=plane_id,
                              inlier_count=res.inlier_count, total_correspondences=res.n_points, reprojection_rmse_px=res.rmse,
                              max_reprojection_error_px=res.max_error, created_at_utc=utc_now_iso(), valid=valid,
                              invalidation_reason=reason, method=f"homography_{res.method}", notes="; ".join([notes, *res.notes]).strip("; "))
    return prof, res


def save_profile(profile: CalibrationProfile, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return p


def load_profile(path: str | Path) -> CalibrationProfile:
    return CalibrationProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))
