# Project notes

The detailed log behind `CLAUDE.md`: measurements, design decisions with dates, and the next-work list. Full research with sources is in `RESEARCH.md`, and this file keeps the short takeaways.

Upkeep:
- Add a dated entry when something is built, measured or decided. Put the newest info in the right section, not at the bottom.
- Every few weeks, or when this file passes about 300 lines, compress it: merge old entries into one line each, drop superseded numbers, keep the decisions and why. Full measurements live in `docs/TEST_RESULTS.md`, so link there instead of copying.
- Only stable, everyday facts belong in `CLAUDE.md`.

## Next work (suggested order)

The parent/home version comes first (main audience, decided 2026-11-17). The school/daycare version waits.

1. **Privacy setup, with Andrew and an advisor.** Decide where frames are processed (the Pi 3 A+ is too weak for recognition, but streaming images is the main legal risk), what is stored, and the parent consent flow. See `RESEARCH.md` section C.
2. **Recognition accuracy.** Record more own rounds (`docs/RECORDING_GUIDE.md`), ideally 2 to 3 teammates with a few rounds each and varied technique. Retrain and benchmark with a different person held out. Three rounds of Andrew gave 48% credited time on a held-out round, and the model memorizes training rounds. Every feature below makes recognition errors more visible.
3. **Audio coach prototype on the laptop.** Quiet by default, a one-step hint after 4 to 5 s with no recognized step, quiet mode for kids who do 3+ steps unprompted, optional washing song. Build on `WashScore` and events, don't re-implement validation.
4. **On-device progression on the projector.**
   - Kid picks their avatar on the projection before washing, which tells the system who is washing at home without biometrics.
   - A collection or growing character shown at the start and end of each wash.
   - Surprise unlocks, new germ sets every 1 to 2 weeks, a clean-wash count that never resets (no streaks).
   - Rewards fade over about 8 to 10 weeks and spoken praise takes over.
   - Reward step quality, not the number of washes.
5. **Parent app.**
   - A simple summary screen first: washes completed, trend, and "parts to practice" only once accuracy allows.
   - Consent flow (COPPA plus CUBI notice), adult-only accounts, written retention policy.
   - Web app vs app store: a web app avoids the Texas App Store Act.
   - React + Vite and Supabase have been proposed but not installed.
6. **Hardware day** on the Pi 3 A+, and record 10 to 20 team washes for evaluation and retraining.
7. **Revisit score thresholds.** Kids aged 4 to 6 average 1 to 2 steps, so "finished = 5 of 7" may be out of reach for them.

Deferred, school/daycare version:
- Class germ jar (shared progress, no child identity) and teacher challenges tied to Texas childcare wash times (26 TAC 746.3417).
- Class totals only in the teacher view, and classroom sinks instead of restroom sinks.

Parked: motion sensor wake-up. The camera already starts washes (`--auto-wash`). Revisit only if battery life is a problem.

## Findings for ideation (2026-11-17, details in `RESEARCH.md`)

