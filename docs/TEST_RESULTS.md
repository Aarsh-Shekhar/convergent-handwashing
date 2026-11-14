# Test results (executed 2026-11-07)

Environment: Linux x86_64 container (2 vCPU, no GPU), Python 3.11.14 in `.venv` created by
`uv sync --extra backend --extra yolo --extra dev --extra skia-legacy` from `uv.lock`
(mediapipe 0.10.21, torch 2.6.0, tensorflow-cpu 2.18.0 / keras 3.15.1, scikit-learn 1.6.1,
opencv-contrib-python 4.11.0, fastapi 0.115, sqlalchemy 2.0.x, alembic 1.x, websockets 14.2).
Hardware tests (Pi, Arducam, RIF6) were **not** run – no hardware.

## 1. Automated suite

Command: `.venv/bin/python -m pytest -q --timeout 300` (run three times to check for flakiness)

```
119 passed, 12 warnings in ~29 s      (re-run after the temporal model was installed; regression fingerprint regenerated)
```

| File | Tests | Covers |
|---|---|---|
| tests/unit/test_types.py | 14 | schema round trips, invalid/missing fields, timestamp order, dimension mismatch, extra fields, singular homography, order guard, clock offset |
| tests/unit/test_sources.py | 11 | deterministic synthetic + MP4 replay (identical timestamps twice), PTS decimation, no-upscale preprocessing + inverse mapping incl. rotation, latest-frame queue drops, network source push/disconnect/out-of-order |
| tests/unit/test_hand_tracking.py | 9 | one/two hands, order independence, handedness flip outvoted, crossing keeps ids, duplicate-side resolution, gap expiry, scripted backend visibility, null backend, overlay, malformed landmarks |
| tests/unit/test_labels_and_adapters.py | 24 | registry + side-resolution overrides + invalid configs; HandHygiene feature ordering proof (right→left, centroid), zero blocks, raw vs anatomical slots, missing/unsupported/dangerous pickles, numpy-forest == sklearn, real converted artifact; S-Kia ordering (left→right), legacy normalization, sequence buffer windows/gaps/stride, contiguous windows, temporal model needs > 1 step, synthetic train → grouped split → adapter inference, bad artifacts, augmentation invariants (mirror/label-swap, absent hands stay zero), buffer ↔ trainer window equivalence, scaler std floor; YOLO letterbox/RGB/rescale, decode+NMS, distribution, missing weights, untrusted hash, label/timestamp mapping |
| tests/unit/test_fusion_temporal.py | 19 | all branches / one missing / two missing (renormalisation), contradiction, invalid mapping, side resolution, tracking gate, zero weight, aligner staleness, temperature+histogram calibration reduce ECE, meta fusion guard; validator: sustained vs short, 10 vs 30 FPS equal durations, transitions, pause/resume, long gap, hysteresis, tracking gating, max duration, monotonic timestamps; merging + duplicate suppression; metrics + ablation subsets |
| tests/unit/test_regions_projection.py | 15 | geometry/anchors, left/right isolation, unresolved side unattributed, duration accumulation, partial visibility, progress snapshot + coverage definition, segmentation masks, foam proxy flags; homography recovery (< 2 px, noiseless and 0.5 px noise), inverse, degenerate sets, profile save/load, validity (OOB, resolution change, invalidated), anchors onto 854×480 + render command, smoothing/reset/bounded prediction, pattern generation + detection through a simulated camera, manual pairs, intrinsics from synthetic views, renderer expiry |
| tests/unit/test_protocol.py | 7 | binary frame header round trip + all error cases, control messages, render command round trip, JPEG/raw payload decode, bounded queues, emulated camera |
| tests/integration/test_backend_api.py | 7 | migrations applied/idempotent, auth (401, fail-closed 503, strict reads), 422/404/409 errors, session lifecycle with predictions/events/regions + duplicates + stale snapshots, persistence across restart, calibrations/models/evaluations/annotations, live-server WebSocket pub/sub, device status + reconnect, bad token |
| tests/integration/test_pipeline_e2e.py | 6 | model-unavailable mode (no fake output), deterministic replay twice + in-process backend persistence, backend outage tolerance, calibration targets → render commands → renderer, temporal branch joining fusion, one-hand sides |
| tests/integration/test_pi_transport.py | 4 | emulator → gateway frames/status/render/ack, reconnect after gateway restart with bounded queue, unauthorized device rejected (frames refused until hello), garbage/bad payload tolerance |
| tests/integration/test_mediapipe_real.py | 2 | real MediaPipe on the sample video: two-hand frames, landmark sanity; mirroring/handedness convention |
| tests/regression/test_replay_regression.py | 1 | 120-frame replay of the sample video twice → identical fused labels/events; fingerprint stored in `tests/regression/replay_fingerprint.<backend>.json` |

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
(equal fusion weights, run after the temporal model was installed; the recording is a different
camera/subject than any training data and the reference boundaries are approximate; the video's
actual missing step is `thumb_rubbing`)

