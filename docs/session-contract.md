# Wash contract: station to app

The brief proposed `POST /api/v1/sessions` with a new payload. The repo already had a working contract, so
the existing one is kept and hardened. `POST /api/v1/sessions` already exists for pipeline runs and is unrelated.

## Endpoint

`POST /api/v1/washes`, header `Authorization: Bearer <CONVERGENT_API_TOKEN>`, body = `WashRecord`
(`src/convergent/scoring/wash_session.py`, schema `wash-record-v1`).

| Brief's field | Actual field | Note |
| --- | --- | --- |
| `schema_version` | `schema_version` = `"wash-record-v1"` | other versions are refused |
| `session_id` (one per wash) | `wash_id` = `<run id>-w001` | the unique key; `session_id` is the camera run |
| `device_id` | none | one station per backend; the token identifies the sender |
| `profile_id` | none | the server assigns the active child. The station cannot name a child. |
| `started_at`, `ended_at`, `duration_seconds` | `started_utc`, `ended_utc`, `duration_s` | checked against each other |
| `completion_status` | `score.finished`, `score.stars` | 0 stars = nothing recognized |
| `algorithm_version` | `models.temporal_v2.version` | |
| `estimated_coverage`, `regions[]` | `seconds{technique: s}` | zones are derived on the server: share of `step_min_s` (3 s) |
| `virtual_germs` | none | the projection's germ count is not recorded |

## Answers

| Code | Meaning | Station does |
| --- | --- | --- |
| 201 | saved; body has the wash view, `duplicate: false`, `received` | done |
| 200 | same record again; `duplicate: true`, nothing counted twice | done |
| 409 | same `wash_id`, different contents | park, do not retry |
| 422 | malformed, unknown step, impossible times or values, future timestamp | park |
| 413 | body over 64 KB | park |
| 401 / 503 | wrong token / no token configured on the backend | park (401), retry (503) |
| 429 | more than 240 washes a minute; `Retry-After: 15` | wait and retry |
| 5xx, no answer | | retry with backoff |

Checks are in `backend/services/parent_app.py: check_record`. What a wash earns (zaps, points, a boss win)
is fixed when it is saved, in the same request.

## The upload queue (`backend/outbox.py`)

`Pipeline._end_wash` writes the record to `runs/wash_outbox.sqlite3` and returns. A background thread uploads:
oldest first, backoff 2 s doubling to 5 min with jitter, `Retry-After` respected. A wash leaves "waiting" only
after a 2xx. Refusals that will not change are parked with the reason. The file survives restarts; the next run
uploads what is left. Limits: 2000 waiting washes, the last 200 sent kept as a receipt. Only wash records are
stored, no frames.

    .venv/bin/python -m convergent.cli wash-queue              # what is waiting or parked
    .venv/bin/python -m convergent.cli wash-queue --send       # upload now
    .venv/bin/python -m convergent.cli wash-queue --retry-dead # after fixing the cause

Used only with `--auto-wash` and an HTTP backend. `--backend inprocess` still saves directly.
Switch off with `backend.wash_queue: false`.

Not changed: the pipeline's other backend calls (events, regions, live updates) are still made in the frame
loop with a 5 s timeout, as before. With the backend down they slow the loop. Only the wash upload was moved.

## Heartbeat

There is no separate heartbeat. The pipeline's existing live updates (`POST /sessions/{id}/live`, 5 a second)
set "last seen". `GET /api/v1/app/station` reports `online` only if one arrived in the last 15 s. It is kept in
memory, so it reads "not heard from" after a backend restart.

## What the app reads

- `/ws/v1/observations`: `live` messages (hands seen, current step, seconds per step, score) drive the kid's Live
  screen and the Station page. `wash_saved` makes every open screen reload its numbers.
- `GET /api/v1/app/sync`: the last washes with source, end time, arrival time, delay and size, plus the newest
  record as stored. This is what the Station page's sync log shows. Scoped to the active child.

## Not built

Per-device tokens, pairing codes, HTTPS, config sent back to the station. The shared token and plain HTTP are
for one laptop or a trusted home network only.
