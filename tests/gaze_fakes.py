"""Synthetic eye geometry for the gaze tests, built from independent physics.

The builder here does NOT invert the estimator's formula. It places a
three-dimensional eyeball of radius ``EYEBALL_RADIUS_MM`` behind a palpebral
fissure of width ``FISSURE_WIDTH_MM``, puts the iris centre on that sphere at
the requested eye-in-head angles, rotates the whole head rigidly, and projects
the result orthographically into the frame. The estimator then has to recover
the angles from the projected pixels, so the tests measure real model error
rather than confirming an algebraic round trip.

Anatomy, camera and frames
--------------------------
The head frame matches ``HeadPose``: ``+x`` toward the subject's left, ``+y``
up, ``+z`` where the face points. The camera frame is the same when the head
is unrotated. Projection drops the camera ``z`` and maps the camera frame into
image pixels, remembering that image rows grow DOWNWARDS while camera ``y``
points up. The projection is orthographic, matching the estimator's own
assumption; ``perspective_scale`` optionally adds a weak-perspective divide so
a test can measure what a real camera's projection does to the estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from gazefix.tracking import landmarks as topology
from gazefix.tracking.analysis import AnalysisSettings
from gazefix.tracking.models import FrameGeometry, TrackingResult, TrackingStatus
from tracking_fakes import FAKE_BACKEND_THRESHOLDS, synthetic_landmarks, tracked_result


#: Population-average anatomy the fixture is built from. The estimator's
#: default ``eye_model_ratio`` is (FISSURE_WIDTH_MM / 2) / EYEBALL_RADIUS_MM.
EYEBALL_RADIUS_MM = 12.0
FISSURE_WIDTH_MM = 30.0
#: Horizontal separation of the two eyeball centres, and how far above the
#: face origin they sit, in the head frame.
EYE_SEPARATION_MM = 62.0
EYE_HEIGHT_MM = 10.0
#: Pixels per millimetre at the nominal viewing distance. A 30 mm eye is then
#: 90 px wide, comfortably above ``tracking_min_eye_width_px``.
PIXELS_PER_MM = 3.0
#: Distance from the camera to the face origin, in millimetres, used only by
#: the optional weak-perspective projection.
NOMINAL_DEPTH_MM = 500.0


@dataclass(frozen=True, slots=True)
class GazeScene:
    """A synthetic frame: the landmarks, the head transform, and the truth."""

    landmarks: np.ndarray
    transform: np.ndarray | None
    geometry: FrameGeometry
    eye_yaw_deg: float
    eye_pitch_deg: float
    head_yaw_deg: float
    head_pitch_deg: float
    head_roll_deg: float

    def result(
        self,
        *,
        with_pose: bool = True,
        status: TrackingStatus = TrackingStatus.TRACKED,
        settings: AnalysisSettings | None = None,
        sequence: int = 1,
        camera_request_id: int = 1,
        captured_at_ns: int = 1_000_000,
    ) -> TrackingResult:
        """Run the scene through the real M1 analysis path into a result.

        The result carries ``gaze=None``: these fixtures feed the estimator
        directly, so nothing here fabricates a gaze value.
        """

        return tracked_result(
            self.landmarks,
            self.geometry,
            settings=settings,
            transform=self.transform if with_pose else None,
            status=status,
            sequence=sequence,
            camera_request_id=camera_request_id,
            captured_at_ns=captured_at_ns,
        )


def rotation_matrix(yaw_deg: float, pitch_deg: float, roll_deg: float) -> np.ndarray:
    """``Rz(roll) @ Ry(yaw) @ Rx(pitch)`` — the decomposition M1 inverts.

    Building the matrix with exactly the composition
    ``gazefix.tracking.analysis.head_pose_from_matrix`` decomposes guarantees
    the fixture's requested angles are the angles ``HeadPose`` reports, so a
    test can state head pose in degrees and trust it.
    """

    yaw, pitch, roll = map(math.radians, (yaw_deg, pitch_deg, roll_deg))
    rx = np.array(
        [[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]],
        dtype=np.float64,
    )
    ry = np.array(
        [[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]],
        dtype=np.float64,
    )
    rz = np.array(
        [[math.cos(roll), -math.sin(roll), 0], [math.sin(roll), math.cos(roll), 0], [0, 0, 1]],
        dtype=np.float64,
    )
    return rz @ ry @ rx


def gaze_scene(
    eye_yaw_deg: float = 0.0,
    eye_pitch_deg: float = 0.0,
    head_yaw_deg: float = 0.0,
    head_pitch_deg: float = 0.0,
    head_roll_deg: float = 0.0,
    *,
    geometry: FrameGeometry | None = None,
    with_iris: bool = True,
    eye_openness: float = 0.3,
    perspective_scale: bool = False,
    eyeball_radius_mm: float = EYEBALL_RADIUS_MM,
    fissure_width_mm: float = FISSURE_WIDTH_MM,
    canthus_depth_mm: float | None = None,
    pixels_per_mm: float = PIXELS_PER_MM,
) -> GazeScene:
    """A frame whose eyes look ``eye_yaw/eye_pitch`` degrees inside their sockets.

    Positive ``eye_yaw_deg`` looks toward the subject's own left, positive
    ``eye_pitch_deg`` looks up — the gaze conventions, not the head-pose ones.
    Head angles follow ``HeadPose``: positive yaw turns toward the subject's
    left, positive pitch tilts the head DOWN, positive roll rotates
    counter-clockwise in the unmirrored image.

    ``canthus_depth_mm`` is how far in FRONT of the eyeball centre the two
    palpebral corners sit, and it is the fixture's one idealisation worth
    naming. It defaults to ``eyeball_radius_mm``, which puts the corners at
    exactly the depth a centred iris reaches, so a centred iris and the corner
    midpoint are coplanar and head rotation produces no apparent iris offset
    at all. Real canthi are not at that depth, and the estimator's
    foreshortening cancellation is only exact when they are. Pass a different
    value to measure how much head rotation leaks into the "eye-in-head"
    signal once the assumption is relaxed; see docs/gaze.md section 5.

    ``pixels_per_mm`` scales the whole projection, so lowering it models a
    face further from the camera: every angle is unchanged but the eye covers
    fewer pixels, which is what ``GazeConfidence.resolution_term`` reports.
    """

    geometry = geometry or FrameGeometry(1280, 720)
    count = (
        topology.LANDMARK_COUNT_WITH_IRIS if with_iris else topology.LANDMARK_COUNT_WITHOUT_IRIS
    )
    # Start from the shared synthetic face so every non-eye landmark is
    # plausible, the face oval is well formed and quality passes.
    landmarks = synthetic_landmarks(
        count=count, face_height=0.55, eye_openness=eye_openness
    ).astype(np.float64)

    rotation = rotation_matrix(head_yaw_deg, head_pitch_deg, head_roll_deg)
    centre_px = np.array([geometry.width / 2.0, geometry.height / 2.0], dtype=np.float64)
    gaze = _direction(eye_yaw_deg, eye_pitch_deg)

    for side in ("right", "left"):
        # Subject's right eye sits at negative head-frame x (the subject's
        # right), which projects to the image's left for an unrotated head.
        sign = -1.0 if side == "right" else 1.0
        eyeball_centre = np.array(
            [sign * EYE_SEPARATION_MM / 2.0, EYE_HEIGHT_MM, 0.0], dtype=np.float64
        )
        half = fissure_width_mm / 2.0
        depth = eyeball_radius_mm if canthus_depth_mm is None else canthus_depth_mm
        # The palpebral corners sit on a plane across the front of the globe.
        # ``+x`` is the subject's left, so for the subject's RIGHT eye the outer
        # (temporal) corner is the one at more negative x, and for the LEFT eye
        # it is the one at more positive x.
        outward = np.array([sign * half, 0.0, depth], dtype=np.float64)
        inward = np.array([-sign * half, 0.0, depth], dtype=np.float64)
        outer_head = eyeball_centre + outward
        inner_head = eyeball_centre + inward
        iris_head = eyeball_centre + eyeball_radius_mm * gaze

        outer_px = _project(outer_head, rotation, centre_px, perspective_scale, pixels_per_mm)
        inner_px = _project(inner_head, rotation, centre_px, perspective_scale, pixels_per_mm)
        iris_px = _project(iris_head, rotation, centre_px, perspective_scale, pixels_per_mm)
        _write_eye(landmarks, side, outer_px, inner_px, iris_px, geometry, eye_openness, with_iris)

    normalised = landmarks.astype(np.float32)
    transform = np.eye(4, dtype=np.float32)
    transform[:3, :3] = rotation.astype(np.float32)
    transform[:3, 3] = (0.0, 0.0, -NOMINAL_DEPTH_MM / 10.0)  # centimetres, in front of the camera
    return GazeScene(
        landmarks=normalised,
        transform=transform,
        geometry=geometry,
        eye_yaw_deg=eye_yaw_deg,
        eye_pitch_deg=eye_pitch_deg,
        head_yaw_deg=head_yaw_deg,
        head_pitch_deg=head_pitch_deg,
        head_roll_deg=head_roll_deg,
    )


def _direction(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    """Unit gaze direction in the head frame (x subject's left, y up, z forward)."""

    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    return np.array(
        [math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch)],
        dtype=np.float64,
    )


