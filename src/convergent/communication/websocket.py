"""Laptop-side device gateway: accepts the Raspberry Pi agent's WebSocket connection,
decodes timestamped frames into a :class:`NetworkSource`, tracks device health and sends
render/debug commands back.

Runs its own asyncio loop in a background thread so the synchronous pipeline can consume
frames through the bounded latest-frame queue of :class:`NetworkSource`.
"""

from __future__ import annotations

import asyncio
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from convergent.common.logging import get_logger
from convergent.common.timestamps import ClockOffsetEstimator, monotonic
from convergent.communication.protocol import (
    ENC_JPEG,
    ENC_RAW_BGR,
    DeviceStatus,
    ProtocolError,
    RenderCommand,
    decode_frame,
    make_message,
    parse_message,
)
from convergent.vision.sources import NetworkFrame, NetworkSource

log = get_logger(__name__)


@dataclass
class DeviceState:
    device_id: str = ""
    software_version: str = ""
    device_session_id: str = ""
    connected: bool = False
    connections: int = 0
    frames_received: int = 0
    decode_errors: int = 0
    protocol_errors: int = 0
    last_frame_ts: float | None = None
    last_status: DeviceStatus | None = None
    last_render_ack: int | None = None
    clock: ClockOffsetEstimator = field(default_factory=ClockOffsetEstimator)
    hello: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id, "software_version": self.software_version, "connected": self.connected,
            "connections": self.connections, "frames_received": self.frames_received, "decode_errors": self.decode_errors,
            "protocol_errors": self.protocol_errors, "last_frame_ts": self.last_frame_ts, "clock_offset_s": self.clock.offset,
            "last_render_ack": self.last_render_ack, "status": None if self.last_status is None else self.last_status.__dict__,
        }


def decode_payload(encoding: int, payload: bytes, width: int, height: int) -> np.ndarray | None:
    if encoding == ENC_JPEG:
        arr = np.frombuffer(payload, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        if img.shape[1] != width or img.shape[0] != height:
            return None
        return img
    if encoding == ENC_RAW_BGR:
        return np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 3).copy()
    return None


class DeviceGateway:
    """WebSocket server for one device. Thread-safe public API."""

    def __init__(self, source: NetworkSource, host: str = "0.0.0.0", port: int = 8765, token: str = "",
                 on_status: Callable[[DeviceStatus], None] | None = None, config_for_device: dict[str, Any] | None = None) -> None:
        self.source = source
        self.host, self.port, self.token = host, port, token
        self.state = DeviceState()
        self.on_status = on_status
        self.config_for_device = config_for_device or {"target_fps": 15, "width": 640, "height": 480, "jpeg_quality": 80}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self._conn: Any = None
        self._seq = 0
        self._ready = threading.Event()
        self._stop = asyncio.Event()

    # ---- lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="device-gateway", daemon=True)
        self._thread.start()
        if not self._ready.wait(5.0):
            raise RuntimeError("device gateway failed to start")

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(5.0)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop = asyncio.Event()
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        from websockets.asyncio.server import serve

        async with serve(self._handler, self.host, self.port, max_size=16 * 1024 * 1024, ping_interval=5, ping_timeout=10) as server:
            self._server = server
            if self.port == 0:
                self.port = next(iter(server.sockets)).getsockname()[1]
            self._ready.set()
            await self._stop.wait()

    # ---- connection handling
    async def _handler(self, ws: Any) -> None:
        self.state.connections += 1
        self.state.connected = True
        self._conn = ws
        authenticated = not self.token  # with a configured token, frames are ignored until hello succeeds
        log.info("device connected from %s", getattr(ws, "remote_address", "?"))
        try:
            async for message in ws:
                if isinstance(message, bytes | bytearray):
                    if authenticated:
                        self._on_frame(bytes(message))
                    else:
                        self.state.protocol_errors += 1
                else:
                    authenticated = await self._on_control(ws, str(message)) or authenticated
        except Exception as exc:  # noqa: BLE001 - connection errors are expected; logged, not fatal
            log.warning("device connection ended: %s", exc)
        finally:
            self.state.connected = False
            self._conn = None
            self.source.on_disconnect()
            log.info("device disconnected")

    def _on_frame(self, data: bytes) -> None:
        try:
            header, payload = decode_frame(data)
        except ProtocolError as exc:
            self.state.protocol_errors += 1
            log.warning("bad frame: %s", exc)
            return
        img = decode_payload(header.encoding, payload, header.width, header.height)
        if img is None:
            self.state.decode_errors += 1
            return
        arrival = monotonic()
        self.state.frames_received += 1
        self.state.last_frame_ts = header.device_ts
        self.state.clock.add(header.device_ts, arrival)
        self.source.push(NetworkFrame(image=img, device_ts=header.device_ts, frame_index=header.frame_id,
                                      device_session_id=header.session_id, arrival_ts=arrival))

    async def _on_control(self, ws: Any, text: str) -> bool:
        """Handle a JSON control message. Returns True when a hello was accepted."""
        try:
            msg = parse_message(text)
        except ProtocolError as exc:
            self.state.protocol_errors += 1
            await ws.send(make_message("error", self._next_seq(), message=str(exc)))
            return False
        t = msg["type"]
        if t == "hello":
            if self.token and not secrets.compare_digest(str(msg.get("token", "")), self.token):
                await ws.send(make_message("error", self._next_seq(), message="unauthorized"))
                await ws.close(code=4401, reason="unauthorized")
                return False
            self.state.device_id = str(msg.get("device_id", "pi"))
            self.state.software_version = str(msg.get("software_version", ""))
            self.state.device_session_id = str(msg.get("session_id", ""))
            self.state.hello = msg
            self.source.set_device_id(self.state.device_id)
            await ws.send(make_message("hello_ack", self._next_seq(), session_id=self.source.session_id,
                                       config=self.config_for_device, laptop_monotonic_ns=time.monotonic_ns()))
            return True
        elif t == "status":
            st = DeviceStatus.from_message(msg)
            self.state.last_status = st
            if self.on_status:
                self.on_status(st)
        elif t == "render_ack":
            self.state.last_render_ack = int(msg.get("ack_seq", -1))
        elif t == "ping":
            await ws.send(make_message("pong", self._next_seq(), echo=msg.get("seq")))
        elif t == "bye":
            await ws.close()
        else:
            log.debug("unhandled control message %s", t)
        return False

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ---- outbound
    def send_render(self, cmd: RenderCommand) -> bool:
        if self._loop is None or self._conn is None:
            return False
        fut = asyncio.run_coroutine_threadsafe(self._conn.send(cmd.to_message()), self._loop)
        try:
            fut.result(timeout=2.0)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("render send failed: %s", exc)
            return False

    def next_render_seq(self) -> int:
        return self._next_seq()
