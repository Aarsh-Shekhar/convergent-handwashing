"""Executable orchestration pipeline: one input source, one shared output contract.

Per frame::

    frame      = source.read()
    hands      = tracker.detect(frame)                      # shared MediaPipe (once per frame)
    spatial    = handhygiene.predict(hands)                 # Repo A branch
    temporal   = skia.predict(hands)                        # Repo B branch (sequence buffer inside)
    visual     = yolo.predict(frame)   [every N frames, optionally in a worker thread]
    fused      = fusion.combine(aligned branch predictions)
    events     = event_detector.update(fused, tracking_quality)
    progress   = region tracker (events -> region evidence -> progress state)
    targets    = projection_mapper.map_hands(hands)
    sinks      -> results files, backend, device renderer

Missing models never participate in fusion; their status is recorded on the session. Buffers
are bounded (latest-frame queues, fixed sequence window, capped prediction history).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from convergent.backend.client import BackendClient, BackendError
from convergent.common.config import PipelineConfig, Settings, load_settings, resolve_path
from convergent.common.logging import get_logger
from convergent.common.timestamps import monotonic, utc_now_iso
from convergent.common.types import (
    CalibrationProfile,
    FramePacket,
    GestureEvent,
    ModelPrediction,
    PredictionStatus,
    ProjectionTarget,
    TrackedHands,
)
from convergent.communication.websocket import DeviceGateway
from convergent.detection.base import ArtifactStatus
from convergent.detection.evaluation import LatencyStats, ResourceMonitor
from convergent.detection.event_detector import EventDetector
from convergent.detection.fusion import FusionEngine, PredictionAligner
from convergent.detection.handhygiene_adapter import HandHygieneAdapter
from convergent.detection.labels import LabelRegistry
from convergent.detection.registry import ModelRegistry
from convergent.detection.skia_adapter import SkiaLegacyAdapter, SkiaTemporalAdapter
from convergent.detection.yolo_adapter import YoloAdapter
from convergent.projection.calibration import load_profile
from convergent.projection.diagnostics import render_command_for_targets
from convergent.projection.mapping import ProjectionMapper
from convergent.regions.evidence import EvidenceAccumulator
from convergent.regions.progress import ProgressState, ProgressTracker
from convergent.vision.hand_tracker import HandTracker
from convergent.vision.sources import FrameSource, NetworkSource, create_source

log = get_logger(__name__)


@dataclass
class FrameResult:
    frame: FramePacket
    hands: TrackedHands
    branch_predictions: dict[str, ModelPrediction]
    fused: ModelPrediction
    events: list[GestureEvent]
    targets: list[ProjectionTarget]
    timing_ms: dict[str, float]
    progress: ProgressState | None = None


@dataclass
class RunSummary:
    session_id: str
    source_id: str
    frames: int
    duration_s: float
    events: list[GestureEvent]
    model_status: dict[str, dict[str, Any]]
    source_stats: dict[str, Any]
    latency: dict[str, Any]
    resources: dict[str, Any]
    backend: dict[str, Any]
    progress: dict[str, Any] | None
    results_dir: str | None
    fused_counts: dict[str, int] = field(default_factory=dict)
    dropped_frames: int = 0

    def to_json(self) -> str:
        d = self.__dict__.copy()
        d["events"] = [e.model_dump(mode="json") for e in self.events]
        return json.dumps(d, indent=2, default=str)


class Pipeline:
    def __init__(self, cfg: PipelineConfig, source: FrameSource | None = None, tracker: HandTracker | None = None,
                 backend_client: BackendClient | None = None, gateway: DeviceGateway | None = None, settings: Settings | None = None,
                 registry: LabelRegistry | None = None, deterministic: bool = True, save_results: bool = False,
                 calibration: CalibrationProfile | None = None) -> None:
        self.cfg = cfg
        self.settings = settings or load_settings()
        self.registry = registry or LabelRegistry.load(cfg.labels_path)
        self.model_registry = ModelRegistry.load(cfg.models_registry_path)
        self.source = source or create_source(cfg.source)
        self.session_id = self.source.session_id
        self.tracker = tracker or HandTracker(cfg.tracker)
        self.handhygiene = HandHygieneAdapter(cfg.handhygiene, self.registry)
        self.skia = SkiaTemporalAdapter(cfg.skia, self.registry)
        self.skia_legacy = SkiaLegacyAdapter(cfg.skia, self.registry)
        self.yolo = YoloAdapter(cfg.yolo, self.registry, self.model_registry)
        self.fusion = FusionEngine(cfg.fusion, self.registry)
        self.aligner = PredictionAligner(cfg.fusion.alignment_tolerance_s, cfg.fusion.max_prediction_age_s)
        self.events = EventDetector(cfg.temporal, self.session_id)
        self.evidence = EvidenceAccumulator(cfg.regions)
        self.progress = ProgressTracker(self.session_id, self.evidence)
        profile = calibration
        if profile is None and cfg.projector.profile_path and resolve_path(cfg.projector.profile_path).exists():
            try:
                profile = load_profile(resolve_path(cfg.projector.profile_path))
            except Exception as exc:  # noqa: BLE001
                log.warning("calibration profile unreadable: %s", exc)
        self.mapper = ProjectionMapper(profile, cfg.projector)
        self.backend = backend_client
        self.gateway = gateway
        self.deterministic = deterministic
        self.save_results = save_results
        self.model_status: dict[str, ArtifactStatus] = {}
        self._yolo_pool: ThreadPoolExecutor | None = None
        self._yolo_future: Future[ModelPrediction] | None = None
        self._pending_predictions: list[ModelPrediction] = []
        self._all_events: list[GestureEvent] = []
        self._latency: list[float] = []
        self._fused_counts: dict[str, int] = {}
        self._results_dir: Path | None = None
        self._results_fh = None
        self._last_region_push = -1e9
        self._render_seq = 0
        self.on_frame: Callable[[FrameResult], None] | None = None

    # ---- setup
    def load_models(self) -> dict[str, ArtifactStatus]:
        self.model_status = {}
        for adapter in (self.handhygiene, self.skia, self.skia_legacy, self.yolo):
            st = adapter.load()
            self.model_status[adapter.model_id] = st
            log.info("model %-14s available=%-5s %s", adapter.model_id, st.available, st.message)
        if self.yolo.available and not self.deterministic:
            self._yolo_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yolo")
        return self.model_status

    def model_versions(self) -> dict[str, Any]:
        return {k: {"version": v.version, "available": v.available, "preprocessing": v.preprocessing_version, "sha256": v.sha256}
                for k, v in self.model_status.items()} | {"fusion": self.fusion.model_version, "tracker": f"{self.tracker.tracker_id}:{self.tracker.backend.version}"}

    # ---- per-frame
    def process_frame(self, frame: FramePacket) -> FrameResult:
        t0 = time.perf_counter()
        timing: dict[str, float] = {}
        hands = self.tracker.detect(frame)
        timing["tracker"] = hands.processing_time_ms
        preds: dict[str, ModelPrediction] = {}
        for adapter in (self.handhygiene, self.skia, self.skia_legacy):
            if adapter.available:
                p = adapter.predict(hands)  # type: ignore[attr-defined]
                preds[adapter.model_id] = p
                timing[adapter.model_id] = p.processing_time_ms
        if self.yolo.available and self.yolo.should_run(frame.frame_id):
            if self._yolo_pool is None:
                preds["yolo"] = self.yolo.predict(frame)
            elif self._yolo_future is None or self._yolo_future.done():
                if self._yolo_future is not None:
                    preds["yolo"] = self._yolo_future.result()
                self._yolo_future = self._yolo_pool.submit(self.yolo.predict, frame.without_image().model_copy(update={"image": frame.image}))
        elif self._yolo_future is not None and self._yolo_future.done():
            preds["yolo"] = self._yolo_future.result()
            self._yolo_future = None
        for p in preds.values():
            if p.status != PredictionStatus.NO_INPUT:
                self.aligner.offer(p)
        aligned = self.aligner.collect(frame.capture_ts)
        quality = max([h.tracking_quality for h in hands.hands], default=0.0)
        fused = self.fusion.combine(aligned, frame.capture_ts, tracking_ok=hands.num_hands > 0, frame_ids=[frame.frame_id])
        self._fused_counts[fused.status.value] = self._fused_counts.get(fused.status.value, 0) + 1
        if fused.canonical is not None:
            self.progress.observe_detection(fused.canonical.technique)
        self.evidence.observe_hands(hands)
        new_events = self.events.update(fused, quality)
        for ev in new_events:
            self.progress.add_event(ev)
        self._all_events.extend(new_events)
        targets = self.mapper.map_hands(hands, (frame.width, frame.height)) if self.mapper.ready else []
        frame.timestamps.processed_ts = monotonic()
        timing["total"] = (time.perf_counter() - t0) * 1000.0
        self._latency.append(timing["total"])
        progress = None
        if new_events or frame.frame_id % 30 == 0:
            progress = self.progress.snapshot(frame.capture_ts, self._candidate_dict())
        result = FrameResult(frame=frame.without_image(), hands=hands, branch_predictions=preds, fused=fused, events=new_events,
                             targets=targets, timing_ms=timing, progress=progress)
        self._sink(result)
        if self.on_frame:
            self.on_frame(result)
        return result

    def _candidate_dict(self) -> dict[str, Any] | None:
        c = self.events.state.active
        return None if c is None else {"technique": c.technique, "side": c.side.value, "start_ts": c.start_ts, "supported_s": c.supported_s, "validated": c.validated}

    # ---- sinks
    def _sink(self, r: FrameResult) -> None:
        if self._results_fh is not None:
            rec = {"frame_id": r.frame.frame_id, "ts": r.frame.capture_ts, "hands": r.hands.num_hands,
                   "fused": {"status": r.fused.status.value, "label": r.fused.native_label, "confidence": r.fused.confidence,
                             "participating": r.fused.extras.get("participating", [])},
                   "branches": {k: {"status": p.status.value, "label": p.native_label, "conf": p.confidence} for k, p in r.branch_predictions.items()},
                   "events": [e.event_id for e in r.events], "targets": sum(1 for t in r.targets if t.valid), "timing_ms": r.timing_ms}
            self._results_fh.write(json.dumps(rec) + "\n")
        if self.backend is not None:
            self._pending_predictions.append(r.fused)
            self._pending_predictions.extend(p for p in r.branch_predictions.values() if p.status in (PredictionStatus.VALID, PredictionStatus.UNKNOWN))
            if len(self._pending_predictions) >= self.cfg.backend.batch_size:
                self._flush_predictions()
            if r.events:
                self._safe(lambda: self.backend.post_events(self.session_id, r.events))  # type: ignore[union-attr]
            if r.events or r.frame.capture_ts - self._last_region_push >= 5.0:
                self._last_region_push = r.frame.capture_ts
                self._safe(lambda: self.backend.post_regions(self.session_id, r.frame.capture_ts, self.evidence.evidence()))  # type: ignore[union-attr]
        if self.gateway is not None and r.targets:
            self._render_seq = self.gateway.next_render_seq()
            self.gateway.send_render(render_command_for_targets(self._render_seq, r.targets, self.mapper.profile))

    def _flush_predictions(self) -> None:
        if self.backend is None or not self._pending_predictions:
            return
        batch, self._pending_predictions = self._pending_predictions[:500], self._pending_predictions[500:]
        self._safe(lambda: self.backend.post_predictions(self.session_id, batch))  # type: ignore[union-attr]

    def _safe(self, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except BackendError as exc:
            log.warning("backend write failed (continuing): %s", exc)

    # ---- run
    def run(self, max_frames: int | None = None) -> RunSummary:
        if not self.model_status:
            self.load_models()
        mon = ResourceMonitor()
        started = monotonic()
        if self.save_results:
            self._results_dir = resolve_path(self.cfg.results_dir) / self.session_id
            self._results_dir.mkdir(parents=True, exist_ok=True)
            self._results_fh = open(self._results_dir / "frames.jsonl", "w", encoding="utf-8")  # noqa: SIM115
        if self.backend is not None:
            self._safe(lambda: self.backend.create_session(  # type: ignore[union-attr]
                self.session_id, self.source.source_id, self.cfg.source.width, self.cfg.source.height, self.cfg.source.target_fps,
                self.cfg.device_id, self.cfg.model_dump(mode="json"), self.model_versions(), "video_pts" if self.cfg.source.kind == "video" else "source_monotonic",
                self.mapper.profile.profile_id if self.mapper.profile else None, False, None))
        frames = 0
        last_ts = 0.0
        status_every = float(self.cfg.live_status_every_s)
        next_status = monotonic() + status_every if status_every > 0 else None
        window_frames, window_t0 = 0, monotonic()
        try:
            with self.source:
                for frame in self.source:
                    res = self.process_frame(frame)
                    frames += 1
                    window_frames += 1
                    last_ts = frame.capture_ts
                    if frames % 15 == 0:
                        mon.sample()
                    if next_status is not None and monotonic() >= next_status:
                        now = monotonic()
                        fps = window_frames / max(now - window_t0, 1e-6)
                        window_frames, window_t0, next_status = 0, now, now + status_every
                        label = res.fused.native_label or res.fused.status.value
                        conf = f" ({res.fused.confidence:.2f})" if res.fused.confidence is not None else ""
                        log.info("live: frames=%d fps=%.1f hands=%d fused=%s%s events=%d tracker=%.0fms",
                                 frames, fps, res.hands.num_hands, label, conf, len(self._all_events), res.timing_ms.get("tracker", 0.0))
                    if max_frames is not None and frames >= max_frames:
                        break
                    if isinstance(self.source, NetworkSource) and self.source.queue.closed:
                        break
        finally:
            tail = self.events.flush(last_ts)
            for ev in tail:
                self.progress.add_event(ev)
            self._all_events.extend(tail)
            if self.backend is not None:
                if tail:
                    self._safe(lambda: self.backend.post_events(self.session_id, tail))  # type: ignore[union-attr]
                self._flush_predictions()
                self._safe(lambda: self.backend.post_regions(self.session_id, last_ts, self.evidence.evidence()))  # type: ignore[union-attr]
            if self._yolo_pool is not None:
                self._yolo_pool.shutdown(wait=True)
            mon.sample()
        progress = self.progress.snapshot(last_ts, None)
        summary = RunSummary(session_id=self.session_id, source_id=self.source.source_id, frames=frames, duration_s=monotonic() - started,
                             events=list(self._all_events), model_status={k: v.as_dict() for k, v in self.model_status.items()},
                             source_stats=self.source.stats.as_dict(), latency=LatencyStats.from_samples(self._latency).__dict__,
                             resources=mon.summary(), backend={} if self.backend is None else self.backend.stats.__dict__ | {"session": self.session_id},
                             progress=progress.model_dump(mode="json"), results_dir=None if self._results_dir is None else str(self._results_dir),
                             fused_counts=dict(self._fused_counts), dropped_frames=self.source.stats.frames_dropped_queue)
        if self.backend is not None:
            self._safe(lambda: self.backend.end_session(self.session_id, {"frames": frames, "events": len(self._all_events), "latency": summary.latency,  # type: ignore[union-attr]
                                                                           "source": summary.source_stats, "fused_counts": summary.fused_counts,
                                                                           "ended_at": utc_now_iso()}))
        if self._results_fh is not None:
            self._results_fh.close()
            (self._results_dir / "summary.json").write_text(summary.to_json(), encoding="utf-8")  # type: ignore[operator]
            (self._results_dir / "events.json").write_text(json.dumps([e.model_dump(mode="json") for e in self._all_events], indent=2), encoding="utf-8")  # type: ignore[operator]
        return summary

    def close(self) -> None:
        self.tracker.close()
        if self.backend is not None:
            self.backend.close()