| Branches | Frame acc | Macro-F1 | Event P / R | False completion | Missing steps predicted | p50 latency |
|---|---|---|---|---|---|---|
| handhygiene (RF) | 0.304 | 0.183 | 0.29 / 0.33 | 0.71 | backs_of_fingers, thumb_rubbing, fingertip_rubbing | 23 ms |
| **skia_temporal (v0.1.0)** | **0.465** | **0.380** | 0.40 / **0.67** | 0.60 | **thumb_rubbing** (exactly right) | 25 ms |
| skia_legacy (1-step Keras) | 0.400 | 0.268 | 0.33 / 0.50 | 0.67 | interlaced_fingers, thumb_rubbing, fingertip_rubbing | 79 ms |
| handhygiene + skia_temporal (weights 1/1) | 0.419 | 0.272 | 0.43 / 0.50 | 0.57 | palm_to_palm, thumb_rubbing | 26 ms |
| handhygiene + skia_legacy | 0.339 | 0.218 | 0.50 / 0.33 | 0.50 | palm_to_palm, thumb_rubbing, fingertip_rubbing | 82 ms |
| skia_temporal + skia_legacy | 0.461 | 0.320 | 0.33 / 0.50 | 0.67 | thumb_rubbing | 85 ms |
| all three (1/1/0.5) | 0.391 | 0.250 | 0.33 / 0.33 | 0.67 | palm_to_palm, thumb_rubbing, fingertip_rubbing | 81 ms |
| **handhygiene + skia_temporal, production weights 0.4 / 1.0** (`configs/development.yaml`, `--branches handhygiene,skia_temporal`) | 0.426 | 0.286 | **0.50 / 0.67** | **0.50** | **thumb_rubbing** | 26 ms |

Reading: the temporal model trained here is the best single branch on a recording from a camera
it never saw (0.465 frame accuracy, 2/3 of the reference events recovered, the one missing step
named correctly), and its event sequence reads like a real wash (palm_to_palm → back_of_hand →
interlaced_fingers → backs_of_fingers → fingertip_rubbing → wrist). Equal-weight fusion with the
weaker branches *lowers* frame accuracy (contradictions → `unknown`); the production weights
(0.4 / 1.0, chosen from the independent held-out evidence in §3, not fitted to this video) keep
the temporal branch's recall and missing-step answer and raise event precision to 0.50 at the cost
of 4 points of frame accuracy. Frame accuracy in the 0.4s on this video is also limited by the
approximate reference (boundaries laid out from step durations). No calibrator has been fitted.

### Corrected temporal LSTM – see §3 below (trained on the Kaggle dataset)

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

## 3. Corrected temporal LSTM trained on real data (2026-11-07)

**Data.** Kaggle `realtimear/hand-wash-dataset`: 300 videos (12 classes × 25 sessions, 5 sink
groups `G_01…G_05`), 720×480 / 1920×1080 @ 30 FPS → `scripts/extract_landmark_sequences.py`
(shared `HandTracker`, legacy MediaPipe graph, 15 FPS PTS decimation, `raw_label` feed,
`swap_handedness: true`) → 300 `.npz`, **58,168 frames**, a hand visible in 92.4 % of frames
(per class 86–100 %), 25 min on 2 CPU cores. Raw MediaPipe finds **one** hand in ~97 % of frames
(both hands overlap in every technique) – measured against raw `mediapipe.solutions.hands`
on `Step_3/HandWash_003_A_04_G_01.mp4`: tracker 1 hand 130 / 2 hands 10 / none 11 frames, raw
MediaPipe 128 / 12 / 11. So the model mostly sees one hand's 21 landmarks over time plus *which*
hand is visible.

