# Convergent Handwashing

A faucet-mounted handwashing trainer for children ages 4 to 10, built by the Texas Convergent tech team. A camera watches the child's hands. A laptop recognizes the washing motions and scores them. A projector shows germs that disappear as the child washes.

This repo holds the recognition pipeline and the Scrubble app (`web/`, served by the backend): a kid view with the game and a grown-up view with the numbers. Start a demo of the app with `bash START_SCRUBBLE_DEMO.command`. App docs: `docs/SCRUBBLE_APP.md`.

Dated history, measurements, decisions and the next-work list are in `NOTES.md`. Read it before planning work. Add a dated entry there when something is built, measured or decided, and compress it every few weeks (rules at its top). Keep this file to stable, everyday facts.

## Environment: Bryan's Windows laptop (this branch)

- Windows 11, NVIDIA RTX 3050 Ti Laptop GPU (4 GB), driver 616.56 (CUDA 13.4 capable, no update needed).
- Shell: PowerShell 5.1 (no `&&`, use `;`). Python: `.venv\Scripts\python` (3.11). Other Pythons on the machine (3.12 default, 3.9) are not used.
- `.venv` was built with `uv sync --extra backend --extra yolo --extra dev`, then PyTorch swapped to the CUDA build. A plain `uv sync` puts CPU PyTorch back. Restore the GPU build with:
  ```powershell
  uv pip install --python .venv\Scripts\python.exe --reinstall --no-deps torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu126
  ```
- GPU use: training only (`--device cuda`). Live recognition and MediaPipe run on the CPU by design (small model, MediaPipe has no GPU on Windows).
- Webcam: built-in camera is `--device 0`. Bryan runs camera commands himself.
- Tests: `.venv\Scripts\python -m pytest -q` (224 pass on 2026-11-17, about 3 min). Fast: `.venv\Scripts\python -m pytest tests/unit -m "not mediapipe"`. Lint: `.venv\Scripts\python -m ruff check src tests`.
- Sample clip: `data/samples/handwashing_missing_step.mp4`, git-ignored, from `dpt-xyz/hand-wash-compliance-yolo` (`TestingData/missingStep_test1.mp4`). Don't swap in a different clip, the regression fingerprint depends on it.

## Environment: Andrew's Mac

- Repo `~/convergent-handwashing`, Python `.venv/bin/python` (not Conda base). GPU flag is `--device mps`.
- Camera index 0 is usually the iPhone (Continuity Camera), the MacBook webcam is usually `--device 1`.
- The Claude desktop terminal panel has no camera permission. Give Andrew the command to run in his own Terminal.

## Run commands (Windows paths)

```powershell
# Live webcam: diagnostic window + germ graphics. Esc stops and prints the score, P toggles graphics, F fullscreen.
.venv\Scripts\python -m convergent.cli camera --device 0 --show --projection
# Clean game view instead of the diagnostic view: add --game. Save the run: add --save-results.

# Older "dinos" germ scene instead of the default "coverage" scene (temporary config copy)
(Get-Content configs\development.yaml) -replace 'mode: coverage','mode: dinos' | Set-Content $env:TEMP\dinos.yaml; .venv\Scripts\python -m convergent.cli --config $env:TEMP\dinos.yaml camera --device 0 --show --projection

# Sample clip, no server
.venv\Scripts\python -m convergent.cli replay --video data\samples\handwashing_missing_step.mp4 --save-results --backend inprocess

# Backend API (docs at http://127.0.0.1:8000/docs). Then use --backend http on camera runs.
.venv\Scripts\python -m convergent.cli backend
```

`--save-results` writes `runs/<session_id>/` (`summary.json`, `events.json`, `frames.jsonl`, `landmarks.npz`). The summary, events and landmarks are only written when the run ends with Esc or Ctrl+C, not when the window is closed.

Training and evaluation commands are in `docs/RECORDING_GUIDE.md`, `scripts/train_temporal_v2.py`, `scripts/benchmark_recognition.py` and `scripts/eval_own_rounds.py`. Long training runs started in the background of a Claude session stall while Claude is not in a tool call. Run them in the foreground or wait with an `until` loop.

## Pipeline (per frame, `src/convergent/pipeline.py`)

1. MediaPipe tracks up to 2 hands (21 points each). Hands under 10% of the picture are dropped. A light fix cleans dark or tinted pictures.
2. `temporal_v2` (`detection/pair_adapter.py`) names the technique. It is the only model that decides. The older RandomForest and v1 LSTM still run and are logged with weight 0. YOLO has no weights.
3. Fusion: below 0.45 confidence, or "none", the frame is unknown.
4. `detection/temporal.py` and `event_detector.py` turn frames into events: start at 0.6, continue at 0.4, at least 0.5 s to validate, gaps up to 0.5 s, fragments under 0.75 s apart merged. Events arrive about 1.25 s after the motion stops.
5. Region evidence (`regions/`) tracks 10 cells (5 regions x 2 hands). The side comes from `detection/side_resolver.py`.
6. Wash score (`scoring/wash_score.py`) runs every frame.
7. Projection graphics, then sinks (results files, backend, Pi gateway).

### Recognition model `temporal_v2`

