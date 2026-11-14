# Convergent Interactive Handwashing System – technical foundation

Computer-vision foundation for a faucet-mounted, projector-guided handwashing trainer for
children (Texas Convergent). One executable pipeline: camera frames → shared MediaPipe hand
tracking → `temporal_v2` technique model (ours; METC + Kaggle + own rounds) → side resolver
(which hand is being washed) → temporal validation → anatomical region evidence → wash score →
projector coordinates → backend persistence + live WebSocket feed → (next) game engine.

```
Arducam B0176 ──CSI──▶ Raspberry Pi Zero 2 W (or 3 A+) ──Wi-Fi (JPEG/WebSocket)──▶ Laptop (CV, fusion, backend)
                                   ▲                                      │
                           HDMI ◀──┘ ◀──── render/debug commands ─────────┘
                           RIF6 Cube (854×480 logical canvas)
```

No game engine, scoring or final animations are included (by design); the typed
`ProgressState`, `GestureEvent`, `RegionEvidence` and `ProjectionTarget` contracts plus the
backend API are what the gamification layer will consume (see `docs/GAMIFICATION_HANDOFF.md`).

## Install and run (copy-paste, macOS)

```bash
# 1. get the code (one of):
git clone https://github.com/<owner>/convergent-handwashing.git ~/convergent-handwashing
cd ~/convergent-handwashing

# 2. one-shot setup (~15 min the first time: installs uv + Python 3.11 + packages, writes .env, runs tests + a demo replay)
bash SETUP_MAC.command
tail -n 3 setup_log.txt            # must say "Setup finished successfully"

# 3. see it work on the sample video (no hardware)
.venv/bin/python -m convergent.cli replay --video data/samples/handwashing_missing_step.mp4 --save-results --backend inprocess

# 4. hardware day
bash START_LAPTOP.command          # laptop: backend + gateway + pipeline, prints your LAN IP and the device token to use
#   on the Pi (after flashing Raspberry Pi OS Lite 64-bit and copying the repo there):
#   bash scripts/pi/install_pi.sh <LAPTOP_IP> <CONVERGENT_DEVICE_TOKEN from .env>   then   sudo reboot
```

Linux instead of macOS: `make install && make models && make test`, then the same commands.
Windows: use WSL2 and the Linux commands. Everything is logged; if a step fails, send `setup_log.txt`.

## Start here

| You want to… | Do this |
|---|---|
| **Set up a laptop** (macOS Apple Silicon or Intel; ~15 min, unattended) | double-click `SETUP_MAC.command` (or `bash SETUP_MAC.command`). It installs `uv` + Python 3.11 + every package from `uv.lock`, writes `.env` with random tokens, fetches model artifacts, runs the test-suite and a full sample replay. Check `setup_log.txt` ends with `Setup finished successfully`. Linux: `make install && make models && make test`. |
| **Hardware day** (Pi + camera + projector arrive) | follow `docs/HARDWARE_DAY_RUNBOOK.md`: laptop `bash START_LAPTOP.command`; Pi `bash scripts/pi/install_pi.sh <LAPTOP_IP> <DEVICE_TOKEN>`. That is the whole bring-up. |
| **See it run without hardware** | terminal 1 `bash START_LAPTOP.command`; terminal 2 `.venv/bin/python -m convergent.cli pi-emulator --video data/samples/handwashing_missing_step.mp4 --max-frames 300` |
| **Run the pipeline on a video** | `.venv/bin/python -m convergent.cli replay --video <mp4> --save-results --backend inprocess` → `runs/<session>/` |
| **Check which models are loaded** | `.venv/bin/python -m convergent.cli models` |
| **Record our own clips / retrain** | `convergent record` (see `docs/RECORDING_GUIDE.md`) → `scripts/extract_landmarks_v2.py` → `scripts/train_temporal_v2.py --install` → `scripts/benchmark_recognition.py --rounds <held-out>`; side resolver: `scripts/train_side_resolver.py` |
| **Check the model still gives the known answer** | `make accept` (1 min) |
| **Evaluate / ablate branches on a labelled video** | `scripts/evaluate_models.py --config configs/evaluation.yaml --video <mp4> --reference <json> --ablation --out runs/evaluation.json` |
| **Build the game layer** | `docs/GAMIFICATION_HANDOFF.md`, `docs/API.md` (REST + WebSocket contracts) |
| **See what's done and what's left** | `docs/TEAM_HANDOFF.md` |

