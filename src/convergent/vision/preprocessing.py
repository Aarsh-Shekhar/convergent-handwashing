"""Frame preprocessing: rotation + aspect-preserving resize with an invertible transform.

The processing frame is at most ``target_width x target_height``; the image is scaled
uniformly to fit (no stretching, no padding) so that normalized landmark coordinates keep
their aspect relationship with the original capture.
"""

from __future__ import annotations

import cv2
import numpy as np

from convergent.common.types import ImageTransform

_ROT = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


class FramePreprocessor:
    def __init__(self, target_width: int = 640, target_height: int = 480, rotation_deg: int = 0) -> None:
        if target_width <= 0 or target_height <= 0:
            raise ValueError("target size must be positive")
        if rotation_deg % 90 != 0:
            raise ValueError("rotation must be a multiple of 90 degrees")
        self.target_width = target_width
        self.target_height = target_height
        self.rotation_deg = rotation_deg % 360

    def apply(self, image: np.ndarray) -> tuple[np.ndarray, ImageTransform]:
        if image is None or image.ndim < 2:
            raise ValueError("invalid image")
        oh, ow = image.shape[:2]
        img = image
        if self.rotation_deg:
            img = cv2.rotate(img, _ROT[self.rotation_deg])
        h, w = img.shape[:2]
        scale = min(1.0, self.target_width / w, self.target_height / h)  # never upscale
        if scale != 1.0:
            nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
            interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
            img = cv2.resize(img, (nw, nh), interpolation=interp)
        else:
            nw, nh = w, h
        transform = ImageTransform(
            original_width=ow,
            original_height=oh,
            scale_x=nw / w,
            scale_y=nh / h,
            rotation_deg=self.rotation_deg,
        )
        return np.ascontiguousarray(img), transform


def processing_to_original(x: float, y: float, t: ImageTransform) -> tuple[float, float]:
    """Map a processing-frame pixel back to the original capture pixel."""
    # undo scale and crop
    xr = x / t.scale_x + t.crop_x
    yr = y / t.scale_y + t.crop_y
    # undo rotation (processing frame was rotated clockwise by rotation_deg)
    if t.rotation_deg == 0:
        return xr, yr
    ow, oh = t.original_width, t.original_height
    if t.rotation_deg == 90:  # rotated frame size (oh, ow) -> (W=oh, H=ow)
        return yr, (oh - 1) - xr
    if t.rotation_deg == 180:
        return (ow - 1) - xr, (oh - 1) - yr
    if t.rotation_deg == 270:
        return (ow - 1) - yr, xr
    raise ValueError("unsupported rotation")


def normalized_to_pixels(xn: float, yn: float, width: int, height: int) -> tuple[float, float]:
    return xn * width, yn * height
