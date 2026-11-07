"""WebSocket hub: live observations, render messages and device status.

* ``/ws/v1/observations``  – subscribers receive JSON live-analysis messages published by the
  pipeline (``publish`` role requires the token; subscribers follow the read policy).
* ``/ws/v1/render``        – render/debug commands published by the pipeline; a Pi renderer or
  a debug viewer can subscribe.
* ``/ws/v1/device``        – device agents post ``hello``/``status`` control messages (same JSON
  protocol as the video gateway); binary video frames are NOT accepted here (they go to the
  pipeline's gateway, see communication/websocket.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from convergent.communication.protocol import ProtocolError, make_message, parse_message


@dataclass
class Hub:
    """Subscriber registry. All access happens on the server's single event loop, so plain
    set operations are sufficient (no cross-task await between read and write)."""

    channels: dict[str, set[WebSocket]] = field(default_factory=lambda: {"observations": set(), "render": set(), "device": set()})
    device_connections: int = 0

    async def join(self, channel: str, ws: WebSocket) -> None:
        self.channels[channel].add(ws)

    async def leave(self, channel: str, ws: WebSocket) -> None:
        self.channels[channel].discard(ws)

    async def broadcast(self, channel: str, message: str, exclude: WebSocket | None = None) -> int:
        targets = [w for w in self.channels[channel] if w is not exclude]
        sent = 0
        for w in targets:
            try:
                await w.send_text(message)
                sent += 1
            except Exception:  # noqa: BLE001 - dead subscriber
                await self.leave(channel, w)
        return sent

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.channels.items()}


async def pubsub_loop(hub: Hub, channel: str, ws: WebSocket, can_publish: bool) -> None:
    """Generic loop: text messages from publishers are validated and rebroadcast."""
    seq = 0
    while True:
        text = await ws.receive_text()
        try:
            msg = parse_message(text)
        except ProtocolError as exc:
            seq += 1
            await ws.send_text(make_message("error", seq, message=str(exc)))
            continue
        if msg.get("type") == "ping":
            seq += 1
            await ws.send_text(make_message("pong", seq, echo=msg.get("seq")))
            continue
        if not can_publish:
            seq += 1
            await ws.send_text(make_message("error", seq, message="publishing requires the API token"))
            continue
        await hub.broadcast(channel, text, exclude=ws)
        seq += 1
        await ws.send_text(make_message("ack", seq, echo=msg.get("seq")))


def jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))
