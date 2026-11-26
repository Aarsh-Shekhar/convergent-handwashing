# Scrubble companion app

The app for the sink station, in two views: a game for the kid and the numbers for the grown-up.
Switch between them, and between phone and desktop layout, inside the app (`docs/design-spec.md`).
Extends Andrew's parent app (`andrew` branch). AI-assisted (Claude); review before relying on it.

    camera -> laptop pipeline -> WashRecord -> wash queue (SQLite file) -> POST /api/v1/washes
           -> backend saves wash + zaps + points -> "wash_saved" on the WebSocket -> open app reloads its numbers

## Run

See `docs/demo-runbook.md`. Development with hot reload: backend on 8010, then `cd web && npm run dev` (port 5173).

## Where Andrew's app lives now

Andrew built the first app (branches `andrew`, `parent-app`, merged to `main` on 2026-11-25). On 2026-11-26 it was
merged with the two-view app. His backend is used as it is. Each of his screens has a place in the two views:

| Andrew's screen or feature | Where it is now |
| --- | --- |
| Backend: per-wash saving, progress rules, app API, zap rule `worth()` | Unchanged, `src/convergent/backend`, `scoring/progression.py` |
| Home (washes today, average, latest wash, tip) | Kid Home (`/kid`) and grown-up Overview (`/`). His tip is the "Coaching tip" on Overview |
| Wash history and wash detail | Grown-up Washes (`/washes`), with the score arithmetic added. Kid wash page `/kid/wash/:id` |
| Live wash | Kid Live (`/kid/live`), his page ported |
| Progress (day, week, month, trouble spots) | Grown-up Overview and Insights (range picker, heatmap, per-step bars) |
| Rewards: zaps, catching germs, badges | Kid Germs (`/kid/germs`) for zaps and catching, Kid Rewards for badges |
| Germ playground | Kid Germs, `components/Playground.tsx`. Tap a germ and it hops and says where it hides |
| Germ-dex with boss and "coming soon" slots | Kid Germs. The four empty slots are shown as "Coming soon" |
| Onboarding: tour, grown-up, kid, station, camera check, routines | `/onboarding`, same ten steps. The camera step turns green from the live feed as in his version |
| Routines and daily goal | Grown-up Settings |
| Settings: station row, scrub rules, kid profile, delete history, run setup again | Grown-up Settings and Station. "Scrub rules" and "Run setup again" added |
| `scripts/give_zaps.py`, `scripts/seed_demo_washes.py` | Kept |

Not carried over: his light blue single-view styling and his page files (`web/src/pages/Home.tsx` and the others),
which the two views replace. The name on screen is Scrubble. His build said Scrubby.

## What is where

| Part | Path |
| --- | --- |
| Rules: zones, zaps, points, streak, badges, boss, map | `src/convergent/scoring/progression.py` |
| Storage scoped to the active child, wash checks | `src/convergent/backend/services/parent_app.py` |
| Family rewards, requests, high-fives, parent PIN | `src/convergent/backend/services/family.py`, `routes/family_v1.py` |
| Tables | `backend/models.py`, migration `0003_family.py` |
| Wash upload queue | `src/convergent/backend/outbox.py`, hooked in `pipeline.py: _end_wash` |
| Web app | `web/src`: `pages/kid`, `pages/parent`, `components`, `art`, `styles`, `mode.tsx` (views and layouts), `live.tsx` (live feed) |
| Trends for the grown-up view | `progression.insights()`, `GET /api/v1/app/insights?days=7|14|30|90` |
| Sync log and the newest wash record | `GET /api/v1/app/sync` |
| Map levels and daily quests | `progression.adventure()`, `progression.quests()`, `GET /api/v1/app/adventure` |
| Doctor contact (Extensions) | `GET` and `PUT /api/v1/app/care`, migration `0004_care.py` |
| Summary text, CSV, calendar file | `web/src/report.ts` (built in the browser, nothing is sent) |
| Demo family, simulated wash | `scripts/seed_demo_family.py`, `scripts/send_test_wash.py` |

## Rules (product choices, first guesses)

