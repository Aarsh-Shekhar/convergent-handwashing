"""Diagnostic HDMI renderer for the Raspberry Pi (Pillow + numpy only).

* :class:`FramebufferRenderer` writes directly to ``/dev/fb0`` (works on Raspberry Pi OS Lite
  without X/Wayland). The framebuffer's negotiated mode (e.g. 1280x720 if the RIF6
  negotiates 720p) may differ from the 854x480 logical canvas; the canvas is scaled to the
  framebuffer with letterboxing, so logical coordinates stay valid.
* :class:`ImageRenderer` keeps the last rendered canvas in memory (and optionally writes PNGs)
  for the laptop emulator and tests.

Render commands are regenerated from parameters (patterns are drawn here, not streamed).
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from convergent.communication.protocol import RenderCommand, RenderItem


def _draw_chessboard(draw: ImageDraw.ImageDraw, w: int, h: int, cols: int = 9, rows: int = 6, margin: int = 40) -> None:
    sq = int(min((w - 2 * margin) / (cols + 1), (h - 2 * margin) / (rows + 1)))
    bw, bh = sq * (cols + 1), sq * (rows + 1)
    x0, y0 = (w - bw) // 2, (h - bh) // 2
    draw.rectangle([0, 0, w, h], fill=(255, 255, 255))
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                draw.rectangle([x0 + c * sq, y0 + r * sq, x0 + (c + 1) * sq - 1, y0 + (r + 1) * sq - 1], fill=(0, 0, 0))


def _draw_dot_grid(draw: ImageDraw.ImageDraw, w: int, h: int, cols: int = 8, rows: int = 5, margin: int = 60, radius: int = 8) -> None:
    xs = np.linspace(margin, w - margin, cols)
    ys = np.linspace(margin, h - margin, rows)
    for y in ys:
        for x in xs:
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(255, 255, 255))


def render_canvas(cmd: RenderCommand, previous: np.ndarray | None = None) -> np.ndarray:
    """Render a command to an RGB uint8 canvas of the command's logical size.

    Every command describes a complete frame (a diagnostic frame is replaced, never
    accumulated), so ``previous`` is only kept for API compatibility."""
    w, h = cmd.canvas_width, cmd.canvas_height
    img = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    if cmd.command == "clear":
        return np.asarray(img)
    for it in cmd.items:
        color = tuple(int(c) for c in it.color)
        if it.shape == "clear":
            draw.rectangle([0, 0, w, h], fill=(0, 0, 0))
        elif it.shape == "chessboard":
            _draw_chessboard(draw, w, h)
        elif it.shape == "dot_grid":
            _draw_dot_grid(draw, w, h)
        elif it.shape in ("crosshair", "circle") and it.x is not None and it.y is not None:
            x, y, r = it.x, it.y, it.radius
            if 0 <= x < w and 0 <= y < h:
                if it.shape == "crosshair":
                    draw.line([x - r, y, x + r, y], fill=color, width=2)
                    draw.line([x, y - r, x, y + r], fill=color, width=2)
                draw.ellipse([x - r, y - r, x + r, y + r], outline=color, width=2)
                if it.label:
                    draw.text((x + r + 4, y - 10), it.label, fill=color)
        elif it.shape in ("polygon", "skeleton") and it.points:
            pts = [(float(p[0]), float(p[1])) for p in it.points]
            if it.shape == "polygon" and len(pts) >= 3:
                draw.polygon(pts, outline=color)
            elif len(pts) >= 2:
                draw.line(pts, fill=color, width=2)
        elif it.shape == "text" and it.x is not None and it.y is not None:
            draw.text((it.x, it.y), it.label, fill=color)
        elif it.shape in ("marker_grid", "aruco_grid"):
            # ArUco bitmaps require OpenCV; on the Pi we draw a labelled dot grid as a fallback
            _draw_dot_grid(draw, w, h)
            draw.text((10, 10), f"{it.shape} (fallback dot grid)", fill=(255, 255, 0))
    if cmd.text:
        draw.text((10, h - 20), cmd.text[:120], fill=(200, 200, 200))
    return np.asarray(img)


class ImageRenderer:
    """In-memory renderer (emulator/tests)."""

    def __init__(self, out_dir: str | Path | None = None) -> None:
        self.out_dir = None if out_dir is None else Path(out_dir)
        self.last: np.ndarray | None = None
        self.rendered = 0
        self.last_seq: int | None = None
        self.last_cmd: RenderCommand | None = None
        self.expired_at: float | None = None

    def render(self, cmd: RenderCommand) -> np.ndarray:
        self.last = render_canvas(cmd, self.last)
        self.rendered += 1
        self.last_seq = cmd.seq
        self.last_cmd = cmd
        if self.out_dir is not None:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            Image.fromarray(self.last).save(self.out_dir / f"render_{cmd.seq:06d}.png")
        return self.last

    def tick(self, now_ns: int | None = None) -> None:
        """Clear expired frames (valid_until_ns is on the device monotonic clock)."""
        if self.last_cmd is not None and self.last_cmd.valid_until_ns and (now_ns or time.monotonic_ns()) > self.last_cmd.valid_until_ns and self.last is not None:
            self.last = np.zeros_like(self.last)
            self.expired_at = time.monotonic()
            self.last_cmd = None

    def close(self) -> None:
        pass


class FramebufferRenderer(ImageRenderer):
    """Writes the canvas to the Linux framebuffer (``/dev/fb0``)."""

    def __init__(self, device: str = "/dev/fb0") -> None:
        super().__init__(None)
        self.device = device
        self.fb_width, self.fb_height, self.bpp = self._read_mode()
        self.ok = self.fb_width > 0

    def _read_mode(self) -> tuple[int, int, int]:
        try:
            with open(self.device, "rb") as f:
                import fcntl

                FBIOGET_VSCREENINFO = 0x4600
                buf = bytearray(160)
                fcntl.ioctl(f, FBIOGET_VSCREENINFO, buf)
                xres, yres, _xv, _yv, _xo, _yo, bpp = struct.unpack_from("<7I", buf, 0)
                return int(xres), int(yres), int(bpp)
        except OSError:
            return 0, 0, 0

    def render(self, cmd: RenderCommand) -> np.ndarray:
        canvas = super().render(cmd)
        if not self.ok:
            return canvas
        fw, fh = self.fb_width, self.fb_height
        scale = min(fw / canvas.shape[1], fh / canvas.shape[0])
        nw, nh = max(1, int(canvas.shape[1] * scale)), max(1, int(canvas.shape[0] * scale))
        img = Image.fromarray(canvas).resize((nw, nh))
        frame = Image.new("RGB", (fw, fh), (0, 0, 0))
        frame.paste(img, ((fw - nw) // 2, (fh - nh) // 2))
        arr = np.asarray(frame)
        if self.bpp == 16:
            r, g, b = arr[..., 0].astype(np.uint16), arr[..., 1].astype(np.uint16), arr[..., 2].astype(np.uint16)
            packed = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            data = packed.astype("<u2").tobytes()
        else:  # 32 bpp BGRA
            bgra = np.zeros((fh, fw, 4), dtype=np.uint8)
            bgra[..., 0], bgra[..., 1], bgra[..., 2] = arr[..., 2], arr[..., 1], arr[..., 0]
            data = bgra.tobytes()
        try:
            with open(self.device, "wb") as f:
                f.write(data)
        except OSError:
            self.ok = False
        return canvas

    def close(self) -> None:
        if self.ok and os.path.exists(self.device):
            try:
                with open(self.device, "wb") as f:
                    f.write(b"\x00" * (self.fb_width * self.fb_height * (self.bpp // 8)))
            except OSError:
                pass


def create_renderer(kind: str = "auto", out_dir: str | None = None) -> ImageRenderer:
    if kind == "image":
        return ImageRenderer(out_dir)
    if kind == "framebuffer" or (kind == "auto" and os.path.exists("/dev/fb0")):
        fb = FramebufferRenderer()
        if fb.ok:
            return fb
    return ImageRenderer(out_dir)


__all__ = ["ImageRenderer", "FramebufferRenderer", "render_canvas", "create_renderer", "RenderItem"]
