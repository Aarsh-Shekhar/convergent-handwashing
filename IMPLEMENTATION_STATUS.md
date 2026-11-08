# Implementation status (progress file – keep current)

Last updated: 2026-11-07 (evening: temporal model trained on the Kaggle dataset). Verification
environment: Linux x86_64 container, Python 3.11.14 (uv), CPU only (2 cores). macOS install is
scripted (`SETUP_MAC.command`, logs to `setup_log.txt`) but has not been executed on a Mac yet –
the first teammate to run it should paste the last lines of the log into `docs/TEST_RESULTS.md`.
Hardware (Pi 3 A+, Arducam B0176, RIF6) has **not** arrived: everything Pi/projector-specific is
"implemented, awaiting hardware"; `docs/HARDWARE_DAY_RUNBOOK.md` + `START_LAPTOP.command` +
`scripts/pi/install_pi.sh` are the bring-up path.

Legend: ✅ implemented & tested here · 🟡 implemented, awaiting model artifacts or validation data ·
🔧 implemented, awaiting physical hardware · ⛔ blocked by a real technical issue

| Stage | Scope | Status | Verification |
|---|---|---|---|
| 1 Foundation & interfaces | `pyproject.toml` + `uv.lock` (4 dependency groups), typed Pydantic structures (`FramePacket`, `HandObservation`, `TrackedHands`, `ModelPrediction`, `GestureEvent`, `RegionEvidence`, `CalibrationProfile`, `ProjectionTarget`), clocks, config, logging | ✅ | `tests/unit/test_types.py` (13 tests): serialization, invalid inputs, missing fields, timestamp order, size mismatch |
| 2 Video ingestion & replay | `FrameSource` abstraction: MP4 (PTS timestamps), webcam, network (Pi), synthetic; PTS-based decimation; latest-frame bounded queue with drop counters; out-of-order rejection; device gateway + Pi camera agent + local emulator | ✅ (webcam path not exercised – no camera in the container) | `test_sources.py` (11): deterministic double replay, decimation, queue drops, reconnect; `tests/integration/test_pi_transport.py` (4): emulator→gateway frames, status, render ack, reconnect after gateway restart, auth rejection |
| 3 Shared hand tracking | `HandTracker` with MediaPipe `tasks` or bundled `solutions` backend, swap-based anatomical handedness, Hungarian track association + handedness voting + uniqueness, visibility states, diagnostic overlay | ✅ | `test_hand_tracking.py` (9): single/two hands, order independence, flips, crossing, duplicates, gaps; `test_mediapipe_real.py` (2): two-hand detection on the sample video, mirroring/handedness convention |
| 4 Landmark classifiers | HandHygiene adapter (exact right→left centroid features, `RestrictedUnpickler`, **validated numpy-forest conversion of the sklearn-1.0.2 RandomForest**: 18,262/18,262 rows identical `predict_proba`); S-Kia legacy adapter (Keras checkpoint, loads with TF 2.18/Keras 3.15, reproduces 200/200 in-sample rows); **corrected temporal LSTM trained on the 300 Kaggle videos** (PyTorch; contiguous windows that skip hand-less frames exactly like the online buffer; session-grouped split; train-only scaler with std floor; class-balanced loss; training-time augmentation; versioned artifact at `models/skia_temporal/current`, committed) + `scripts/extract_landmark_sequences.py`, `train_lstm.py`, `sweep_lstm.py`, `crossval_lstm.py` | ✅ code + ✅ real artifact (metrics: docs/TEST_RESULTS.md §3) · 🟡 accuracy on **our** camera unmeasured | `test_labels_and_adapters.py` (24) incl. feature-ordering proofs, unsupported/dangerous checkpoints, augmentation invariants, buffer/trainer window equivalence, scaler floor, synthetic train→load→infer |
| 5 YOLO branch | `YoloAdapter`: hash-allow-listed loading via pinned yolov5 v7.0 `DetectMultiBackend`, own letterbox/decode/NMS/rescale, `Step1..7` mapping, `MODEL_UNAVAILABLE` when absent; `scripts/train_yolo.py` + `fetch_yolov5.sh` | ✅ code · 🟡 no upstream weights. A **1-epoch smoke checkpoint** (`models/yolo/smoke_1epoch_last.pt`, mAP@.5 ≈ 0.07, NOT a usable detector) was trained here to prove the train→load→infer path | unit tests (4) + manual run (docs/TEST_RESULTS.md) |
| 6 Fusion & temporal validation | timestamp-aware aligner, reliability-weighted fusion over canonical keys with renormalisation over participating branches, contradiction detection, unknown rejection, per-branch calibrators (temperature/histogram), meta-classifier interface (out-of-sample guard); hysteresis/min-duration/gap/pause-resume validator; merge + duplicate suppression; evaluation (frame, event P/R, false completion, missing steps, latency, resources, ablation) | ✅ · fusion weights set from held-out evidence (temporal 1.0, HandHygiene 0.4, legacy 0.3; `configs/development.yaml`), calibrators still identity | `test_fusion_temporal.py` (19) |
| 7 Region evidence | landmark geometry (orientation, palm/back/thumb/fingers/fingertips polygons, palm-facing heuristic), technique→region mapping with acting/receiving hand, visibility-weighted accumulation, unresolved-side evidence kept unattributed, typed `ProgressState` with explicit `coverage_estimate` definition, replaceable segmentation interface, experimental foam proxy (flagged unvalidated) | ✅ | `test_regions_projection.py` (regions part, 5) |
| 8 Projection calibration | intrinsics (`calibrateCamera`), homography (`findHomography` + RANSAC, degeneracy checks, reprojection error), chessboard/dot/ArUco patterns + detection, manual-pairs fallback, profile persistence/versioning/invalidations (file + backend), `camera_to_projector`/`projector_to_camera` with validity, anchor mapping, EMA/One-Euro smoothing with reset + bounded prediction, diagnostic renderer + render protocol | ✅ synthetic · 🔧 physical calibration | `test_regions_projection.py` (projection part, 9): recovery < 2 px, inverse, degenerate rejection, OOB, resolution change, invalidation, smoothing; `scripts/calibrate_projector.py synthetic` passes |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic (`0001_initial`), SQLite dev / PostgreSQL compose, bearer-token writes (fail-closed), consistent errors, idempotent predictions/events, region snapshot monotonicity, calibration versions/activation/invalidation, evaluations, models, annotations, WebSockets (`observations`, `render`, `device`), rotating logs | ✅ | `test_backend_api.py` (7); full-video replay persisted 2,625 predictions, 7 events, 10 region rows |
| Pi agent | Picamera2 capture (lazy import), JPEG framing, bounded send queue, reconnect/backoff, status heartbeats (vcgencmd throttle flags, temperature, memory), render handling, framebuffer renderer with letterboxing, controlled shutdown; emulator | ✅ emulator · 🔧 Pi hardware | `test_pi_transport.py`, CLI round trip (`network` + `pi-emulator`) |
| Pipeline & CLI | `Pipeline` orchestration (one shared tracker, lazy branches, YOLO every N frames / worker thread in live mode, bounded buffers, backend batching, render commands), `convergent replay|camera|network|backend|pi-emulator|pi-agent|calibrate|evaluate|models|test`, Makefile | ✅ | `test_pipeline_e2e.py` (6), `tests/regression/test_replay_regression.py` (deterministic replay fingerprint) |

