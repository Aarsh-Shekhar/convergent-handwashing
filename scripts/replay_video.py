#!/usr/bin/env python
"""Replay a prerecorded video through the integrated pipeline (thin wrapper over the CLI).

    python scripts/replay_video.py --video data/samples/handwashing_missing_step.mp4 --save-results
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from convergent.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["replay", *sys.argv[1:]]))