- **Retention ceiling:** no kids' hygiene gadget has shown engagement beyond about 2 months, and gains fade once the device is removed. Plan to measure 8-week use ourselves.
- **Quality, not frequency:** the closest study (day care sink animation) raised soaping time 62% but not how often kids washed. Footprints and arrows to the sink raised how often (4% to 74%).
- **Market gap:** competitors show rewards and progress on a phone. None shows long-term progress on the device. The phone requirement was the top barrier in a school study (29% never connected).
- **What lasts:** a growing character, rotating content, variable or surprise rewards, and an involved parent or teacher. Fixed promised rewards and losable streaks are risky. A tracking error that breaks a streak upsets kids.
- **Coaching:** hint only after a wait, one step at a time, 3 to 5 words for ages 4 to 6, phrased forward ("Now thumbs!"), never "you missed". Kids stop trusting a coach that's wrong. Praise the specific action, not the kid.
- **Rewards:** low risk for handwashing (kids don't already enjoy it). Surprise beats promise. Fade after about 2 months (habit median 59 to 66 days).
- **Over-engagement:** cap the post-wash play (Philips's Sparkly delayed bedtimes).
- **Privacy is a design constraint:** in a bathroom, sending images out is the biggest legal risk. Store derived wash records only.

## Log

### 2026-11-26: Andrew's app and the two-view app merged, now on `main` (Aarsh)

- `main` had Andrew's single-view parent app (PR 2). `scrubble-companion` had the two-view app on the same backend. They are now one: the two views are the base and every screen of his has a place in them. The table is in `docs/SCRUBBLE_APP.md`.
- Brought over from his last commit: the germ playground, "coming soon" germ slots, the live camera check in onboarding, scrub rules and "Run setup again" in settings, the coaching tip.
- `main` also gets Bryan's commits (this file, `RESEARCH.md`, `docs/PITCH_INFO.md`, the Windows fixes), which were not on `main` before.
- Tests: Playwright 20. Others as below.

### 2026-11-24: Scrubble companion app, two views (branch `scrubble-companion`, Aarsh)

- Built on Andrew's backend and web app. Kid view (`/kid`, game) and grown-up view (`/`, tables, charts, hand heatmap), with Phone / Desktop layout switch. Details: `docs/SCRUBBLE_APP.md`, `docs/design-spec.md`.
- Station page shows how a wash gets from the sink to the app: live feed, what is sent and not sent, the record, a sync log with the delay per wash.
- Washes upload through a queue file (`backend/outbox.py`) so none is lost when the backend is down.
- Tested in a Linux container only: pytest 300 passed, vitest 7, Playwright 17 in Chrome. Not tested: camera, Pi, projector, Safari, a real phone.
- Third pass the same day: kid view back to the dark ocean colours but flat, grown-up view with no characters. Map places are tappable, each rewarded wash is a level, three daily quests (no extra rewards). Extensions page: summary for a doctor, saved doctor contact, calendar file, CSV. Partner ideas are listed as not built. Tests now: pytest 304, vitest 11, Playwright 19.
- Run it: `bash START_SCRUBBLE_DEMO.command` (demo family, made-up history tagged Demo).

### 2026-11-17: gameplay loop research, parent version first

- Three research agents: comparable products, child coaching and rewards, US/Texas data rules. Full reports in `RESEARCH.md`, takeaways above.
- Decisions: parent/home version first, school version deferred, motion sensor parked.

### 2026-11-17: Windows setup (Bryan)

- `.venv` built with `uv sync --extra backend --extra yolo --extra dev`, then PyTorch swapped to the CUDA build (cu126). `pyproject.toml` and `uv.lock` untouched.
- Windows bug fixed: numpy's default integer is 32-bit on Windows, so `detection/pair_training.py` training crashed ("expected Long but found Int"). Labels now use `.long()`.
- Live window (`cli.py _attach_show_window`) is now resizable, opens at 960x720, and F toggles fullscreen. Before, OpenCV's autosize window was locked to 640x480.
- Full suite on Windows: 224 passed, including `test_events_in_who_order_with_thumb_missing` (which failed on Andrew's Mac).
- Sample clip result on Windows: 6 of 7 steps (thumb missing), 90.5 s, finished, 4 stars, 90 points. The older note (4 of 7, 49.6 s, 2 stars, 70 points) predates the `temporal_v2` model. Confirm with Andrew.

### 2026-11-14: graphics, sessions, robustness

- Projected graphics: `projection/scene.py` + `projection/sprites.py`, germ-dinos per (hand, region) cell that die with region evidence, glow, bottom step strip. Same `RenderCommand` protocol as the Pi (`sprite`, `bar`, `filled_polygon` added). Config `projector.graphics`. `lead_ms` extrapolates hand graphics by measured latency (0 until measured). Details: `docs/PROJECTION_GRAPHICS.md`.
- Coverage scene (`mode: coverage`, now the default): `projection/coverage.py CoverageScene`, 20 germs (three kinds) per visible hand side, each tied to a wash step, separate palm and back sets. A step's germs pop one by one as its 3 s fill. No guide, any order: Andrew's decision after trying a guided game live (removed, copy in `runs/removed_guided/`). Top bar: germs left, ring per step, stars. Sprites from `scripts/make_sprites.py` into `projection/assets/`, stored without colour and tinted. A lost hand is held 0.4 s. `flip_facing` must match the camera.
- Green fix (`projector.graphics.green_only`, off): hand graphics in projector green only, `vision/projector_light.py` removes that green from the tracker's picture. Simulated projection, own `down3` frame accuracy: 63% no projection, 54% normal colours, 61% green fix. Held-out METC: 78 / 68 / 76%. Red-only tracking dropped (about 15 points lower). `green_fit` is per camera (`scripts/fit_green.py`), `green_leak` is a guess until hardware day.
- Do not raise `lead_ms` without measuring: straight-line prediction made scrubbing error worse on saved live runs (15 mm vs 12 mm at 67 ms).
- Auto wash sessions (`wash_sessions.enabled`, `camera --auto-wash`, off): `scoring/wash_session.py` starts a wash after 0.5 s of hands, ends it 4 s after they leave. Each wash writes a `WashRecord` to `runs/<session>/washes.jsonl`, `RunSummary.washes`, `Pipeline.on_wash` and the `live` message, then resets score, events, evidence and germs. Format in `docs/GAMIFICATION_HANDOFF.md`.
- False tiny hands (`tracker.min_hand_size: 0.10`): detections under 10% of the picture are dropped. A background object once earned 32 s of fingertip credit. Real hands are 12% or more in all data.
- Light fix (`tracker.light_fix`): `normalise_light` cleans dark, tinted, flat or grainy pictures and leaves good ones alone. Numbers in `docs/TEST_RESULTS.md` section 10. Simulate with `scripts/benchmark_recognition.py --degrade dark|blue|flat|grainy`.
- Side resolver (`detection/side_resolver.py`): MLP on label-free hand geometry, 96.5% held-out frame accuracy on Kaggle. Sample clip coverage 0.40 -> 0.60. `configs/labels.yaml: side_resolution` verified (`*_Left` = left hand receives).
- Low frame rate support: model window resampled onto a 15 FPS grid, webcam grabbed in a background thread, `tracker.backend: solutions` (tasks is about 2x slower on macOS).
- SOAP checkmark (`regions/foam.py`): brightness heuristic for UI and `live` feed only.
- `live` WebSocket messages: `POST /api/v1/sessions/{id}/live` -> `/ws/v1/observations`, 5 Hz plus every event.
- Wash score: finished is a milestone (`finished_at_ts`), timers, points and stars keep accruing.
- Hardware parts list corrected: Pi 3 Model A+, not Zero 2 W.

### 2026-11-12: lag cuts and installed model

- Validation support 1.0 s -> 0.5 s. Model smoothing off (`smooth_s: 0`).
- Score backfill: a validating step gets up to 1.5 s of unrecognized time just before it (model switch lag, median 1.4 s). Before, a step's timer started 2.5 to 4 s late.
- Installed model: full training on all data (`runs/v2/own_all`), then a 10-epoch fine-tune with own weight 12 (`runs/v2/ft_all`). Public-only model backed up in `runs/v2/installed_backup_public_only`.

### 2026-11-11: `temporal_v2` model

Replaced the v1 LSTM, which on Andrew's webcam only said "palm to palm" when a hand was lost (98 to 99% of its palm predictions) and flickered about 200 times a minute.

Held-out METC people, full pipeline:

| Measure | Old models | New model |
| --- | --- | --- |
| Frame accuracy | 22% | 75% |
| Credited time / performed time | 7% | 70% |
| Palm-to-palm credited | 0% | 80% |
| Label changes per minute (truth 7.8) | 248 | 24 |

Andrew's webcam, held-out round `down3`:

| Measure | Public-only | With own rounds 1 and 2 |
| --- | --- | --- |
| Frame accuracy | 24% | 59% |
| Credited time / performed time | 10% | 48% |
| Wrist credited | 0% | 0% |
| Palm to palm credited | 21% | 65% |
| Thumb credited | 11% | 18% |

Held-out own-round window accuracy 52 to 69%, trained rounds 100%: the model memorizes. Weak spots: thumb (53% credited on METC), wrist read as backs of fingers, "other movement" earns some credit. Details in `docs/TEST_RESULTS.md` sections 7 and 8. Own rounds `data/own/down1..3`: laptop webcam, front view at chest height, 15 s per class.

### 2026-11-10: wash score

- Built `scoring/wash_score.py` with Andrew's rules (see `CLAUDE.md`). Thresholds are first guesses.
- Added `Pipeline.stop()`. Esc and Ctrl+C now end a run normally (before, the summary and `summary.json` were lost).
- Contract in `docs/GAMIFICATION_HANDOFF.md`. Tests in `tests/unit/test_wash_score.py` and `tests/integration/test_pipeline_e2e.py`.
