"""Synthetic landmark sets and raw-detection fakes shared by the tracking tests.

Nothing here imports MediaPipe or touches hardware. The arrays are laid out
from the canonical topology in ``gazefix.tracking.landmarks`` so the
analysis, selection, stabiliser and overlay code can be exercised
deterministically with faces whose geometry the tests can reason about.
"""

from __future__ import annotations

import math

import numpy as np

from gazefix.tracking import landmarks as topology
from gazefix.tracking.analysis import (
    AnalysisSettings,
    compute_quality,
    extract_eye,
    head_pose_from_matrix,
    validate_landmarks,
)
from gazefix.tracking.models import FrameGeometry, TrackingResult, TrackingStatus
from gazefix.tracking.tracker import RawFace


# Layout of the synthetic face as fractions of the face ellipse's half-axes
# (``hx`` horizontally, ``hy`` vertically).
EYE_ROW = -0.3  # eye centres sit this far above the face centre (x hy)
EYE_OFFSET = 0.5  # eye centres sit this far either side of the face centre (x hx)
EYE_WIDTH = 0.45  # corner-to-corner eye width (x hx)
IRIS_RADIUS = 0.12  # iris contour radius as a fraction of the eye width
FILLER_RADIUS = 0.9  # generic mesh points stay strictly inside the oval
FAKE_BACKEND_THRESHOLDS = (0.5, 0.5, 0.5)


