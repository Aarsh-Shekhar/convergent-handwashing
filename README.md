# Convergent Interactive Handwashing System – technical foundation

Computer-vision foundation for a faucet-mounted, projector-guided handwashing trainer for
children (Texas Convergent). One executable pipeline: camera frames → shared MediaPipe hand
tracking → three recognition branches (HandHygiene spatial classifier, S-Kia temporal
classifier, YOLOv5 image detector) → timestamp-aware fusion → temporal validation → anatomical
region evidence → projector coordinates → backend persistence → (future) game engine.

```
Arducam B0176 ──CSI──▶ Raspberry Pi 3 A+ ──Wi-Fi (JPEG/WebSocket)──▶ Laptop (CV, fusion, backend)
                                   ▲                                      │
                           HDMI ◀──┘ ◀──── render/debug commands ─────────┘
                           RIF6 Cube (854×480 logical canvas)
```

No game engine, scoring or final animations are included (by design); the typed
`ProgressState`, `GestureEvent`, `RegionEvidence` and `ProjectionTarget` contracts plus the
backend API are what the gamification layer will consume (see `docs/GAMIFICATION_HANDOFF.md`).

## Quick start (laptop, macOS Apple Silicon or Linux, Python 3.11 via uv)

```bash
make install                 # uv sync from uv.lock (+ copies .env.example to .env)
#   edit .env: CONVERGENT_API_TOKEN / CONVERGENT_DEVICE_TOKEN (any long random strings)
make models                  # fetch upstream artifacts (hash-checked) + MediaPipe task bundle
make yolov5                  # pinned YOLOv5 v7.0 checkout (only needed for the YOLO branch)
make samples UPSTREAM=<dir with the three upstream clones>   # sample handwashing video
make test                    # whole test-suite (117 tests)

# run the integrated pipeline on a recording and persist to an in-process backend:
.venv/bin/python -m convergent.cli replay --video data/samples/handwashing_missing_step.mp4 --save-results --backend inprocess
```

Every command below is real (`convergent --help`):

| Task | Command |
|---|---|
| Install everything | `make install` (laptop) · `make install-legacy` (adds TensorFlow for the S-Kia legacy checkpoint) · `make install-pi` (Raspberry Pi) |
| Start the backend | `.venv/bin/python -m convergent.cli backend` (SQLite) · `make db-up` then set `CONVERGENT_DATABASE_URL=postgresql+psycopg://convergent:convergent@localhost:5432/convergent` |
| Prerecorded-video inference | `.venv/bin/python -m convergent.cli replay --video <mp4> --save-results [--backend http]` |
| Local camera inference | `.venv/bin/python -m convergent.cli camera --show` |
| Pipeline on the Pi stream | `.venv/bin/python -m convergent.cli network --port 8765 --save-results --backend http` |
| Simulated Pi agent | `.venv/bin/python -m convergent.cli pi-emulator --url ws://127.0.0.1:8765 --video data/samples/handwashing_missing_step.mp4` |
| Real Pi agent (on the Pi) | `python -m convergent.pi_agent --config configs/pi_agent.yaml` |
| Projection calibration | `.venv/bin/python -m convergent.cli calibrate synthetic` · `… calibrate pattern --kind chessboard` · `… calibrate from-images --images cam1.jpg …` · `… calibrate from-pairs --pairs pairs.json --image-size 640 480` |
| Model evaluation (with ablation) | `.venv/bin/python scripts/evaluate_models.py --config configs/evaluation.yaml --video <mp4> --reference <json> --ablation --out runs/evaluation.json` |
| Train corrected LSTM | `.venv/bin/python scripts/extract_landmark_sequences.py --root data/HandWashDataset --out data/landmark_sequences && .venv/bin/python scripts/train_lstm.py --data data/landmark_sequences --out models/skia_temporal/v0.1.0` |
| Train YOLO | `.venv/bin/python scripts/train_yolo.py --dataset <HandWashDataset_yoloFormat> --epochs 100 --out runs/yolo_handwash` |
| Artifact status | `.venv/bin/python -m convergent.cli models` |
| All tests / lint | `make test` · `make lint` |

## Repository layout

```
src/convergent/
  common/        types.py (shared contracts), config.py, timestamps.py, logging.py
  vision/        sources.py, preprocessing.py, hand_tracker.py, hand_identity.py, overlays.py
  detection/     labels.py, handhygiene_adapter.py, skia_adapter.py, yolo_adapter.py, sequence_buffer.py,
                 lstm_model.py, training.py, numpy_forest.py, fusion.py, confidence_calibration.py,
                 temporal.py, event_detector.py, evaluation.py, registry.py, base.py
  regions/       geometry.py, evidence.py, progress.py, segmentation.py, foam.py
  projection/    calibration.py, homography.py, mapping.py, smoothing.py, diagnostics.py
  backend/       app.py, database.py, models.py, schemas.py, auth.py, ws.py, client.py, routes/, services/, migrations/
  communication/ protocol.py (wire format, stdlib only), websocket.py (device gateway), buffering.py
  pi_agent/      camera.py, transport.py, renderer.py, diagnostics.py, agent.py, __main__.py
  pipeline.py    orchestration · cli.py  commands
scripts/         train_lstm.py, train_yolo.py, train_handhygiene.py, convert_handhygiene_rf.py, evaluate_models.py,
                 extract_landmark_sequences.py, calibrate_projector.py, replay_video.py, fetch_models.py, fetch_yolov5.sh
configs/         development.yaml, evaluation.yaml, models.yaml, labels.yaml, projector.yaml, pi_agent.yaml
tests/           unit/ integration/ regression/
docs/            PI_SETUP.md, API.md, MODEL_INTEGRATION.md, CALIBRATION.md, TEST_RESULTS.md,
                 GAMIFICATION_HANDOFF.md, HARDWARE_ARRIVAL_CHECKLIST.md
```

See `ARCHITECTURE.md` for the data flow and contracts, `IMPLEMENTATION_STATUS.md` for what is
verified vs. awaiting artifacts/hardware, `THIRD_PARTY.md` for provenance and licenses.

## Honest scope notes

* The camera sees movements, not germs: outputs are `gesture_detected`, `gesture_validated`,
  `region_evidence`, `region_unknown` and an explicitly defined `coverage_estimate` – never a
  cleanliness claim.
* Upstream model accuracy on our setup is unverified (see `docs/TEST_RESULTS.md`); fusion
  weights are placeholders until validation data exists.
* Nothing here is a production child-data platform; `docs/API.md` lists the controls required
  before real deployment.
