"""WebSocket client transport for the Pi agent: bounded send queue, reconnect with backoff,
status heartbeats, render-command reception. Uses only ``websockets`` + stdlib."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from convergent.communication.buffering import AsyncDropOldestQueue
from convergent.communication.protocol import (
    ENC_JPEG,
    DeviceHello,
    DeviceStatus,
    FrameHeader,
    ProtocolError,
    RenderCommand,
    encode_frame,
    make_message,
    parse_message,
)


@dataclass
class TransportStats:
    connects: int = 0
    disconnects: int = 0
    frames_sent: int = 0
    frames_dropped: int = 0
    renders_received: int = 0
    last_error: str = ""
    connected: bool = False
    hello_acked: bool = False
    assigned_session_id: str = ""
    server_config: dict[str, Any] = field(default_factory=dict)


class AgentTransport:
    def __init__(self, url: str, device_id: str, software_version: str, token: str = "", queue_size: int = 2,
                 on_render: Callable[[RenderCommand], None] | None = None, status_interval_s: float = 2.0,
                 reconnect_min_s: float = 0.5, reconnect_max_s: float = 10.0, hardware: dict[str, Any] | None = None) -> None:
        self.url, self.device_id, self.software_version, self.token = url, device_id, software_version, token
        self.queue: AsyncDropOldestQueue[tuple[FrameHeader, bytes]] = AsyncDropOldestQueue(queue_size)
        self.on_render = on_render
        self.status_interval_s = status_interval_s
        self.reconnect_min_s, self.reconnect_max_s = reconnect_min_s, reconnect_max_s
        self.hardware = hardware or {}
        self.stats = TransportStats()
        self.status_provider: Callable[[], DeviceStatus] | None = None
        self._seq = 0
        self._stop = asyncio.Event()
        self._ws: Any = None

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ---- producer API (called from the capture loop)
    def offer_frame(self, header: FrameHeader, payload: bytes) -> None:
        before = self.queue.dropped
        self.queue.push((header, payload))
        self.stats.frames_dropped += self.queue.dropped - before

    def stop(self) -> None:
        self._stop.set()

    # ---- main loop
    async def run(self) -> None:
        from websockets.asyncio.client import connect

        backoff = self.reconnect_min_s
        while not self._stop.is_set():
            try:
                async with connect(self.url, max_size=16 * 1024 * 1024, ping_interval=5, ping_timeout=10, open_timeout=5) as ws:
                    self._ws = ws
                    self.stats.connects += 1
                    self.stats.connected = True
                    backoff = self.reconnect_min_s
                    await self._session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - network errors are expected; we reconnect
                rcvd = getattr(exc, "rcvd", None)
                if (rcvd is not None and getattr(rcvd, "code", None) == 4401) or self.stats.last_error == "unauthorized":
                    self.stats.last_error = "unauthorized"
                    self._stop.set()  # a wrong token never fixes itself by reconnecting
                else:
                    self.stats.last_error = f"{type(exc).__name__}: {exc}"
            finally:
                if self.stats.connected:
                    self.stats.disconnects += 1
                self.stats.connected = False
                self.stats.hello_acked = False
                self._ws = None
            if self._stop.is_set():
                break
            await asyncio.sleep(backoff + random.uniform(0, backoff / 2))  # noqa: S311 - jitter, not crypto
            backoff = min(backoff * 2, self.reconnect_max_s)

    async def _session(self, ws: Any) -> None:
        hello = DeviceHello(self.device_id, self.software_version, session_id="", hardware=self.hardware,
                            capabilities={"encodings": ["jpeg"], "render": True})
        msg = hello.to_message(self._next_seq())
        if self.token:
            import json

            d = json.loads(msg)
            d["token"] = self.token
            msg = json.dumps(d, separators=(",", ":"))
        await ws.send(msg)
        sender = asyncio.create_task(self._send_loop(ws))
        status = asyncio.create_task(self._status_loop(ws))
        try:
            async for message in ws:
                if isinstance(message, bytes | bytearray):
                    continue  # server never sends binary
                try:
                    m = parse_message(str(message))
                except ProtocolError:
                    continue
                t = m.get("type")
                if t == "hello_ack":
                    self.stats.hello_acked = True
                    self.stats.assigned_session_id = str(m.get("session_id", ""))
                    self.stats.server_config = dict(m.get("config") or {})
                elif t == "render":
                    self.stats.renders_received += 1
                    try:
                        cmd = RenderCommand.from_message(m)
                    except ProtocolError as exc:
                        await ws.send(make_message("error", self._next_seq(), message=str(exc)))
                        continue
                    if self.on_render:
                        self.on_render(cmd)
                    await ws.send(make_message("render_ack", self._next_seq(), ack_seq=cmd.seq, device_monotonic_ns=time.monotonic_ns()))
                elif t == "error":
                    self.stats.last_error = str(m.get("message", "server error"))
                    if m.get("message") == "unauthorized":
                        self._stop.set()
                elif t == "pong":
                    pass
        finally:
            sender.cancel()
            status.cancel()
            for task in (sender, status):
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    async def _send_loop(self, ws: Any) -> None:
        while not self.stats.hello_acked:  # never stream before the laptop accepted our hello
            if self._stop.is_set():
                return
            await asyncio.sleep(0.02)
        while True:
            item = await self.queue.pop(timeout=1.0)
            if item is None:
                if self._stop.is_set():
                    return
                continue
            header, payload = item
            await ws.send(encode_frame(header, payload))
            self.stats.frames_sent += 1

    async def _status_loop(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(self.status_interval_s)
            if self.status_provider is not None:
                await ws.send(self.status_provider().to_message(self._next_seq()))


def frame_header(session_id: str, frame_id: int, device_ts_ns: int, width: int, height: int) -> FrameHeader:
    return FrameHeader(session_id=session_id, frame_id=frame_id, device_ts_ns=device_ts_ns, width=width, height=height, encoding=ENC_JPEG)