def _project(
    point_head_mm: np.ndarray,
    rotation: np.ndarray,
    centre_px: np.ndarray,
    perspective_scale: bool,
    pixels_per_mm: float = PIXELS_PER_MM,
) -> np.ndarray:
    """Head-frame millimetres to image pixels (camera y up, image rows down)."""

    camera = rotation @ point_head_mm
    scale = pixels_per_mm
    if perspective_scale:
        # Weak perspective: points nearer the camera (larger camera z) project
        # slightly larger. The face sits NOMINAL_DEPTH_MM in front.
        scale *= NOMINAL_DEPTH_MM / (NOMINAL_DEPTH_MM - float(camera[2]))
    return centre_px + np.array([camera[0] * scale, -camera[1] * scale], dtype=np.float64)


def _write_eye(
    landmarks: np.ndarray,
    side: str,
    outer_px: np.ndarray,
    inner_px: np.ndarray,
    iris_px: np.ndarray,
    geometry: FrameGeometry,
    openness: float,
    with_iris: bool,
) -> None:
    """Overwrite one eye's contour and iris with the projected geometry."""

    contour = topology.eye_contour(side)
    scale = np.array([geometry.width, geometry.height], dtype=np.float64)
    outer, inner, iris = outer_px / scale, inner_px / scale, iris_px / scale

    axis = inner - outer
    width = float(np.hypot(axis[0] * geometry.width, axis[1] * geometry.height))
    # Lid separation perpendicular to the eye axis, in pixels, so openness
    # survives head roll.
    unit = axis / (np.linalg.norm(axis) or 1.0)
    perpendicular = np.array([unit[1] * geometry.height, -unit[0] * geometry.width])
    perpendicular = perpendicular / (np.linalg.norm(perpendicular) or 1.0)
    perpendicular = perpendicular / scale  # back to normalised units

    landmarks[contour[topology.CONTOUR_OUTER_CORNER_POSITION], :2] = outer
    landmarks[contour[topology.CONTOUR_INNER_CORNER_POSITION], :2] = inner
    lid_count = len(topology.CONTOUR_LOWER_LID_POSITIONS)
    fraction = np.arange(1, lid_count + 1) / (lid_count + 1.0)
    profile = np.sin(math.pi * fraction)
    separation = profile * (openness * width / profile.mean())
    for k, position in enumerate(topology.CONTOUR_LOWER_LID_POSITIONS):  # outer -> inner
        base = outer + axis * fraction[k]
        landmarks[contour[position], :2] = base + perpendicular * (separation[k] / 2.0)
    for k, position in enumerate(topology.CONTOUR_UPPER_LID_POSITIONS):  # inner -> outer
        j = lid_count - 1 - k
        base = outer + axis * fraction[j]
        landmarks[contour[position], :2] = base - perpendicular * (separation[j] / 2.0)

    if with_iris:
        indices = topology.iris_indices(side)
        landmarks[indices[0], :2] = iris
        radius = 0.12 * width
        for k, index in enumerate(indices[1:]):
            theta = k * math.pi / 2.0
            landmarks[index, :2] = iris + np.array(
                [radius * math.cos(theta) / geometry.width, radius * math.sin(theta) / geometry.height]
            )


__all__ = [
    "EYEBALL_RADIUS_MM",
    "FAKE_BACKEND_THRESHOLDS",
    "FISSURE_WIDTH_MM",
    "MEASURED_CANTHUS_DEPTH_MM",
    "GazeScene",
    "gaze_scene",
    "rotation_matrix",
]


#: Depth of the palpebral corners in front of the eyeball centre, in the same
#: millimetres as ``EYEBALL_RADIUS_MM``. Measured, not assumed: MediaPipe's own
#: model-relative landmark ``z`` puts the canthal midpoint about 0.2 of the
#: lever arm behind the iris centre on the licensed fixture face (depth ratio
#: 0.755 for the right eye, 0.808 for the left), which is 9.4 mm here. Passing
#: this to ``gaze_scene(canthus_depth_mm=...)`` reproduces the realistic
#: geometry rather than the coplanar idealisation the default uses; see
#: docs/gaze.md section 5 and
#: tests/test_real_model_tracking.py::test_real_canthal_depth_matches_the_documented_ratio.
MEASURED_CANTHUS_DEPTH_MM = 9.4