## Model-specific acceptance criteria that remain unverified

* **HandHygiene generalisation**: on the held-out sample video the upstream RandomForest labels the
  palm-to-palm segment as `interlaced_fingers` (frame accuracy 0.30 vs. approximate reference).
  The artifact works mechanically; its accuracy on our camera/subjects is unknown. Retrain with
  `scripts/train_handhygiene.py` on own videos.
* **HandHygiene side semantics** (`2.1/2.2`, …) and **S-Kia side semantics** (`2lt/2rt`, …) are
  `unresolved` until verified against source videos (`configs/labels.yaml: side_resolution`).
* **Corrected temporal LSTM**: trained and evaluated on held-out Kaggle sessions and on
  held-out sink groups (docs/TEST_RESULTS.md §3). Unknown: accuracy on the faucet-mounted
  Arducam view and on children's hands – the Kaggle videos are an overhead sink camera with
  adults, and MediaPipe sees only one of the two overlapping hands in ~97 % of their frames.
* **YOLO**: no usable detector; the smoke checkpoint only proves the path.
* **Fusion weights / calibrators**: weights chosen from independent held-out evidence, not fitted; calibrators identity. On the sample video the weighted two-branch fusion gives event P 0.50 / R 0.67 and names the correct missing step, but frame accuracy 0.43 vs 0.47 for the temporal branch alone – re-derive on our own recordings.
* **Pi 3 A+ throughput, B0176 focus control, RIF6 HDMI mode**: hardware not available.

## Done-criteria checklist (spec §12)

- [x] Runnable code, not plans · [x] reproducible env (`uv.lock`) · [x] ingestion/replay · [x] two-hand shared MediaPipe
- [x] HandHygiene adapter with exact input format · [x] S-Kia adapter with exact input format · [x] corrected multi-frame LSTM path
- [x] YOLO adapter integrated · [x] available artifacts genuinely loaded (HandHygiene RF/LR, S-Kia legacy) · [x] missing artifacts reported, no fake detections
- [x] documented canonical mapping for all three · [x] time-aligned fusion · [x] temporal validation events · [x] region evidence
- [x] projection calibration on synthetic fixtures · [x] Pi agent + diagnostic renderer · [x] backend with migrations · [x] pipeline persists through the backend
- [x] integration/regression tests executed (119 passed) · [x] runnable commands + docs · [x] hardware-dependent items distinguished · [x] no gamification built
