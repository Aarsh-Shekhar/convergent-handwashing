# Architecture

## Processes

| Process | Where | Role |
|---|---|---|
| **Pi agent** (`convergent.pi_agent`) | Raspberry Pi Zero 2 W (or 3 A+) (512 MB) | Picamera2 capture → JPEG → WebSocket client (bounded 2-deep queue, latest wins) → laptop. Receives render commands, draws diagnostic frames to `/dev/fb0` (HDMI → RIF6). Heartbeats with throttle/temperature/memory. Reconnects with backoff. No ML, no OpenCV. |
| **Pipeline** (`convergent.cli network|replay|camera`) | Laptop | Hosts the **device gateway** (WebSocket server, port 8765) that decodes frames into a `NetworkSource`; runs tracker → branches → fusion → validation → regions → projection; sends render commands back over the same connection; writes to the backend over HTTP. |
| **Backend** (`convergent.cli backend`) | Laptop | FastAPI + SQLAlchemy + Alembic. REST `/api/v1/*`, WebSockets `/ws/v1/{observations,render,device}`. SQLite for dev/tests, PostgreSQL (docker-compose) for persistence. |

The video stream goes to the pipeline process (it needs the pixels); the backend only receives
structured outputs and device health. `/ws/v1/device` on the backend accepts the same JSON
control messages so a Pi can report health even when no pipeline is running.

## Per-frame data flow and contracts (`common/types.py`)

```
FrameSource.read()            -> FramePacket   {frame_id, session_id, timestamps{capture,arrival,processed}, w,h, transform, image}
HandTracker.detect(frame)     -> TrackedHands  {left: HandObservation|None, right: ..., unassigned[]}   (one MediaPipe call per frame)
HandHygieneAdapter.predict(h) -> ModelPrediction {model_id, version, window, native_label, canonical{technique,side,resolved}, probabilities, status}
SkiaTemporalAdapter.predict(h)-> ModelPrediction (window of 16 contiguous frames; NO_INPUT until full)
YoloAdapter.predict(frame)    -> ModelPrediction (every N frames; boxes in extras)
PredictionAligner.collect(ts) -> {model_id: latest prediction overlapping ts}
FusionEngine.combine(...)     -> ModelPrediction(model_id="fusion", canonical_probabilities over registry keys, participating branches in extras)
EventDetector.update(fused,q) -> [GestureEvent]  (validated/rejected; merged; de-duplicated)
ProgressTracker.add_event(ev) -> RegionEvidence x 10 (region x hand), ProgressState
ProjectionMapper.map_hands(h) -> [ProjectionTarget]  (camera px -> 854x480 projector px, smoothed, validity)
BackendClient / results files / DeviceGateway.send_render(RenderCommand)
```

Every module only imports `common.types` and the public interface of the module directly below
it; adapters never see each other's tensors (HandHygiene's right→left centroid vector is never
fed to S-Kia's left→right raw vector).

## Clocks

* `capture_ts` – source clock (video PTS, Pi monotonic, laptop monotonic for webcam). All
  temporal reasoning (sequence windows, hysteresis, durations, event times, region intervals)
  uses this clock only, so 10 FPS and 30 FPS recordings yield the same durations.
* `arrival_ts` / `processed_ts` – laptop monotonic, for latency diagnostics. `ClockOffsetEstimator`
  (NTP-style lower envelope) relates the Pi clock to the laptop clock for reporting only.
* UTC – session bookkeeping in the backend (`started_utc`, `ended_utc`, row timestamps).

## Label space (`configs/labels.yaml`)

Canonical techniques: the six WHO rubbing techniques, `none/unknown/transition`, and extensions
(`wrist_rubbing`). Sided techniques carry the hand **receiving** the action. Each model has a
native→canonical map with a `resolved` flag; upstream side semantics (`2.1`, `2lt`, …) are
`unresolved` until a human verifies them, and unresolved sides never create side-specific region
evidence. Fused distributions live over `canonical_keys()` (`palm_to_palm`, `left_thumb_rubbing`, …).

## Fusion (`detection/fusion.py`)

reliability-weighted average of per-branch **calibrated** canonical distributions, renormalised
over branches that actually produced a VALID/UNKNOWN output. Missing branches contribute nothing
and are listed in `extras.participating`/`branches`. A confident disagreeing branch halves the
fused confidence; below `unknown_threshold` the frame is UNKNOWN. `MetaClassifierFusion` is the
learnable alternative (requires out-of-sample base predictions).

## Temporal validation (`detection/temporal.py`, `event_detector.py`)

Hysteresis (enter/exit confidence), minimum supported duration, pause on UNKNOWN/low-quality
frames, gap termination, switching on a new confident technique, max duration cap; merging of
fragments within `merge_gap_s`; duplicate suppression by `(technique, side, start)`.

## Regions (`regions/`)

Technique → regions (acting/receiving hands) with weights; evidence accumulates
`duration × weight × visibility × confidence`; `SUFFICIENT` when ≥ `min_sufficient_duration_s`
of weighted evidence; `PARTIAL` if visibility/side uncertainty; otherwise `INSUFFICIENT`/`UNKNOWN`.
`coverage_estimate` = confidence-weighted fraction of the 10 cells that are SUFFICIENT.

## Projection (`projection/`)

Planar homography camera→projector (RANSAC, degeneracy checks, reprojection RMSE), profile
versioning (file + backend), anchors (centroids, fingertips, region centroids) → projector px →
One-Euro smoothing with reset on gaps and bounded (≤ 100 ms) prediction. Parallax above the
calibration plane is a documented limitation; the mapper is the only module that knows the
geometry, so a 3-D model can replace it later without touching contracts.

## Backend schema (`backend/models.py`)

devices, sessions, model_artifacts, predictions (idempotency key), gesture_events (dedupe key),
region_evidence (one row per region×side per session, snapshot-monotonic), calibration_profiles
(full document + active flag), evaluation_runs, annotations. No raw frames in the DB; optional
recordings are files referenced by `sessions.recording_path` (off by default).

## Extensibility rules

* Adding a technique: edit `labels.yaml` (+ `regions/evidence.py` mapping if it is a core region technique).
* Adding a classifier: implement `Classifier` (`load`, `status`, `predict`) and register its label map; fusion picks it up via `fusion.weights`.
* Swapping transport encoding: `communication/protocol.py` encoding byte; CV modules untouched.
* Replacing the homography: implement the `ProjectionMapper` point methods.
