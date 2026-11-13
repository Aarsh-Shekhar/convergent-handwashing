# Convergent Handwashing

A faucet-mounted handwashing trainer for children ages 4 to 10, built by the Texas Convergent tech team. A camera watches the child's hands. A laptop recognizes the washing motions and scores them. A projector shows guidance and germs that disappear as the child washes.

This repo is the technical foundation. The child-facing game, the parent app and the XP/progression system are not built yet.

## Environment (Andrew's Mac)

- Repo: `~/convergent-handwashing`. Always use `.venv/bin/python`, not the Conda `(base)` Python.
- Fast tests: `.venv/bin/python -m pytest tests/unit -m "not mediapipe"`. Full suite: `.venv/bin/python -m pytest -q` (158 tests, all passing as of 2026-11-11).
- Lint: `.venv/bin/ruff check src tests`.
- Sample clip: `data/samples/handwashing_missing_step.mp4`. It is git-ignored and was downloaded from `dpt-xyz/hand-wash-compliance-yolo` (`TestingData/missingStep_test1.mp4`). Don't swap in a different clip, because the regression fingerprint depends on this one.
- Cameras: index 0 is usually the iPhone (Continuity Camera). The MacBook webcam is usually `--device 1`. Index order can change between machines and sessions.
- The webcam only works from Andrew's own Terminal app. The Claude desktop terminal panel has no camera permission ("not authorized to capture video"). Give Andrew the command to run himself.

### Run commands

```bash
# Terminal 1 (leave running): backend API, docs at http://127.0.0.1:8000/docs
.venv/bin/python -m convergent.cli backend

# Terminal 2: live webcam with diagnostic window + score panel. Esc stops and prints the score.
.venv/bin/python -m convergent.cli camera --device 1 --show --save-results --backend http

# Replay the sample clip without a server
.venv/bin/python -m convergent.cli replay --video data/samples/handwashing_missing_step.mp4 --save-results --backend inprocess
```

