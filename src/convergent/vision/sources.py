"""Frame sources: prerecorded video, local webcam, network stream (Pi), synthetic.

Every source yields :class:`FramePacket` objects with the pixel data attached and with
``timestamps.capture_ts`` on the source clock (see ``common.types``). The rest of the
pipeline never knows which source produced a frame.

Determinism: ``VideoFileSource`` and ``SyntheticSource`` are deterministic – running them
twice yields identical frame ids, timestamps and pixels. Decimation to ``target_fps`` is
done on *capture timestamps*, never on wall-clock time.
"""

from __future__ import annotations

import math
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from convergent.common.config import SourceConfig
from convergent.common.logging import get_logger
from convergent.common.timestamps import OrderGuard, monotonic
from convergent.common.types import (
    ColorFormat,
    FramePacket,
    FrameTimestamps,
    new_id,
)
from convergent.vision.preprocessing import FramePreprocessor

log = get_logger(__name__)


class SourceError(RuntimeError):
    pass


@dataclass
class SourceStats:
    frames_emitted: int = 0
    frames_skipped_decimation: int = 0
    frames_dropped_queue: int = 0
    frames_rejected_order: int = 0
    decode_failures: int = 0
    reconnects: int = 0
    last_capture_ts: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class FrameSource(ABC):
    """Abstract image source.

    Usage::

        with source:
            for packet in source:
                ...
    """

    def __init__(self, config: SourceConfig, session_id: str | None = None) -> None:
        self.config = config
        self.session_id = session_id or new_id("ses_")
        self.stats = SourceStats()
        self.preprocessor = FramePreprocessor(
            target_width=config.width, target_height=config.height, rotation_deg=config.rotation_deg
        )
        self._frame_id = 0
        self._next_emit_ts: float | None = None
        self._first_ts = 0.0
        self._emit_count = 0
        self._order = OrderGuard()
        self._opened = False

    # ---- lifecycle
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def _read_raw(self) -> tuple[np.ndarray, float, int, str] | None:
        """Return (bgr_image, capture_ts, source_frame_index, capture_clock) or None at end."""

    @property
    @abstractmethod
    def source_id(self) -> str: ...

    def __enter__(self) -> FrameSource:
        self.open()
        self._opened = True
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
        self._opened = False

    def __iter__(self) -> Iterator[FramePacket]:
        while True:
            pkt = self.read()
            if pkt is None:
                return
            yield pkt

    # ---- main entry
    def read(self) -> FramePacket | None:
        if self.config.max_frames is not None and self.stats.frames_emitted >= self.config.max_frames:
            return None
        while True:
            raw = self._read_raw()
            if raw is None:
                return None
            image, capture_ts, src_index, clock = raw
            if not self._should_emit(capture_ts):
                self.stats.frames_skipped_decimation += 1
                continue
            if not self._order.accept(self._frame_id, capture_ts):
                self.stats.frames_rejected_order += 1
                log.warning("rejecting out-of-order frame idx=%s ts=%.4f", src_index, capture_ts)
                continue
            packet = self._build_packet(image, capture_ts, src_index, clock)
            self._frame_id += 1
            self.stats.frames_emitted += 1
            self.stats.last_capture_ts = capture_ts
            return packet

    def _should_emit(self, capture_ts: float) -> bool:
        fps = self.config.target_fps
        if fps is None or fps <= 0:
            return True
        period = 1.0 / fps
        eps = 1e-6
        if self._next_emit_ts is None:
            self._first_ts = capture_ts
            self._emit_count = 1
            self._next_emit_ts = capture_ts + period
            return True
        if capture_ts + eps >= self._next_emit_ts:
            # anchor on the first timestamp (no float accumulation); skip whole periods after a stall
            self._emit_count = math.floor((capture_ts - self._first_ts + eps) / period) + 1
            self._next_emit_ts = self._first_ts + self._emit_count * period
            return True
        return False

    def _build_packet(self, image: np.ndarray, capture_ts: float, src_index: int, clock: str) -> FramePacket:
        proc, transform = self.preprocessor.apply(image)
        return FramePacket(
            frame_id=self._frame_id,
            session_id=self.session_id,
            timestamps=FrameTimestamps(capture_ts=capture_ts, arrival_ts=monotonic(), capture_clock=clock),
            width=proc.shape[1],
            height=proc.shape[0],
            color_format=ColorFormat.BGR,
            source_id=self.source_id,
            source_frame_index=src_index,
            transform=transform,
            image=proc,
        )


