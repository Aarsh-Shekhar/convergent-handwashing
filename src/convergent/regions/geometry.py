"""Landmark-derived hand geometry: orientation, approximate region polygons and anchors.

All geometry is 2-D in normalized image coordinates. Polygons are *approximations* built
from the 21 MediaPipe landmarks – they are not skin segmentation and must not be presented
as exact surface extents. ``z`` is only used for a coarse palm-vs-back heuristic.

MediaPipe landmark indices::

    0 wrist | 1-4 thumb (CMC, MCP, IP, TIP) | 5-8 index | 9-12 middle | 13-16 ring | 17-20 pinky
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from convergent.common.types import HandObservation, HandSide, Region

WRIST = 0
THUMB = (1, 2, 3, 4)
INDEX = (5, 6, 7, 8)
MIDDLE = (9, 10, 11, 12)
RING = (13, 14, 15, 16)
PINKY = (17, 18, 19, 20)
FINGERTIPS = (4, 8, 12, 16, 20)
PALM_OUTLINE = (0, 1, 5, 9, 13, 17)  # wrist, thumb CMC, MCPs
FINGER_CHAIN = (5, 6, 7, 8, 12, 16, 20, 19, 18, 17, 13, 9)  # loop around the four fingers


@dataclass
class RegionPolygon:
    region: Region
    side: HandSide
    points: np.ndarray  # (N,2) normalized
    anchor: np.ndarray  # (2,) centroid
    support: float  # 0..1 how well the landmarks support this polygon (in-frame fraction)

    def contains(self, x: float, y: float) -> bool:
        return point_in_polygon(np.array([x, y]), self.points)


@dataclass
class HandGeometry:
    side: HandSide
    palm_center: np.ndarray
    hand_centroid: np.ndarray
    orientation_deg: float  # angle of wrist -> middle MCP vector, image coords (y down)
    hand_length: float  # wrist -> middle fingertip, normalized units
    palm_facing_camera: bool | None  # heuristic; None if undeterminable
    bbox: tuple[float, float, float, float]
    polygons: dict[Region, RegionPolygon]

    def anchor(self, region: Region) -> np.ndarray | None:
        p = self.polygons.get(region)
        return None if p is None else p.anchor


def point_in_polygon(p: np.ndarray, poly: np.ndarray) -> bool:
    x, y = float(p[0]), float(p[1])
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _in_frame_fraction(pts: np.ndarray) -> float:
    return float(np.mean((pts[:, 0] >= 0) & (pts[:, 0] <= 1) & (pts[:, 1] >= 0) & (pts[:, 1] <= 1)))


def palm_facing_camera(lm: np.ndarray, side: HandSide) -> bool | None:
    """Coarse heuristic from the 2-D winding of (wrist, index MCP, pinky MCP).

    For a RIGHT hand with the palm facing the camera (image y down, non-mirrored), the triangle
    wrist -> index MCP -> pinky MCP winds one way; the back of the hand winds the other way.
    The LEFT hand is mirrored. Not reliable for extreme rotations – callers treat it as a hint.
    """
    if side not in (HandSide.LEFT, HandSide.RIGHT):
        return None
    w, i, p = lm[WRIST, :2], lm[INDEX[0], :2], lm[PINKY[0], :2]
    cross = (i[0] - w[0]) * (p[1] - w[1]) - (i[1] - w[1]) * (p[0] - w[0])
    if abs(cross) < 1e-5:
        return None
    facing_right = cross < 0
    return facing_right if side == HandSide.RIGHT else not facing_right


def compute_geometry(hand: HandObservation) -> HandGeometry:
    lm = hand.landmark_array()
    pts2 = lm[:, :2]
    wrist, mid_mcp, mid_tip = pts2[WRIST], pts2[MIDDLE[0]], pts2[MIDDLE[3]]
    v = mid_mcp - wrist
    orientation = float(np.degrees(np.arctan2(v[1], v[0])))
    hand_len = float(np.linalg.norm(mid_tip - wrist))
    palm_poly = pts2[list(PALM_OUTLINE)]
    palm_center = palm_poly.mean(axis=0)
    facing = palm_facing_camera(lm, hand.side)
    polys: dict[Region, RegionPolygon] = {}
    # palm / back share the same outline; which one faces the camera is a heuristic
    for region, visible in ((Region.PALM, facing is not False), (Region.BACK_OF_HAND, facing is not True)):
        polys[region] = RegionPolygon(region, hand.side, palm_poly, palm_center,
                                      _in_frame_fraction(palm_poly) * (1.0 if visible else 0.5))
    thumb_pts = pts2[list(THUMB)]
    # thumb polygon: thicken the thumb chain by a fraction of hand length
    polys[Region.THUMB] = RegionPolygon(Region.THUMB, hand.side, _thicken(thumb_pts, 0.08 * hand_len), thumb_pts.mean(axis=0), _in_frame_fraction(thumb_pts))
    finger_pts = pts2[list(FINGER_CHAIN)]
    polys[Region.FINGERS] = RegionPolygon(Region.FINGERS, hand.side, finger_pts, pts2[[6, 10, 14, 18]].mean(axis=0), _in_frame_fraction(finger_pts))
    tip_pts = pts2[list(FINGERTIPS)]
    polys[Region.FINGERTIPS] = RegionPolygon(Region.FINGERTIPS, hand.side, _thicken(tip_pts, 0.06 * hand_len), tip_pts.mean(axis=0), _in_frame_fraction(tip_pts))
    return HandGeometry(side=hand.side, palm_center=palm_center, hand_centroid=pts2.mean(axis=0), orientation_deg=orientation,
                        hand_length=hand_len, palm_facing_camera=facing,
                        bbox=(hand.bbox.x_min, hand.bbox.y_min, hand.bbox.x_max, hand.bbox.y_max), polygons=polys)


def _thicken(chain: np.ndarray, width: float) -> np.ndarray:
    """Turn a poly-line into a closed polygon by offsetting both sides along the normals."""
    if len(chain) < 2:
        return chain
    d = np.gradient(chain, axis=0)
    norms = np.linalg.norm(d, axis=1, keepdims=True)
    d = d / np.where(norms > 1e-9, norms, 1.0)
    n = np.stack([-d[:, 1], d[:, 0]], axis=1) * (width / 2.0)
    return np.concatenate([chain + n, (chain - n)[::-1]], axis=0)


def region_anchors(hand: HandObservation) -> dict[Region, tuple[float, float]]:
    g = compute_geometry(hand)
    return {r: (float(p.anchor[0]), float(p.anchor[1])) for r, p in g.polygons.items()}