Every run with `--save-results` writes `runs/<session_id>/summary.json`, `events.json`, `frames.jsonl` (with `v2_top`, the model's top 3 guesses) and `landmarks.npz` (slotted hand points of every frame, `RawRecording` format, so a live run can be replayed through a newer model). `summary.json`, `events.json` and `landmarks.npz` are only written when the run ends with Esc or Ctrl+C, not when the window or Terminal is closed. `--backend inprocess` saves data but starts no web server.

## Pipeline (per frame, `src/convergent/pipeline.py`)

1. MediaPipe tracks up to 2 hands (21 landmarks each).
2. Model branches predict the technique:
   - **`temporal_v2`** (`detection/pair_adapter.py`), the model that decides. Details below.
   - The two older models, HandHygiene RandomForest and the v1 LSTM (`skia_temporal`), still run and are logged, but have fusion weight 0. On held-out data they scored 21% and 25% and made the result worse when they voted.
   - YOLO has no weights and stays unavailable.
3. Fusion combines the branches. Below 0.45 confidence, or when the model says "none", the frame is unknown.
4. The temporal validator and `EventDetector` (`detection/temporal.py`, `event_detector.py`) turn frames into events:
   - a motion starts at confidence 0.6 or more and continues at 0.4 or more;
   - it needs at least 0.5 s of support to be validated (1.0 s before 2026-11-12);
   - gaps of up to 0.5 s are allowed;
   - fragments less than 0.75 s apart are merged.
   Finalized `GestureEvent`s arrive about 1.25 s after the motion stops.
5. Region evidence and `ProgressState` (`regions/`) track 10 cells (5 regions × 2 hands).
6. The wash score (`scoring/wash_score.py`) runs on every frame.
7. Projection mapping, then sinks (results files, backend, Pi gateway).

### Recognition model: `temporal_v2` (built 2026-11-11)

Why it replaced the v1 LSTM: on Andrew's webcam the LSTM only said "palm to palm" when the tracker lost a hand (98 to 99% of its palm predictions), and the label flickered about 200 times a minute.

- **Classes:** the 7 techniques plus `none` (not washing). No left/right. The coverage work will get the side from hand geometry.
- **Features** (`detection/pair_features.py`, 183 values per frame): each hand described in its own frame (position, size and in-plane rotation removed), its motion, and the other hand seen from it.
- **Hand slots:** by position continuity (`HandSlotter`), not by MediaPipe's left/right guess. Hands without a resolved side are used too.
- **Window:** the last 48 frames (3.2 s). Frames without hands stay in as empty frames, so a dropout costs no warm-up. It answers after 8 frames with a hand and keeps answering for 0.35 s after the hands vanish.
- **Model:** temporal convolution network, `models/temporal_v2/current` (2.2 MB, committed). Output is calibrated. Smoothing is off since 2026-11-12 (`smooth_s: 0`) to cut lag.
- **Training data:** METC (Zenodo 5808789, 212 washes, frame labels), Kaggle `realtimear/hand-wash-dataset` (300 clips) and Andrew's own rounds `data/own/down1..3` (recorded 2026-11-11, laptop webcam, front view at chest height, 15 s per class). All in `data/`, git-ignored.
- **Installed model (2026-11-12):** full training on all data (`runs/v2/own_all`), then a 10-epoch fine-tune with own weight 12 (`runs/v2/ft_all`, `--init-from`). The previous public-only model is backed up in `runs/v2/installed_backup_public_only`.

Results on held-out METC people, through the full pipeline:

| Measure | Old models | New model |
| --- | --- | --- |
| Frame accuracy | 22% | 75% |
| Credited time / performed time (mean over steps) | 7% | 70% |
| Palm-to-palm credited | 0% | 80% |
| Label changes per minute (truth 7.8) | 248 | 24 |

Weak spots: thumb rubbing (53% credited), "other movement" still earns some step credit. Full numbers are in `docs/TEST_RESULTS.md` section 7.

On Andrew's webcam (held-out round `down3`, model trained without it, full pipeline):

| Measure | Public-only model | With own rounds 1 and 2 |
| --- | --- | --- |
| Frame accuracy | 24% | 59% |
| Credited time / performed time | 10% | 48% |
| Wrist credited | 0% | 0% |
| Palm to palm credited | 21% | 65% |
| Thumb credited | 11% | 18% |

Window accuracy on a held-out own round ranged 52 to 69% depending on which round was held out. The model scores 100% on the rounds it trained on, so it memorizes: 2 rounds of one person are too few. More rounds from several people, with varied technique, are the main lever. Wrist is read as backs of fingers. Details in `docs/TEST_RESULTS.md` section 8.

Commands:

```bash
# record labelled clips on our camera (run from Andrew's Terminal); guide in docs/RECORDING_GUIDE.md
.venv/bin/python -m convergent.cli record --device 1 --view down --round down1
# landmarks -> train -> install (about 15 minutes on the M5 Pro)
.venv/bin/python scripts/extract_landmarks_v2.py --metc data/METC --kaggle data/HandWashDataset --own data/own
.venv/bin/python scripts/train_temporal_v2.py --out runs/v2/<name> --window 48 --layers 5 --device mps --test-own-rounds down2,front2 --install
# fine-tune an existing artifact on own rounds (about 2 minutes); keeps the last epoch
.venv/bin/python scripts/train_temporal_v2.py --out runs/v2/<name> --window 48 --layers 5 --device mps --init-from runs/v2/own_all --own-weight 12 --epochs 10 --lr 5e-4 --samples-per-epoch 20000 --install
# measure through the real pipeline (--set accepts paths, e.g. temporal_v2.artifact_dir=runs/v2/<name>)
.venv/bin/python scripts/benchmark_recognition.py --own data/own --rounds down3 --metc data/METC
# window accuracy per own round (shows memorization: trained rounds vs held-out)
.venv/bin/python scripts/eval_own_rounds.py --model runs/v2/<name> --rounds down1,down2,down3
```

Tooling note: long training runs started in the background of a Claude session stall while Claude is not in a tool call. Run them in the foreground, or wait on them with an `until` loop.

### Technique names

`palm_to_palm`, `back_of_hand`, `interlaced_fingers`, `backs_of_fingers`, `thumb_rubbing`, `fingertip_rubbing` (the 6 WHO core techniques) and `wrist_rubbing` (WHO step 7, an extension). `configs/labels.yaml` still has `side_resolution: {}`, so every sided technique is "unresolved".

## Wash score (built 2026-11-10)

`src/convergent/scoring/wash_score.py`, configured in `configs/development.yaml` under `scoring:`. Andrew chose these rules:

- **Step time:** validated seconds per technique, summed across tries, either hand. Side mapping is not needed.
- **Live time:** released events, plus `EventDetector.pending` (the event held for a merge), plus the active candidate's `supported_s` once it is validated. The displayed time never decreases.
- **Backfill (2026-11-12):** when a step validates, it also gets up to `backfill_s` (1.5 s) of the unrecognized time just before it, never time already credited to another step. This makes up for the model's switch lag (median 1.4 s, measured by playing one own clip into another). Before this fix a step's timer started 2.5 to 4 s after the motion began.
- **Step done:** 3.0 s or more. Finished: 5 of 7 steps done AND a total of 20 s or more.
- **Order:** `next_step` suggests WHO order, but any step gets credit.
- **Points (0 to 100):** up to 10 per step (partial credit) plus up to 30 for total time, capped at 20 s.
- **Stars:**

  | Stars | Condition |
  | --- | --- |
  | 0 | Nothing recognized |
  | 1 | Some washing recognized |
  | 2 | 3 steps done, or 10 s total |
  | 3 | Finished |
  | 4 | Finished with 6 steps |
  | 5 | Finished with all 7 steps |

- **Freeze:** once finished, the score is frozen. The camera and recognition keep running.

Where the score shows up:

- `FrameResult.score` on every frame.
- `RunSummary.score` and `summary.json`.
- The backend session's `stats.wash_score`, via `GET /api/v1/sessions/{id}`. No migration was needed.
- The CLI end-of-run summary.
- `draw_score_panel` in `vision/overlays.py`, the live window.

If a run ends without finishing, the saved score uses released events only.

Other changes in the same work:

- `Pipeline.stop()` was added.
- Esc and Ctrl+C now end a run normally. Before, the summary, `end_session` and `summary.json` were lost.

The contract is documented in `docs/GAMIFICATION_HANDOFF.md`. Tests are in `tests/unit/test_wash_score.py` and `tests/integration/test_pipeline_e2e.py`.

Sample clip result: 4 of 7 steps found (no palm, thumb or wrist), 49.6 s total, not finished, 2 stars, 70 points.

**Status:** the thresholds (3 s, 20 s, 5 of 7) are first guesses. Tune them from real washes. The score and model changes are uncommitted on `main` unless git says otherwise. Branch before committing.

## Known limits (state these honestly)

- The score and coverage measure recognized motion time. They are not proof of clean hands, soap contact or microbial removal. Foam/soap detection is experimental.
- Region coverage tops out at about 0.4 today, because thumb, fingertip and back-of-hand credit need the left/right side mapping. Fill `labels.yaml: side_resolution` only after watching dataset clips. Never guess it to make numbers rise.
- Recognition accuracy has only been measured on public top-down sink videos of adults (METC, Kaggle). It has not been measured on Andrew's webcam, the faucet camera or children's hands. Passing tests is software verification, not real-world accuracy.
- One pipeline run is one session. There is no automatic per-child session lifecycle and no child identity in the schema. `WashScorer.reset()` is ready for future lifecycle work.
- `docs/GAMIFICATION_HANDOFF.md` mentions `live` WebSocket messages, but nothing publishes them yet. In-process `Pipeline.on_frame` is the only live feed.

## Hardware (planned, not arrived)

The repo docs describe a Raspberry Pi 3 A+. The actual plan uses a Raspberry Pi Zero 2 W:

- 512 MB RAM, 2.4 GHz Wi-Fi only;
- mini 22-pin CSI camera connector;
- mini-HDMI to the projector;
- Arducam B0176 5 MP camera;
- RIF6 Cube projector;
- power bank.

Pi docs and runbooks (`docs/PI_SETUP.md`, `docs/HARDWARE_DAY_RUNBOOK.md`) still need updating for the Zero 2 W. Keep heavy recognition on the laptop and the Pi agent lightweight (camera, JPEG over WebSocket port 8765, render commands back to HDMI).

## Next work (suggested order)

1. Record more own rounds (`docs/RECORDING_GUIDE.md`), ideally 2 to 3 teammates with a few rounds each and varied technique, then retrain and benchmark with a different person held out. Three rounds of Andrew gave 48% credited time on a held-out round, and the model memorizes the training rounds.
2. Build a one-motion game demo (germ, instruction, celebration) on top of `WashScore`. Don't re-implement validation in the game layer.
3. Coaching state machine, session lifecycle (hands arrive or leave), basic XP that does not reward washing extra times.
4. Parent/admin frontend and child-profile pairing. React + Vite and Supabase have been proposed but not installed.
5. Resolve the native label sides, then hardware testing on the Zero 2 W and recording 10 to 20 team washes for evaluation and retraining.

## How we work

- Andrew is the senior engineer and Claude is the junior. We plan together before writing code.
- When something is unclear, ask Andrew. Don't guess.
- Always use these skills: `andrej-karpathy-skills:karpathy-guidelines`, `superpowers`, `i-have-adhd:i-have-adhd` (load at session start, applies to every response).
- Responses: most important info first. Short and scannable, no fluff. Andrew has ADHD.
- Code: write the minimum lines needed, only what we need. No extra features or abstractions.

## Working style for Andrew

- Use clear, simple language and direct terminal commands. Andrew pastes them into his own Terminal.
- Lead with the action or diagnosis. Medium-length answers, one milestone at a time.
- Keep these separate: confirmed behavior, results Andrew reported, and proposed work.
- Avoid em dashes, semicolons, asterisk emphasis and unnecessary adjectives.
- Never print secrets from `.env`.