**Windows.** Frames without hands are skipped and a timestamp gap > 0.25 s breaks the window
(identical rule in `SequenceBuffer.update` and `training.build_windows`, unit-tested for
equivalence). Prediction coverage on these recordings: window 16 → 80.5 % of frames get a
prediction, 24 → 75.4 %, 32 → 70.7 %.

**Sweep** (`scripts/sweep_lstm.py --epochs 80 --patience 12`, split seed 0, grouped by session:
17 train / 4 val `003,007,024,025` / 4 test `005,011,012,020`; selection on validation
macro-F1 only; test reported for information after the fact):

| Config | Windows (train) | Epochs | Val acc | Val macro-F1 | Test acc | Test macro-F1 |
|---|---|---|---|---|---|---|
| w16 s2 h128, no augmentation | 14.8k | 23 | 0.947 | 0.943 | 0.915 | 0.925 |
| w16 s2 h128, augmentation | 14.8k | 31 | 0.965 | 0.963 | 0.912 | 0.922 |
| w16 s2 h128, augmentation without mirror | 14.8k | 15 | 0.921 | 0.918 | 0.872 | 0.881 |
| w24 s2 h128, augmentation | 14.8k | 30 | 0.968 | 0.967 | 0.910 | 0.922 |
| w32 s2 h128, augmentation | 13.9k | 22 | 0.963 | 0.962 | 0.891 | 0.906 |
| **w24 s2 h192 d0.3, augmentation (installed as v0.1.0)** | 14.8k | 24 | **0.973** | **0.975** | 0.905 | 0.918 |

Test differences between the augmented configs (0.89–0.92) are within the noise of a 4-session
test set; the two things that clearly matter are (a) the scaler std floor – without it the
training-time jitter on MediaPipe's constant wrist-z feature (std 2×10⁻⁷) collapsed training to
chance (`FeatureScaler.MIN_STD`, now unit-tested) and (b) the mirror augmentation with
side-label swap (+4 points val over geometric augmentation alone).

**Installed artifact `models/skia_temporal/current` (v0.1.0, sha256 `98da402f…`):** window 24
frames (1.6 s at 15 FPS), stride 2, hidden 192 × 2 layers, dropout 0.3, AdamW 1e-3 + plateau
schedule, label smoothing 0.05, class-balanced loss, 22,020 windows (14,842 / 3,428 / 3,750).
Held-out sessions: **accuracy 0.905, macro-F1 0.918**; per class recall 0.91 (`1`), 0.60/0.80
(`2lt`/`2rt` – confused with each other), 0.84 (`3`, confused with `1`), ≥ 0.95 for `4lt…7rt`.
With the two sides merged (what fusion uses while `side_resolution` is `unresolved`):
technique accuracy 0.968, macro-F1 0.958.

**Leave-one-sink-group-out cross-validation** (`scripts/crossval_lstm.py`, same
hyper-parameters, each fold trains on only 3 of the 5 groups and early-stops on a 4th):

| Held-out group | Sessions | Test acc | Test macro-F1 |
|---|---|---|---|
| G_01 (DarkSteelSink1) | 5 | 0.745 | 0.730 |
| G_02 (LightSteelSink1) | 3 | 0.751 | 0.689 |
| G_03 (CeramicSink1) | 3 | 0.863 | 0.852 |
| G_04 (SmallCeramicSink6) | 3 | 0.921 | 0.918 |
| G_05 (CeramicSink2) | 8 | 0.596 | 0.559 |
| **mean ± std** | | **0.775 ± 0.112** | **0.750 ± 0.126** |

Reading: on an unseen sink/camera placement (and very likely unseen washer) the model is at
~60–92 % frame accuracy depending on how different the location is, with only 60 % of the data
to train on per fold. That is the number to expect on *our* faucet camera before any of our own
recordings are added – and the reason `docs/HARDWARE_DAY_RUNBOOK.md` §4 asks for them on day one.

Artifacts: `runs/lstm_sweep/{sweep,summary}.json`, `runs/lstm_crossval/crossval.json`,
`models/skia_temporal/current/{meta,history}.json` (git-ignored `runs/`; the installed artifact is
committed).

## 4. Important errors encountered and resolved

