"""``python -m convergent.pi_agent`` – run the camera agent (on the Pi) or the emulator (laptop)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import yaml

from convergent.pi_agent.agent import AgentConfig, PiAgent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convergent Raspberry Pi camera agent")
    ap.add_argument("--config", type=Path, default=None, help="YAML with AgentConfig fields (no secrets)")
    ap.add_argument("--url", default=None, help="laptop gateway ws://host:port")
    ap.add_argument("--device-id", default=None)
    ap.add_argument("--camera", choices=["auto", "picamera2", "emulated"], default=None)
    ap.add_argument("--video", default=None, help="emulated camera video file")
    ap.add_argument("--renderer", choices=["auto", "framebuffer", "image"], default=None)
    ap.add_argument("--render-out", default=None, help="directory for rendered PNGs (image renderer)")
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    data: dict = {}
    if args.config:
        data = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    cfg = AgentConfig(**data)
    if args.url:
        cfg.laptop_url = args.url
    if args.device_id:
        cfg.device_id = args.device_id
    if args.camera:
        cfg.camera = args.camera
    if args.video:
        cfg.video_path = args.video
    if args.renderer:
        cfg.renderer = args.renderer
    if args.render_out:
        cfg.render_out_dir = args.render_out
    if args.fps:
        cfg.fps = args.fps
    if args.max_frames is not None:
        cfg.max_frames = args.max_frames
    PiAgent(cfg).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
