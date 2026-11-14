"""API request/response schemas (Pydantic v2). Versioned under ``/api/v1``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from convergent.common.types import (
    CalibrationProfile,
    GestureEvent,
    ModelPrediction,
    RegionEvidence,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorResponse(BaseModel):
    error: str
    detail: Any = None
    code: str = "error"


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    migration_revision: str | None
    uptime_s: float
    sessions_open: int
    device_connections: int


# ---- devices
class DeviceIn(ApiModel):
    device_id: str = Field(min_length=1, max_length=64)
    hardware: dict[str, Any] = Field(default_factory=dict)
    software_version: str = ""
    status: str = "unknown"


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device_id: str
    hardware: dict[str, Any]
    software_version: str
    status: str
    last_seen_utc: Any = None
    last_status: dict[str, Any]


# ---- sessions
class SessionCreate(ApiModel):
    session_id: str | None = None
    device_id: str | None = None
    source_id: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    target_fps: float = Field(gt=0)
    processing_config: dict[str, Any] = Field(default_factory=dict)
    recording_enabled: bool = False
    recording_path: str | None = None
    capture_clock: str = "source_monotonic"
    model_versions: dict[str, Any] = Field(default_factory=dict)
    calibration_profile_id: str | None = None


class SessionUpdate(ApiModel):
    ended: bool = False
    stats: dict[str, Any] | None = None
    model_versions: dict[str, Any] | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    session_id: str
    device_id: str | None
    started_utc: Any
    ended_utc: Any = None
    source_id: str
    width: int
    height: int
    target_fps: float
    processing_config: dict[str, Any]
    recording_enabled: bool
    recording_path: str | None
    capture_clock: str
    model_versions: dict[str, Any]
    calibration_profile_id: str | None
    stats: dict[str, Any]


# ---- predictions / events / regions (reuse the shared types for the payload)
class PredictionBatch(ApiModel):
    predictions: list[ModelPrediction] = Field(min_length=1, max_length=500)


class BatchResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: int = 0
    errors: list[str] = Field(default_factory=list)


class LiveUpdate(ApiModel):
    """Not persisted: rebroadcast as a `live` message on /ws/v1/observations for the game layer."""

    ts: float
    frame_id: int | None = None
    hands: int = 0
    fused: dict[str, Any] = Field(default_factory=dict)      # status, technique, confidence
    active: dict[str, Any] | None = None                      # temporal validator candidate (technique, supported_s, validated)
    score: dict[str, Any] | None = None                       # WashScore
    progress: dict[str, Any] | None = None                    # ProgressState (sent when the pipeline refreshed it)


class EventBatch(ApiModel):
    events: list[GestureEvent] = Field(min_length=1, max_length=500)


class RegionBatch(ApiModel):
    snapshot_ts: float
    evidence: list[RegionEvidence] = Field(min_length=1, max_length=50)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_id: str
    session_id: str
    technique: str
    side: str
    side_resolved: bool
    start_ts: float
    end_ts: float
    validated_duration_s: float
    confidence: float
    quality: float
    validation_status: str
    evidence: dict[str, Any]
    model_versions: dict[str, Any]
    sequence_no: int


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    region: str
    side: str
    first_ts: float | None
    last_ts: float | None
    observed_duration_s: float
    confidence: float
    status: str
    visibility: str
    supporting_events: list[str]
    supporting_techniques: list[str]
    snapshot_ts: float


# ---- calibrations
class CalibrationCreate(ApiModel):
    profile: CalibrationProfile
    device_id: str | None = None
    activate: bool = True


class CalibrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    profile_id: str
    version: int
    device_id: str | None
    projector_width: int
    projector_height: int
    reprojection_rmse_px: float | None
    inlier_count: int
    valid: bool
    invalidation_reason: str
    active: bool
    profile: dict[str, Any]
    created_utc: Any


class CalibrationInvalidate(ApiModel):
    reason: str = Field(min_length=1)


# ---- evaluations / models
class EvaluationCreate(ApiModel):
    run_id: str | None = None
    dataset: str
    dataset_version: str = ""
    split: dict[str, Any] = Field(default_factory=dict)
    model_config_: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    model_config = ConfigDict(extra="forbid", populate_by_name=True, protected_namespaces=())


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    run_id: str
    dataset: str
    dataset_version: str
    split: dict[str, Any]
    model_config_: dict[str, Any] = Field(alias="model_config")
    metrics: dict[str, Any]
    artifacts: dict[str, Any]
    notes: str
    created_utc: Any


class ModelArtifactIn(ApiModel):
    model_id: str
    name: str = ""
    version: str
    artifact_hash: str | None = None
    artifact_path: str | None = None
    preprocessing_version: str = ""
    label_mapping: dict[str, Any] = Field(default_factory=dict)
    available: bool = False
    validation: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class ModelArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    model_id: str
    name: str
    version: str
    artifact_hash: str | None
    artifact_path: str | None
    preprocessing_version: str
    label_mapping: dict[str, Any]
    available: bool
    validation: dict[str, Any]
    registered_utc: Any


class AnnotationIn(ApiModel):
    session_id: str | None = None
    recording_id: str | None = None
    technique: str
    side: str = "unknown"
    start_ts: float
    end_ts: float
    annotator: str = ""
    kind: str = "reference"
    notes: str = ""


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: str | None
    recording_id: str | None
    technique: str
    side: str
    start_ts: float
    end_ts: float
    annotator: str
    kind: str
    notes: str