* `cv2.ROTATE_*` missing → mixed opencv-headless/contrib wheels; fixed by reinstalling contrib (Makefile does this).
* scikit-learn 1.6 cannot unpickle the 1.0.2 RandomForest → validated conversion (above).
* MediaPipe `hand_landmarker.task` download blocked in this environment (storage.googleapis.com) → tracker falls back to the bundled legacy graph; `make models` downloads it where allowed.
* `download.pytorch.org` and Kaggle unreachable here → PyPI torch (CUDA wheels, unused); the Kaggle zip was downloaded by the user and copied in.
* yolov5 v7.0 vs modern deps: needs `ipython`, `setuptools<80` (`pkg_resources`), a local font (Arial download blocked), and `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` for its pickled checkpoints (torch ≥ 2.6) – all handled in the `yolo` extra / scripts.
* Starlette `TestClient` runs each WebSocket on its own event loop → WebSocket pub/sub tests use a live uvicorn server.
* Gateway accepted frames before the hello was authenticated → now refused until `hello_ack`; agent waits for the ack before streaming.
* Training-time jitter + unfloored scaler std on a constant feature → chance-level model (§3); fixed with `FeatureScaler.MIN_STD`.
* `.gitignore` trailing comments on the `!models/...` lines silently kept the converted HandHygiene forest out of the first commit → comments moved to their own lines; both artifacts are now tracked.

## 5. macOS run (2026-11-07, MacBook Apple M3, macOS 26.5.2)

`bash SETUP_MAC.command`: uv 0.13.7 → Python 3.11 + arm64 wheels (cv2 4.11.0, mediapipe 0.10.21,
torch 2.6.0), `.env` written, MediaPipe `hand_landmarker.task` downloaded (so the tracker uses the
`tasks` backend there), all artifacts found; pytest 118 passed + the replay-regression test, which
had compared against the Linux (`solutions` backend) fingerprint – now one fingerprint per backend.
Live pipeline on the M3: ~23 FPS on the sample video, tracker 34–52 ms/frame.

## 6. Not verified (see IMPLEMENTATION_STATUS.md)

webcam path; Picamera2 capture, B0176 focus control, `/dev/fb0`
rendering, RIF6 HDMI mode, Wi-Fi throughput on the Pi 3 A+; accuracy of any model on our
camera; fitted fusion weights / calibrators (current weights are chosen from evidence, not fitted).

## 7. Hand-relative temporal model `temporal_v2` (2026-11-11, MacBook Apple M5 Pro)

Why and how: `docs/MODEL_INTEGRATION.md` "The hand-relative temporal model". Installed artifact:
`models/temporal_v2/current` (TCN, 48-frame window, 5 residual blocks, 128 channels, 8 classes).

**Training data** (landmarks from the live tracker settings, `scripts/extract_landmarks_v2.py`):
METC 212 videos / 207,969 frames (frame labels, 72 students) + Kaggle 300 clips / 58,168 frames.
68,773 windows; split by person (METC) and by wash (Kaggle), fixed per dataset.

**Window-level results on held-out people/washes** (`meta.json`; both hand-slot orders averaged):

| Split | Accuracy | Macro-F1 | Windows |
|---|---|---|---|
| validation (model selection) | 0.866 | 0.882 | 10,745 |
| test, all | 0.842 | 0.856 | 12,142 |
| test, METC subjects | 0.790 | 0.801 | 9,016 |
| test, Kaggle washes | 0.990 | 0.988 | 3,126 |

Per-class recall on the METC test subjects: palm 0.86, back of hand 0.89, interlaced 0.77,
backs of fingers 0.91, thumb 0.67, fingertips 0.77, none 0.73. Kaggle test: every class
≥ 0.94 (wrist 0.99). The Kaggle number is within-dataset (same five sinks); the METC number is
the more honest one. Published landmark results on METC are ~0.70 macro-F1 (Ivanovs & Ivanova
2026, different split), so 0.80 is plausible, not a leak. Calibration temperature 1.05 (ECE 0.035 → 0.031).

Variants tried on METC only (same split): TCN w32 0.787 acc, GRU w32 0.784, **TCN w48 0.805**.

**Through the full pipeline** (`scripts/benchmark_recognition.py --metc data/METC`: tracker →
branches → fusion → temporal validator, 35 videos of the held-out METC subjects, 36 min,
frame labels; `runs/benchmark_metc_*.json`):

