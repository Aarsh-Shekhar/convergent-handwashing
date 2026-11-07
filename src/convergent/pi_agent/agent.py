"""Raspberry Pi camera agent main loop (also used for the laptop emulator).

Responsibilities (spec §7): camera init, capture, connect to the laptop, timestamped frame
transmission, health reporting, render-command handling, HDMI diagnostic output, reconnect,
controlled shutdown. Memory footprint is kept small: one capture buffer, a 2-deep send queue
and one render canvas.

Configuration is a small YAML file (``configs/pi_agent.yaml``) or CLI flags; the shared
secret comes from the ``CONVERGENT_DEVICE_TOKEN`` environment variable, never from YAML.
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from convergent.communication.protocol import DeviceStatus, RenderCommand
from convergent.pi_agent import diagnostics
from convergent.pi_agent.camera import BaseCamera, CameraUnavailable, EmulatedCamera, encode_jpeg
from convergent.pi_agent.renderer import ImageRenderer, create_renderer
from convergent.pi_agent.transport import AgentTransport, frame_header

AGENT_VERSION = "pi-agent-0.1.0"


@dataclass
class AgentConfig:
    laptop_url: str = "ws://127.0.0.1:8765"
    device_id: str = "pi-faucet-01"
    width: int = 640
    height: int = 480
    fps: float = 15.0
    jpeg_quality: int = 80
    send_queue: int = 2
    status_interval_s: float = 2.0
    renderer: str = "auto"  # auto | framebuffer | image
    render_out_dir: str | None = None
    camera: str = "auto"  # auto | picamera2 | emulated
    video_path: str | None = None
    max_frames: int | None = None
    token: str = field(default_factory=lambda: os.environ.get("CONVERGENT_DEVICE_TOKEN", ""))


class PiAgent:
    def __init__(self, cfg: AgentConfig, camera: BaseCamera | None = None, renderer: ImageRenderer | None = None) -> None:
        self.cfg = cfg
        self.camera = camera or self._make_camera()
        self.renderer = renderer or create_renderer(cfg.renderer, cfg.render_out_dir)
        self.transport = AgentTransport(cfg.laptop_url, cfg.device_id, AGENT_VERSION, cfg.token, cfg.send_queue,
                                        on_render=self._on_render, status_interval_s=cfg.status_interval_s,
                                        hardware={"camera": type(self.camera).__name__, "renderer": type(self.renderer).__name__})
        self.transport.status_provider = self.status
        self.frames_captured = 0
        self.capture_errors = 0
        self.last_render_seq: int | None = None
        self._stop = threading.Event()
        self._fps_window: list[float] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def _make_camera(self) -> BaseCamera:
        if self.cfg.camera in ("auto", "picamera2"):
            try:
                from convergent.pi_agent.camera import Picamera2Camera

                return Picamera2Camera(self.cfg.width, self.cfg.height, self.cfg.fps, self.cfg.jpeg_quality)
            except CameraUnavailable:
                if self.cfg.camera == "picamera2":
                    raise
        return EmulatedCamera(self.cfg.width, self.cfg.height, self.cfg.fps, self.cfg.video_path)

    # ---- status
    def status(self) -> DeviceStatus:
        d = diagnostics.collect()
        now = time.monotonic()
        self._fps_window = [t for t in self._fps_window if now - t < 2.0]
        return DeviceStatus(device_id=self.cfg.device_id, monotonic_ns=time.monotonic_ns(), frames_captured=self.frames_captured,
                            frames_sent=self.transport.stats.frames_sent, frames_dropped=self.transport.stats.frames_dropped,
                            queue_depth=len(self.transport.queue), cpu_temp_c=d["cpu_temp_c"], throttled_flags=d["throttled_flags"],
                            under_voltage=d["under_voltage"], mem_available_mb=d["mem_available_mb"],
                            camera_ok=bool(self.camera.health().get("ok", False)), display_ok=bool(getattr(self.renderer, "ok", True)),
                            last_render_seq=self.last_render_seq, fps=len(self._fps_window) / 2.0,
                            errors=[self.transport.stats.last_error] if self.transport.stats.last_error else [])

    def _on_render(self, cmd: RenderCommand) -> None:
        self.renderer.render(cmd)
        self.last_render_seq = cmd.seq

    # ---- capture loop (thread)
    def _capture_loop(self) -> None:
        period = 1.0 / self.cfg.fps
        next_t = time.monotonic()
        session = self.transport.stats.assigned_session_id or "unassigned"
        while not self._stop.is_set():
            if self.cfg.max_frames is not None and self.frames_captured >= self.cfg.max_frames:
                self._stop.set()
                break
            frame = self.camera.capture()
            if frame is None:
                self.capture_errors += 1
                time.sleep(period)
                continue
            self.frames_captured += 1
            self._fps_window.append(time.monotonic())
            payload = frame.jpeg if frame.jpeg is not None else encode_jpeg(frame.bgr, self.cfg.jpeg_quality)  # type: ignore[arg-type]
            session = self.transport.stats.assigned_session_id or session
            hdr = frame_header(session, frame.index, frame.device_ts_ns, frame.width, frame.height)
            self.transport.offer_frame(hdr, payload)
            self.renderer.tick()
            next_t += period
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.monotonic()  # fell behind: do not burst

    # ---- lifecycle
    async def run_async(self) -> None:
        self.camera.start()
        self._loop = asyncio.get_running_loop()
        cap = threading.Thread(target=self._capture_loop, name="pi-capture", daemon=True)
        cap.start()
        transport_task = asyncio.create_task(self.transport.run())
        try:
            while not self._stop.is_set() and not transport_task.done():
                await asyncio.sleep(0.1)
        finally:
            self._stop.set()
            self.transport.stop()
            cap.join(2.0)
            try:
                await asyncio.wait_for(transport_task, 3.0)
            except (TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                transport_task.cancel()
            self.camera.stop()
            self.renderer.close()

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def _sig(*_: Any) -> None:
            self._stop.set()

        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(s, _sig)
            except (NotImplementedError, RuntimeError):
                signal.signal(s, _sig)
        try:
            loop.run_until_complete(self.run_async())
        finally:
            loop.close()

    def stop(self) -> None:
        self._stop.set()
