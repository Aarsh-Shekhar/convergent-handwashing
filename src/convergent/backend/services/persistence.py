"""Persistence services: idempotent writes of pipeline outputs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from convergent.backend import models as m
from convergent.backend.schemas import BatchResult
from convergent.common.timestamps import utc_now
from convergent.common.types import (
    CalibrationProfile,
    GestureEvent,
    ModelPrediction,
    RegionEvidence,
    new_id,
    stable_hash,
)


class NotFound(LookupError):
    pass


def prediction_key(p: ModelPrediction) -> str:
    return stable_hash(p.model_id, p.model_version, round(p.window_start_ts, 4), round(p.window_end_ts, 4), tuple(p.frame_ids[-1:]))


# ---- devices
def upsert_device(db: DbSession, device_id: str, hardware: dict[str, Any] | None = None, software_version: str = "",
                  status: str = "unknown", last_status: dict[str, Any] | None = None) -> m.Device:
    dev = db.get(m.Device, device_id)
    now = utc_now()
    if dev is None:
        dev = m.Device(device_id=device_id, hardware=hardware or {}, software_version=software_version, status=status,
                       last_seen_utc=now, last_status=last_status or {}, created_utc=now)
        db.add(dev)
    else:
        if hardware:
            dev.hardware = hardware
        if software_version:
            dev.software_version = software_version
        dev.status = status
        dev.last_seen_utc = now
        if last_status is not None:
            dev.last_status = last_status
    db.commit()
    db.refresh(dev)
    return dev


# ---- sessions
def create_session(db: DbSession, data: dict[str, Any]) -> m.Session:
    sid = data.get("session_id") or new_id("ses_")
    if db.get(m.Session, sid) is not None:
        raise IntegrityError("session exists", params=None, orig=Exception("duplicate session_id"))
    if data.get("device_id"):
        upsert_device(db, data["device_id"])
    row = m.Session(session_id=sid, device_id=data.get("device_id"), started_utc=utc_now(), source_id=data["source_id"],
                    width=data["width"], height=data["height"], target_fps=data["target_fps"],
                    processing_config=data.get("processing_config", {}), recording_enabled=data.get("recording_enabled", False),
                    recording_path=data.get("recording_path"), capture_clock=data.get("capture_clock", "source_monotonic"),
                    model_versions=data.get("model_versions", {}), calibration_profile_id=data.get("calibration_profile_id"))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_session(db: DbSession, session_id: str) -> m.Session:
    row = db.get(m.Session, session_id)
    if row is None:
        raise NotFound(f"session {session_id} not found")
    return row


def update_session(db: DbSession, session_id: str, ended: bool = False, stats: dict[str, Any] | None = None,
                   model_versions: dict[str, Any] | None = None) -> m.Session:
    row = get_session(db, session_id)
    if ended and row.ended_utc is None:
        row.ended_utc = utc_now()
    if stats is not None:
        row.stats = {**(row.stats or {}), **stats}
    if model_versions is not None:
        row.model_versions = {**(row.model_versions or {}), **model_versions}
    db.commit()
    db.refresh(row)
    return row


# ---- predictions
def add_predictions(db: DbSession, session_id: str, preds: list[ModelPrediction]) -> BatchResult:
    get_session(db, session_id)
    accepted = dup = 0
    errors: list[str] = []
    existing = set(db.scalars(select(m.Prediction.prediction_key).where(m.Prediction.session_id == session_id,
                                                                        m.Prediction.prediction_key.in_([prediction_key(p) for p in preds]))).all())
    for p in preds:
        key = prediction_key(p)
        if key in existing:
            dup += 1
            continue
        existing.add(key)
        db.add(m.Prediction(session_id=session_id, prediction_key=key, model_id=p.model_id, model_version=p.model_version,
                            window_start_ts=p.window_start_ts, window_end_ts=p.window_end_ts, frame_ids=list(p.frame_ids),
                            native_label=p.native_label, canonical_key=p.canonical.key if p.canonical else None,
                            distribution=p.canonical_probabilities or p.probabilities, confidence=p.confidence, status=p.status.value,
                            processing_time_ms=p.processing_time_ms, extras=_jsonable(p.extras)))
        accepted += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        errors.append(str(exc.orig))
        return BatchResult(accepted=0, duplicates=dup, rejected=accepted, errors=errors)
    return BatchResult(accepted=accepted, duplicates=dup, errors=errors)


# ---- events
def add_events(db: DbSession, session_id: str, events: list[GestureEvent]) -> BatchResult:
    get_session(db, session_id)
    accepted = dup = 0
    for ev in events:
        if ev.session_id != session_id:
            return BatchResult(accepted=accepted, duplicates=dup, rejected=1, errors=[f"event {ev.event_id} belongs to session {ev.session_id}"])
        exists = db.scalar(select(m.GestureEventRow.event_id).where(m.GestureEventRow.session_id == session_id,
                                                                    (m.GestureEventRow.dedupe_key == ev.dedupe_key) | (m.GestureEventRow.event_id == ev.event_id)))
        if exists:
            dup += 1
            continue
        db.add(m.GestureEventRow(event_id=ev.event_id, session_id=session_id, dedupe_key=ev.dedupe_key, technique=ev.technique,
                                 side=ev.side.value, side_resolved=ev.side_resolved, start_ts=ev.start_ts, end_ts=ev.end_ts,
                                 validated_duration_s=ev.validated_duration_s, confidence=ev.confidence, quality=ev.quality,
                                 validation_status=ev.validation_status.value,
                                 evidence={"supporting_predictions": [r.model_dump() for r in ev.supporting_predictions],
                                           "tracking_gaps_s": ev.tracking_gaps_s},
                                 model_versions=ev.model_versions, sequence_no=ev.sequence_no, created_utc=utc_now()))
        accepted += 1
    try:
        db.commit()
    except IntegrityError as exc:  # concurrent duplicate
        db.rollback()
        return BatchResult(accepted=0, duplicates=dup + accepted, errors=[str(exc.orig)])
    return BatchResult(accepted=accepted, duplicates=dup)


def list_events(db: DbSession, session_id: str) -> list[m.GestureEventRow]:
    get_session(db, session_id)
    return list(db.scalars(select(m.GestureEventRow).where(m.GestureEventRow.session_id == session_id).order_by(m.GestureEventRow.start_ts)).all())


# ---- regions
def upsert_regions(db: DbSession, session_id: str, snapshot_ts: float, evidence: list[RegionEvidence]) -> BatchResult:
    get_session(db, session_id)
    n = 0
    for e in evidence:
        row = db.scalar(select(m.RegionEvidenceRow).where(m.RegionEvidenceRow.session_id == session_id,
                                                          m.RegionEvidenceRow.region == e.region.value, m.RegionEvidenceRow.side == e.side.value))
        if row is None:
            row = m.RegionEvidenceRow(session_id=session_id, region=e.region.value, side=e.side.value, updated_utc=utc_now())
            db.add(row)
        elif row.snapshot_ts > snapshot_ts:
            continue  # stale snapshot: never move evidence backwards
        row.first_ts, row.last_ts = e.first_ts, e.last_ts
        row.observed_duration_s, row.confidence = e.observed_duration_s, e.confidence
        row.status, row.visibility = e.status.value, e.visibility.value
        row.supporting_events, row.supporting_techniques = list(e.supporting_events), list(e.supporting_techniques)
        row.snapshot_ts, row.updated_utc = snapshot_ts, utc_now()
        n += 1
    db.commit()
    return BatchResult(accepted=n, duplicates=len(evidence) - n)


def list_regions(db: DbSession, session_id: str) -> list[m.RegionEvidenceRow]:
    get_session(db, session_id)
    return list(db.scalars(select(m.RegionEvidenceRow).where(m.RegionEvidenceRow.session_id == session_id)
                           .order_by(m.RegionEvidenceRow.side, m.RegionEvidenceRow.region)).all())


# ---- calibration
def add_calibration(db: DbSession, profile: CalibrationProfile, device_id: str | None, activate: bool) -> m.CalibrationProfileRow:
    if db.get(m.CalibrationProfileRow, profile.profile_id) is not None:
        raise IntegrityError("profile exists", params=None, orig=Exception("duplicate profile_id"))
    if device_id:
        upsert_device(db, device_id)
    if activate:
        for other in db.scalars(select(m.CalibrationProfileRow).where(m.CalibrationProfileRow.active.is_(True))).all():
            other.active = False
    row = m.CalibrationProfileRow(profile_id=profile.profile_id, version=profile.version, device_id=device_id,
                                  camera={"width": profile.image_width, "height": profile.image_height, "rotation_deg": profile.image_rotation_deg,
                                          "mirrored": profile.image_mirrored, "intrinsics": None if profile.intrinsics is None else profile.intrinsics.model_dump()},
                                  projector_width=profile.projector_width, projector_height=profile.projector_height,
                                  camera_to_projector=profile.camera_to_projector, reprojection_rmse_px=profile.reprojection_rmse_px,
                                  inlier_count=profile.inlier_count, valid=profile.valid, invalidation_reason=profile.invalidation_reason,
                                  active=activate and profile.valid, profile=profile.model_dump(mode="json"), created_utc=utc_now())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_calibration(db: DbSession, profile_id: str) -> m.CalibrationProfileRow:
    row = db.get(m.CalibrationProfileRow, profile_id)
    if row is None:
        raise NotFound(f"calibration {profile_id} not found")
    return row


def invalidate_calibration(db: DbSession, profile_id: str, reason: str) -> m.CalibrationProfileRow:
    row = get_calibration(db, profile_id)
    row.valid = False
    row.active = False
    row.invalidation_reason = reason
    prof = dict(row.profile)
    prof["valid"] = False
    prof["invalidation_reason"] = reason
    row.profile = prof
    db.commit()
    db.refresh(row)
    return row


def active_calibration(db: DbSession) -> m.CalibrationProfileRow | None:
    return db.scalar(select(m.CalibrationProfileRow).where(m.CalibrationProfileRow.active.is_(True)).order_by(m.CalibrationProfileRow.created_utc.desc()))


# ---- evaluations / models / annotations
def add_evaluation(db: DbSession, data: dict[str, Any]) -> m.EvaluationRun:
    rid = data.get("run_id") or new_id("eval_")
    row = m.EvaluationRun(run_id=rid, dataset=data["dataset"], dataset_version=data.get("dataset_version", ""), split=data.get("split", {}),
                          model_config=data.get("model_config", data.get("model_config_", {})), metrics=data.get("metrics", {}),
                          artifacts=data.get("artifacts", {}), notes=data.get("notes", ""), created_utc=utc_now())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_evaluation(db: DbSession, run_id: str) -> m.EvaluationRun:
    row = db.get(m.EvaluationRun, run_id)
    if row is None:
        raise NotFound(f"evaluation {run_id} not found")
    return row


def register_model(db: DbSession, data: dict[str, Any]) -> m.ModelArtifact:
    row = db.scalar(select(m.ModelArtifact).where(m.ModelArtifact.model_id == data["model_id"], m.ModelArtifact.version == data["version"]))
    if row is None:
        row = m.ModelArtifact(registered_utc=utc_now(), **{k: v for k, v in data.items() if k in m.ModelArtifact.__table__.columns})
        db.add(row)
    else:
        for k, v in data.items():
            if k in m.ModelArtifact.__table__.columns and k not in ("model_id", "version"):
                setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


def list_models(db: DbSession) -> list[m.ModelArtifact]:
    return list(db.scalars(select(m.ModelArtifact).order_by(m.ModelArtifact.model_id, m.ModelArtifact.registered_utc.desc())).all())


def add_annotation(db: DbSession, data: dict[str, Any]) -> m.Annotation:
    if data.get("session_id"):
        get_session(db, data["session_id"])
    row = m.Annotation(created_utc=utc_now(), **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _jsonable(x: Any) -> Any:
    import json

    return json.loads(json.dumps(x, default=str))
