# Hardware-day runbook (Pi 3 A+ · Arducam B0176 · RIF6 Cube)

Goal: when the parts arrive, go from boxes to **live hand-tracking on the projector feed in one
sitting**, with every software step already done. Everything below is a real command in this
repo. Do the "before the hardware arrives" part now; the day-of part is three commands.

## 0. Before the hardware arrives (laptop, once, ~15 min unattended)

1. Clone the repo and run the one-shot setup (installs `uv`, Python 3.11, all packages, writes
   `.env` with random tokens, fetches model artifacts, runs the 119-test suite and a full sample
   replay). Double-click `SETUP_MAC.command` in Finder, or:
   ```bash
   bash ~/Downloads/convergent-handwashing/SETUP_MAC.command
   ```
   Read the last lines of `setup_log.txt`: it must end with `Setup finished successfully`.
2. Confirm the trained models are picked up:
   ```bash
   .venv/bin/python -m convergent.cli models
   ```
   Expected: `handhygiene … loaded`, `skia_temporal … loaded (version 0.1.0+…)`, `yolo … MODEL_UNAVAILABLE`
   (YOLO is optional; the system runs on the two landmark branches).
3. Dry-run the whole Pi path **without a Pi** (two terminals):
   ```bash
   bash START_LAPTOP.command                                  # terminal 1: backend + gateway + pipeline
   .venv/bin/python -m convergent.cli pi-emulator --url ws://127.0.0.1:8765 --video data/samples/handwashing_missing_step.mp4 --max-frames 300   # terminal 2
   ```
   Terminal 1 prints frames received, fused labels and validated events; `runs/<session>/` and the
   SQLite DB fill up. Ctrl-C in terminal 1 stops everything.
4. Flash the microSD now (Raspberry Pi Imager → Raspberry Pi OS Lite 64-bit, hostname
   `convergent-pi`, user `pi`, your Wi-Fi, SSH enabled). You do not need the Pi for this.
5. Print one chessboard or ArUco pattern for calibration (`docs/CALIBRATION.md`), or plan to
   project the pattern from the Pi.

## 1. Day of – laptop (1 command)

```bash
bash START_LAPTOP.command
```
It prints the laptop's LAN IP and starts: backend (`http://127.0.0.1:8000/docs`), device gateway
(`ws://<LAN_IP>:8765`), CV pipeline waiting for the Pi (15 min frame timeout; tune with
`CONVERGENT_FRAME_TIMEOUT=3600 bash START_LAPTOP.command`). Allow TCP 8765 through the macOS
firewall if prompted. Laptop and Pi must be on the same Wi-Fi network.

## 2. Day of – Raspberry Pi (2 commands)

Assemble first: ribbon into the CSI slot (contacts toward the HDMI side), HDMI → RIF6 mini-HDMI
**before** power, power from the onn. bank with a short, thick cable. Boot, then from the laptop:

```bash
ssh pi@convergent-pi.local
git clone <repo-url> ~/convergent-handwashing && cd ~/convergent-handwashing      # or scp the folder
bash scripts/pi/install_pi.sh <LAPTOP_IP> <CONVERGENT_DEVICE_TOKEN from the laptop .env>
sudo reboot        # only the first time (camera overlay)
```
`install_pi.sh` installs the camera stack from apt, the agent venv (no torch/TF/OpenCV on the Pi),
writes `~/pi_agent.yaml` + `/etc/convergent.env`, enables `dtoverlay=ov5647` and a systemd service
that starts the agent at every boot. After the reboot the agent connects on its own; watch it with
`journalctl -u convergent-agent -f`.

What "working" looks like on the laptop terminal within seconds: `device connected from (<pi ip>, …)`,
then every 2 s a line like `live: frames=240 fps=14.8 hands=2 fused=palm_to_palm (0.81) events=1 tracker=24ms`
while hands are washing (`fused=no_input` when no hands are in view, `unknown` when the branches
disagree). At the end (Ctrl-C) a session summary lists validated events, backend counts and the
device stats (`frames_received`, `frames_dropped`, render acks).

## 3. First-hour checks (write results into docs/TEST_RESULTS.md §Hardware)

| # | Check | Command / where | Pass criterion |
|---|---|---|---|
| 1 | Camera detected | Pi: `rpicam-hello --list-cameras` | lists `ov5647` |
| 2 | Power | Pi: `vcgencmd get_throttled` (also in status messages) | `0x0` under load; otherwise change cable/bank first |
| 3 | Frame rate / drops | laptop summary `frames_received`, Pi status `frames_dropped` | ≈15 FPS, drops < 5 % on 5 GHz |
| 4 | Handedness convention | hold up only the **right** hand → `runs/<session>/frames.jsonl` shows `hands.right` | if `left` instead: set `tracker.swap_handedness: false` in `configs/development.yaml` and note it in `configs/labels.yaml` |
| 5 | Field of view | both hands fit while washing with the camera clipped to the faucet | adjust mount angle, not hardware |
| 6 | Focus | `Picamera2Camera.set_focus(None)` vs manual `LensPosition` (docs/PI_SETUP.md §4) | sharp landmarks at 30–50 cm; record the lens position |
| 7 | Projector mode | Pi: `cat /sys/class/graphics/fb0/virtual_size` | 854×480 or 1280×720 (renderer letterboxes either) |
| 8 | Calibration | `docs/CALIBRATION.md`: project pattern → capture → `convergent calibrate from-images` | RMSE ≤ 4 px, inliers ≥ 50 %; crosshairs land on fingertips |
| 9 | End-to-end persistence | `curl -s http://127.0.0.1:8000/api/v1/sessions \| head` then `/api/v1/sessions/{id}/events` | events + region evidence rows present |
| 10 | Reconnect | toggle Pi Wi-Fi off/on | agent reconnects, pipeline continues, no crash |
| 11 | 15-min soak | status `mem_available_mb` (Pi), summary `resources.rss_mb_max` (laptop) | flat memory |

## 4. Record real data the same day (unblocks model validation)

The models were trained on the public Kaggle videos (overhead sink camera, adults). Our faucet
camera will look different, so the most valuable thing to do with the first working setup is to
**record a few labelled washes** (adult volunteers, no children, no faces in frame):

```bash
# laptop, while START_LAPTOP.command is running in another terminal: results already go to runs/<session>/
# afterwards, label the step boundaries (seconds) in a JSON next to the recording like
# data/fixtures/handwashing_missing_step.reference.json, then:
.venv/bin/python scripts/evaluate_models.py --config configs/evaluation.yaml --video <our.mp4> --reference <our.json> --ablation --out runs/eval_ours.json
```
If accuracy is poor on our camera, put the clips in a `data/OurDataset/Step_*/` folder (same layout
as the Kaggle set), re-run `scripts/extract_landmark_sequences.py` on both datasets and
`scripts/sweep_lstm.py` – the artifact is versioned and installs itself.

## 5. If something does not work

* Agent "keeps reconnecting" → laptop not running `START_LAPTOP.command`, wrong `laptop_url`
  in `~/pi_agent.yaml`, firewall, or token mismatch (`unauthorized` stops the agent on purpose).
* `camera_ok: false` → `docs/PI_SETUP.md` §4 and §8.
* No hands tracked but frames arrive → lighting/focus; look at JPEGs the laptop saves in `runs/<session>/`.
* Anything else: `docs/PI_SETUP.md` §8 troubleshooting table, `logs/` on the laptop, `journalctl` on the Pi.
