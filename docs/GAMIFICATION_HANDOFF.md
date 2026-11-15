# Gamification hand-off: what the game engine will consume

The game engine is **not** implemented. These are the stable inputs it gets.

## Live stream (during a session)

Subscribe to `ws://<laptop>:8000/ws/v1/observations` (or receive `FrameResult` objects
in-process via `Pipeline.on_frame`). Messages:

| type | payload | meaning |
|---|---|---|
| `gesture_event` | `GestureEvent` | a technique was **validated** (`validation_status`), with `technique`, `side` (`left/right/both/unresolved/unknown`), `side_resolved`, `start_ts`, `end_ts`, `validated_duration_s`, `confidence`, `quality`, supporting model versions |
| `device_status` | `DeviceStatus` | Pi health (camera ok, display ok, fps, drops, under-voltage) |
| `live` | see below | published by the pipeline at `backend.live_hz` (5 Hz) and on every new event: fused label, active candidate, `WashScore`, and `ProgressState` when it was refreshed. **This is the feed to drive the game from.** |

`live` message body (fields besides `type`/`seq`/`session_id`):

```json
{"ts": 12.5, "frame_id": 187, "hands": 2,
 "fused": {"status": "valid", "technique": "thumb_rubbing", "side": "left", "confidence": 0.91},
 "active": {"technique": "thumb_rubbing", "side": "left", "start_ts": 10.0, "supported_s": 2.4, "validated": true},
 "score": { "...WashScore, see below..." },
 "soap": {"detected": true, "seen": true, "proxy": 0.08, "validated": false},
 "progress": null}
```
`soap` is a demo-grade yes/no: `seen` latches once white lather was visible on the hands for
0.7 s this wash, `detected` is the live state. It is a brightness heuristic (not validated, tune
`configs/development.yaml: soap.*` on the real sink); show it as a checkmark, never as a score input.
`active` is the step the child is doing *right now* (before it is validated); `fused.technique`
is the model's answer for this frame; `score.steps[*].seconds` are the per-step timers. Subscribe
to `ws://<laptop>:8000/ws/v1/observations` (read-only needs no token when
`allow_unauthenticated_reads` is on). Reference client: `tests/integration/test_backend_api.py::test_live_endpoint_fans_out_to_observation_subscribers`.

Sides: `side` is `left`/`right` = the hand **receiving** the technique (the static hand), set by the
side resolver (`docs/TEST_RESULTS.md` §9); `both` for palm-to-palm and interlaced fingers;
`unresolved` only when the resolver was unsure (then no hand-specific region credit is given).

Per-frame structures available in-process: `TrackedHands` (where the hands are),
`ModelPrediction` (fused, with `extras.participating`), `ProjectionTarget[]` (where to draw).

## State snapshot (`ProgressState`, `regions/progress.py`)

```json
{
  "session_id": "ses_…", "timestamp": 42.1,
  "techniques": {"palm_to_palm": {"validated_duration_s": 6.1, "event_count": 2, "sides_observed": ["both"],
                                   "gesture_detected": true, "gesture_validated": true, "side_unresolved_duration_s": 0.0}, "...": {}},
  "hands": {"left": {"regions": {"palm": RegionEvidence, "back_of_hand": …, "thumb": …, "fingers": …, "fingertips": …},
                     "sufficient_regions": ["palm"], "unknown_regions": ["thumb", "fingertips", "back_of_hand"]},
            "right": {…}},
  "coverage_estimate": 0.2,
  "coverage_definition": "fraction of (region x hand) cells with SUFFICIENT evidence, confidence-weighted",
  "unattributed_evidence": [{"event_id": "evt_…", "technique": "back_of_hand", "region": "back_of_hand", "duration_s": 5.5, "reason": "side unresolved"}],
  "active_candidate": {"technique": "thumb_rubbing", "side": "left", "start_ts": 40.0, "supported_s": 0.6, "validated": false},
  "procedure_states": {"wetting": "not_detected", "soap": "not_detected", "rinsing": "not_detected", "drying": "not_detected"},
  "schema_version": "progress-v1"
}
```

Vocabulary the game must respect: `gesture_detected` (a movement was classified),
`gesture_validated` (duration/quality requirements met), `RegionEvidence.status ∈
{unknown, insufficient, partial, sufficient}` (observed evidence, **not** cleanliness),
`coverage_estimate` (defined above). Wetting/soap/rinsing/drying have no validated detectors;
treat them as guided steps, not observations.

## Wash score (`WashScore`, `scoring/wash_score.py`)

`FrameResult.score` carries a live `WashScore` on **every** frame. The final one is in
`RunSummary.score`, `runs/<session_id>/summary.json` and the backend session's
`stats.wash_score` (`GET /api/v1/sessions/{id}`). The game should use it and not recompute it.

```json
{
  "session_id": "ses_…", "timestamp": 31.4,
  "steps": [{"technique": "palm_to_palm", "seconds": 4.2, "done": true, "points": 10.0}, "… 7 steps in suggested order …"],
  "steps_done": 5, "steps_required": 5, "step_min_s": 3.0,
  "total_s": 20.3, "total_min_s": 20.0,
  "finished": true, "finished_at_ts": 31.4, "next_step": "fingertip_rubbing",
  "points": 80, "stars": 3, "schema_version": "wash-score-v1"
}
```

