# Scrubble repo audit (2026-11-24)

What was in the repository before the companion-app work, read from the source. Written with AI assistance
(Claude), like the code in this change. Check anything marked UNKNOWN before relying on it.

## Branches

| Branch | Head | What it holds |
| --- | --- | --- |
| `main` | `1ac5ebe` (Andrew, Nov 15) | Recognition pipeline, projection, backend, Pi agent |
| `bryan` | `082f206` (Bryan, Nov 17) | `main` plus research and pitch notes (`RESEARCH.md`, `NOTES.md`, `docs/PITCH_INFO.md`) |
| `andrew` | `ceab9da` (Andrew, Nov 24 01:33) | `bryan` plus a parent app: backend tables and API, and a React + Vite web app |
| `scrubble-companion` | this work | Branched from `andrew`. Nothing on the other branches was changed. |

The handoff brief assumed no app existed. `andrew` already had one, so this work extends it instead of
adding the Next.js + Supabase app the brief suggested (the brief's own rule: use the existing stack, do not
duplicate a backend). Aarsh confirmed this choice.

## How the system actually runs

- The **laptop** does the work: `convergent.cli camera` runs MediaPipe hand tracking, the `temporal_v2`
  recognizer, scoring and the projection scene. The **Raspberry Pi** (`src/convergent/pi_agent/`) only
  sends camera JPEGs and draws render commands on HDMI. The Pi never talks to the app.
- The **backend** (`src/convergent/backend/`, FastAPI + SQLAlchemy + Alembic, SQLite by default) also runs
  on the laptop and serves the built web app from `web/dist`.
- Python 3.11 (`pyproject.toml`), dependencies locked in `uv.lock`. Web: React 18.3.1, Vite 6.4.6,
  TypeScript 5.6.3 (`web/package-lock.json`).

## The wash lifecycle (the integration seam)

1. `scoring/wash_session.py: WashSessions` starts a wash after 0.5 s of hands and ends it 4 s after they
   leave (`camera --auto-wash`, `wash_sessions.enabled`).
2. `pipeline.py: Pipeline._end_wash` builds one `WashRecord` (`wash-record-v1`) and, on `andrew`, called
   `backend.post_wash` inside the frame loop.
3. `POST /api/v1/washes` (bearer token `CONVERGENT_API_TOKEN`) stores it and announces `wash_saved` on
   `/ws/v1/observations`. The web app refetches on that message.

`_end_wash` is the finalization point. The only pipeline change in this work is there: the wash now goes
to a durable queue instead of a blocking HTTP call (see `docs/session-contract.md`).

## What a wash record contains (and does not)

Measured by the recognizer: validated seconds for each of 7 techniques (`palm_to_palm`, `back_of_hand`,
`interlaced_fingers`, `backs_of_fingers`, `thumb_rubbing`, `fingertip_rubbing`, `wrist_rubbing`).
Derived by `scoring/wash_score.py`: points 0 to 100, stars 0 to 5, steps done, finished.
Also: duration, a lather heuristic (`soap_seen`, unvalidated), quality numbers, model version.

Not in the record: which child, left or right hand, germs popped by the projection, pictures, hand points.
So the app shows zones (worked out from techniques in `scoring/progression.py: ZONES`), not per-hand
results, and never a "germs zapped 12/14" figure.

## Facts that shaped the app

- No child identity anywhere: the parent picks the active child in the app.
- No accounts or pairing. App routes are open on the laptop's address; writes from the pipeline need the token.
- The station reads no settings from the backend, so timer, difficulty and sound cannot be changed from the app.
- Accuracy is only measured on public adult videos and one webcam (`docs/TEST_RESULTS.md`). Not on children.
- `tests/unit/test_show_window.py` opens an OpenCV window and aborts without a display. It does this on
  `andrew` too. It was not changed.

## Unknown, not verified here

- Any run on the real Pi, camera or projector. Nothing in this work was tested on hardware.
- Andrew's local `.env` and port. `web/vite.config.ts` proxies to 8010; `configs/development.yaml` points the
  pipeline at 8000. The runbook uses 8000 for the real run.
- Rights to the character art (see `docs/art-manifest.md`).
- Competition rules on AI-assisted code. The team must check them.
