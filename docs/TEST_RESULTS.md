# Test results (executed 2026-11-07)

Environment: Linux x86_64 container (2 vCPU, no GPU), Python 3.11.14 in `.venv` created by
`uv sync --extra backend --extra yolo --extra dev --extra skia-legacy` from `uv.lock`
(mediapipe 0.10.21, torch 2.6.0, tensorflow-cpu 2.18.0 / keras 3.15.1, scikit-learn 1.6.1,
opencv-contrib-python 4.11.0, fastapi 0.115, sqlalchemy 2.0.x, alembic 1.x, websockets 14.2).
Hardware tests (Pi, Arducam, RIF6) were **not** run – no hardware.

## 1. Automated suite

Command: `.venv/bin/python -m pytest -q --timeout 300` (run three times to check for flakiness)

```
117 passed, 12 warnings in ~26.5 s      (x3, identical)
```

| File | Tests | Covers |
|---|---|---|
| tests/unit/test_types.py | 14 | schema round trips, invalid/missing fields, timestamp order, dimension mismatch, extra fields, singular homography, order guard, clock offset |
| tests/unit/test_sources.py | 11 | deterministic synthetic + MP4 replay (identical timestamps twice), PTS decimation, no-upscale preprocessing + inverse mapping incl. rotation, latest-frame queue drops, network source push/disconnect/out-of-order |
| tests/unit/test_hand_tracking.py | 9 | one/two hands, order independence, handedness flip outvoted, crossing keeps ids, duplicate-side resolution, gap expiry, scripted backend visibility, null backend, overlay, malformed landmarks |
| tests/unit/test_labels_and_adapters.py | 22 | registry + side-resolution overrides + invalid configs; HandHygiene feature ordering proof (right→left, centroid), zero blocks, raw vs anatomical slots, missing/unsupported/dangerous pickles, numpy-forest == sklearn, real converted artifact; S-Kia ordering (left→right), legacy normalization, sequence buffer windows/gaps/stride, contiguous windows, temporal model needs > 1 step, synthetic train → grouped split → adapter inference, bad artifacts; YOLO letterbox/RGB/rescale, decode+NMS, distribution, missing weights, untrusted hash, label/timestamp mapping |
| tests/unit/test_fusion_temporal.py | 19 | all branches / one missing / two missing (renormalisation), contradiction, invalid mapping, side resolution, tracking gate, zero weight, aligner staleness, temperature+histogram calibration reduce ECE, meta fusion guard; validator: sustained vs short, 10 vs 30 FPS equal durations, transitions, pause/resume, long gap, hysteresis, tracking gating, max duration, monotonic timestamps; merging + duplicate suppression; metrics + ablation subsets |
| tests/unit/test_regions_projection.py | 15 | geometry/anchors, left/right isolation, unresolved side unattributed, duration accumulation, partial visibility, progress snapshot + coverage definition, segmentation masks, foam proxy flags; homography recovery (< 2 px, noiseless and 0.5 px noise), inverse, degenerate sets, profile save/load, validity (OOB, resolution change, invalidated), anchors onto 854×480 + render command, smoothing/reset/bounded prediction, pattern generation + detection through a simulated camera, manual pairs, intrinsics from synthetic views, renderer expiry |
| tests/unit/test_protocol.py | 7 | binary frame header round trip + all error cases, control messages, render command round trip, JPEG/raw payload decode, bounded queues, emulated camera |
| tests/integration/test_backend_api.py | 7 | migrations applied/idempotent, auth (401, fail-closed 503, strict reads), 422/404/409 errors, session lifecycle with predictions/events/regions + duplicates + stale snapshots, persistence across restart, calibrations/models/evaluations/annotations, live-server WebSocket pub/sub, device status + reconnect, bad token |
| tests/integration/test_pipeline_e2e.py | 6 | model-unavailable mode (no fake output), deterministic replay twice + in-process backend persistence, backend outage tolerance, calibration targets → render commands → renderer, temporal branch joining fusion, one-hand sides |
| tests/integration/test_pi_transport.py | 4 | emulator → gateway frames/status/render/ack, reconnect after gateway restart with bounded queue, unauthorized device rejected (frames refused until hello), garbage/bad payload tolerance |
| tests/integration/test_mediapipe_real.py | 2 | real MediaPipe on the sample video: two-hand frames, landmark sanity; mirroring/handedness convention |
| tests/regression/test_replay_regression.py | 1 | 120-frame replay of the sample video twice → identical fused labels/events; fingerprint stored in `tests/regression/replay_fingerprint.json` |

`ruff check src tests scripts` → All checks passed.

## 2. Manual verification runs

### Artifact conversion (scikit-learn 1.0.2 pickle → numpy-forest)
`/tmp/skl12/bin/python scripts/convert_handhygiene_rf.py --pickle …/rf_10102024.pkl --csv …/Points_10102024.csv --out models/handhygiene/rf_10102024.numpy-forest.npz`
→ `rows=18262 max|dp|=0.00e+00 argmax agreement=1.0000` (export written). The original RF pickle
fails to load under scikit-learn 1.6 (tree node dtype change); LR pickles load directly.

### Full sample replay with persistence
`convergent replay --video data/samples/handwashing_missing_step.mp4 --save-results --backend inprocess`
→ 1,359 frames (90 s video decimated to 15 FPS) in 42 s wall; latency p50 25.5 ms / p90 33.8 ms
per frame (MediaPipe solutions + numpy forest); fused statuses valid 935 / unknown 53 / no_input 371;
7 validated events; backend received 2,625 predictions, 7 events, 24 region snapshots, session
ended with stats. SQLite inspection confirmed rows in `predictions` (fusion + handhygiene),
`gesture_events` (7), `region_evidence` (10 rows, e.g. palm left/right SUFFICIENT, thumbs UNKNOWN).