- **Zone washed:** 3 s of its scrubbing motion (the station's `step_min_s`). Backs is the mean of two techniques.
- **Zaps** (Andrew's): 1 per step done, +3 for a finished wash. Spent on germs.
- **Points:** the wash score, 0 to 100. Spent on family rewards.
- **Daily cap:** washes after the daily goal earn no zaps and no points, and do not move the map.
  A wash with nothing recognized earns nothing and does not count toward the goal.
- **Balance:** points earned minus requests that are waiting or approved. Never stored as a total.
- **Streak:** local days in a row with a counted wash. Today not washed yet does not break it. Nothing is taken away.
- **Map:** places open at 0, 10, 25 and 50 rewarded washes. Each rewarded wash is one level. Every fifth level shows a chest. The chest is a marker and holds nothing.
- **Daily quests:** one wash, 3 stars in one wash, the boss's zone fully scrubbed once. They earn nothing extra. Full quest days are counted per week.
- **Extensions:** the summary is text the parent sends. "Book a visit" opens a link the parent saved. No clinic, insurer or school is connected.
- **Boss:** Andrew's rule. The boss's zone fully washed in 20 washes within the week.
- **Germ "zapped x N":** washes in which that germ's zone was fully washed. Not a count of projected germs.
- **Delete history:** removes the active child's washes, germs and reward requests. Points and the map reset
  because they are sums over washes. Rewards and the profile stay.
- Days and weeks use the family's timezone, which follows the browser.

## Differences from the brief

| Brief | Built | Why |
| --- | --- | --- |
| Next.js, Supabase, Vercel | FastAPI + SQLite + Vite React | An app already existed on `andrew` |
| Supabase Auth, RLS, households | One family per backend, no login, optional parent PIN | No account system exists. The PIN keeps a child out of parent screens. It is not security against someone on the network. |
| Per-device hashed tokens, pairing codes | The existing shared bearer token | One station per backend |
| Pi uploads over HTTPS | The laptop pipeline uploads over HTTP on the laptop or LAN | The Pi is only camera and display |
| Config sync to the station | Not built; shown read-only | The station reads no config from the backend |
| Reminders, push | Shown as not available | Not built |
| Virtual germs zapped per wash | Steps done | Not in the wash record |
| ESLint | `tsc` strict only | None was set up in `web/`; not added |
| Framer Motion, Tailwind, Recharts | Plain CSS and SVG | Not needed |

Changed in Andrew's code, on purpose:

- `GermUnlock` moved to table `child_germs` with a `child_id` (migration keeps existing rows).
- `washes()`, `unlocks()`, `buy()`, `delete_history()` act on the active child.
- `test_a_wash_is_saved_once_and_earns_zaps` now sends the identical record twice. A different record under
  the same id is a 409 now.
- `tests/integration/test_backend_api.py` expects migration `0004_care`.
- His web pages were rewritten in the new visual style. His data hooks, router and live feed were kept and extended.
- His later commits (Live page, rewards, Germ-dex, the zap rule `worth()`) were merged on 2026-11-24. The zap rule is
  his. The Live page was ported to `pages/kid/KidLive.tsx`. His other pages were replaced by the two-view pages.

## Tests

Run on 2026-11-24 in a Linux container. No camera, Pi, projector or sample video was available.

| Command | Result |
| --- | --- |
| `.venv/bin/ruff check src tests scripts` | All checks passed |
| `.venv/bin/python -m pytest -q tests --deselect tests/unit/test_show_window.py` | 304 passed, 6 skipped, 4 deselected |
| `cd web && npm run typecheck` | exit 0 |
| `cd web && npm test` | 11 passed |
| `cd web && npm run build` | exit 0 |
| `cd web && npm run test:e2e` (Chrome, real backend) | 20 passed, run in America/Chicago and Asia/Tokyo |

`tests/unit/test_show_window.py` aborts here because it opens a window and there is no display. It aborts the
same way on `andrew`. Run it on a Mac. The 6 skips need `data/samples/handwashing_missing_step.mp4`.

Covered by tests: wash validation, duplicates, conflicts, concurrency, size and rate limits, token; active-child
isolation; points cap, exact balance, concurrent requests, approve and decline, PIN; migration up and down with
data; queue backoff, ordering, parking, restart, one upload one award; the queue through the real pipeline with
scripted hands; every screen in both views at 320, 390, 430 and 1280 px; the two switches; the live wash flow;
live update without reload; onboarding; errors; insights and the sync log; the map, a place and a level;
quests; the doctor contact, the summary text and both downloads.

## Status

Implemented and tested here: everything in the table above.

Implemented, not tested here:

- Any real camera run, the Pi, the projector. The queue was exercised with scripted hands, not a camera.
- Safari. Only Chrome was available.
- A phone on the LAN.

Not built: partner booking or pricing, HSA receipts, classroom reports, soap reminders (listed in the app as
planned), accounts, pairing, HTTPS, config sync, reminders, moving a wash to another child,
PWA install, deployment anywhere.

For the team to do: run the hardware day checklist with `--auto-wash --backend http` and confirm a real wash
lands; confirm art rights; draw the four stand-in germs; check the competition's rules on AI-assisted code;
record the demo.