def synthetic_landmarks(
    center: tuple[float, float] = (0.5, 0.5),
    face_height: float = 0.3,
    aspect: float = 0.75,
    count: int = topology.LANDMARK_COUNT_WITH_IRIS,
    eye_openness: float = 0.3,
    seed: int = 0,
) -> np.ndarray:
    """A plausible ``(count, 3)`` float32 landmark set in normalised frame units.

    The face is an ellipse around ``center`` that is ``face_height`` of the
    frame tall and ``aspect * face_height`` wide. ``FACE_OVAL`` runs around
    that ellipse (forehead 10 at the top, chin 152 at the bottom, the cheek
    edges at the sides), the nose tip sits at the centre, and the eyes are
    small eye-shaped loops: the subject's RIGHT eye on the image's LEFT
    (smaller x) and the LEFT eye on the image's right, upper lid above lower
    lid by a mean of ``eye_openness`` times the eye width, iris centre and
    contour (478-point sets only) at each eye's centre. Every other mesh point
    is scattered inside the oval by a seeded generator, so the result is
    deterministic for equal arguments.
    """

    if count not in (topology.LANDMARK_COUNT_WITH_IRIS, topology.LANDMARK_COUNT_WITHOUT_IRIS):
        raise ValueError(f"count must be 478 or 468, got {count}")
    cx, cy = float(center[0]), float(center[1])
    hy = face_height / 2.0
    hx = aspect * hy
    mesh_count = topology.LANDMARK_COUNT_WITHOUT_IRIS
    rng = np.random.default_rng(seed)
    points = np.zeros((count, 3), dtype=np.float64)

    # Generic mesh points: scattered strictly inside the oval.
    radius = FILLER_RADIUS * np.sqrt(rng.random(mesh_count))
    angle = rng.random(mesh_count) * (2.0 * math.pi)
    points[:mesh_count, 0] = cx + hx * radius * np.cos(angle)
    points[:mesh_count, 1] = cy + hy * radius * np.sin(angle)

    # Face oval: clockwise in image coordinates, with the four named points
    # exactly at the top, image-right, bottom and image-left of the ellipse.
    oval = topology.FACE_OVAL
    anchors = [
        0,
        oval.index(topology.LEFT_FACE_EDGE),
        oval.index(topology.CHIN),
        oval.index(topology.RIGHT_FACE_EDGE),
        len(oval),
    ]
    anchor_angles = [-math.pi / 2, 0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
    angles = np.interp(np.arange(len(oval)), anchors, anchor_angles)
    points[list(oval), 0] = cx + hx * np.cos(angles)
    points[list(oval), 1] = cy + hy * np.sin(angles)
    points[topology.FOREHEAD, :2] = (cx, cy - hy)
    points[topology.CHIN, :2] = (cx, cy + hy)
    points[topology.NOSE_TIP, :2] = (cx, cy)

    eye_y = cy + EYE_ROW * hy
    eye_width = EYE_WIDTH * hx
    with_iris = count == topology.LANDMARK_COUNT_WITH_IRIS
    _place_eye(points, "right", cx - EYE_OFFSET * hx, eye_y, eye_width, eye_openness, with_iris)
    _place_eye(points, "left", cx + EYE_OFFSET * hx, eye_y, eye_width, eye_openness, with_iris)

    # Depth: a dome over the ellipse, nose tip closest to the camera (most negative).
    rho_squared = ((points[:, 0] - cx) / hx) ** 2 + ((points[:, 1] - cy) / hy) ** 2
    points[:, 2] = -0.5 * hx * np.sqrt(np.clip(1.0 - rho_squared, 0.0, None))
    return points.astype(np.float32)


def _place_eye(
    points: np.ndarray,
    side: str,
    eye_x: float,
    eye_y: float,
    width: float,
    openness: float,
    with_iris: bool,
) -> None:
    contour = topology.eye_contour(side)
    # The outer (temporal) corner of the subject's right eye is on the image's
    # left; for the left eye it is on the image's right.
    outward = -1.0 if side == "right" else 1.0
    outer_x = eye_x + outward * width / 2.0
    inner_x = eye_x - outward * width / 2.0
    lid_count = len(topology.CONTOUR_LOWER_LID_POSITIONS)
    fraction = np.arange(1, lid_count + 1) / (lid_count + 1.0)  # outer -> inner
    profile = np.sin(math.pi * fraction)
    separation = profile * (openness * width / profile.mean())
    lid_x = outer_x + (inner_x - outer_x) * fraction

    points[contour[topology.CONTOUR_OUTER_CORNER_POSITION], :2] = (outer_x, eye_y)
    points[contour[topology.CONTOUR_INNER_CORNER_POSITION], :2] = (inner_x, eye_y)
    for k, position in enumerate(topology.CONTOUR_LOWER_LID_POSITIONS):  # outer -> inner
        points[contour[position], :2] = (lid_x[k], eye_y + separation[k] / 2.0)
    for k, position in enumerate(topology.CONTOUR_UPPER_LID_POSITIONS):  # inner -> outer
        j = lid_count - 1 - k
        points[contour[position], :2] = (lid_x[j], eye_y - separation[j] / 2.0)

    if with_iris:
        iris = topology.iris_indices(side)
        points[iris[0], :2] = (eye_x, eye_y)
        radius = IRIS_RADIUS * width
        for k, index in enumerate(iris[1:]):
            theta = k * math.pi / 2.0
            points[index, :2] = (eye_x + radius * math.cos(theta), eye_y + radius * math.sin(theta))


def shift(landmarks: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """A float32 copy of ``landmarks`` translated by ``(dx, dy)`` in normalised units."""

    moved = np.array(landmarks, dtype=np.float32, copy=True)
    moved[:, 0] += np.float32(dx)
    moved[:, 1] += np.float32(dy)
    return moved


def identity_transform() -> np.ndarray:
    """A 4x4 float32 face-to-camera matrix: no rotation, face 45 cm in front of the camera."""

    transform = np.eye(4, dtype=np.float32)
    transform[:3, 3] = (0.0, 0.0, -45.0)
    return transform


def make_raw_face(landmarks: np.ndarray, transform: np.ndarray | None = None) -> RawFace:
    return RawFace(landmarks=np.asarray(landmarks, dtype=np.float32), transform=transform)


def tracked_result(
    landmarks: np.ndarray,
    geometry: FrameGeometry,
    *,
    settings: AnalysisSettings | None = None,
    transform: np.ndarray | None = None,
    status: TrackingStatus = TrackingStatus.TRACKED,
    sequence: int = 1,
    captured_at_ns: int = 1_000_000,
    camera_request_id: int = 1,
    faces_detected: int = 1,
    stabilized: bool = False,
) -> TrackingResult:
    """Run ``landmarks`` through the analysis path into a landmark-bearing result."""

    if not status.has_landmarks:
        raise ValueError(f"{status.value} results carry no landmarks")
    settings = settings or AnalysisSettings()
    points, iris_available = validate_landmarks(landmarks)
    return TrackingResult(
        status=status,
        capture_sequence=sequence,
        captured_at_ns=captured_at_ns,
        camera_request_id=camera_request_id,
        geometry=geometry,
        faces_detected=faces_detected,
        landmarks=points,
        left_eye=extract_eye(points, "left", geometry, settings, iris_available),
        right_eye=extract_eye(points, "right", geometry, settings, iris_available),
        iris_available=iris_available,
        pose=None if transform is None else head_pose_from_matrix(transform),
        quality=compute_quality(points, geometry, settings, FAKE_BACKEND_THRESHOLDS),
        stabilized=stabilized,
    )