Every command below is real (`.venv/bin/python -m convergent.cli --help`):

| Task | Command |
|---|---|
| Install | `SETUP_MAC.command` (macOS) · `make install` (Linux) · `make install-legacy` (adds TensorFlow for the S-Kia legacy checkpoint) · `scripts/pi/install_pi.sh` (Raspberry Pi) |
| Start everything for the Pi | `bash START_LAPTOP.command` (= backend + `convergent network --backend http --save-results`) |
| Backend only | `.venv/bin/python -m convergent.cli backend` (SQLite) · `make db-up` then `CONVERGENT_DATABASE_URL=postgresql+psycopg://convergent:convergent@localhost:5432/convergent` |
| Prerecorded-video inference | `.venv/bin/python -m convergent.cli replay --video <mp4> --save-results [--backend http]` |
| Local webcam inference | `.venv/bin/python -m convergent.cli camera --show` |
| Pipeline on the Pi stream | `.venv/bin/python -m convergent.cli network --port 8765 --save-results --backend http` |
| Simulated Pi agent | `.venv/bin/python -m convergent.cli pi-emulator --url ws://127.0.0.1:8765 --video data/samples/handwashing_missing_step.mp4` |
| Real Pi agent (on the Pi) | `python -m convergent.pi_agent --config ~/pi_agent.yaml` (installed as a systemd service by `install_pi.sh`) |
| Projection calibration | `.venv/bin/python -m convergent.cli calibrate synthetic` · `… calibrate pattern --kind chessboard` · `… calibrate from-images --images cam1.jpg …` · `… calibrate from-pairs --pairs pairs.json --image-size 640 480` |
| Model evaluation (with ablation) | `.venv/bin/python scripts/evaluate_models.py --config configs/evaluation.yaml --video <mp4> --reference <json> --ablation --out runs/evaluation.json` |
| Train the recognition model the pipeline uses (`temporal_v2`) | `scripts/extract_landmarks_v2.py` → `scripts/train_temporal_v2.py --install` → `scripts/benchmark_recognition.py` (see `docs/MODEL_INTEGRATION.md`, results in `docs/TEST_RESULTS.md` §7) |
| Train the technique model / side resolver | `scripts/train_temporal_v2.py` (see `CLAUDE.md` commands) · `scripts/train_side_resolver.py` · legacy v1 LSTM: `scripts/sweep_lstm.py` |
| Train YOLO (optional branch, GPU recommended) | `.venv/bin/python scripts/train_yolo.py --dataset <HandWashDataset_yoloFormat> --epochs 100 --out runs/yolo_handwash` |
| Artifact status | `.venv/bin/python -m convergent.cli models` |
| All tests / lint | `make test` · `make lint` |

## What is in the box (status at a glance)

**Model v1.0 is frozen (2026-11-14)** – `docs/MODEL_CARD.md` is the one-page summary.

* ✅ `temporal_v2` (2.2 MB TCN, hand-relative features, 7 techniques + "not washing"): 79 % window
  accuracy on never-seen METC people, **70 % of performed seconds credited to the right step
  through the full pipeline** (previous models: 7 %), 24 label changes/min instead of 248.
* ✅ Side resolver (108 KB MLP): which hand is receiving a one-sided technique, **96.5 %** on
  never-seen Kaggle sessions. Left/right label semantics verified on the footage. Region coverage
  on the sample clip 0.40 → 0.60.
* ✅ Wash score: per-step timers that start ~1 s after a step begins, 0–100 points, 0–5 stars,
  `finished` milestone; `live` WebSocket feed at 5 Hz for the game layer (`docs/GAMIFICATION_HANDOFF.md`).
* ✅ Acceptance test (`make accept`): the full sample clip must give 6 events in WHO order, thumb
  missing, correct sides, ≥ 3 stars. 172 tests in total, pass on Linux and macOS (M3, M5 Pro).