Rules (all in `configs/development.yaml: scoring.*`):

* Steps: the 6 WHO techniques plus `wrist_rubbing`, in WHO order. Either hand counts (no side mapping needed).
* Step time: validated seconds, summed across tries. Live time adds the event held for merging
  and the active candidate once it is validated, so bars move while the child rubs. Displayed
  time never goes down.
* A step is done at `step_min_s` (3 s). The wash is finished when `steps_required` (5 of 7)
  steps are done and the total of all step times reaches `total_min_s` (20 s).
* `next_step`: the first step not yet done, in WHO order. It is a suggestion, and any step is credited.
* Points (0 to 100): up to 10 per step with partial credit, plus up to 30 for total time (capped at 20 s).
* Stars: 0 nothing recognized, 1 some washing, 2 three steps or 10 s, 3 finished,
  4 finished with 6 steps, 5 finished with all 7.
* `finished` is a milestone, not a freeze: `finished_at_ts` keeps the first time the wash
  qualified, and timers, points and stars keep going up afterwards (never down), so steps done
  after the 20 s mark still earn the 4th and 5th star.
* If a run ends before finishing, the saved score uses released events only (the same record as
  `/events`). It can be a fraction of a second below the last live value.

The score measures recognized washing-motion time. It does not measure clean hands, soap
contact or surface coverage. One pipeline run is one wash. `WashScorer.reset()` exists for
the future per-child session lifecycle.

## Wash records (auto wash sessions, 2026-11-14)

With `wash_sessions.enabled` (`camera --auto-wash`) one camera run is split into washes: a wash starts
when a hand has been tracked for 0.5 s and ends 4 s after the last hand was seen. Each wash gives one
`WashRecord` (`scoring/wash_session.py`), then score, events, evidence and germs are reset for the next
child. A hand in view for under 3 s with nothing washed is a walk-by and gives no record.

Where it goes: `Pipeline.on_wash(record)` and `Pipeline.wash_records` in process, one line per wash in
`runs/<session_id>/washes.jsonl`, `RunSummary.washes` / `summary.json`, the `wash` field of the `live`
message on the frame the wash ended, and `stats.washes` of the backend session when the run ends
(no new table). A wash still going when the run stops is recorded too.

```json
{"schema_version": "wash-record-v1", "wash_id": "ses_d830...-w001", "session_id": "ses_d830...",
 "started_utc": "2026-11-15T02:52:40.007Z", "ended_utc": "2026-11-15T02:54:10.540Z", "duration_s": 90.53,
 "seconds": {"palm_to_palm": 19.5, "back_of_hand": 18.07, "interlaced_fingers": 18.47, "backs_of_fingers": 17.2,
             "thumb_rubbing": 0.0, "fingertip_rubbing": 9.0, "wrist_rubbing": 7.53},
 "score": { "...WashScore..." },
 "soap_seen": true,
 "quality": {"frames": 1359, "fps": 15.0, "no_hand_share": 0.081, "two_hand_share": 0.16, "light_fix": true, "green_only": false},
 "models": {"temporal_v2": {"version": "2.0.0", "sha256": "f33fdd0d..."}, "tracker": "mediapipe.solutions.hands:0.10.21"}}
```

`seconds` is what the parents' app shows: recognized washing-motion time per part, not proof of clean
hands. `quality` lets the app skip a bad session (low fps, hands lost most of the time). There is no
child identity: pairing a wash with a child is the app's job. `ended_utc` is when the hands were last seen.

## Projection

`ProjectionTarget[]` per frame: `{anchor_type: landmark|hand_centroid|region_centroid, anchor_id:
"left:lm8" | "right:hand_centroid" | "left:thumb", side, camera_xy, projector_xy (854×480),
confidence, valid, reason, calibration_profile_id/version}`. Draw only `valid` targets. To put
graphics on the projector, send a `RenderCommand` (`communication/protocol.py`) through the
pipeline's device gateway or publish on `/ws/v1/render`; the future animation engine replaces
the diagnostic renderer on the Pi behind the same message contract.

## Persistence / history (REST)

* `GET /api/v1/sessions/{id}/events` – validated events for replays, stats, badges.
* `GET /api/v1/sessions/{id}/regions` – final region evidence per hand.
* `GET /api/v1/sessions/{id}` – session metadata, model/calibration versions, stats.
* `POST /api/v1/annotations` – store a human correction when the child/adult disputes a result.

## Guarantees and non-guarantees

* Timestamps are capture-clock seconds within a session; durations are frame-rate independent.
* Missing models never fake output; check `session.model_versions[*].available` to adapt the game (e.g. fewer techniques scored).
* Side-specific feedback is only possible for events with `side_resolved=true`.
* Thresholds (`configs/development.yaml: temporal.*, regions.*, scoring.*`) are tunable without code changes; the game should not re-implement validation.


## Projected graphics already in the repo (2026-11-14)

`docs/PROJECTION_GRAPHICS.md`: germ-dinos on the hands, glow, step strip, rendered through the
Pi `RenderCommand` protocol and previewed on the laptop (`camera --show --projection`, P key).
The game layer can either extend `projection/scene.py` (same protocol, works on the Pi today) or
drive its own page from the `live` WebSocket feed; both read the same `ProgressState`/`WashScore`.
