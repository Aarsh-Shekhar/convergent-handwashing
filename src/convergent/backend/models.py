"""SQLAlchemy 2 ORM entities.

Timestamps: ``*_utc`` columns are timezone-aware UTC wall-clock times (bookkeeping only).
``capture``-style float columns are seconds on the device monotonic clock of the owning
session (see ``common.types``); they are comparable only within a session. Raw video frames
are never stored as rows; optional recordings are files referenced by ``Session.recording_path``.
No child-identifying data exists in this schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from convergent.backend.database import Base


class Device(Base):
    __tablename__ = "devices"
    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hardware: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    software_version: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_seen_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Session(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.device_id"), nullable=True)
    started_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_id: Mapped[str] = mapped_column(String(128))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    target_fps: Mapped[float] = mapped_column(Float)
    processing_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    recording_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    capture_clock: Mapped[str] = mapped_column(String(32), default="source_monotonic")
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    calibration_profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0.0")

    predictions: Mapped[list[Prediction]] = relationship(back_populates="session", cascade="all, delete-orphan")
    events: Mapped[list[GestureEventRow]] = relationship(back_populates="session", cascade="all, delete-orphan")
    regions: Mapped[list[RegionEvidenceRow]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(256), default="")
    version: Mapped[str] = mapped_column(String(128))
    artifact_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    preprocessing_version: Mapped[str] = mapped_column(String(64), default="")
    label_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    registered_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("model_id", "version", name="uq_model_version"),)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id", ondelete="CASCADE"), index=True)
    prediction_key: Mapped[str] = mapped_column(String(96))  # client idempotency key
    model_id: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(128))
    window_start_ts: Mapped[float] = mapped_column(Float)
    window_end_ts: Mapped[float] = mapped_column(Float)
    frame_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    native_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    distribution: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    processing_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    extras: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    session: Mapped[Session] = relationship(back_populates="predictions")
    __table_args__ = (UniqueConstraint("session_id", "prediction_key", name="uq_prediction_key"),
                      Index("ix_pred_session_ts", "session_id", "window_end_ts"))


class GestureEventRow(Base):
    __tablename__ = "gesture_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id", ondelete="CASCADE"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    technique: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(16))
    side_resolved: Mapped[bool] = mapped_column(Boolean, default=True)
    start_ts: Mapped[float] = mapped_column(Float)
    end_ts: Mapped[float] = mapped_column(Float)
    validated_duration_s: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    quality: Mapped[float] = mapped_column(Float, default=1.0)
    validation_status: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sequence_no: Mapped[int] = mapped_column(Integer, default=0)
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session: Mapped[Session] = relationship(back_populates="events")
    __table_args__ = (UniqueConstraint("session_id", "dedupe_key", name="uq_event_dedupe"),)


class RegionEvidenceRow(Base):
    __tablename__ = "region_evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id", ondelete="CASCADE"), index=True)
    region: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(16))
    first_ts: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_ts: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32))
    visibility: Mapped[str] = mapped_column(String(16), default="missing")
    supporting_events: Mapped[list[str]] = mapped_column(JSON, default=list)
    supporting_techniques: Mapped[list[str]] = mapped_column(JSON, default=list)
    snapshot_ts: Mapped[float] = mapped_column(Float, default=0.0)
    updated_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session: Mapped[Session] = relationship(back_populates="regions")
    __table_args__ = (UniqueConstraint("session_id", "region", "side", name="uq_region_side"),)


class CalibrationProfileRow(Base):
    __tablename__ = "calibration_profiles"
    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.device_id"), nullable=True)
    camera: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    projector_width: Mapped[int] = mapped_column(Integer)
    projector_height: Mapped[int] = mapped_column(Integer)
    camera_to_projector: Mapped[list[list[float]]] = mapped_column(JSON)
    reprojection_rmse_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    inlier_count: Mapped[int] = mapped_column(Integer, default=0)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    invalidation_reason: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON)  # full CalibrationProfile document
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(256))
    dataset_version: Mapped[str] = mapped_column(String(128), default="")
    split: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ---- parent app (one family per backend for now; the child is named by the parent, never recognized)
class Child(Base):
    __tablename__ = "children"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    buddy: Mapped[str] = mapped_column(String(32), default="scrubby")
    age_band: Mapped[str] = mapped_column(String(8), default="5-6")
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WashRow(Base):
    """One wash (WashRecord) with the zaps it earned when it arrived. No pictures, no hand points."""

    __tablename__ = "washes"
    wash_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    child_id: Mapped[int | None] = mapped_column(ForeignKey("children.id", ondelete="SET NULL"), nullable=True)
    session_id: Mapped[str] = mapped_column(String(64))
    ended_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    stars: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)
    finished: Mapped[bool] = mapped_column(Boolean)
    steps_done: Mapped[int] = mapped_column(Integer)
    zaps: Mapped[int] = mapped_column(Integer)
    reward_points: Mapped[int] = mapped_column(Integer, default=0)  # family-reward points, fixed when the wash arrives
    source: Mapped[str] = mapped_column(String(16), default="station")  # station | demo (made-up seed data)
    seconds: Mapped[dict[str, Any]] = mapped_column(JSON)
    record: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppSettings(Base):
    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    parent_name: Mapped[str] = mapped_column(String(64), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="America/Chicago")
    daily_goal: Mapped[int] = mapped_column(Integer, default=6)
    routines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    toggles: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    active_child_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # the child new washes belong to (picked by the parent)
    parent_pin_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)  # salted PBKDF2, never the PIN itself
    care: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # the family's doctor contact, typed in by the parent
    updated_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GermUnlock(Base):
    """A germ a child bought with zaps or won from the boss. ``child_id`` is NULL only before the first child exists."""

    __tablename__ = "child_germs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    child_id: Mapped[int | None] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), nullable=True, index=True)
    germ: Mapped[str] = mapped_column(String(32))
    spent: Mapped[int] = mapped_column(Integer, default=0)  # zaps paid (0 for a boss win)
    how: Mapped[str] = mapped_column(String(16))  # bought | boss
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("child_id", "germ", name="uq_child_germ"),)


class FamilyReward(Base):
    """A real-life reward the parent offers for points (extra bedtime story, pick the Friday movie)."""

    __tablename__ = "family_rewards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(80))
    cost: Mapped[int] = mapped_column(Integer)
    icon: Mapped[str] = mapped_column(String(16), default="gift")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Redemption(Base):
    """A child's request to trade points for a family reward. The points are held from the request until a parent decides."""

    __tablename__ = "redemptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)  # made by the app, so a repeated tap or retry is stored once
    child_id: Mapped[int | None] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), nullable=True, index=True)
    reward_id: Mapped[int | None] = mapped_column(ForeignKey("family_rewards.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(80))   # as it was when asked for
    cost: Mapped[int] = mapped_column(Integer)       # as it was when asked for
    status: Mapped[str] = mapped_column(String(12), default="requested")  # requested | approved | declined
    requested_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Encouragement(Base):
    """A parent's high-five on one wash. Kept in the app only; nothing is sent to the station."""

    __tablename__ = "encouragements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wash_id: Mapped[str] = mapped_column(ForeignKey("washes.wash_id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16), default="high_five")
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("wash_id", "kind", name="uq_encouragement_wash_kind"),)


class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=True, index=True)
    recording_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    technique: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(16), default="unknown")
    start_ts: Mapped[float] = mapped_column(Float)
    end_ts: Mapped[float] = mapped_column(Float)
    annotator: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32), default="reference")  # reference | correction
    notes: Mapped[str] = mapped_column(Text, default="")
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