* ✅ Laptop pipeline, backend (REST + WebSocket), Pi agent + emulator, calibration tools, one-shot
  setup scripts for Mac and Pi, recording/benchmark/training scripts.
* 🔧 Pi Zero 2 W, Arducam B0176 and RIF6 specifics are implemented against the documented
  interfaces but **unverified on hardware** – `docs/HARDWARE_DAY_RUNBOOK.md`.
* 🟡 Accuracy on **our** camera and on children is unmeasured (all training data is adults at
  overhead sink cameras; 2 own webcam rounds moved held-out accuracy 24 % → 59 %). Recording
  more people on the real mount is the next model task (`docs/RECORDING_GUIDE.md`).
* 🟡 Older branches (HandHygiene RF, v1 LSTM) still load and are logged with fusion weight 0;
  YOLO has no weights (optional).

Full detail: `IMPLEMENTATION_STATUS.md`.

## Repository layout

```
SETUP_MAC.command        one-shot laptop setup (macOS)      START_LAPTOP.command   hardware-day start (laptop)
scripts/pi/install_pi.sh one-shot Raspberry Pi setup
src/convergent/
  common/        types.py (shared contracts), config.py, timestamps.py, logging.py
  vision/        sources.py, preprocessing.py, hand_tracker.py, hand_identity.py, overlays.py
  detection/     labels.py, handhygiene_adapter.py, skia_adapter.py, yolo_adapter.py, sequence_buffer.py,
                 lstm_model.py, training.py (incl. augmentation), numpy_forest.py, fusion.py,
                 confidence_calibration.py, temporal.py, event_detector.py, evaluation.py, registry.py, base.py
  regions/       geometry.py, evidence.py, progress.py, segmentation.py, foam.py
  projection/    calibration.py, homography.py, mapping.py, smoothing.py, diagnostics.py
  backend/       app.py, database.py, models.py, schemas.py, auth.py, ws.py, client.py, routes/, services/, migrations/
  communication/ protocol.py (wire format, stdlib only), websocket.py (device gateway), buffering.py
  pi_agent/      camera.py, transport.py, renderer.py, diagnostics.py, agent.py, __main__.py
  pipeline.py    orchestration · cli.py  commands
scripts/         extract_landmark_sequences.py, train_lstm.py, sweep_lstm.py, train_yolo.py, train_handhygiene.py,
                 convert_handhygiene_rf.py, evaluate_models.py, calibrate_projector.py, replay_video.py, fetch_models.py, fetch_yolov5.sh
configs/         development.yaml, evaluation.yaml, models.yaml, labels.yaml, projector.yaml, pi_agent.yaml
models/          temporal_v2/current + side_resolver/current (committed, the v1.0 stack), handhygiene/, skia_temporal/current (legacy v1), yolo/
data/            samples/ (sample video), fixtures/ (reference labels), HandWashDataset/ + landmark_sequences/ (not committed; see docs/MODEL_INTEGRATION.md)
tests/           unit/ integration/ regression/
docs/            MODEL_CARD.md, TEAM_HANDOFF.md, HARDWARE_DAY_RUNBOOK.md, RECORDING_GUIDE.md, HARDWARE_ARRIVAL_CHECKLIST.md, PI_SETUP.md, API.md, MODEL_INTEGRATION.md,
                 CALIBRATION.md, TEST_RESULTS.md, GAMIFICATION_HANDOFF.md
```

See `ARCHITECTURE.md` for the data flow and contracts, `IMPLEMENTATION_STATUS.md` for what is
verified vs. awaiting hardware, `THIRD_PARTY.md` for provenance and licenses.

## Honest scope notes

* The camera sees movements, not germs: outputs are `gesture_detected`, `gesture_validated`,
  `region_evidence`, `region_unknown` and an explicitly defined `coverage_estimate` – never a
  cleanliness claim.
* The temporal model's held-out numbers are on Kaggle *sessions* it never saw, filmed from an
  overhead sink camera. Accuracy on our faucet camera and on children's hands is unmeasured
  until we record our own clips (`docs/HARDWARE_DAY_RUNBOOK.md` §4).
* Nothing here is a production child-data platform; `docs/API.md` lists the controls required
  before real deployment. No video of children is stored; `.env` holds the only secrets.
