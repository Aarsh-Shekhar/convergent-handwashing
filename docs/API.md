# Backend API (v1)

Base URL: `http://127.0.0.1:8000` (`CONVERGENT_API_HOST/PORT`). Interactive docs: `/docs`.
Writes require `Authorization: Bearer <CONVERGENT_API_TOKEN>`; with an empty token the backend
answers `503` to every write (fail closed). Reads are open on the development LAN unless
`CONVERGENT_ALLOW_UNAUTHENTICATED_READS=false`. Errors are always
`{"error": str, "detail": any, "code": "http_<status>|validation_error|internal_error"}`.

| Method & path | Body / result | Notes |
|---|---|---|
| `GET /health` | `{status, version, database, migration_revision, uptime_s, sessions_open, device_connections}` | migration head is `0001_initial` |
| `GET /api/v1/devices` | `[DeviceOut]` | last status from the device channel |
| `POST /api/v1/devices` | `DeviceIn` | upsert |
| `POST /api/v1/sessions` → 201 | `SessionCreate{source_id,width,height,target_fps,device_id?,processing_config,model_versions,capture_clock,calibration_profile_id?,recording_enabled=false}` | `session_id` optional (client-generated ids allowed, 409 on duplicate) |
| `GET /api/v1/sessions/{id}` | `SessionOut` | 404 if unknown |
| `PATCH /api/v1/sessions/{id}` | `{ended, stats, model_versions}` | ends the session (UTC) |
| `POST /api/v1/sessions/{id}/predictions` | `{predictions:[ModelPrediction]}` → `{accepted,duplicates,rejected,errors}` | idempotent on (model, version, window, last frame) |
| `POST /api/v1/sessions/{id}/events` | `{events:[GestureEvent]}` → BatchResult | idempotent on `dedupe_key` (technique, side, start); broadcast to `/ws/v1/observations` |
| `GET /api/v1/sessions/{id}/events` | `[EventOut]` | ordered by start |
| `POST /api/v1/sessions/{id}/regions` | `{snapshot_ts, evidence:[RegionEvidence]}` | one row per region×side; older snapshots never overwrite newer |
| `GET /api/v1/sessions/{id}/regions` | `[RegionOut]` | |
| `POST /api/v1/calibrations` → 201 | `{profile: CalibrationProfile, device_id?, activate=true}` | new versions are new profiles; activating deactivates others |
| `GET /api/v1/calibrations/active` | `CalibrationOut|null` | |
| `GET /api/v1/calibrations/{id}` | `CalibrationOut` | |
| `POST /api/v1/calibrations/{id}/invalidate` | `{reason}` | marks invalid + inactive |
| `POST /api/v1/evaluations` → 201 / `GET /api/v1/evaluations/{run_id}` | `EvaluationCreate` | metrics + model config + artifacts |
| `GET /api/v1/models` | `{registered:[ModelArtifactOut], discovered:[…]}` | discovered = `configs/models.yaml` on disk |
| `POST /api/v1/models` | `ModelArtifactIn` | upsert by (model_id, version) |
| `POST /api/v1/annotations` → 201 | `AnnotationIn` | reference labels / corrections |

WebSockets (query `?token=` for publishing):

* `/ws/v1/observations` – pub/sub of live JSON (`gesture_event`, `device_status`, pipeline `live` messages). Publishing requires the token.
* `/ws/v1/render` – pub/sub of `render` commands (same schema as the device gateway).
* `/ws/v1/device` – device agents send `hello`/`status`/`ping` (token required); binary frames are refused (video goes to the pipeline gateway on 8765).

All payload schemas are the shared models in `src/convergent/common/types.py` (`ModelPrediction`,
`GestureEvent`, `RegionEvidence`, `CalibrationProfile`).

## Timestamps

`*_utc` fields are UTC wall-clock. `*_ts` floats are seconds on the session's capture clock
(`sessions.capture_clock`: `video_pts` for recordings, `source_monotonic` for the Pi = the Pi's
`time.monotonic()`; values are only comparable within a session).

## Security & privacy – required before any real deployment

This is a LAN development backend for a child-facing project. Before deploying with real users:

1. TLS (reverse proxy) and per-device/per-user credentials instead of one shared token; token rotation.
2. Bind to loopback or a dedicated VLAN; firewall 8000/8765.
3. No raw video retention by default (already off; `CONVERGENT_RETAIN_RAW_VIDEO`); if recordings are ever enabled: encrypted storage, retention limits, guardian consent, deletion endpoint.
4. No child-identifying data in sessions/devices (the schema has none; keep it that way – no names, photos, birthdates).
5. Audit logging, backups, migration review, rate limiting, dependency scanning.
6. PostgreSQL with a non-default password and restricted network access (`docker-compose.yml` binds to 127.0.0.1 only).