# --------------------------------------------------------------------------- video file
class VideoFileSource(FrameSource):
    """Prerecorded MP4 (or any OpenCV-decodable file).

    Capture timestamps come from the decoder's presentation timestamps (``CAP_PROP_POS_MSEC``)
    when the backend reports them monotonically; otherwise they fall back to
    ``frame_index / fps``. Both are deterministic across runs.
    """

    def __init__(self, config: SourceConfig, session_id: str | None = None) -> None:
        super().__init__(config, session_id)
        if not config.path:
            raise SourceError("video source requires `path`")
        self.path = Path(config.path)
        self._cap: cv2.VideoCapture | None = None
        self._index = -1
        self._fps = 0.0
        self._use_pts = True
        self._last_pts = -1.0
        self._first_pts: float | None = None

    @property
    def source_id(self) -> str:
        return f"video:{self.path.name}"

    def open(self) -> None:
        if not self.path.exists():
            raise SourceError(f"video file not found: {self.path}")
        self._cap = cv2.VideoCapture(str(self.path))
        if not self._cap.isOpened():
            raise SourceError(f"could not open video: {self.path}")
        self._fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if self._fps <= 0 or not math.isfinite(self._fps):
            log.warning("video reports no FPS; assuming 30 for fallback timestamps")
            self._fps = 30.0
        self._index = -1
        self._last_pts = -1.0
        self._first_pts = None
        self._use_pts = True

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _read_raw(self) -> tuple[np.ndarray, float, int, str] | None:
        assert self._cap is not None, "source not opened"
        while True:
            ok, frame = self._cap.read()
            if not ok or frame is None:
                if self.config.loop and self._index >= 0:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.stats.reconnects += 1
                    # keep timestamps monotonic across loops
                    offset = (self._index + 1) / self._fps
                    self._first_pts = (self._first_pts or 0.0) - offset
                    continue
                return None
            self._index += 1
            pts_ms = float(self._cap.get(cv2.CAP_PROP_POS_MSEC))
            if self._use_pts:
                if pts_ms <= self._last_pts and self._index > 0:
                    # backend not reporting monotonic PTS -> switch to index/fps for the whole run
                    log.warning("non-monotonic PTS from decoder; using frame_index/fps timestamps")
                    self._use_pts = False
                else:
                    self._last_pts = pts_ms
            if self._use_pts:
                ts = pts_ms / 1000.0
                if self._first_pts is None:
                    self._first_pts = ts
                ts -= self._first_pts
                clock = "video_pts"
            else:
                ts = self._index / self._fps
                clock = "video_index"
            return frame, ts, self._index, clock


