"""Fit the camera's green channel from red and blue, for ``projector.graphics.green_fit``.

Use footage of the wash area with hands in view and the projector OFF (or showing nothing).
The fit belongs to one camera and its white balance, so redo it for the Arducam on hardware day.

    python scripts/fit_green.py --video data/own/down1/*.mp4
    python scripts/fit_green.py --device 1 --seconds 10
"""

from __future__ import annotations

import argparse
import time

import cv2
import numpy as np

from convergent.vision.projector_light import fit_green


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", nargs="*", default=[], help="video files recorded with the projector off")
    ap.add_argument("--device", type=int, default=None, help="camera index to sample live instead")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--per-video", type=int, default=12, help="frames sampled per video")
    a = ap.parse_args()
    frames: list[np.ndarray] = []
    for path in a.video:
        cap = cv2.VideoCapture(path)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for i in np.linspace(0, max(n - 1, 0), a.per_video).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, f = cap.read()
            if ok:
                frames.append(f[::2, ::2])
        cap.release()
    if a.device is not None:
        cap = cv2.VideoCapture(a.device)
        end = time.monotonic() + a.seconds
        while time.monotonic() < end:
            ok, f = cap.read()
            if ok:
                frames.append(f[::2, ::2])
            time.sleep(0.5)
        cap.release()
    if not frames:
        print("no frames: give --video or --device")
        return 1
    a_, b_, c_ = fit_green(frames)
    px = np.concatenate([f.reshape(-1, 3) for f in frames]).astype(np.float32)
    err = px[:, 1] - (a_ * px[:, 2] + b_ * px[:, 0] + c_)
    print(f"{len(frames)} frames: green = {a_:.3f} R + {b_:.3f} B + {c_:.1f}")
    print(f"error median {np.median(np.abs(err)):.1f}, p95 {np.percentile(np.abs(err), 95):.1f} (of 255); "
          f"pixels that would look projector-lit (> 25): {np.mean(err > 25):.2%}")
    print(f"configs/development.yaml -> projector.graphics.green_fit: [{a_:.3f}, {b_:.3f}, {c_:.1f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
