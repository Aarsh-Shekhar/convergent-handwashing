"""Planar camera -> projector homography estimation and validation (OpenCV).

A single planar homography maps camera pixels to projector pixels *for points on the
calibration plane* (the sink/basin surface). Hands above that plane show parallax, so the
mapping is approximate for raised hands; see docs/CALIBRATION.md. The transformation lives
behind :class:`HomographyResult` so a more advanced model can replace it without touching
the detector, backend or message contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


class CalibrationError(ValueError):
    pass


@dataclass
class HomographyResult:
    H: np.ndarray  # 3x3 camera -> projector
    inlier_mask: np.ndarray  # (N,) bool
    reprojection_errors: np.ndarray  # (N,) px for all correspondences
    rmse: float
    max_error: float
    method: str
    n_points: int
    notes: list[str] = field(default_factory=list)

    @property
    def inlier_count(self) -> int:
        return int(self.inlier_mask.sum())

    @property
    def inlier_ratio(self) -> float:
        return float(self.inlier_mask.mean()) if len(self.inlier_mask) else 0.0

    def inverse(self) -> np.ndarray:
        return np.linalg.inv(self.H)


def _as_points(p: np.ndarray, name: str) -> np.ndarray:
    arr = np.asarray(p, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise CalibrationError(f"{name} must be (N,2), got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise CalibrationError(f"{name} contains non-finite values")
    return arr


def check_degenerate(points: np.ndarray, min_points: int = 4, min_spread: float = 1e-3, collinear_tol: float = 1e-6) -> list[str]:
    """Return a list of problems (empty = ok)."""
    problems: list[str] = []
    if len(points) < min_points:
        problems.append(f"need at least {min_points} correspondences, got {len(points)}")
        return problems
    uniq = np.unique(np.round(points, 6), axis=0)
    if len(uniq) < min_points:
        problems.append("fewer than 4 distinct points (duplicates)")
    centered = uniq - uniq.mean(axis=0)
    cov = centered.T @ centered / max(len(uniq), 1)
    ev = np.linalg.eigvalsh(cov)
    if ev[-1] <= min_spread:
        problems.append("points have no spatial spread")
    elif ev[0] / ev[-1] < collinear_tol:
        problems.append("points are (nearly) collinear")
    else:
        # at least 4 points must be in general position: no three collinear among the hull
        hull = cv2.convexHull(uniq.astype(np.float32))
        if len(hull) < 4:
            problems.append("convex hull has fewer than 4 vertices (no 4 points in general position)")
    return problems


def estimate_homography(camera_pts: np.ndarray, projector_pts: np.ndarray, ransac: bool = True,
                        ransac_threshold_px: float = 3.0, min_inlier_ratio: float = 0.5) -> HomographyResult:
    cam = _as_points(camera_pts, "camera_pts")
    prj = _as_points(projector_pts, "projector_pts")
    if len(cam) != len(prj):
        raise CalibrationError("camera/projector point counts differ")
    problems = check_degenerate(cam) + [f"projector: {p}" for p in check_degenerate(prj)]
    if problems:
        raise CalibrationError("degenerate correspondences: " + "; ".join(problems))
    method = cv2.RANSAC if (ransac and len(cam) >= 5) else 0
    H, mask = cv2.findHomography(cam, prj, method, ransac_threshold_px)
    if H is None or not np.all(np.isfinite(H)) or abs(np.linalg.det(H)) < 1e-12:
        raise CalibrationError("cv2.findHomography failed or returned a singular matrix")
    H = H / H[2, 2] if abs(H[2, 2]) > 1e-12 else H
    inliers = mask.ravel().astype(bool) if mask is not None else np.ones(len(cam), dtype=bool)
    if inliers.sum() < 4:
        raise CalibrationError("fewer than 4 RANSAC inliers")
    errs = reprojection_errors(H, cam, prj)
    inl_err = errs[inliers]
    res = HomographyResult(H=H, inlier_mask=inliers, reprojection_errors=errs,
                           rmse=float(np.sqrt(np.mean(inl_err**2))), max_error=float(inl_err.max()),
                           method="ransac" if method == cv2.RANSAC else "least_squares", n_points=len(cam))
    if res.inlier_ratio < min_inlier_ratio:
        res.notes.append(f"low inlier ratio {res.inlier_ratio:.2f} < {min_inlier_ratio}")
    return res


def reprojection_errors(H: np.ndarray, src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    proj = transform_points(H, src)
    return np.linalg.norm(proj - np.asarray(dst, dtype=np.float64), axis=1)


def transform_points(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    arr = _as_points(pts, "pts")
    if len(arr) == 0:
        return arr.copy()
    out = cv2.perspectiveTransform(arr.reshape(-1, 1, 2), np.asarray(H, dtype=np.float64))
    return out.reshape(-1, 2)


def transform_point(H: np.ndarray, x: float, y: float) -> tuple[float, float] | None:
    """Single point with explicit failure (point at infinity -> None)."""
    v = np.asarray(H, dtype=np.float64) @ np.array([x, y, 1.0])
    if abs(v[2]) < 1e-12 or not np.all(np.isfinite(v)):
        return None
    return float(v[0] / v[2]), float(v[1] / v[2])


def synthetic_homography(seed: int = 0, scale: float = 1.3, rotation_deg: float = 4.0, tx: float = 40.0, ty: float = -25.0,
                         perspective: float = 2e-4) -> np.ndarray:
    """A plausible camera->projector transform for synthetic tests (known ground truth)."""
    th = np.radians(rotation_deg)
    A = np.array([[scale * np.cos(th), -scale * np.sin(th), tx], [scale * np.sin(th), scale * np.cos(th), ty], [0, 0, 1.0]])
    rng = np.random.default_rng(seed)
    P = np.eye(3)
    P[2, 0] = perspective * rng.uniform(-1, 1)
    P[2, 1] = perspective * rng.uniform(-1, 1)
    H = A @ P
    return H / H[2, 2]