| Measure | v1 branches (before) | all branches fused | **temporal_v2 only (installed config)** |
|---|---|---|---|
| Frame accuracy (8 classes) | 0.224 | 0.378 | **0.754** |
| Frame accuracy on washing frames | 0.079 | 0.167 | **0.729** |
| Credited / performed seconds, mean over steps | 0.065 | 0.141 | **0.705** |
| – palm to palm | 0.000 | – | **0.803** |
| – back of hand / interlaced / backs of fingers | 0.230 / 0.037 / 0.068 | – | **0.841 / 0.668 / 0.675** |
| – thumb / fingertips | 0.054 / 0.003 | – | **0.532 / 0.708** |
| Palm recall with 1 / 2 hands tracked | 0.008 / 0.004 | – | **0.871 / 0.808** |
| Seconds credited to a wrong step, per 10 s of a step | 0.7–3.2 | – | **0.15–0.73** |
| Seconds credited per 10 s of "other movement" | 1.42 | 0.21 | 1.26 |
| Fused-label changes per minute (truth: 7.8) | 248 | 65 | **24** |

Hence `fusion.weights`: temporal_v2 1.0, v1 branches 0 (they still run and are logged).

**Sample clip** (`data/samples/handwashing_missing_step.mp4`, the "thumb step missing" clip):
before – 10 fragmented events, no palm-to-palm, wash score 2★/70 "not finished"; after – six
events in order (palm 17.1 s, back of hand 17.5 s, interlaced 20.9 s, backs of fingers 17.5 s,
fingertips 8.3 s, wrist 5.7 s), thumb correctly absent, score 3★/80 finished. This clip comes
from the same footage family as the Kaggle set, so it is a sanity check, not an independent test.

**Honest limits of these numbers**

* No recording from OUR camera was used for training or testing (none exists yet). Both public
  sets are top-down sink views of adults. `docs/RECORDING_GUIDE.md` + `--rounds` in the benchmark
  give the real number in ~15 minutes once clips are recorded.
* Thumb rubbing is the weakest step (0.53 credited): the tracker loses both hands for long
  stretches there (any hand visible in ~79 % of thumb frames).
* "Other movement" in METC still earns 1.3 s of step credit per 10 s. That class is whatever
  the students did between steps (often washing-like); idle hands on our camera are untested.
* Wrist rubbing is learned from Kaggle only (25 washes).
* Targets set in the plan (credited ≥ 0.80 per step, ≤ 10 label changes/min) are met for palm
  and back of hand only.

## 8. Own webcam rounds (2026-11-12)

Data: 3 rounds by Andrew (`data/own/down1..3`), laptop webcam, front view at chest height, 15 s per
class (7 steps + not washing). down1 was recorded in a different room and shirt from down2/down3.
The tracker sees both hands in only 8 to 20% of palm-to-palm frames from this view.

Full pipeline on held-out round down3 (`scripts/benchmark_recognition.py --own data/own --rounds down3`):

| Measure | Public-only model | Trained with down1 + down2 (full train, then fine-tune) |
| --- | --- | --- |
| Frame accuracy | 0.24 | 0.59 |
| Credited / performed (mean over steps) | 0.10 | 0.48 |
| Palm to palm credited | 0.21 | 0.65 |
| Back of hand | 0.00 | 0.33 |
| Interlaced fingers | 0.16 | 0.68 |
| Backs of fingers | 0.00 | 0.53 |
| Thumb | 0.11 | 0.18 |
| Fingertips | 0.23 | 1.00 |
| Wrist | 0.00 | 0.00 (read as backs of fingers) |

Window accuracy, model fine-tuned from the public-only model (own weight 12): 0.52 with down3 held out,
0.69 with down1 held out. The same model scores 1.00 on the rounds it trained on, so it memorizes
the few own examples. The baseline on all 3 rounds was 0.27 frame accuracy, 0.14 credited.

Installed model: trained on all 3 rounds (no own test round left), so its own-camera accuracy is
expected to be around the held-out numbers above, not higher. Held-out METC window accuracy stays
0.80, Kaggle 0.98. The sample clip still gives six in-order events with thumb absent.


## 9. Side resolver and model v1.0 freeze (2026-11-14)

