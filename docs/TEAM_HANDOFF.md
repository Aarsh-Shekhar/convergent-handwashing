# Team handoff – what this repo does, and what is left

Status date: 2026-11-14 (model v1.0 frozen; `docs/MODEL_CARD.md`). Repo: `github.com/Aarsh-Shekhar/convergent-handwashing` (private).
Setup for a new laptop: `bash SETUP_MAC.command` (README has the full install/run block).

## 1. What is built and working

Everything below is real code with tests (172 passing on Linux and on M3 / M5 Pro MacBooks).

| # | Piece | What it does | Where |
|---|---|---|---|
| 1 | Video ingestion | MP4 replay, webcam, Pi Wi-Fi stream, synthetic frames; frame timestamps from the source; bounded queues with drop counters | `vision/sources.py` |
| 2 | Hand tracking | One shared MediaPipe tracker for the whole system, two hands, stable left/right identity across frames, crossings and brief dropouts | `vision/hand_tracker.py`, `hand_identity.py` |
| 3 | Recognition branch A | HandHygiene RandomForest (upstream repo), converted to a dependency-free artifact, bit-exact with the original | `detection/handhygiene_adapter.py` |
| 4 | Recognition branch B | **Our temporal LSTM**, trained here on the 300-video Kaggle hand-wash set: 90.5 % on held-out sessions, 77.5 % on unseen sink setups | `detection/lstm_model.py`, `training.py`, `models/skia_temporal/current` |
| 5 | Recognition branch C | YOLOv5 adapter – code complete, no usable weights exist (optional branch, reports `MODEL_UNAVAILABLE`) | `detection/yolo_adapter.py` |
| 6 | Fusion | Time-aligned, reliability-weighted combination of the branches; disagreements become `unknown` instead of a guess | `detection/fusion.py` |
| 7 | Temporal validation | Turns per-frame labels into `gesture_validated` events (min duration, hysteresis, gap tolerance); detects missing steps | `detection/temporal.py`, `event_detector.py` |
| 8 | Region evidence | Which regions of each hand received rubbing and for how long; `coverage_estimate` with an explicit definition (never a cleanliness claim) | `regions/` |
| 9 | Projector mapping | Camera→projector calibration (chessboard / ArUco / manual points), smoothing, render commands for an 854×480 canvas | `projection/`, `scripts/calibrate_projector.py` |
| 10 | Backend | FastAPI + SQLite (Postgres optional), migrations, token auth, REST + WebSocket; stores sessions, predictions, events, region evidence, calibrations, evaluations | `backend/`, `docs/API.md` |
| 11 | Raspberry Pi agent | Camera capture, JPEG streaming, auto-reconnect, health reporting, framebuffer renderer; emulator so everything can be tested without a Pi | `pi_agent/`, `communication/` |
| 12 | Pipeline + CLI | `replay`, `camera`, `network`, `backend`, `pi-emulator`, `calibrate`, `evaluate`, `models`, `test` | `pipeline.py`, `cli.py` |
| 13 | Training + evaluation tools | `record` command, landmark extraction, training / fine-tuning, pipeline benchmark on held-out people or rounds, side-resolver training, model acceptance test (`make accept`) | `scripts/`, `tests/acceptance/` |
| 14 | Ops | One-shot Mac setup, one-shot Pi setup, hardware-day start script, runbook, status docs | `SETUP_MAC.command`, `scripts/pi/install_pi.sh`, `START_LAPTOP.command`, `docs/HARDWARE_DAY_RUNBOOK.md` |

In one sentence: hands in front of the camera → validated WHO-technique events, per-region evidence
and projector coordinates, persisted through an API, in real time, with a Pi on the other end.

## 2. Software still to build (besides visual design)

Ordered roughly by how much it blocks a demo. "Owner" is blank on purpose – assign in the team.

| # | Item | What it is | Depends on | Size | Owner |
|---|---|---|---|---|---|
| S1 | **Game / coaching engine** | The layer that decides *what to tell the child next*: which step is due, when to prompt, when to celebrate, when to time out. Consumes `GestureEvent` + `ProgressState` over the WebSocket (`docs/GAMIFICATION_HANDOFF.md`). Deliberately not built in this repo | nothing – can start now against the emulator | large | |
| S2 | **Projected guidance graphics** | Real content for the projector canvas: step prompts, region highlights, progress, animations. Today only diagnostic overlays (crosshairs, calibration patterns) exist. Producer of `RenderCommand`s | S1 for logic; projector for tuning | large | |
| S3 | **Session lifecycle at a public sink** | Auto-start a session when hands appear, end it on idle, handle a second person walking up, reset state. Today a session = one pipeline run | nothing | medium | |
| S4 | **Laptop as an appliance** | Auto-start on boot (launchd), auto-restart, log rotation checked, no terminal needed. `START_LAPTOP.command` is the manual version | nothing | small | |
| S5 | **Calibration workflow** | Guided flow (project pattern → capture → fit → verify) instead of the CLI steps in `docs/CALIBRATION.md` | projector | medium | |
| S6 | **Teacher / admin view** | See sessions, missing-step stats, device health; export. Backend endpoints exist, no front-end | nothing | medium | |
| S7 | **Child-data controls** | Enforce the policy in `docs/API.md`: no raw video, retention limits, consent flag per session, delete endpoint, LAN-only binding review | before any real use | small–medium | |
| S8 | ~~Left/right semantics~~ | Done 2026-11-14 (verified on frames; side resolver ships) | – | – | done |
| S9 | **Record our own clips** | `convergent record` exists (`docs/RECORDING_GUIDE.md`); what is missing is the data: ≥ 5 people × 2 rounds on the planned camera mount, incl. idle / soap / rinse as `none` | a webcam clipped to a faucet now, the Pi later | small per person | |
| S10 | **Retrain on our camera** | `scripts/train_temporal_v2.py` on public + our clips, benchmark with a whole person held out; re-check the side resolver with `mirrored` set for the mount | S9 | small (compute) | |
| S11 | Children's hands | No training data for kids exists. Needs a consent process plus recordings | S9 + ethics | medium | |
| S12 | Soap/foam detection | Only an unvalidated brightness proxy exists; would need labelled data | optional | medium | |
| S13 | YOLO branch weights | Optional third opinion; needs a GPU for hours | optional | medium | |
| S14 | Real-camera regression tests | Replace the one sample-video fixture with clips from our rig | S9 | small | |

## 3. Hardware verification (software done, never run on the parts)

Pi Zero 2 W (or 3 A+) frame rate and memory, Arducam focus control, RIF6 HDMI mode, Wi-Fi drop behaviour,
projector calibration on the real basin, 15-minute soak. Exact checks and pass criteria:
`docs/HARDWARE_DAY_RUNBOOK.md` §3. Day-of bring-up is two commands (laptop + Pi).

## 4. Known limits to say out loud

* The model has only seen adults at an overhead sink camera; expect ~77 % until we add our own clips.
* MediaPipe sees one of the two overlapping hands most of the time; the model works with that.
* The system reports movements and evidence, never "clean hands".
* The wash score exists; the game logic, projected graphics and animations do not – by design, that is the next layer (`docs/GAMIFICATION_HANDOFF.md`).
