"""Analytic eye geometry and inverse-M2 relative mapping; NumPy, no pixels/I/O."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from gazefix.gaze.models import angles_from_direction, direction_from_angles
from gazefix.tracking.models import EyeLandmarks, FrameGeometry, TrackingResult


@dataclass(frozen=True, slots=True)
class EyeGeometry:
    opening: np.ndarray
    ex: np.ndarray
    ey: np.ndarray
    half_width_px: float
    aperture: float
    iris_center: np.ndarray
    iris_radius: float


def derive_eye(eye: EyeLandmarks, frame: FrameGeometry) -> EyeGeometry:
    scale = np.array([frame.width, frame.height], dtype=np.float64)
    opening = eye.contour[:, :2] * scale
    axis = opening[8] - opening[0]
    width = float(np.linalg.norm(axis))
    ex = axis / width if width > 0 else np.array([1., 0.])
    if eye.side == "left":
        ex = -ex
    ey = np.array([ex[1], -ex[0]])
    aperture = float(np.mean(np.abs((opening[9:16][::-1] - opening[1:8]) @ ey))) / width if width > 0 else 0.
    iris = eye.iris[:, :2] * scale
    return EyeGeometry(opening, ex, ey, width / 2, aperture, iris[0],
                       float(np.linalg.norm(iris[1:] - iris[0], axis=1).mean()))


def polygon_area(p: np.ndarray) -> float:
    return abs(float(np.dot(p[:, 0], np.roll(p[:, 1], 1))
                     - np.dot(p[:, 1], np.roll(p[:, 0], 1)))) / 2


def edge_distance(point: np.ndarray, polygon: np.ndarray) -> float:
    ends = np.roll(polygon, -1, axis=0)
    segments = ends - polygon
    square = np.sum(segments * segments, axis=1)
    t = np.clip(np.sum((point - polygon) * segments, axis=1) / np.maximum(square, 1e-20), 0, 1)
    return float(np.linalg.norm(point - (polygon + t[:, None] * segments), axis=1).min())


def contains(point: np.ndarray, polygon: np.ndarray) -> bool:
    if edge_distance(point, polygon) < 1e-8:
        return True
    a, b = polygon, np.roll(polygon, -1, axis=0)
    crossing = (a[:, 1] > point[1]) != (b[:, 1] > point[1])
    a, b = a[crossing], b[crossing]
    intersections = a[:, 0] + (point[1] - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1])
    return bool(np.count_nonzero(point[0] < intersections) % 2)


def simple_polygon(p: np.ndarray) -> bool:
    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        if np.linalg.norm(b - a) < 1e-8:
            return False
        for j in range(i + 1, len(p)):
            if j == i + 1 or (i == 0 and j == len(p) - 1):
                continue
            c, d = p[j], p[(j + 1) % len(p)]
            if (max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0])
                    or max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1])):
                continue
            if cross(b-a, c-a) * cross(b-a, d-a) <= 0 and cross(d-c, a-c) * cross(d-c, b-c) <= 0:
                return False
    return True


def normalize_target(target: np.ndarray) -> np.ndarray | None:
    vector = np.asarray(target, dtype=np.float64)
    if vector.shape != (3,) or not np.isfinite(vector).all():
        return None
    size = float(np.max(np.abs(vector)))
    if size == 0:
        return None
    vector = vector / size
    return vector / np.linalg.norm(vector)


def head_change(tracking: TrackingResult, target: np.ndarray, strength: float,
                min_cos: float) -> tuple[np.ndarray, float, float]:
    gaze, pose = tracking.gaze, tracking.pose
    rotation = np.eye(3)
    cy = cp = 1.
    if (gaze.confidence.head_pose_applied and pose is not None
            and pose.rotation.shape == (3, 3) and np.isfinite(pose.rotation).all()
            and all(math.isfinite(a) for a in (pose.yaw_deg, pose.pitch_deg, pose.roll_deg))):
        rotation = pose.rotation
        cy = max(min_cos, abs(math.cos(math.radians(pose.yaw_deg))))
        cp = max(min_cos, abs(math.cos(math.radians(pose.pitch_deg))))
    ys, ps = angles_from_direction(gaze.direction)
    yt, pt = angles_from_direction(target)
    corrected = direction_from_angles(ys + strength * (yt - ys), ps + strength * (pt - ps))
    delta = (rotation.T @ (corrected - gaze.direction))[:2]
    return delta, cy, cp


def displacement(eye: EyeGeometry, change: tuple[np.ndarray, float, float],
                 ratio: float, gain: float) -> np.ndarray:
    delta, cy, cp = change
    return gain * eye.half_width_px / ratio * (delta[0] * eye.ex + delta[1] * cp / cy * eye.ey)


def clamp_displacement(d: np.ndarray, half_width: float, fraction: float) -> tuple[np.ndarray, bool]:
    length, limit = float(np.linalg.norm(d)), fraction * half_width
    return (d * limit / length, True) if length > limit else (d, False)


def roi_for(eye: EyeGeometry, d: np.ndarray, padding_fraction: float, edge_px: float) -> tuple[int, int, int, int]:
    padding = max(padding_fraction * 2 * eye.half_width_px, float(np.linalg.norm(d)) + edge_px + 2)
    lo = np.floor(eye.opening.min(axis=0) - padding).astype(int)
    hi = np.ceil(eye.opening.max(axis=0) + padding).astype(int) + 1
    return int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1])


def openings_overlap(a: EyeGeometry, b: EyeGeometry) -> bool:
    return bool(np.all(a.opening.max(axis=0) >= b.opening.min(axis=0))
                and np.all(b.opening.max(axis=0) >= a.opening.min(axis=0)))
