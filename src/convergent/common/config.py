"""Typed configuration.

Configuration is layered: ``configs/*.yaml`` (committed, no secrets) + environment
variables / ``.env`` (secrets such as the backend token, DB URL). No local paths are
hard-coded; all paths are relative to the repository root or overridden by env/CLI.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    env = os.environ.get("CONVERGENT_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceConfig(_Cfg):
    kind: Literal["video", "webcam", "network", "synthetic"] = "synthetic"
    path: str | None = None
    device_index: int = 0
    width: int = 640
    height: int = 480
    target_fps: float = 15.0
    rotation_deg: int = 0
    loop: bool = False
    max_frames: int | None = None
    synthetic_pattern: Literal["moving_hands", "blank", "noise"] = "moving_hands"
    synthetic_seed: int = 0


class TrackerConfig(_Cfg):
    backend: Literal["auto", "tasks", "solutions", "null"] = "auto"
    task_model_path: str = "models/mediapipe/hand_landmarker.task"
    num_hands: int = 2
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    min_presence_confidence: float = 0.5
    model_complexity: int = 1
    # MediaPipe reports handedness assuming a mirrored (selfie) image. Our faucet camera
    # produces a NON-mirrored image, so by default the raw label is swapped to obtain the
    # anatomical side. Verify on hardware (docs/MODEL_INTEGRATION.md "Handedness").
    swap_handedness: bool = True
    identity_max_jump: float = 0.35  # normalized distance for track association
    identity_max_gap_s: float = 0.5
    handedness_trust_threshold: float = 0.8
    partial_visibility_margin: float = 0.02


class HandHygieneConfig(_Cfg):
    enabled: bool = True
    model_path: str = "models/handhygiene/rf_10102024.numpy-forest.npz"
    sha256: str | None = None
    unknown_threshold: float = 0.4  # upstream: max(prob) < 0.4 -> "no step"
    feed_mode: Literal["raw_label", "anatomical"] = "raw_label"
    legacy_vote_buffer: int = 0  # 0 disables upstream 15-frame majority vote (we do temporal validation downstream)


class SkiaConfig(_Cfg):
    enabled: bool = True
    mode: Literal["temporal", "legacy", "both"] = "temporal"
    temporal_artifact_dir: str = "models/skia_temporal/current"
    legacy_model_path: str = "models/skia_legacy/generalized_lstm_model.keras"
    legacy_stats_path: str = "models/skia_legacy/legacy_scaler_stats.npz"
    window_frames: int = 16
    stride_frames: int = 1
    max_gap_s: float = 0.25
    unknown_threshold: float = 0.4
    feed_mode: Literal["raw_label", "anatomical"] = "raw_label"


class YoloConfig(_Cfg):
    enabled: bool = True
    weights_path: str = "models/yolo/handwash_yolov5.pt"
    sha256: str | None = None
    yolov5_repo_dir: str = "third_party/yolov5"
    img_size: int = 640
    conf_threshold: float = 0.25
    iou_threshold: float = 0.45
    every_n_frames: int = 3
    device: str = "cpu"


class FusionConfig(_Cfg):
    method: Literal["reliability_weighted", "meta"] = "reliability_weighted"
    weights: dict[str, float] = Field(
        default_factory=lambda: {"handhygiene": 1.0, "skia_temporal": 1.0, "yolo": 1.0}
    )
    unknown_threshold: float = 0.45
    contradiction_margin: float = 0.15
    alignment_tolerance_s: float = 0.25
    max_prediction_age_s: float = 0.6
    min_branches: int = 1
    require_tracking: bool = True
    meta_model_path: str | None = None


class TemporalConfig(_Cfg):
    enter_confidence: float = 0.6
    exit_confidence: float = 0.4
    min_duration_s: float = 1.0
    max_gap_s: float = 0.5
    min_tracking_quality: float = 0.3
    merge_gap_s: float = 0.75
    duplicate_window_s: float = 1.0
    max_event_duration_s: float = 60.0


class RegionsConfig(_Cfg):
    min_sufficient_duration_s: float = 3.0
    partial_visibility_weight: float = 0.5
    use_unresolved_side_evidence: bool = False


class SmoothingConfig(_Cfg):
    method: Literal["ema", "one_euro", "none"] = "one_euro"
    ema_alpha: float = 0.4
    one_euro_min_cutoff: float = 1.5
    one_euro_beta: float = 0.05
    one_euro_d_cutoff: float = 1.0
    max_prediction_horizon_s: float = 0.1
    reset_gap_s: float = 0.5


class ProjectorConfig(_Cfg):
    logical_width: int = 854
    logical_height: int = 480
    profile_path: str | None = "models/calibration/active_profile.json"
    smoothing: SmoothingConfig = Field(default_factory=SmoothingConfig)
    anchors: list[str] = Field(default_factory=lambda: ["hand_centroid", "fingertips"])
    test_tolerance_px: float = 2.0


class BackendClientConfig(_Cfg):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8000"
    timeout_s: float = 5.0
    batch_size: int = 32


class PipelineConfig(_Cfg):
    source: SourceConfig = Field(default_factory=SourceConfig)
    tracker: TrackerConfig = Field(default_factory=TrackerConfig)
    handhygiene: HandHygieneConfig = Field(default_factory=HandHygieneConfig)
    skia: SkiaConfig = Field(default_factory=SkiaConfig)
    yolo: YoloConfig = Field(default_factory=YoloConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    temporal: TemporalConfig = Field(default_factory=TemporalConfig)
    regions: RegionsConfig = Field(default_factory=RegionsConfig)
    projector: ProjectorConfig = Field(default_factory=ProjectorConfig)
    backend: BackendClientConfig = Field(default_factory=BackendClientConfig)
    labels_path: str = "configs/labels.yaml"
    models_registry_path: str = "configs/models.yaml"
    queue_size: int = 4
    device_id: str = "laptop-dev"
    results_dir: str = "runs"
    live_status_every_s: float = 2.0  # log a one-line status this often while running (0 = off)

    @classmethod
    def load(cls, path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> PipelineConfig:
        data: dict[str, Any] = {}
        if path is not None:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        if overrides:
            data = _deep_merge(data, overrides)
        return cls.model_validate(data)


def _deep_merge(base: dict[str, Any], upd: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings(BaseSettings):
    """Environment-driven settings (secrets live here, never in YAML)."""

    model_config = SettingsConfigDict(env_prefix="CONVERGENT_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./convergent_dev.db"
    api_token: str = ""  # empty => backend refuses write requests
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_max_bytes: int = 5_000_000
    log_backup_count: int = 5
    allow_unauthenticated_reads: bool = True
    retain_raw_video: bool = False

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def load_settings() -> Settings:
    return Settings()


def resolve_path(p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else repo_root() / path
