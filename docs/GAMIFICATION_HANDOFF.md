# Gamification hand-off: what the game engine will consume

The game engine is **not** implemented. These are the stable inputs it gets.

## Live stream (during a session)

Subscribe to `ws://<laptop>:8000/ws/v1/observations` (or receive `FrameResult` objects
in-process via `Pipeline.on_frame`). Messages:

| type | payload | meaning |
|---|---|---|
| `gesture_event` | `GestureEvent` | a technique was **validated** (`validation_status`), with `technique`, `side` (`left/right/both/unresolved/unknown`), `side_resolved`, `start_ts`, `end_ts`, `validated_duration_s`, `confidence`, `quality`, supporting model versions |
| `device_status` | `DeviceStatus` | Pi health (camera ok, display ok, fps, drops, under-voltage) |
| `live` (pipeline-published) | free-form | e.g. fused label per frame, active candidate (`ProgressState.active_candidate`) |

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
* Thresholds (`configs/development.yaml: temporal.*, regions.*`) are tunable without code changes; the game should not re-implement validation.