### Evaluation with ablation (approximate reference, out-of-distribution video)
`scripts/evaluate_models.py --config configs/evaluation.yaml --video data/samples/handwashing_missing_step.mp4 --reference data/fixtures/handwashing_missing_step.reference.json --ablation --out runs/evaluation.json`

| Branches | Frame acc | Macro-F1 | Event P / R | False completion | Missing steps predicted (actual: thumb_rubbing) | p50 latency |
|---|---|---|---|---|---|---|
| handhygiene (RF) | 0.304 | 0.183 | 0.29 / 0.33 | 0.71 | backs_of_fingers, thumb_rubbing, fingertip_rubbing | 25.7 ms |
| skia_legacy (1-step Keras) | 0.400 | 0.268 | 0.33 / 0.50 | 0.67 | interlaced_fingers, thumb_rubbing, fingertip_rubbing | 81 ms |
| handhygiene + skia_legacy (fusion) | 0.339 | 0.218 | 0.50 / 0.33 | 0.50 | palm_to_palm, thumb_rubbing, fingertip_rubbing | 82 ms |

Reading: both upstream models generalise poorly to this recording (different camera, subject
and lighting than their training data; reference boundaries are approximate), and fusion of
two weak, uncalibrated branches does not beat the best single branch on frame accuracy
(it does raise event precision). This is the measurement the spec asked for – it is not a
validation of any model, and no fusion weight has been tuned. `skia_temporal` and `yolo` did
not participate (no artifacts).

### Corrected temporal LSTM training path (synthetic smoke)
`scripts/train_lstm.py --synthetic --out /tmp/skia_smoke --epochs 8` → artifact with
`window_frames=16`, grouped split (train subjects 0,1,4,5 / val 2 / test 3), scaler fitted on
train only, loads through `SkiaTemporalAdapter` (available=True). Metrics are meaningless
(synthetic motions) and are labelled as such in `meta.json`.

### YOLOv5 training path (1-epoch smoke)
`scripts/train_yolo.py --dataset …/HandWashDataset_yoloFormat --epochs 1 --batch 8 --img 320 --out /tmp/yolo_smoke`
→ completed on CPU (yolov5 v7.0, COCO `yolov5s.pt` init); val mAP@.5 ≈ 0.07 (expected for one
epoch). The checkpoint loads through `YoloAdapter` only when its sha256 is passed/registered
(`available=True`, classes Step1..Step7, 52 ms/inference at 320 px); with an unregistered hash it
is refused (`MODEL_UNAVAILABLE … not registered as trusted`). On a val frame it returns
`UNKNOWN` (no box above 0.25) – correct behaviour for an untrained detector. Kept as
`models/yolo/smoke_1epoch_last.pt` (git-ignored); **not** registered as the handwashing detector.

### S-Kia legacy checkpoint
With the `skia-legacy` extra: `generalized_lstm_model.keras` loads (`input (None,1,126)`), and
reproduces the upstream result on 200 in-sample class-"1" landmark rows (200/200 → "1"). It is
reported as `legacy-1step`, never as the corrected temporal model.

### Projector calibration self-test
`convergent calibrate synthetic --noise 0.3` → rmse 0.40 px, max 0.80 px, 24/24 inliers,
inverse mean error 0.27 px, H relative error 0.7 %, pass. ArUco pattern detected 11/15 markers
in a simulated 640×480 camera view (others outside the view) → recovered rmse 0.16 px; chessboard
54/54 corners detected.

### Pi emulator ↔ pipeline round trip (two processes, localhost)
`convergent network --port 8766 --max-frames 80 --backend inprocess` + `convergent pi-emulator --url ws://127.0.0.1:8766 --video data/samples/handwashing_missing_step.mp4`
→ gateway received 82 frames (JPEG, 640×480), device status with fps 15, clock offset 6.9 ms;
pipeline processed 80 frames (p50 27 ms), 1 validated event persisted; 80 render commands sent,
all acknowledged (`last_render_ack=81`), 80 diagnostic PNGs written by the emulator renderer
(crosshair at hand centroid + fingertip circles on the 854×480 canvas). This run also surfaced
and fixed a real bug (numpy-array equality in dataclass `in` checks during identity resolution).

## 3. Important errors encountered and resolved

* `cv2.ROTATE_*` missing → mixed opencv-headless/contrib wheels; fixed by reinstalling contrib (Makefile does this).
* scikit-learn 1.6 cannot unpickle the 1.0.2 RandomForest → validated conversion (above).
* MediaPipe `hand_landmarker.task` download blocked in this environment (storage.googleapis.com) → tracker falls back to the bundled legacy graph; `make models` downloads it where allowed.
* `download.pytorch.org` and Kaggle unreachable here → PyPI torch (CUDA wheels, unused) and no Kaggle data.
* yolov5 v7.0 vs modern deps: needs `ipython`, `setuptools<80` (`pkg_resources`), a local font (Arial download blocked), and `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` for its pickled checkpoints (torch ≥ 2.6) – all handled in the `yolo` extra / scripts.
* Starlette `TestClient` runs each WebSocket on its own event loop → WebSocket pub/sub tests use a live uvicorn server.
* Gateway accepted frames before the hello was authenticated → now refused until `hello_ack`; agent waits for the ack before streaming.

## 4. Not verified (see IMPLEMENTATION_STATUS.md)

macOS Apple-Silicon install; webcam path; Picamera2 capture, B0176 focus control, `/dev/fb0`
rendering, RIF6 HDMI mode, Wi-Fi throughput on the Pi 3 A+; accuracy of any model on our
camera; fusion weights/calibrators.