# --------------------------------------------------------------------------- webcam
class WebcamSource(FrameSource):
    """Local webcam for development. Capture timestamps are the laptop monotonic clock."""

    def __init__(self, config: SourceConfig, session_id: str | None = None) -> None:
        super().__init__(config, session_id)
        self._cap: cv2.VideoCapture | None = None
        self._index = -1

    @property
    def source_id(self) -> str:
        return f"webcam:{self.config.device_index}"

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.config.device_index)
        if not self._cap.isOpened():
            raise SourceError(f"could not open webcam index {self.config.device_index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _read_raw(self) -> tuple[np.ndarray, float, int, str] | None:
        assert self._cap is not None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            self.stats.decode_failures += 1
            return None
        self._index += 1
        return frame, monotonic(), self._index, "laptop_monotonic"


# --------------------------------------------------------------------------- synthetic
class SyntheticSource(FrameSource):
    """Deterministic frames for tests. ``moving_hands`` draws two hand-like blobs moving on
    a fixed trajectory; pixels depend only on (seed, frame index)."""

    def __init__(self, config: SourceConfig, session_id: str | None = None) -> None:
        super().__init__(config, session_id)
        self._index = -1
        self._rng = np.random.default_rng(config.synthetic_seed)
        self._fps = 30.0

    @property
    def source_id(self) -> str:
        return f"synthetic:{self.config.synthetic_pattern}:{self.config.synthetic_seed}"

    def open(self) -> None:
        self._index = -1
        self._rng = np.random.default_rng(self.config.synthetic_seed)

    def close(self) -> None:
        pass

    def _read_raw(self) -> tuple[np.ndarray, float, int, str] | None:
        total = self.config.max_frames
        if total is not None and self._index + 1 >= total * max(1, int(round(self._fps / max(self.config.target_fps, 1e-6)))):
            return None
        self._index += 1
        w, h = self.config.width, self.config.height
        if self.config.synthetic_pattern == "blank":
            img = np.full((h, w, 3), 32, dtype=np.uint8)
        elif self.config.synthetic_pattern == "noise":
            rng = np.random.default_rng(self.config.synthetic_seed * 7919 + self._index)
            img = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
        else:
            img = np.full((h, w, 3), 40, dtype=np.uint8)
            t = self._index / self._fps
            cx = int(w * (0.5 + 0.25 * math.sin(t * 1.5)))
            cy = int(h * (0.55 + 0.1 * math.cos(t * 1.1)))
            cv2.circle(img, (cx - w // 6, cy), w // 10, (120, 160, 210), -1)
            cv2.circle(img, (cx + w // 6, cy), w // 10, (110, 150, 200), -1)
            cv2.putText(img, f"{self._index}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        return img, self._index / self._fps, self._index, "synthetic"


# --------------------------------------------------------------------------- queues
class LatestFrameQueue:
    """Thread-safe bounded queue with a latest-frame policy.

    When full, the *oldest* item is discarded and counted so that latency never grows
    unboundedly if the consumer (inference) is slower than the producer.
    """

    def __init__(self, maxsize: int = 4) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._dq: deque[Any] = deque()
        self.maxsize = maxsize
        self._cv = threading.Condition()
        self.dropped = 0
        self._closed = False

    def put(self, item: Any) -> None:
        with self._cv:
            if len(self._dq) >= self.maxsize:
                self._dq.popleft()
                self.dropped += 1
            self._dq.append(item)
            self._cv.notify()

    def get(self, timeout: float | None = None) -> Any | None:
        with self._cv:
            end = None if timeout is None else time.monotonic() + timeout
            while not self._dq and not self._closed:
                remaining = None if end is None else end - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._cv.wait(remaining)
            if not self._dq:
                return None
            return self._dq.popleft()

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    @property
    def closed(self) -> bool:
        return self._closed

    def __len__(self) -> int:
        with self._cv:
            return len(self._dq)


# --------------------------------------------------------------------------- network
@dataclass
class NetworkFrame:
    """Decoded frame pushed by the communication layer into a :class:`NetworkSource`."""

    image: np.ndarray
    device_ts: float
    frame_index: int
    device_session_id: str = ""
    arrival_ts: float = field(default_factory=monotonic)


class NetworkSource(FrameSource):
    """Frames arriving from the Raspberry Pi agent through the WebSocket gateway.

    The gateway decodes JPEG payloads and calls :meth:`push`. ``capture_ts`` is the Pi's
    monotonic clock; a :class:`ClockOffsetEstimator` upstream provides latency diagnostics.
    """

    def __init__(self, config: SourceConfig, session_id: str | None = None, queue_size: int = 4, read_timeout_s: float = 5.0) -> None:
        super().__init__(config, session_id)
        self.queue = LatestFrameQueue(queue_size)
        self.read_timeout_s = read_timeout_s
        self._device_id = "pi"
        self.disconnects = 0

    @property
    def source_id(self) -> str:
        return f"network:{self._device_id}"

    def set_device_id(self, device_id: str) -> None:
        self._device_id = device_id

    def open(self) -> None:
        pass

    def close(self) -> None:
        self.queue.close()

    def push(self, frame: NetworkFrame) -> None:
        self.queue.put(frame)

    def on_disconnect(self) -> None:
        self.disconnects += 1
        self.stats.reconnects += 1
        self._order.reset()  # device may restart its frame counter / clock

    def _read_raw(self) -> tuple[np.ndarray, float, int, str] | None:
        item = self.queue.get(timeout=self.read_timeout_s)
        self.stats.frames_dropped_queue = self.queue.dropped
        if item is None:
            return None
        return item.image, item.device_ts, item.frame_index, "source_monotonic"


# --------------------------------------------------------------------------- factory
def create_source(config: SourceConfig, session_id: str | None = None) -> FrameSource:
    if config.kind == "video":
        return VideoFileSource(config, session_id)
    if config.kind == "webcam":
        return WebcamSource(config, session_id)
    if config.kind == "network":
        return NetworkSource(config, session_id)
    if config.kind == "synthetic":
        return SyntheticSource(config, session_id)
    raise SourceError(f"unknown source kind {config.kind}")