**Side semantics resolved from the data.** Mid-clip frames of four sessions per Kaggle folder
(`Step_{2,4,5,6,7}_{Left,Right}`, sessions 001/009/017/024) were viewed: in every `*_Left` clip the
LEFT hand is the static, receiving hand (its back / thumb / wrist is rubbed, or its palm hosts the
right hand's fingertips). `configs/labels.yaml: side_resolution` is now filled for the S-Kia labels
and the region mapping for fingertip rubbing credits the fingertips of the *acting* hand.

**MediaPipe handedness is unusable for this.** On the sided Kaggle clips, the single visible hand
carried the "acting" MediaPipe label 62 % (step 2), 22 % (4), 8 % (5), 60 % (6), 100 % (7) of the
time: a per-technique coin flip, because a hand seen palm-down over another looks like the other
hand mirrored. `temporal_v2` therefore rightly ignores it, but then had no side at all.

**Side resolver** (`detection/side_resolver.py`, `scripts/train_side_resolver.py`): an MLP
(140 → 128 → 64 → 2) on label-free geometry – the visible hands sorted by image x, each relative to
its own wrist and hand size, the wrist offset between the two when both are visible, the hand
count and the technique – predicts P(receiving hand = right). 44,164 frames / 250 clips / 25
sessions, 5-fold cross-validation grouped by session:

| Technique | Frame accuracy | Per-clip majority | Clips |
|---|---|---|---|
| back_of_hand | 0.890 | 0.960 | 50 |
| backs_of_fingers | 0.998 | 1.000 | 50 |
| thumb_rubbing | 0.977 | 1.000 | 50 |
| fingertip_rubbing | 0.989 | 1.000 | 50 |
| wrist_rubbing | 0.971 | 1.000 | 50 |
| **all** | **0.965** | | 250 |

A gradient-boosting model scored the same (0.960); the MLP ships because it is a 108 KB
`state_dict` loaded with `weights_only=True`, no pickles. The pipeline averages the per-frame
probability over the frames of each validated sided event and assigns the side when at least 6
frames were scored and the mean is ≥ 0.15 from 0.5; otherwise the event stays `unresolved`.
Camera convention is Kaggle's (overhead, user at the bottom of the frame); `side_resolver.mirrored:
true` flips it for a camera that faces the user. Caveat: trained on one camera family; re-check
on our rig (the same `--rounds` benchmark reports it).

**Region evidence visibility.** Evidence for a sided event is now gated on the pair's best
visibility over the event (median), not on the receiving hand's own label-based visibility – the
receiving hand is under the acting hand by definition, so the old rule marked every such cell
"partial". Symmetric techniques keep per-hand visibility.

**Wash score.** `finished` is a milestone, not a freeze: `finished_at_ts` is kept, timers / points /
stars keep accruing (monotonically), so a 6th or 7th step after the 20 s mark still earns 4-5 stars.
On the sample clip the step list previously showed fingertips 3.0 s / wrist 0.0 s at the moment
of finishing although 9.4 s and 5.5 s were recognised.

**Live feed.** `POST /api/v1/sessions/{id}/live` fans a `live` message (fused label, active
candidate, score, progress) out on `/ws/v1/observations`; the pipeline posts it at
`backend.live_hz` (5 Hz) and on every new event. Nothing is stored. Integration-tested with a
real WebSocket subscriber.

**Sample clip, end to end (acceptance test `tests/acceptance`, `make accept`, 53 s):**

| | before (2026-11-13) | now |
|---|---|---|
| Validated events | 6 in WHO order, thumb absent | same |
| Sides of the 4 sided events | `unresolved` | `left` (matches the footage) |
| Region cells with sufficient evidence | 4 / 10 (coverage 0.40) | 6 / 10 (coverage ≥ 0.55; thumbs unknown because the step is missing, one back-of-hand and one fingertips cell unknown because only one side was washed) |
| Wash score | 3★ / 80, step timers frozen at 76.6 s | 3★ / 80, `finished_at` 76.6 s, timers complete (fingertips 9.4 s, wrist 5.5 s) |

Test-suite: 172 passed (unit + integration + regression + acceptance) on Linux; the acceptance
module is marked `slow` + `mediapipe`. The replay regression fingerprints were re-recorded (the
model set now includes the side resolver and events carry sides); the `tasks` (macOS) fingerprint
is re-created by the first macOS test run and should be committed then.

**Model v1.0 is frozen as of this commit**: `temporal_v2` (sha256 `f33fdd0d…`), `side_resolver`
v0.1.0 (sha256 `939ac261…`), the thresholds in `configs/development.yaml` and the acceptance test
above. Changing any of them means re-agreeing the known answer in `tests/acceptance`.
