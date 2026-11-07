"""WebSocket routes under /ws/v1."""

from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from convergent.backend.auth import ws_token_ok
from convergent.backend.services import persistence as P
from convergent.backend.ws import pubsub_loop
from convergent.communication.protocol import (
    DeviceStatus,
    ProtocolError,
    make_message,
    parse_message,
)

router = APIRouter()


async def _accept(ws: WebSocket, token: str | None) -> bool:
    settings = ws.app.state.settings
    can_publish = ws_token_ok(settings, token)
    if not settings.allow_unauthenticated_reads and not can_publish:
        await ws.close(code=4401, reason="unauthorized")
        return False
    await ws.accept()
    return True


@router.websocket("/ws/v1/observations")
async def observations(ws: WebSocket, token: str | None = Query(default=None)) -> None:
    if not await _accept(ws, token):
        return
    hub = ws.app.state.hub
    await hub.join("observations", ws)
    try:
        await pubsub_loop(hub, "observations", ws, can_publish=ws_token_ok(ws.app.state.settings, token))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave("observations", ws)


@router.websocket("/ws/v1/render")
async def render(ws: WebSocket, token: str | None = Query(default=None)) -> None:
    if not await _accept(ws, token):
        return
    hub = ws.app.state.hub
    await hub.join("render", ws)
    try:
        await pubsub_loop(hub, "render", ws, can_publish=ws_token_ok(ws.app.state.settings, token))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave("render", ws)


@router.websocket("/ws/v1/device")
async def device(ws: WebSocket, token: str | None = Query(default=None)) -> None:
    """Device health channel: accepts hello/status JSON from a Pi agent (write token required)."""
    settings = ws.app.state.settings
    if not ws_token_ok(settings, token):
        await ws.close(code=4401, reason="unauthorized")
        return
    await ws.accept()
    hub = ws.app.state.hub
    await hub.join("device", ws)
    seq = 0
    device_id = ""
    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                seq += 1
                await ws.send_text(make_message("error", seq, message="binary frames are not accepted here; stream video to the pipeline gateway"))
                continue
            try:
                msg = parse_message(message.get("text") or "")
            except ProtocolError as exc:
                seq += 1
                await ws.send_text(make_message("error", seq, message=str(exc)))
                continue
            t = msg.get("type")
            with ws.app.state.db.session() as db:
                if t == "hello":
                    device_id = str(msg.get("device_id", "pi"))
                    P.upsert_device(db, device_id, msg.get("hardware") or {}, str(msg.get("software_version", "")), "connected")
                    seq += 1
                    await ws.send_text(make_message("hello_ack", seq, session_id="", config={}))
                elif t == "status":
                    st = DeviceStatus.from_message(msg)
                    device_id = st.device_id or device_id
                    P.upsert_device(db, device_id, status="connected", last_status=st.__dict__)
                    await hub.broadcast("observations", make_message("device_status", 0, status=st.__dict__), exclude=ws)
                elif t == "ping":
                    seq += 1
                    await ws.send_text(make_message("pong", seq, echo=msg.get("seq")))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave("device", ws)
        if device_id:
            with ws.app.state.db.session() as db:
                P.upsert_device(db, device_id, status="disconnected")
