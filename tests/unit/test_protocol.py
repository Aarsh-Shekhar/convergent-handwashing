import json

import numpy as np
import pytest

from convergent.communication.buffering import AsyncDropOldestQueue, DropOldestQueue
from convergent.communication.protocol import (
    ENC_JPEG,
    ENC_RAW_BGR,
    HEADER_SIZE,
    MAX_PAYLOAD,
    PROTOCOL_VERSION,
    DeviceHello,
    DeviceStatus,
    FrameHeader,
    ProtocolError,
    RenderCommand,
    RenderItem,
    decode_frame,
    encode_frame,
    make_message,
    parse_message,
)
from convergent.communication.websocket import decode_payload
from convergent.pi_agent.camera import EmulatedCamera, encode_jpeg


def test_frame_roundtrip_and_header_size():
    hdr = FrameHeader(session_id="ses_" + "ab" * 16, frame_id=42, device_ts_ns=123456789, width=640, height=480, encoding=ENC_JPEG, flags=1)
    payload = b"\xff\xd8" + bytes(100)
    msg = encode_frame(hdr, payload)
    assert len(msg) == HEADER_SIZE + len(payload) and HEADER_SIZE == 48
    h2, p2 = decode_frame(msg)
    assert p2 == payload and h2.frame_id == 42 and h2.device_ts_ns == 123456789 and h2.width == 640 and h2.height == 480
    assert h2.session_id == hdr.session_id and h2.flags == 1 and h2.device_ts == pytest.approx(0.123456789)
    short = FrameHeader(session_id="pi-local", frame_id=1, device_ts_ns=1, width=2, height=2, encoding=ENC_RAW_BGR)
    h3, _ = decode_frame(encode_frame(short, bytes(12)))
    assert h3.session_id == "pi-local"


def test_frame_decode_errors():
    hdr = FrameHeader(session_id="x", frame_id=1, device_ts_ns=1, width=4, height=4)
    good = encode_frame(hdr, b"abc")
    with pytest.raises(ProtocolError):
        decode_frame(good[:10])
    with pytest.raises(ProtocolError):
        decode_frame(b"XXXX" + good[4:])
    with pytest.raises(ProtocolError):
        decode_frame(good[:4] + bytes([PROTOCOL_VERSION + 1]) + good[5:])
    with pytest.raises(ProtocolError):
        decode_frame(good + b"extra")
    with pytest.raises(ProtocolError):
        encode_frame(hdr, bytes(MAX_PAYLOAD + 1))
    with pytest.raises(ProtocolError):
        encode_frame(FrameHeader(session_id="x", frame_id=1, device_ts_ns=1, width=0, height=4), b"")
    with pytest.raises(ProtocolError):
        decode_frame(encode_frame(FrameHeader(session_id="x", frame_id=1, device_ts_ns=1, width=4, height=4, encoding=ENC_RAW_BGR), bytes(5)))


def test_control_messages_and_dataclasses():
    m = parse_message(make_message("status", 3, device_id="pi"))
    assert m["type"] == "status" and m["seq"] == 3 and m["v"] == PROTOCOL_VERSION
    with pytest.raises(ProtocolError):
        parse_message("{not json")
    with pytest.raises(ProtocolError):
        parse_message(json.dumps({"seq": 1}))
    with pytest.raises(ProtocolError):
        parse_message(json.dumps({"type": "x", "v": 99}))
    st = DeviceStatus("pi", 1, 10, 9, 1, 0, cpu_temp_c=45.0, errors=["e"])
    back = DeviceStatus.from_message(parse_message(st.to_message(1)))
    assert back == st
    hello = parse_message(DeviceHello("pi", "v1", "ses").to_message(1))
    assert hello["device_id"] == "pi" and "monotonic_ns" in hello


def test_render_command_roundtrip():
    cmd = RenderCommand(seq=9, command="draw", calibration_profile_id="cal", calibration_version=3, canvas_width=854, canvas_height=480,
                        items=[RenderItem(shape="circle", x=1, y=2, radius=3, color=[1, 2, 3], label="a", anchor_id="left:lm8"),
                               RenderItem(shape="polygon", points=[[0, 0], [1, 0], [1, 1]])], text="t", valid_until_ns=5)
    back = RenderCommand.from_message(parse_message(cmd.to_message()))
    assert back.seq == 9 and back.items[0].anchor_id == "left:lm8" and back.items[1].points == [[0, 0], [1, 0], [1, 1]]
    assert back.calibration_version == 3 and back.valid_until_ns == 5
    with pytest.raises(ProtocolError):
        RenderCommand.from_message({"type": "status"})


def test_jpeg_payload_roundtrip_and_decode_validation():
    img = np.zeros((48, 64, 3), np.uint8)
    img[:, :, 2] = 200
    jpg = encode_jpeg(img, 90)
    out = decode_payload(ENC_JPEG, jpg, 64, 48)
    assert out is not None and out.shape == (48, 64, 3) and out[0, 0, 2] > 150
    assert decode_payload(ENC_JPEG, jpg, 32, 32) is None  # size mismatch
    assert decode_payload(ENC_JPEG, b"garbage", 64, 48) is None
    raw = decode_payload(ENC_RAW_BGR, img.tobytes(), 64, 48)
    assert raw is not None and np.array_equal(raw, img)


def test_drop_oldest_queues():
    q = DropOldestQueue(2)
    for i in range(4):
        q.push(i)
    assert q.dropped == 2 and q.pop(0.01) == 2 and q.stats()["depth"] == 1
    with pytest.raises(ValueError):
        DropOldestQueue(0)

    async def run():
        aq: AsyncDropOldestQueue[int] = AsyncDropOldestQueue(1)
        aq.push(1)
        aq.push(2)
        assert aq.dropped == 1
        assert await aq.pop(0.01) == 2
        assert await aq.pop(0.01) is None
        aq.close()
        assert await aq.pop(0.01) is None

    import asyncio

    asyncio.run(run())


def test_emulated_camera_frames():
    cam = EmulatedCamera(64, 48, 15.0)
    cam.start()
    f1, f2 = cam.capture(), cam.capture()
    assert f1.index == 0 and f2.index == 1 and f1.bgr.shape == (48, 64, 3) and f2.device_ts_ns >= f1.device_ts_ns
    cam.stop()
