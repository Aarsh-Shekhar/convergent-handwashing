"""Guided recording of labelled washing clips from a local webcam (training/evaluation data).

One *round* = one short clip per class (the seven scored techniques plus ``none`` = not
washing). Layout::

    data/own/<round_id>/round.json                 view, device, fps, created_at
    data/own/<round_id>/<class>.mp4                the clip (no audio)
    data/own/<round_id>/<class>.json               label, capture timestamps per written frame

Clips stay on this machine (``data/own/`` is git-ignored). Nothing is uploaded.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from convergent.common.timestamps import utc_now_iso
from convergent.detection.labels import NONE, SCORED_TECHNIQUES

RECORD_CLASSES: tuple[str, ...] = SCORED_TECHNIQUES + (NONE,)

PROMPTS: dict[str, tuple[str, str]] = {
    "palm_to_palm": ("PALM TO PALM", "rub palms together"),
    "back_of_hand": ("BACK OF HAND", "palm over back of other hand, switch hands halfway"),
    "interlaced_fingers": ("INTERLACED FINGERS", "palm to palm, fingers laced, slide"),
    "backs_of_fingers": ("BACKS OF FINGERS", "fingers hooked together, rub knuckles in palms"),
    "thumb_rubbing": ("THUMBS", "wrap hand around thumb and twist, switch halfway"),
    "fingertip_rubbing": ("FINGERTIPS", "rub fingertips in other palm, switch halfway"),
    "wrist_rubbing": ("WRISTS", "wrap hand around wrist and twist, switch halfway"),
    "none": ("NOT WASHING", "hands apart: hold still, wave, reach for tap, shake dry"),
}


def _put(img: np.ndarray, text: str, org: tuple[int, int], scale: float, color: tuple[int, int, int], thick: int = 2) -> None:
    import cv2

    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def record_round(out_root: Path, round_id: str, device: int = 0, view: str = "down", seconds: float = 15.0, ready_s: float = 5.0,
                 fps: float = 15.0, width: int = 640, classes: list[str] | None = None) -> Path:
    """Record one clip per class. Returns the round directory. Esc stops early (finished clips are kept)."""
    import cv2

    classes = list(classes or RECORD_CLASSES)
    bad = [c for c in classes if c not in RECORD_CLASSES]
    if bad:
        raise ValueError(f"unknown classes {bad}; choose from {list(RECORD_CLASSES)}")
    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        raise RuntimeError(f"could not open webcam index {device} (run this from your own Terminal app; try another --device)")
    ok, first = cap.read()
    if not ok or first is None:
        cap.release()
        raise RuntimeError(f"webcam index {device} returned no frame")
    h0, w0 = first.shape[:2]
    scale = width / float(w0)
    size = (int(width), int(round(h0 * scale / 2) * 2))
    rdir = Path(out_root) / round_id
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "round.json").write_text(json.dumps({"round_id": round_id, "view": view, "device": device, "fps": fps, "width": size[0],
                                                 "height": size[1], "seconds": seconds, "created_at": utc_now_iso()}, indent=2), encoding="utf-8")
    win = "record washing clips (Esc = stop)"
    period = 1.0 / fps
    stopped = False
    try:
        for i, cls in enumerate(classes):
            title, hint = PROMPTS[cls]
            writer = None
            stamps: list[float] = []
            t_phase = time.monotonic()
            t_rec0: float | None = None
            next_write = 0.0
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
                now = time.monotonic()
                show = frame.copy()
                _put(show, f"{i + 1}/{len(classes)}  {title}", (12, 34), 0.9, (255, 255, 255))
                _put(show, hint, (12, 62), 0.55, (255, 255, 255), 1)
                if t_rec0 is None:
                    left = ready_s - (now - t_phase)
                    _put(show, f"get ready: {max(0, int(np.ceil(left)))}", (12, size[1] - 20), 1.0, (0, 215, 255))
                    if left <= 0:
                        t_rec0 = now
                        writer = cv2.VideoWriter(str(rdir / f"{cls}.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
                else:
                    el = now - t_rec0
                    if el >= next_write and writer is not None:
                        writer.write(frame)  # the clean frame, without the text overlay
                        stamps.append(round(el, 4))
                        next_write = max(next_write + period, el - period)
                    cv2.circle(show, (size[0] - 28, 28), 12, (0, 0, 255), -1)
                    _put(show, f"REC {max(0.0, seconds - el):4.1f}s", (12, size[1] - 20), 1.0, (0, 0, 255))
                    if el >= seconds:
                        break
                cv2.imshow(win, show)
                if cv2.waitKey(1) & 0xFF == 27:
                    stopped = True
                    break
            if writer is not None:
                writer.release()
            if stopped:
                (rdir / f"{cls}.mp4").unlink(missing_ok=True)  # partial clip
                break
            (rdir / f"{cls}.json").write_text(json.dumps({"label": cls, "round_id": round_id, "view": view, "fps": fps,
                                                          "frames": len(stamps), "timestamps": stamps}), encoding="utf-8")
            print(f"  saved {cls}: {len(stamps)} frames")
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return rdir
