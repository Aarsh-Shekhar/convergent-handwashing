"""Device <-> laptop wire protocol (stdlib only: shared with the Raspberry Pi agent).

Transport: one WebSocket connection per device. Two message families:

**Binary video frames** (``FrameHeader`` + payload) – fixed little-endian header::

    offset size field
    0      4    magic b"CVHW"
    4      1    protocol version (PROTOCOL_VERSION)
    5      1    message type (MSG_FRAME = 1)
    6      1    encoding (1 = JPEG, 2 = raw BGR24)
    7      1    flags (bit0: key frame; reserved)
    8      16   session id (UUID bytes; zero-padded ASCII allowed)
    24     8    frame id (uint64, device sequence number)
    32     8    device monotonic timestamp in nanoseconds (uint64)
    40     2    width  (uint16)
    42     2    height (uint16)
    44     4    payload length (uint32)
    48     ...  payload

**JSON control messages** (text frames) – ``{"type": ..., "seq": int, ...}``:
``hello`` / ``hello_ack``, ``status`` (device health), ``render`` (laptop -> Pi diagnostic
drawing), ``render_ack``, ``ping``/``pong``, ``error``, ``bye``.

Bandwidth/latency (documented trade-off, see docs/PI_SETUP.md): 640x480 JPEG @ q=80 is
roughly 35-60 KB/frame -> 4-7 Mbit/s at 15 FPS, well within 2.4/5 GHz Wi-Fi on the Pi 3 A+,
with ~1-2 frames of encode+transport latency. H.264 would cut bandwidth ~10x at the cost of
encoder latency and decode complexity; the encoding byte makes that switch possible without
touching any computer-vision module.
"""

from __future__ import annotations

import json
import struct
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

PROTOCOL_VERSION = 1
MAGIC = b"CVHW"
MSG_FRAME = 1
ENC_JPEG = 1
ENC_RAW_BGR = 2
HEADER_STRUCT = struct.Struct("<4sBBBB16sQQHHI")
HEADER_SIZE = HEADER_STRUCT.size  # 48
MAX_PAYLOAD = 8 * 1024 * 1024


class ProtocolError(ValueError):
    pass


FLAG_KEYFRAME = 0x1
FLAG_ASCII_SESSION = 0x2  # session id field holds zero-padded ASCII instead of UUID bytes


def _session_bytes(session_id: str) -> tuple[bytes, int]:
    try:
        return uuid.UUID(session_id.replace("ses_", "")).bytes, 0
    except ValueError:
        b = session_id.encode("ascii", "replace")[:16]
        return b.ljust(16, b"\x00"), FLAG_ASCII_SESSION


def _session_str(raw: bytes, flags: int) -> str:
    if flags & FLAG_ASCII_SESSION:
        return raw.rstrip(b"\x00").decode("ascii", "replace")
    return "ses_" + uuid.UUID(bytes=raw).hex


@dataclass(frozen=True)
class FrameHeader:
    session_id: str
    frame_id: int
    device_ts_ns: int
    width: int
    height: int
    encoding: int = ENC_JPEG
    flags: int = 0
    payload_len: int = 0
    version: int = PROTOCOL_VERSION

    @property
    def device_ts(self) -> float:
        return self.device_ts_ns / 1e9


def encode_frame(header: FrameHeader, payload: bytes) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"payload too large ({len(payload)} bytes)")
    if header.width <= 0 or header.height <= 0 or header.width > 65535 or header.height > 65535:
        raise ProtocolError("invalid image size")
    sid, sflag = _session_bytes(header.session_id)
    hdr = HEADER_STRUCT.pack(MAGIC, header.version, MSG_FRAME, header.encoding, header.flags | sflag, sid,
                             header.frame_id, header.device_ts_ns, header.width, header.height, len(payload))
    return hdr + payload


def decode_frame(data: bytes) -> tuple[FrameHeader, bytes]:
    if len(data) < HEADER_SIZE:
        raise ProtocolError(f"message shorter than header ({len(data)} < {HEADER_SIZE})")
    magic, ver, mtype, enc, flags, sid, fid, ts_ns, w, h, plen = HEADER_STRUCT.unpack_from(data, 0)
    if magic != MAGIC:
        raise ProtocolError("bad magic")
    if ver != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version {ver}")
    if mtype != MSG_FRAME:
        raise ProtocolError(f"unexpected binary message type {mtype}")
    if enc not in (ENC_JPEG, ENC_RAW_BGR):
        raise ProtocolError(f"unknown encoding {enc}")
    if w == 0 or h == 0:
        raise ProtocolError("invalid image size")
    payload = data[HEADER_SIZE:]
    if len(payload) != plen:
        raise ProtocolError(f"payload length mismatch: header {plen}, actual {len(payload)}")
    if enc == ENC_RAW_BGR and plen != w * h * 3:
        raise ProtocolError("raw payload size does not match dimensions")
    return FrameHeader(_session_str(sid, flags), fid, ts_ns, w, h, enc, flags & ~FLAG_ASCII_SESSION, plen, ver), payload


