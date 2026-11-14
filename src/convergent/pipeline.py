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
    score      = wash scorer (validated time per step -> finished / stars / points)
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

import numpy as np

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
from convergent.detection.pair_adapter import TemporalV2Adapter
from convergent.detection.pair_features import HandSlotter
from convergent.detection.registry import ModelRegistry
from convergent.detection.side_resolver import SideResolver
from convergent.detection.skia_adapter import SkiaLegacyAdapter, SkiaTemporalAdapter
from convergent.detection.yolo_adapter import YoloAdapter
from convergent.projection.calibration import load_profile
from convergent.projection.diagnostics import render_command_for_targets
from convergent.projection.mapping import ProjectionMapper
from convergent.regions.evidence import EvidenceAccumulator
from convergent.regions.foam import SoapDetector, SoapState
from convergent.regions.progress import ProgressState, ProgressTracker
from convergent.scoring.wash_score import WashScore, WashScorer
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
    score: WashScore | None = None  # live wash score, present on every frame
    soap: SoapState | None = None   # binary lather check (UI only, unvalidated heuristic)


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
    score: dict[str, Any] | None = None  # final WashScore (frozen at finish, else from released events)

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
        self.temporal_v2 = TemporalV2Adapter(cfg.temporal_v2, self.registry)
        self.fusion = FusionEngine(cfg.fusion, self.registry)
        self.aligner = PredictionAligner(cfg.fusion.alignment_tolerance_s, cfg.fusion.max_prediction_age_s)
        self.events = EventDetector(cfg.temporal, self.session_id)
        self.sides = SideResolver.from_config(cfg.side_resolver)
        sc = cfg.soap
        self.soap = SoapDetector(sc.min_value, sc.max_saturation, sc.on_threshold, sc.off_threshold, sc.min_s, sc.ema_s) if sc.enabled else None
        self.evidence = EvidenceAccumulator(cfg.regions)
        self.progress = ProgressTracker(self.session_id, self.evidence)
        self.scorer = WashScorer(cfg.scoring, self.session_id)
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
        # hand points of every frame (slotted like temporal_v2 sees them), saved as landmarks.npz so a
        # live run can be replayed through a newer model or labelled later
        self._land_slotter = HandSlotter()
        self._land_rows: list[tuple[float, np.ndarray, np.ndarray]] = []
        self._land_aspect = 4.0 / 3.0
        self._last_region_push = -1e9
        self._last_live_push = -1e9
        self._render_seq = 0
        self._stop_requested = False
        self.on_frame: Callable[[FrameResult], None] | None = None

    # ---- setup
    def load_models(self) -> dict[str, ArtifactStatus]:
        self.model_status = {}
        for adapter in (self.handhygiene, self.skia, self.skia_legacy, self.yolo, self.temporal_v2):
            st = adapter.load()
            self.model_status[adapter.model_id] = st
            log.info("model %-14s available=%-5s %s", adapter.model_id, st.available, st.message)
        self.model_status["side_resolver"] = self.sides.status()
        log.info("model %-14s available=%-5s %s", "side_resolver", self.sides.available, self.model_status["side_resolver"].message)
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
        self.temporal_v2.aspect = frame.width / float(frame.height) if frame.height else self.temporal_v2.aspect
        if self._results_fh is not None:
            self._record_landmarks(hands, frame)
        for adapter in (self.handhygiene, self.skia, self.skia_legacy, self.temporal_v2):
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
        seen = hands.hands + hands.unassigned  # a hand without a resolved left/right side is still a tracked hand
        quality = max([h.tracking_quality for h in seen], default=0.0)
        tracking_ok = len(seen) > 0
        if not tracking_ok and self.temporal_v2.holding(frame.capture_ts):
            # a dropout of a few frames while the hands keep moving: temporal_v2 still answers from its history
            tracking_ok, quality = True, self.temporal_v2.last_quality
        fused = self.fusion.combine(aligned, frame.capture_ts, tracking_ok=tracking_ok, frame_ids=[frame.frame_id])
        self._fused_counts[fused.status.value] = self._fused_counts.get(fused.status.value, 0) + 1
        if fused.canonical is not None:
            self.progress.observe_detection(fused.canonical.technique)
        self.evidence.observe_hands(hands)
        if fused.canonical is not None:
            self.sides.observe(hands, fused.canonical.technique, frame.capture_ts)
        new_events = self.sides.resolve_all(self.events.update(fused, quality))
        for ev in new_events:
            self.progress.add_event(ev)
        self.scorer.add_events(new_events)
        self._all_events.extend(new_events)
        score = self.scorer.update(frame.capture_ts, self.events.state.active, self.events.pending)
        soap = None
        if self.soap is not None:
            soap = self.soap.update(frame.image, hands.hands + hands.unassigned, frame.capture_ts)
            self.progress.soap_state = "detected" if soap.detected else ("seen" if soap.seen else "not_detected")
        targets =self.mapper.map_hands(hands, (frame.width, frame.height)) if self.mapper.ready else []
        frame.timestamps.processed_ts = monotonic()
        timing["total"] = (time.perf_counter() - t0) * 1000.0
        self._latency.append(timing["total"])
        progress = None
        if new_events or frame.frame_id % 30 == 0:
            progress = self.progress.snapshot(frame.capture_ts, self._candidate_dict())
        result = FrameResult(frame=frame.without_image(), hands=hands, branch_predictions=preds, fused=fused, events=new_events,
                             targets=targets, timing_ms=timing, progress=progress, score=score, soap=soap)
        self._sink(result)
        if self.on_frame:
            self.on_frame(result)
        return result

    def _record_landmarks(self, hands: TrackedHands, frame: FramePacket) -> None:
        if self._land_rows and hands.capture_ts <= self._land_rows[-1][0]:
            return
        found = sorted(hands.hands + hands.unassigned, key=lambda h: -h.tracking_quality)[:2]
        raw, pres = self._land_slotter.assign([h.landmark_array() for h in found], hands.capture_ts)
        self._land_rows.append((hands.capture_ts, raw.astype(np.float32), pres.astype(np.float32)))
        if frame.height:
            self._land_aspect = frame.width / float(frame.height)

    def _save_landmarks(self) -> None:
        if self._results_dir is None or len(self._land_rows) < 2:
            return
        from convergent.detection.pair_training import IGNORE_LABEL, RawRecording

        n = len(self._land_rows)
        rec = RawRecording(f"live_{self.session_id}", "live", "live", self.session_id,
                           np.stack([r[1] for r in self._land_rows]), np.stack([r[2] for r in self._land_rows]),
                           np.array([r[0] for r in self._land_rows], np.float64), np.full(n, IGNORE_LABEL),
                           self._land_aspect, self.source.source_id, float(self.cfg.source.target_fps), "live")
        rec.save(self._results_dir / "landmarks.npz")

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
                   "v2_top": _top_probs(r.branch_predictions.get("temporal_v2")),
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
            hz = self.cfg.backend.live_hz
            if hz > 0 and (r.events or r.frame.capture_ts - self._last_live_push >= 1.0 / hz):
                self._last_live_push = r.frame.capture_ts
                self._safe(lambda: self.backend.post_live(self.session_id, self.live_update(r)))  # type: ignore[union-attr]
        if self.gateway is not None and r.targets:
            self._render_seq = self.gateway.next_render_seq()
            self.gateway.send_render(render_command_for_targets(self._render_seq, r.targets, self.mapper.profile))

    def live_update(self, r: FrameResult) -> dict[str, Any]:
        """The `live` message body: what the game layer needs every few frames (see docs/GAMIFICATION_HANDOFF.md)."""
        c = r.fused.canonical
        return {"ts": r.frame.capture_ts, "frame_id": r.frame.frame_id, "hands": r.hands.num_hands,
                "fused": {"status": r.fused.status.value, "technique": None if c is None else c.technique,
                          "side": None if c is None else c.side.value, "confidence": r.fused.confidence},
                "active": self._candidate_dict(),
                "score": None if r.score is None else r.score.model_dump(mode="json"),
                "soap": None if r.soap is None else {"detected": r.soap.detected, "seen": r.soap.seen, "proxy": r.soap.proxy, "validated": False},
                "progress": None if r.progress is None else r.progress.model_dump(mode="json")}

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
    def stop(self) -> None:
        """Ask a running :meth:`run` to finish after the current frame (normal end: summary and score are saved)."""
        self._stop_requested = True

    def run(self, max_frames: int | None = None) -> RunSummary:
        self._stop_requested = False
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
                        sc = res.score
                        score_txt = "" if sc is None else (f" score: {sc.stars}* {sc.points}pts steps={sc.steps_done}/{sc.steps_required}"
                                                           f" total={sc.total_s:.1f}/{sc.total_min_s:.0f}s{' FINISHED' if sc.finished else ''}")
                        log.info("live: frames=%d fps=%.1f hands=%d fused=%s%s events=%d tracker=%.0fms%s",
                                 frames, fps, res.hands.num_hands, label, conf, len(self._all_events), res.timing_ms.get("tracker", 0.0), score_txt)
                    if max_frames is not None and frames >= max_frames:
                        break
                    if self._stop_requested:
                        break
                    if isinstance(self.source, NetworkSource) and self.source.queue.closed:
                        break
        except KeyboardInterrupt:
            # Ctrl+C ends the run like a normal stop so the summary, score and session end are still saved.
            log.info("stopped by user after %d frames", frames)
        finally:
            tail = self.sides.resolve_all(self.events.flush(last_ts))
            for ev in tail:
                self.progress.add_event(ev)
            self.scorer.add_events(tail)
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
        score = self.scorer.final(last_ts).model_dump(mode="json")
        summary = RunSummary(session_id=self.session_id, source_id=self.source.source_id, frames=frames, duration_s=monotonic() - started,
                             events=list(self._all_events), model_status={k: v.as_dict() for k, v in self.model_status.items()},
                             source_stats=self.source.stats.as_dict(), latency=LatencyStats.from_samples(self._latency).__dict__,
                             resources=mon.summary(), backend={} if self.backend is None else self.backend.stats.__dict__ | {"session": self.session_id},
                             progress=progress.model_dump(mode="json"), results_dir=None if self._results_dir is None else str(self._results_dir),
                             fused_counts=dict(self._fused_counts), dropped_frames=self.source.stats.frames_dropped_queue, score=score)
        if self.backend is not None:
            self._safe(lambda: self.backend.end_session(self.session_id, {"frames": frames, "events": len(self._all_events), "latency": summary.latency,  # type: ignore[union-attr]
                                                                           "source": summary.source_stats, "fused_counts": summary.fused_counts,
                                                                           "wash_score": score, "ended_at": utc_now_iso()}))
        if self._results_fh is not None:
            self._results_fh.close()
            self._save_landmarks()
            (self._results_dir / "summary.json").write_text(summary.to_json(), encoding="utf-8")  # type: ignore[operator]
            (self._results_dir / "events.json").write_text(json.dumps([e.model_dump(mode="json") for e in self._all_events], indent=2), encoding="utf-8")  # type: ignore[operator]
        return summary

    def close(self) -> None:
        self.tracker.close()
        if self.backend is not None:
            self.backend.close()


def _top_probs(p: ModelPrediction | None, k: int = 3) -> list[list[Any]] | None:
    """The model's top ``k`` native labels with probabilities (``none`` included), for diagnosing live runs."""
    if p is None or not p.probabilities:
        return None
    top = sorted(p.probabilities.items(), key=lambda kv: -kv[1])[:k]
    return [[n, round(float(v), 3)] for n, v in top]
