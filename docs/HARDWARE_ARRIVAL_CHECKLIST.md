# Hardware arrival checklist (Pi 3 A+, Arducam B0176, RIF6 Cube)

Tick each item and record results in `docs/TEST_RESULTS.md` (section "Hardware").

## A. Bench setup (laptop only, before touching the Pi)
- [ ] `make install && make models && make test` pass on the laptop (macOS Apple Silicon: confirm `uv sync` resolves the arm64 wheels for mediapipe 0.10.21 / torch; report versions).
- [ ] `.env` has `CONVERGENT_API_TOKEN` and `CONVERGENT_DEVICE_TOKEN`; `convergent backend` answers `GET /health`.
- [ ] `convergent network` + `convergent pi-emulator` round trip works on the laptop (renders appear in `runs/pi_emulator_renders`).

## B. Raspberry Pi 3 A+
- [ ] Flash Raspberry Pi OS Lite 64-bit (docs/PI_SETUP.md §1–3); SSH works over Wi-Fi; note the Pi's IP.
- [ ] Power from the onn. 10,000 mAh bank: `vcgencmd get_throttled` stays `0x0` under load (camera + Wi-Fi). If under-voltage flags appear, change cable/bank before blaming software.
- [ ] `make install-pi`; `python -m convergent.pi_agent --camera emulated --renderer image --url ws://<laptop>:8765 --max-frames 100` → frames arrive at the laptop (`frames_received` in the `network` summary).
- [ ] Measure idle memory (`free -m`) and agent RSS with the real camera; target < 150 MB RSS.

## C. Arducam B0176
- [ ] Ribbon seated; `rpicam-hello --list-cameras` shows `ov5647`.
- [ ] Capture 640×480 at 15 FPS for 60 s without dropped frames (`rpicam-vid --framerate 15 --width 640 --height 480 -t 60000 -o /dev/null`).
- [ ] Focus: confirm whether the VCM overlay from Arducam's guide enables `AfMode`/`LensPosition`; test `Picamera2Camera.set_focus(None)` and a manual value; record the lens position that focuses the basin plane (~30–50 cm).
- [ ] Field of view: with the camera mounted at the faucet, both hands fit in frame while washing (54°×44° FOV → ≈ 50 cm × 40 cm at 50 cm distance). Adjust mount angle, not hardware.
- [ ] Handedness convention: hold up only the right hand → `hands.right` populated in `runs/<session>/frames.jsonl`. If not, set `tracker.swap_handedness: false` and document.
- [ ] Record 3 washes (adult volunteers, no children, no faces) as MP4 on the laptop (`convergent network --save-results` + optional recording) for regression fixtures.

## D. RIF6 Cube projector
- [ ] HDMI cable (A→mini-C) → Pi detects the display: `cat /sys/class/graphics/fb0/virtual_size`; record the negotiated mode (expected 854×480 or 1280×720).
- [ ] `FramebufferRenderer` test: send a chessboard pattern (`convergent calibrate pattern`, then a `pattern` RenderCommand) and confirm the projector shows it letterboxed correctly.
- [ ] Brightness/keystone: find the mount distance/angle where the 854×480 canvas covers the washing area; note keystone (the homography absorbs it for the calibration plane).

## E. Calibration (docs/CALIBRATION.md)
- [ ] Optional intrinsics from a printed chessboard (≥ 10 poses).
- [ ] Project ArUco grid → capture → `convergent calibrate from-images` → RMSE ≤ 4 px, inliers ≥ 50 %; profile stored in the backend and active.
- [ ] Visual check: crosshairs on fingertips while hands rest on the basin plane; note parallax when hands are raised.
- [ ] Record profile id/version in TEST_RESULTS.md; re-run after re-mounting.

## F. End-to-end
- [ ] `convergent network --backend http --save-results` with real Pi stream: events persist (`GET /api/v1/sessions/{id}/events`), region evidence present, render acks increase, latency p90 recorded.
- [ ] Reconnect test: toggle Pi Wi-Fi off/on → agent reconnects, pipeline continues (new frames), no crash.
- [ ] 15-minute soak: no memory growth on the Pi (`status.mem_available_mb`) or the laptop (summary `resources.rss_mb_max`).

## G. Data for the models (unblocks the 🟡 items)
- [ ] Download the Kaggle hand-wash dataset → `scripts/extract_landmark_sequences.py` → `scripts/train_lstm.py` (temporal artifact with real metrics).
- [ ] Train YOLOv5 (`scripts/train_yolo.py`, GPU recommended) and register the checkpoint hash.
- [ ] Resolve side semantics in `configs/labels.yaml`.
- [ ] Fit calibrators and fusion weights on held-out recordings; run `scripts/evaluate_models.py --ablation`.