- Classes: the 7 techniques plus `none`. No left/right.
- Input: 183 features per frame (`detection/pair_features.py`), last 48 frames (3.2 s) resampled onto a 15 FPS grid. Hands slotted by position continuity, not MediaPipe's left/right.
- Temporal convolution network, `models/temporal_v2/current` (2.2 MB, committed).
- Training data: METC (Zenodo 5808789), Kaggle `realtimear/hand-wash-dataset`, Andrew's own rounds `data/own/down1..3`. All in `data/`, git-ignored.
- Accuracy: 75% of frames on held-out public videos, 59% on Andrew's webcam. It memorizes the own rounds it trained on. More rounds from more people is the main lever.

### Technique names

`palm_to_palm`, `back_of_hand`, `interlaced_fingers`, `backs_of_fingers`, `thumb_rubbing`, `fingertip_rubbing` (WHO core 6) and `wrist_rubbing` (WHO step 7, an extension). Side = the receiving (static) hand.

## Wash score

`scoring/wash_score.py`, configured under `scoring:` in `configs/development.yaml`. Andrew's rules:

- Step time: validated seconds per technique, summed across tries, either hand. Live time never decreases. A validating step also gets up to 1.5 s of unrecognized time just before it (model lag).
- Step done: 3.0 s. Finished: 5 of 7 steps done and 20 s total. Finishing is a milestone, points and stars keep accruing.
- Any order gets credit. `next_step` suggests WHO order.
- Points (0 to 100): up to 10 per step plus up to 30 for total time (capped at 20 s).
- Stars: 0 nothing, 1 some washing, 2 three steps or 10 s, 3 finished, 4 finished with 6 steps, 5 finished with all 7.
- Shows up in `FrameResult.score`, `summary.json`, backend `stats.wash_score`, the CLI summary and the live window. Contract in `docs/GAMIFICATION_HANDOFF.md`.
- Thresholds are first guesses. Tune them from real washes.

## Projection and game

- Two germ scenes, `projector.graphics.mode`: `coverage` (default, 20 germs per hand side, any order) and `dinos` (the first scene, one dino per hand region).
- `green_only` (off) draws hand graphics in projector green and removes it from the tracker's picture. `lead_ms` stays 0 until latency is measured.
- `camera --auto-wash` splits a run into washes (`washes.jsonl`).
- Details in `docs/PROJECTION_GRAPHICS.md` and `NOTES.md`.

## Known limits (state these honestly)

- The score measures recognized motion time. It is not proof of clean hands, soap contact or germ removal. The SOAP checkmark is a brightness heuristic for the UI only.
- Accuracy has been measured on public adult videos and Andrew's webcam only. Not on the faucet camera or children's hands. Passing tests is software verification, not real-world accuracy.
- Side resolver accuracy on our camera is unmeasured. `side_resolver.mirrored` and `flip_facing` must match the mount.
- No child identity in the schema. Pairing a wash with a child is the app's job.

## Hardware (planned, not arrived)

- Raspberry Pi 3 Model A+ (backup: Pi 3 Model B), Arducam B0176 5 MP camera (54 x 44 degree view), RIF6 Cube projector (854x480, 50 lumens, throw ratio 1.99, must sit about 60 cm above the hands), power bank, mini-HDMI cable, microSD.
- Heavy recognition stays on the laptop. The Pi sends camera JPEGs over WebSocket port 8765 and draws render commands to HDMI.
- Hardware day: lock the Pi camera's exposure and white balance (`pi_agent/camera.py` leaves them on auto), measure camera-to-projector lag (estimate 150 to 250 ms), calibrate at hand height.

## How we work

- Bryan is new to this repo and not very technical. Andrew is the team's senior engineer. Plan together before writing code.
- When something is unclear, ask Bryan. Don't guess.
- Andrew's setup loads the skills `karpathy-guidelines`, `superpowers` and `i-have-adhd`. They are not installed on Bryan's machine, so follow the style rules here instead.
- Code: write the minimum lines needed. No extra features or abstractions.
- Branch before committing. Don't commit to `main`.

### Subagents

Bryan prefers more subagent use than usual. Delegate research, codebase exploration across several files, and ideation to subagents, and run independent ones in parallel. Don't spawn one when the extra tokens don't save real time or context: a lookup of a known file, a few tool calls, or a file already in context.

Pick the model per agent by how much judgment the task needs:
- `haiku`: mechanical work, such as finding files or code, listing things, summarizing one known document.
- `sonnet`: the default for web research, comparing products, ideation, codebase exploration that needs judgment.
- `opus`: only when a wrong answer is costly or the reasoning is hard: legal or regulatory reading, architecture decisions, tricky debugging.

Research agents return their reports, and the main session saves them to `RESEARCH.md` (rules at its top) with sources, then puts the short takeaways in `NOTES.md`. Parallel agents don't write to the same file directly.

### Teaching Claude Code

Bryan is new to Claude Code and wants to learn from using it. When he uses it badly or inefficiently (too many or unneeded subagents, vague prompts, missing context, a command or feature that would do the job better), say so briefly with the better way. One or two lines, at the end of the answer, not a lecture.

### Working style for Bryan

- Plain language. Explain technical terms briefly when they first appear.
- Lead with the action or diagnosis. Medium-length answers, one milestone at a time.
- Give PowerShell commands Bryan can paste.
- Keep these separate: confirmed behavior, results Bryan reported, and proposed work.
- Avoid em dashes, semicolons, asterisk emphasis and unnecessary adjectives.
- Never print secrets from `.env`.
