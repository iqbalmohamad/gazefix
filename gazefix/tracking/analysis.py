"""Turn a backend's raw detection into the ``TrackingResult`` contract.

Backend-independent: validity, quality, eye extraction and head-pose angles
are computed here from plain arrays, so they are exercised by deterministic
tests with synthetic landmark sets and apply equally to any backend.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import NDArray

from gazefix.tracking import landmarks as topology
from gazefix.tracking.models import (
    Array,
    EyeLandmarks,
    FrameGeometry,
    HeadPose,
    Side,
    TrackingQuality,
    in_frame,
    is_finite,
    pixel_distance,
    readonly,
)


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    """Thresholds that decide validity; documented in docs/tracking.md."""

    min_quality: float = 0.5
    min_eye_width_px: float = 12.0
    size_floor_fraction: float = 0.10
    size_full_fraction: float = 0.20


class MalformedLandmarks(ValueError):
    """The backend returned landmarks that cannot be interpreted."""


def validate_landmarks(points: object) -> tuple[Array, bool]:
    """Return ``(readonly (N,3) float32, iris_available)`` or raise ``MalformedLandmarks``."""

    try:
        array = np.asarray(points, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise MalformedLandmarks(f"landmarks are not numeric: {exc}") from exc
    if array.ndim != 2 or array.shape[1] != 3:
        raise MalformedLandmarks(f"landmarks must be (N, 3), got {array.shape}")
    count = array.shape[0]
    if count == topology.LANDMARK_COUNT_WITH_IRIS:
        iris_available = True
    elif count == topology.LANDMARK_COUNT_WITHOUT_IRIS:
        iris_available = False
    else:
        raise MalformedLandmarks(
            f"landmarks must have {topology.LANDMARK_COUNT_WITH_IRIS} or "
            f"{topology.LANDMARK_COUNT_WITHOUT_IRIS} points, got {count}"
        )
    if not is_finite(array):
        raise MalformedLandmarks("landmarks contain NaN or infinite values")
    return readonly(array), iris_available


def extract_eye(
    landmarks: Array,
    side: Side,
    geometry: FrameGeometry,
    settings: AnalysisSettings,
    iris_available: bool,
) -> EyeLandmarks:
    contour = readonly(landmarks[list(topology.eye_contour(side))], (topology.EYE_CONTOUR_POINTS, 3))
    iris = (
        readonly(landmarks[list(topology.iris_indices(side))], (topology.IRIS_POINTS_PER_EYE, 3))
        if iris_available
        else None
    )
    outer = contour[topology.CONTOUR_OUTER_CORNER_POSITION]
    inner = contour[topology.CONTOUR_INNER_CORNER_POSITION]
    width_px = pixel_distance(outer, inner, geometry)
    lower = contour[list(topology.CONTOUR_LOWER_LID_POSITIONS)]
    upper = contour[list(topology.CONTOUR_UPPER_LID_POSITIONS)][::-1]  # both outer -> inner
    separation_px = float(np.mean(np.abs(upper[:, 1] - lower[:, 1]))) * geometry.height
    openness = separation_px / width_px if width_px > 0 else 0.0
    inside = bool(np.all(in_frame(contour))) and (iris is None or bool(np.all(in_frame(iris))))
    valid = inside and width_px >= settings.min_eye_width_px
    return EyeLandmarks(
        side=side,
        contour=contour,
        iris=iris,
        openness=openness,
        width_px=width_px,
        valid=valid,
    )


def compute_quality(
    landmarks: Array,
    geometry: FrameGeometry,
    settings: AnalysisSettings,
    backend_thresholds: tuple[float, float, float],
) -> TrackingQuality:
    mesh = landmarks[: topology.LANDMARK_COUNT_WITHOUT_IRIS]
    in_frame_fraction = float(np.mean(in_frame(landmarks)))
    face_height_fraction = float(mesh[:, 1].max() - mesh[:, 1].min())
    span = settings.size_full_fraction - settings.size_floor_fraction
    size_term = (
        1.0 if span <= 0 else (face_height_fraction - settings.size_floor_fraction) / span
    )
    size_term = min(1.0, max(0.0, size_term))
    score = min(in_frame_fraction, size_term)
    return TrackingQuality(
        score=score,
        in_frame_fraction=in_frame_fraction,
        face_height_fraction=face_height_fraction,
        backend_thresholds=backend_thresholds,
    )


def head_pose_from_matrix(matrix: object) -> HeadPose | None:
    """Euler angles of a 4×4 (or 3×3) face-to-camera transform; ``None`` if unusable.

    Decomposition ``R = Rz(roll) · Ry(yaw) · Rx(pitch)`` in the right-handed
    camera frame (x right, y up, z toward the viewer); sign meanings are
    documented on ``HeadPose``.
    """

    try:
        m = np.asarray(matrix, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if m.shape == (4, 4):
        rotation, translation = m[:3, :3], m[:3, 3]
    elif m.shape == (3, 3):
        rotation, translation = m, np.zeros(3)
    else:
        return None
    if not np.all(np.isfinite(m)) or abs(np.linalg.det(rotation) - 1.0) > 0.05:
        return None
    sin_yaw = -rotation[2, 0]
    sin_yaw = max(-1.0, min(1.0, float(sin_yaw)))
    yaw = math.asin(sin_yaw)
    if abs(math.cos(yaw)) > 1e-6:
        pitch = math.atan2(rotation[2, 1], rotation[2, 2])
        roll = math.atan2(rotation[1, 0], rotation[0, 0])
    else:  # gimbal lock: yaw at ±90°, pitch and roll are not separable
        pitch = math.atan2(-rotation[1, 2], rotation[1, 1])
        roll = 0.0
    return HeadPose(
        yaw_deg=math.degrees(yaw),
        pitch_deg=math.degrees(pitch),
        roll_deg=math.degrees(roll),
        rotation=readonly(rotation, (3, 3)),
        translation_cm=readonly(translation, (3,)),
    )


def face_bbox(landmarks: Array) -> tuple[float, float, float, float]:
    """``(x_min, y_min, x_max, y_max)`` of the 468 mesh points, normalised."""

    mesh = landmarks[: topology.LANDMARK_COUNT_WITHOUT_IRIS]
    return (
        float(mesh[:, 0].min()),
        float(mesh[:, 1].min()),
        float(mesh[:, 0].max()),
        float(mesh[:, 1].max()),
    )


def face_center_and_area(landmarks: Array) -> tuple[tuple[float, float], float]:
    x0, y0, x1, y1 = face_bbox(landmarks)
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0), max(0.0, x1 - x0) * max(0.0, y1 - y0)
