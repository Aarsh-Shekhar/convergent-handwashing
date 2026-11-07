# Camera–projector calibration

Goal: map a pixel in the 640×480 camera processing frame to a pixel on the RIF6's 854×480
logical canvas, with explicit validity, so projected guidance lands on/near the hands.

## Model and limitation

A planar homography `H` (3×3) relates camera and projector pixels **for points on the
calibration plane** (the basin/sink surface where the pattern is projected). Hands above that
plane show parallax: a hand 5 cm above a plane 40 cm from the camera is displaced by roughly
5/40 ≈ 12 % of its image offset from the optical axis. The system therefore reports
hand-anchor targets as approximate and never claims millimetre accuracy on 3-D hand surfaces.
`ProjectionMapper` is the only geometry-aware module; a depth-aware model can replace it later
without touching contracts.

## Synthetic self-test (no hardware)

```bash
convergent calibrate synthetic --noise 0.3 --tolerance 2.0
```
Generates 24 correspondences through a known homography, recovers it with
`cv2.findHomography(RANSAC)`, checks RMSE < 2 px, inverse mapping error, and maps a synthetic
hand anchor onto the 854×480 canvas. Executed here: rmse 0.40 px, inverse 0.27 px, pass.
`tests/unit/test_regions_projection.py` covers recovery, inverse, degenerate sets (< 4 points,
collinear, duplicates, NaN), out-of-bounds, resolution change, invalidation, smoothing,
pattern generation + detection in a simulated camera view, and intrinsics from synthetic views.

## Physical procedure (when hardware arrives)

1. Mount camera and projector rigidly (foam tape prototype); do not move them during a session.
2. Backend running; pipeline gateway running: `convergent network`.
3. Optional intrinsics: photograph a printed 9×6 chessboard from ≥ 10 poses with the B0176
   (`rpicam-still`), then `convergent calibrate intrinsics --images *.jpg --out models/calibration/intrinsics.json`.
   Lens distortion of the OV5647 is mild; intrinsics mainly improve RMSE at the frame edges.
4. Project a pattern: `convergent calibrate pattern --kind aruco_grid --out runs/pattern_aruco.png`
   (ArUco is robust to partial views and ambient light; chessboard gives more points). Show it
   through the Pi (`RenderCommand(command="pattern")` or display the PNG on the Pi framebuffer).
5. Capture camera frames of the projected pattern (`runs/<session>/` or `rpicam-still`), then
   `convergent calibrate from-images --kind aruco_grid --images cam*.jpg --backend-url http://127.0.0.1:8000`.
   The profile is saved to `models/calibration/active_profile.json` and stored/activated in the backend.
6. If detection fails (glare, low contrast): `convergent calibrate from-pairs --pairs pairs.json --image-size 640 480`
   with ≥ 4 (better ≥ 8) manually measured correspondences (`data/fixtures/manual_pairs.example.json`).
7. Validate: RMSE ≤ 4 px (`configs/projector.yaml: max_rmse_px`), inlier ratio ≥ 0.5, visually
   project crosshairs on fingertips (`projector.anchors`). Record the HDMI mode the RIF6 negotiated.
8. Any camera/projector move → `POST /api/v1/calibrations/{id}/invalidate` and recalibrate.

Profiles record image size/orientation/crop, projector logical size, intrinsics (if any), the
homography, inlier counts, RMSE/max error, plane id, timestamp, version and validity.

## Runtime

* Anchors: hand centroids, fingertips (landmarks 4/8/12/16/20), region centroids.
* Smoothing: One-Euro filter (default) or EMA, reset when a target is missing for > 0.5 s;
  linear prediction limited to 100 ms, never when invalid.
* Targets outside the canvas or from an invalid profile are reported `valid=false` with a reason.
* Render commands: `draw` (crosshair/circle/polygon/text items in projector px), `pattern`,
  `clear`; each describes a complete frame and may carry `valid_until_ns` on the Pi clock.
