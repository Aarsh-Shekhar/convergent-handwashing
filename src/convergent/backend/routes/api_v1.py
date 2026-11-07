"""REST routes under /api/v1 and /health."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from convergent.backend import schemas as S
from convergent.backend.auth import require_read, require_write
from convergent.backend.services import persistence as P
from convergent.detection.registry import ModelRegistry

router = APIRouter()
API_VERSION = "0.1.0"


def get_db(request: Request):  # type: ignore[no-untyped-def]
    yield from request.app.state.db.get_db()


# ---- health
@router.get("/health", response_model=S.HealthResponse)
def health(request: Request, db: DbSession = Depends(get_db)) -> S.HealthResponse:
    from sqlalchemy import func, select

    from convergent.backend import models as m

    st = request.app.state
    try:
        open_sessions = int(db.scalar(select(func.count()).select_from(m.Session).where(m.Session.ended_utc.is_(None))) or 0)
        db_status = "ok"
    except Exception as exc:  # noqa: BLE001
        open_sessions, db_status = 0, f"error: {exc}"
    return S.HealthResponse(status="ok" if db_status == "ok" else "degraded", version=API_VERSION, database=db_status,
                            migration_revision=st.migration_revision, uptime_s=time.monotonic() - st.started_monotonic,
                            sessions_open=open_sessions, device_connections=st.hub.counts().get("device", 0))


# ---- devices
@router.get("/api/v1/devices", response_model=list[S.DeviceOut], dependencies=[Depends(require_read)])
def list_devices(db: DbSession = Depends(get_db)) -> list:
    from sqlalchemy import select

    from convergent.backend import models as m

    return list(db.scalars(select(m.Device).order_by(m.Device.device_id)).all())


@router.post("/api/v1/devices", response_model=S.DeviceOut, dependencies=[Depends(require_write)])
def upsert_device(body: S.DeviceIn, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    return P.upsert_device(db, body.device_id, body.hardware, body.software_version, body.status)


# ---- sessions
@router.post("/api/v1/sessions", response_model=S.SessionOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_write)])
def create_session(body: S.SessionCreate, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.create_session(db, body.model_dump())
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="session_id already exists") from None


@router.get("/api/v1/sessions/{session_id}", response_model=S.SessionOut, dependencies=[Depends(require_read)])
def get_session(session_id: str, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.get_session(db, session_id)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


@router.patch("/api/v1/sessions/{session_id}", response_model=S.SessionOut, dependencies=[Depends(require_write)])
def update_session(session_id: str, body: S.SessionUpdate, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.update_session(db, session_id, body.ended, body.stats, body.model_versions)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


@router.post("/api/v1/sessions/{session_id}/predictions", response_model=S.BatchResult, dependencies=[Depends(require_write)])
def add_predictions(session_id: str, body: S.PredictionBatch, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.add_predictions(db, session_id, body.predictions)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


@router.post("/api/v1/sessions/{session_id}/events", response_model=S.BatchResult, dependencies=[Depends(require_write)])
async def add_events(session_id: str, body: S.EventBatch, request: Request, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        result = P.add_events(db, session_id, body.events)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    if result.accepted:
        from convergent.communication.protocol import make_message

        hub = request.app.state.hub
        for ev in body.events:
            await hub.broadcast("observations", make_message("gesture_event", 0, session_id=session_id, event=ev.model_dump(mode="json")))
    return result


@router.get("/api/v1/sessions/{session_id}/events", response_model=list[S.EventOut], dependencies=[Depends(require_read)])
def list_events(session_id: str, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.list_events(db, session_id)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


@router.post("/api/v1/sessions/{session_id}/regions", response_model=S.BatchResult, dependencies=[Depends(require_write)])
def upsert_regions(session_id: str, body: S.RegionBatch, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.upsert_regions(db, session_id, body.snapshot_ts, body.evidence)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


@router.get("/api/v1/sessions/{session_id}/regions", response_model=list[S.RegionOut], dependencies=[Depends(require_read)])
def list_regions(session_id: str, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.list_regions(db, session_id)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


# ---- calibrations
@router.post("/api/v1/calibrations", response_model=S.CalibrationOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_write)])
def create_calibration(body: S.CalibrationCreate, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.add_calibration(db, body.profile, body.device_id, body.activate)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="profile_id already exists (versions are new profiles)") from None


@router.get("/api/v1/calibrations/active", response_model=S.CalibrationOut | None, dependencies=[Depends(require_read)])
def active_calibration(db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    return P.active_calibration(db)


@router.get("/api/v1/calibrations/{profile_id}", response_model=S.CalibrationOut, dependencies=[Depends(require_read)])
def get_calibration(profile_id: str, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.get_calibration(db, profile_id)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


@router.post("/api/v1/calibrations/{profile_id}/invalidate", response_model=S.CalibrationOut, dependencies=[Depends(require_write)])
def invalidate_calibration(profile_id: str, body: S.CalibrationInvalidate, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.invalidate_calibration(db, profile_id, body.reason)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


# ---- evaluations
@router.post("/api/v1/evaluations", response_model=S.EvaluationOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_write)])
def create_evaluation(body: S.EvaluationCreate, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    return P.add_evaluation(db, body.model_dump(by_alias=True))


@router.get("/api/v1/evaluations/{run_id}", response_model=S.EvaluationOut, dependencies=[Depends(require_read)])
def get_evaluation(run_id: str, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.get_evaluation(db, run_id)
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


# ---- models
@router.get("/api/v1/models", dependencies=[Depends(require_read)])
def list_models(db: DbSession = Depends(get_db)) -> dict:
    registered = [S.ModelArtifactOut.model_validate(r).model_dump() for r in P.list_models(db)]
    try:
        discovered = ModelRegistry.load().discover_all()
    except FileNotFoundError:
        discovered = []
    return {"registered": registered, "discovered": discovered}


@router.post("/api/v1/models", response_model=S.ModelArtifactOut, dependencies=[Depends(require_write)])
def register_model(body: S.ModelArtifactIn, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    return P.register_model(db, body.model_dump())


# ---- annotations
@router.post("/api/v1/annotations", response_model=S.AnnotationOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_write)])
def add_annotation(body: S.AnnotationIn, db: DbSession = Depends(get_db)):  # type: ignore[no-untyped-def]
    try:
        return P.add_annotation(db, body.model_dump())
    except P.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