# --------------------------------------------------------------------------- control messages
def make_message(msg_type: str, seq: int, **fields: Any) -> str:
    return json.dumps({"type": msg_type, "seq": seq, "v": PROTOCOL_VERSION, **fields}, separators=(",", ":"))


def parse_message(text: str) -> dict[str, Any]:
    try:
        msg = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON control message: {exc}") from exc
    if not isinstance(msg, dict) or "type" not in msg:
        raise ProtocolError("control message must be an object with a 'type'")
    if msg.get("v", PROTOCOL_VERSION) != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported control protocol version {msg.get('v')}")
    return msg


@dataclass
class DeviceHello:
    device_id: str
    software_version: str
    session_id: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    hardware: dict[str, Any] = field(default_factory=dict)
    monotonic_ns: int = field(default_factory=time.monotonic_ns)

    def to_message(self, seq: int) -> str:
        return make_message("hello", seq, **asdict(self))


@dataclass
class DeviceStatus:
    device_id: str
    monotonic_ns: int
    frames_captured: int
    frames_sent: int
    frames_dropped: int
    queue_depth: int
    cpu_temp_c: float | None = None
    throttled_flags: str | None = None
    under_voltage: bool | None = None
    mem_available_mb: float | None = None
    camera_ok: bool = True
    display_ok: bool = True
    last_render_seq: int | None = None
    fps: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_message(self, seq: int) -> str:
        return make_message("status", seq, **asdict(self))

    @classmethod
    def from_message(cls, msg: dict[str, Any]) -> DeviceStatus:
        known = {k: v for k, v in msg.items() if k in cls.__dataclass_fields__}
        return cls(**known)


# --------------------------------------------------------------------------- render commands
RENDER_SHAPES = ("crosshair", "circle", "marker_grid", "chessboard", "dot_grid", "aruco_grid", "text", "clear", "skeleton", "polygon")


@dataclass
class RenderItem:
    shape: str  # one of RENDER_SHAPES
    x: float | None = None
    y: float | None = None
    points: list[list[float]] | None = None  # polygon / skeleton points in projector px
    radius: float = 12.0
    color: list[int] = field(default_factory=lambda: [0, 255, 0])
    label: str = ""
    anchor_id: str = ""

    def __post_init__(self) -> None:
        if self.shape not in RENDER_SHAPES:
            raise ProtocolError(f"unknown render shape {self.shape}")


@dataclass
class RenderCommand:
    """Laptop -> Pi: draw a diagnostic frame on the projector."""

    seq: int
    command: str  # "draw" | "pattern" | "clear"
    calibration_profile_id: str | None
    calibration_version: int | None
    canvas_width: int
    canvas_height: int
    items: list[RenderItem] = field(default_factory=list)
    text: str = ""
    valid_until_ns: int = 0  # device monotonic ns after which the frame should be cleared (0 = no expiry)
    laptop_monotonic_ns: int = field(default_factory=time.monotonic_ns)

    def to_message(self) -> str:
        d = asdict(self)
        return make_message("render", self.seq, **{k: v for k, v in d.items() if k != "seq"})

    @classmethod
    def from_message(cls, msg: dict[str, Any]) -> RenderCommand:
        if msg.get("type") != "render":
            raise ProtocolError("not a render message")
        items = [RenderItem(**it) for it in msg.get("items", [])]
        if msg.get("command") not in ("draw", "pattern", "clear"):
            raise ProtocolError(f"unknown render command {msg.get('command')}")
        if int(msg.get("canvas_width", 0)) <= 0 or int(msg.get("canvas_height", 0)) <= 0:
            raise ProtocolError("render canvas size must be positive")
        return cls(seq=int(msg["seq"]), command=msg["command"], calibration_profile_id=msg.get("calibration_profile_id"),
                   calibration_version=msg.get("calibration_version"), canvas_width=int(msg["canvas_width"]),
                   canvas_height=int(msg["canvas_height"]), items=items, text=str(msg.get("text", "")),
                   valid_until_ns=int(msg.get("valid_until_ns", 0)), laptop_monotonic_ns=int(msg.get("laptop_monotonic_ns", 0)))
