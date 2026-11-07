#!/usr/bin/env python
"""Camera-projector calibration tools.

Sub-commands:
  synthetic   self-test: known homography -> synthetic correspondences -> recover -> verify (no hardware)
  pattern     render a calibration pattern (chessboard | dot_grid | aruco_grid) to a PNG for the projector
  from-pairs  build + validate + save a profile from manual correspondences JSON ({"pairs": [...]})
  from-images detect the projected pattern in camera images and build a profile (hardware session)
  intrinsics  camera intrinsics from chessboard images (cv2.calibrateCamera)
  show        print a saved profile and map a few test points both ways

Profiles are saved as JSON (``--out``), default ``models/calibration/active_profile.json``; with
``--backend-url`` they are also POSTed to the backend (versioned, activatable, invalidatable).

    python scripts/calibrate_projector.py synthetic --noise 0.5
    python scripts/calibrate_projector.py pattern --kind chessboard --out runs/pattern_chessboard.png
    python scripts/calibrate_projector.py from-pairs --pairs data/fixtures/manual_pairs.example.json --image-size 640 480
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from convergent.common.config import load_settings, resolve_path  # noqa: E402
from convergent.common.types import PROJECTOR_LOGICAL_HEIGHT, PROJECTOR_LOGICAL_WIDTH  # noqa: E402
from convergent.projection.calibration import (  # noqa: E402
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
from convergent.projection.homography import (  # noqa: E402
    estimate_homography,
    synthetic_homography,
    transform_points,
)
from convergent.projection.mapping import ProjectionMapper  # noqa: E402

DEFAULT_OUT = "models/calibration/active_profile.json"


def _maybe_post(profile, url: str | None) -> None:  # type: ignore[no-untyped-def]
    if not url:
        return
    from convergent.backend.client import BackendClient

    client = BackendClient(url, load_settings().api_token)
    res = client.post_calibration(profile, activate=True)
    print(f"stored in backend: profile_id={res['profile_id']} version={res['version']} active={res['active']}")


def cmd_synthetic(a: argparse.Namespace) -> int:
    H_true = synthetic_homography(a.seed)
    rng = np.random.default_rng(a.seed)
    cam = np.column_stack([rng.uniform(40, a.image_size[0] - 40, a.points), rng.uniform(40, a.image_size[1] - 40, a.points)])
    prj = transform_points(H_true, cam) + rng.normal(0, a.noise, size=cam.shape)
    res = estimate_homography(cam, prj)
    back = transform_points(np.linalg.inv(res.H), prj)
    inv_err = np.linalg.norm(back - cam, axis=1)
    prof, _ = build_profile(cam, prj, tuple(a.image_size), max_rmse_px=a.tolerance * 2)
    mapper = ProjectionMapper(prof)
    hand_anchor = mapper.camera_to_projector(a.image_size[0] / 2, a.image_size[1] / 2)
    ok = res.rmse <= a.tolerance and float(inv_err.mean()) <= a.tolerance
    print(json.dumps({"points": a.points, "noise_px": a.noise, "rmse_px": res.rmse, "max_err_px": res.max_error, "inliers": res.inlier_count,
                      "inverse_mean_err_px": float(inv_err.mean()), "H_rel_error": float(np.abs(res.H - H_true).max() / np.abs(H_true).max()),
                      "center_hand_anchor_projector_xy": hand_anchor.xy, "tolerance_px": a.tolerance, "pass": ok}, indent=2))
    if a.out:
        save_profile(prof, resolve_path(a.out))
        print(f"synthetic profile saved to {a.out} (for emulator/debug use only)")
    return 0 if ok else 1


def cmd_pattern(a: argparse.Namespace) -> int:
    gen = {"chessboard": generate_chessboard, "dot_grid": generate_dot_grid, "aruco_grid": generate_aruco_grid}[a.kind]
    pat = gen()
    out = resolve_path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), pat.image)
    meta = {"kind": pat.kind, "points": pat.points.tolist(), "ids": pat.ids, "meta": pat.meta,
            "canvas": [PROJECTOR_LOGICAL_WIDTH, PROJECTOR_LOGICAL_HEIGHT]}
    Path(str(out) + ".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"pattern {pat.kind} with {len(pat.points)} reference points -> {out} (+ .json with projector coordinates)")
    return 0


def cmd_from_pairs(a: argparse.Namespace) -> int:
    pairs = ManualCorrespondences.load(a.pairs)
    prof, res = build_profile(pairs.camera, pairs.projector, tuple(a.image_size), plane_id=a.plane, max_rmse_px=a.max_rmse, version=a.version,
                              notes="manual correspondences")
    print(f"rmse={res.rmse:.3f}px max={res.max_error:.3f}px inliers={res.inlier_count}/{res.n_points} valid={prof.valid} {prof.invalidation_reason}")
    save_profile(prof, resolve_path(a.out))
    print(f"profile saved to {a.out}")
    _maybe_post(prof, a.backend_url)
    return 0 if prof.valid else 1


def cmd_from_images(a: argparse.Namespace) -> int:
    pat = {"chessboard": generate_chessboard, "aruco_grid": generate_aruco_grid}[a.kind]()
    cam_pts, prj_pts = [], []
    for img_path in a.images:
        img = cv2.imread(str(img_path))
        if img is None:
            print(f"  cannot read {img_path}")
            continue
        if a.kind == "chessboard":
            corners = detect_chessboard_corners(img, pat.meta["cols"], pat.meta["rows"])
            if corners is None:
                print(f"  chessboard not found in {img_path}")
                continue
            cam_pts.append(corners)
            prj_pts.append(pat.points)
        else:
            found = detect_aruco_markers(img)
            for mid, c in found.items():
                if mid in pat.ids:
                    cam_pts.append(c[None])
                    prj_pts.append(pat.points[pat.ids.index(mid)][None])
    if not cam_pts:
        print("no correspondences detected; use the manual fallback (from-pairs)")
        return 1
    cam = np.concatenate(cam_pts)
    prj = np.concatenate(prj_pts)
    h, w = cv2.imread(str(a.images[0])).shape[:2]
    prof, res = build_profile(cam, prj, (w, h), plane_id=a.plane, max_rmse_px=a.max_rmse, version=a.version, notes=f"{a.kind} from {len(a.images)} images")
    print(f"{len(cam)} correspondences rmse={res.rmse:.3f}px inliers={res.inlier_count} valid={prof.valid} {prof.invalidation_reason}")
    save_profile(prof, resolve_path(a.out))
    _maybe_post(prof, a.backend_url)
    return 0 if prof.valid else 1


def cmd_intrinsics(a: argparse.Namespace) -> int:
    imgs = [cv2.imread(str(p)) for p in a.images]
    intr = calibrate_intrinsics([i for i in imgs if i is not None], (a.cols, a.rows), a.square)
    Path(a.out).write_text(intr.model_dump_json(indent=2), encoding="utf-8")
    print(f"intrinsics rms={intr.rms_reprojection_error:.3f}px -> {a.out}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    prof = load_profile(resolve_path(a.profile))
    print(prof.model_dump_json(indent=2))
    mapper = ProjectionMapper(prof)
    for x, y in ((0, 0), (prof.image_width / 2, prof.image_height / 2), (prof.image_width - 1, prof.image_height - 1)):
        m = mapper.camera_to_projector(x, y)
        back = mapper.projector_to_camera(m.x, m.y) if m.x is not None else None
        print(f"camera ({x:.0f},{y:.0f}) -> projector {m.xy} valid={m.valid} {m.reason} -> back {None if back is None else back.xy}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("synthetic")
    p.add_argument("--points", type=int, default=24)
    p.add_argument("--noise", type=float, default=0.3, help="px noise added to projector points")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--tolerance", type=float, default=2.0)
    p.add_argument("--image-size", type=int, nargs=2, default=[640, 480])
    p.add_argument("--out", default=None, help="save the synthetic profile (emulator only)")
    p.set_defaults(func=cmd_synthetic)
    p = sub.add_parser("pattern")
    p.add_argument("--kind", choices=["chessboard", "dot_grid", "aruco_grid"], default="chessboard")
    p.add_argument("--out", default="runs/pattern.png")
    p.set_defaults(func=cmd_pattern)
    for name, fn in (("from-pairs", cmd_from_pairs), ("from-images", cmd_from_images)):
        p = sub.add_parser(name)
        if name == "from-pairs":
            p.add_argument("--pairs", type=Path, required=True)
            p.add_argument("--image-size", type=int, nargs=2, required=True)
        else:
            p.add_argument("--kind", choices=["chessboard", "aruco_grid"], default="chessboard")
            p.add_argument("--images", type=Path, nargs="+", required=True)
        p.add_argument("--plane", default="sink_plane")
        p.add_argument("--max-rmse", type=float, default=4.0)
        p.add_argument("--version", type=int, default=1)
        p.add_argument("--out", default=DEFAULT_OUT)
        p.add_argument("--backend-url", default=None)
        p.set_defaults(func=fn)
    p = sub.add_parser("intrinsics")
    p.add_argument("--images", type=Path, nargs="+", required=True)
    p.add_argument("--cols", type=int, default=9)
    p.add_argument("--rows", type=int, default=6)
    p.add_argument("--square", type=float, default=1.0)
    p.add_argument("--out", default="models/calibration/intrinsics.json")
    p.set_defaults(func=cmd_intrinsics)
    p = sub.add_parser("show")
    p.add_argument("--profile", default=DEFAULT_OUT)
    p.set_defaults(func=cmd_show)
    a = ap.parse_args()
    return int(a.func(a))


if __name__ == "__main__":
    raise SystemExit(main())
