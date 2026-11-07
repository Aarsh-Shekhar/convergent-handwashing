"""Camera capture for the Raspberry Pi agent.

* :class:`Picamera2Camera` – Arducam B0176 (OV5647, motorized focus) through Picamera2/libcamera.
  Imports Picamera2 lazily; constructing it off-Pi raises :class:`CameraUnavailable`.
* :class:`EmulatedCamera` – reads a video file or draws synthetic frames so the whole
  transport/render path can be exercised on the laptop (``convergent pi-emulator``).

Focus control: the B0176 exposes its VCM through libcamera's ``LensPosition`` control once the
``ov5647`` overlay with VCM support is enabled (docs/PI_SETUP.md). ``set_focus`` is a thin
wrapper; it is NOT verified on hardware yet.

Dependencies on the Pi: numpy, Pillow (JPEG encode fallback) and the system
``python3-picamera2`` package. No OpenCV, no ML frameworks.
"""

from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass

import numpy as np


class CameraUnavailable(RuntimeError):
    pass


@dataclass
class CapturedFrame:
    bgr: np.ndarray | None  # raw frame (emulator / raw mode) – may be None when a JPEG is provided directly
    jpeg: bytes | None
    width: int
    height: int
    device_ts_ns: int
    index: int


def encode_jpeg(bgr: np.ndarray, quality: int = 80) -> bytes:
    """JPEG-encode a BGR frame. Uses simplejpeg (ships with picamera2) when present, else Pillow."""
    try:
        import simplejpeg  # type: ignore[import-not-found]

        return simplejpeg.encode_jpeg(np.ascontiguousarray(bgr), quality=quality, colorspace="BGR")
    except ImportError:
        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(bgr[:, :, ::-1]).save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


class BaseCamera:
    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def capture(self) -> CapturedFrame | None:
        raise NotImplementedError

    def health(self) -> dict[str, object]:
        return {"ok": True}


class Picamera2Camera(BaseCamera):
    def __init__(self, width: int = 640, height: int = 480, fps: float = 15.0, jpeg_quality: int = 80) -> None:
        try:
            from picamera2 import Picamera2  # type: ignore[import-not-found]
        except ImportError as exc:
            raise CameraUnavailable("picamera2 not available (install python3-picamera2 on Raspberry Pi OS)") from exc
        self._Picamera2 = Picamera2
        self.width, self.height, self.fps, self.jpeg_quality = width, height, fps, jpeg_quality
        self._cam = None
        self._index = -1
        self._errors = 0

    def start(self) -> None:
        cam = self._Picamera2()
        config = cam.create_video_configuration(main={"size": (self.width, self.height), "format": "RGB888"},
                                                controls={"FrameRate": self.fps})
        cam.configure(config)
        cam.start()
        time.sleep(0.5)  # AGC/AWB settle
        self._cam = cam

    def stop(self) -> None:
        if self._cam is not None:
            self._cam.stop()
            self._cam.close()
            self._cam = None

    def set_focus(self, lens_position: float | None) -> None:
        """``None`` -> continuous autofocus if supported; else a manual LensPosition (dioptres)."""
        if self._cam is None:
            raise CameraUnavailable("camera not started")
        from libcamera import controls  # type: ignore[import-not-found]

        if lens_position is None:
            self._cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        else:
            self._cam.set_controls({"AfMode": controls.AfModeEnum.Manual, "LensPosition": float(lens_position)})

    def capture(self) -> CapturedFrame | None:
        if self._cam is None:
            return None
        try:
            request = self._cam.capture_request()
        except Exception:  # noqa: BLE001
            self._errors += 1
            return None
        try:
            arr = request.make_array("main")  # RGB888 in picamera2 is BGR byte order in memory
            meta = request.get_metadata()
        finally:
            request.release()
        self._index += 1
        ts_ns = int(meta.get("SensorTimestamp", time.monotonic_ns()))
        bgr = np.ascontiguousarray(arr[:, :, :3])
        return CapturedFrame(bgr, None, bgr.shape[1], bgr.shape[0], ts_ns, self._index)

    def health(self) -> dict[str, object]:
        return {"ok": self._cam is not None, "errors": self._errors, "frames": self._index + 1}


class EmulatedCamera(BaseCamera):
    """Laptop-side stand-in: synthetic moving blobs or frames from a video file (OpenCV optional)."""

    def __init__(self, width: int = 640, height: int = 480, fps: float = 15.0, video_path: str | None = None, seed: int = 0) -> None:
        self.width, self.height, self.fps = width, height, fps
        self.video_path = video_path
        self.seed = seed
        self._index = -1
        self._t0 = time.monotonic_ns()
        self._cap = None

    def start(self) -> None:
        self._index = -1
        if self.video_path:
            import cv2

            self._cap = cv2.VideoCapture(self.video_path)
            if not self._cap.isOpened():
                raise CameraUnavailable(f"cannot open {self.video_path}")

    def stop(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def capture(self) -> CapturedFrame | None:
        self._index += 1
        if self._cap is not None:
            import cv2

            ok, frame = self._cap.read()
            if not ok:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
                if not ok:
                    return None
            frame = cv2.resize(frame, (self.width, self.height))
            return CapturedFrame(frame, None, self.width, self.height, time.monotonic_ns(), self._index)
        img = np.full((self.height, self.width, 3), 40, dtype=np.uint8)
        t = self._index / self.fps
        cx = int(self.width * (0.5 + 0.25 * math.sin(t * 1.5)))
        cy = int(self.height * (0.55 + 0.1 * math.cos(t * 1.1)))
        yy, xx = np.mgrid[0:self.height, 0:self.width]
        r = self.width // 10
        for dx, col in ((-self.width // 6, (120, 160, 210)), (self.width // 6, (110, 150, 200))):
            mask = (xx - (cx + dx)) ** 2 + (yy - cy) ** 2 <= r * r
            img[mask] = col
        return CapturedFrame(img, None, self.width, self.height, time.monotonic_ns(), self._index)
