"""Device gateway <-> Pi agent emulator over real localhost WebSockets."""

from __future__ import annotations

import asyncio
import threading
import time

import numpy as np

from convergent.common.config import SourceConfig
from convergent.communication.protocol import RenderCommand, RenderItem
from convergent.communication.websocket import DeviceGateway
from convergent.pi_agent.agent import AgentConfig, PiAgent
from convergent.pi_agent.camera import EmulatedCamera
from convergent.pi_agent.renderer import ImageRenderer
from convergent.vision.sources import NetworkSource


def start_gateway(token: str = "", port: int = 0):
    source = NetworkSource(SourceConfig(kind="network", width=64, height=48, target_fps=0), queue_size=4, read_timeout_s=3.0)
    gw = DeviceGateway(source, "127.0.0.1", port, token=token, config_for_device={"target_fps": 30, "width": 64, "height": 48, "jpeg_quality": 70})
    gw.start()
    return source, gw


def run_agent(cfg: AgentConfig, renderer: ImageRenderer) -> tuple[PiAgent, threading.Thread]:
    agent = PiAgent(cfg, camera=EmulatedCamera(cfg.width, cfg.height, cfg.fps), renderer=renderer)
    t = threading.Thread(target=lambda: asyncio.run(agent.run_async()), daemon=True)
    t.start()
    return agent, t


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_frames_status_and_render_roundtrip():
    source, gw = start_gateway(token="dev-token")
    try:
        cfg = AgentConfig(laptop_url=f"ws://127.0.0.1:{gw.port}", device_id="pi-emu", width=64, height=48, fps=30, status_interval_s=0.3, token="dev-token")
        renderer = ImageRenderer()
        agent, thread = run_agent(cfg, renderer)
        assert wait_for(lambda: gw.state.frames_received >= 10)
        with source:
            pkt = source.read()
        assert pkt is not None and pkt.width == 64 and pkt.height == 48 and pkt.source_id == "network:pi-emu"
        assert pkt.timestamps.capture_clock == "source_monotonic" and gw.state.clock.offset is not None
        assert agent.transport.stats.hello_acked and agent.transport.stats.server_config["jpeg_quality"] == 70
        assert agent.transport.stats.assigned_session_id == source.session_id
        assert wait_for(lambda: gw.state.last_status is not None)
        st = gw.state.last_status
        assert st.device_id == "pi-emu" and st.frames_captured > 0 and st.camera_ok
        cmd = RenderCommand(seq=gw.next_render_seq(), command="draw", calibration_profile_id="cal", calibration_version=1, canvas_width=854, canvas_height=480,
                            items=[RenderItem(shape="crosshair", x=400, y=200, radius=10, color=[0, 255, 0], label="t")])
        assert gw.send_render(cmd)
        assert wait_for(lambda: renderer.last_seq == cmd.seq) and renderer.last[200, 400].tolist() == [0, 255, 0]
        assert wait_for(lambda: gw.state.last_render_ack == cmd.seq)
        agent.stop()
        thread.join(5)
        assert wait_for(lambda: not gw.state.connected)
        assert source.disconnects == 1
    finally:
        gw.stop()


def test_reconnect_after_gateway_restart_and_bounded_queues():
    source, gw = start_gateway()
    port = gw.port
    cfg = AgentConfig(laptop_url=f"ws://127.0.0.1:{port}", device_id="pi-emu", width=64, height=48, fps=60, send_queue=2, status_interval_s=0.5)
    agent, thread = run_agent(cfg, ImageRenderer())
    try:
        assert wait_for(lambda: gw.state.frames_received >= 5)
        gw.stop()  # laptop side goes away
        assert wait_for(lambda: not agent.transport.stats.connected, 10)
        time.sleep(0.5)
        assert agent.transport.stats.disconnects >= 1
        source2, gw2 = start_gateway(port=port)  # comes back on the same port
        try:
            assert wait_for(lambda: gw2.state.frames_received >= 5, 20)  # agent reconnected with backoff
            assert agent.transport.stats.connects >= 2
            assert len(agent.transport.queue) <= 2  # bounded send queue
        finally:
            gw2.stop()
    finally:
        agent.stop()
        thread.join(5)


def test_unauthorized_device_is_rejected():
    source, gw = start_gateway(token="secret")
    try:
        cfg = AgentConfig(laptop_url=f"ws://127.0.0.1:{gw.port}", device_id="bad", width=32, height=32, fps=10, token="wrong")
        agent, thread = run_agent(cfg, ImageRenderer())
        assert wait_for(lambda: agent.transport.stats.last_error == "unauthorized", 10)
        thread.join(5)
        assert gw.state.frames_received == 0
    finally:
        gw.stop()


def test_gateway_ignores_garbage_without_crashing():
    from websockets.sync.client import connect

    source, gw = start_gateway()
    try:
        with connect(f"ws://127.0.0.1:{gw.port}") as ws:
            ws.send(b"\x00" * 20)
            ws.send("not json")
            assert "invalid JSON" in ws.recv(timeout=5)
            ws.send('{"type":"ping","seq":1}')
            assert '"pong"' in ws.recv(timeout=5)
        assert gw.state.protocol_errors == 2
        assert wait_for(lambda: not gw.state.connected)
        img = np.zeros((48, 64, 3), np.uint8)
        from convergent.communication.protocol import ENC_RAW_BGR, FrameHeader, encode_frame

        with connect(f"ws://127.0.0.1:{gw.port}") as ws:
            ws.send(encode_frame(FrameHeader("s", 1, 10, 64, 48, ENC_RAW_BGR), img.tobytes()))
            ws.send(encode_frame(FrameHeader("s", 2, 20, 64, 48, ENC_RAW_BGR), b"short"))  # bad payload -> protocol error
            time.sleep(0.3)
        assert gw.state.frames_received == 1 and gw.state.protocol_errors == 3
    finally:
        gw.stop()
