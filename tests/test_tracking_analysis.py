"""Backend-independent analysis: validation, eyes, quality, head pose and bounding boxes."""

from __future__ import annotations

import math

import numpy as np
import pytest

from gazefix.tracking import landmarks as topology
from gazefix.tracking.analysis import (
    AnalysisSettings,
    MalformedLandmarks,
    compute_quality,
    extract_eye,
    face_bbox,
    face_center_and_area,
    head_pose_from_matrix,
    validate_landmarks,
)
from gazefix.tracking.models import FrameGeometry, HeadPose
from tracking_fakes import identity_transform, shift, synthetic_landmarks


THRESHOLDS = (0.5, 0.6, 0.7)
SQUARE = FrameGeometry(640, 640)
WIDE = FrameGeometry(640, 480)


# --- validate_landmarks ---


def test_validate_accepts_478_points_with_iris_available() -> None:
    points, iris_available = validate_landmarks(synthetic_landmarks(count=478))
    assert iris_available is True
    assert points.shape == (478, 3)


def test_validate_accepts_468_points_without_iris() -> None:
    points, iris_available = validate_landmarks(synthetic_landmarks(count=468))
    assert iris_available is False
    assert points.shape == (468, 3)


def test_validate_returns_a_readonly_float32_copy() -> None:
    source = synthetic_landmarks().astype(np.float64)
    points, _ = validate_landmarks(source)

    assert points.dtype == np.float32
    assert not points.flags.writeable
    assert points is not source
    original = points.copy()
    source[0, 0] = 99.0
    assert np.array_equal(points, original)
    with pytest.raises(ValueError):
        points[0, 0] = 1.0


def test_validate_accepts_plain_python_sequences() -> None:
    points, iris_available = validate_landmarks(synthetic_landmarks().tolist())
    assert iris_available is True
    assert points.shape == (478, 3) and points.dtype == np.float32


def test_malformed_landmarks_is_a_value_error() -> None:
    assert issubclass(MalformedLandmarks, ValueError)


@pytest.mark.parametrize(
    ("description", "points"),
    [
        ("100 points", np.zeros((100, 3), dtype=np.float32)),
        ("477 points", np.zeros((477, 3), dtype=np.float32)),
        ("(N, 2) shape", np.zeros((478, 2), dtype=np.float32)),
        ("(N, 4) shape", np.zeros((478, 4), dtype=np.float32)),
        ("flat vector", np.zeros(478 * 3, dtype=np.float32)),
        ("3-D array", np.zeros((1, 478, 3), dtype=np.float32)),
        ("empty", np.zeros((0, 3), dtype=np.float32)),
    ],
)
def test_validate_rejects_bad_shapes(description: str, points: np.ndarray) -> None:
    with pytest.raises(MalformedLandmarks):
        validate_landmarks(points)


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_validate_rejects_non_finite_values(bad_value: float) -> None:
    points = synthetic_landmarks()
    points[200, 1] = bad_value
    with pytest.raises(MalformedLandmarks):
        validate_landmarks(points)


@pytest.mark.parametrize(
    "points",
    [
        [["a", "b", "c"]] * 478,
        object(),
        None,
        "not landmarks",
    ],
)
def test_validate_rejects_non_numeric_input(points: object) -> None:
    with pytest.raises(MalformedLandmarks):
        validate_landmarks(points)


# --- extract_eye ---


def _eyes(landmarks: np.ndarray, geometry: FrameGeometry, settings: AnalysisSettings | None = None):
    points, iris_available = validate_landmarks(landmarks)
    settings = settings or AnalysisSettings()
    return (
        extract_eye(points, "right", geometry, settings, iris_available),
        extract_eye(points, "left", geometry, settings, iris_available),
    )


def test_extract_eye_sides_are_anatomical() -> None:
    right, left = _eyes(synthetic_landmarks(), WIDE)

    assert right.side == "right" and left.side == "left"
    # Unmirrored frame: the subject's right eye is on the image's left.
    assert right.outer_corner[0] < left.outer_corner[0]
    assert right.outer_corner[0] < right.inner_corner[0] < left.inner_corner[0] < left.outer_corner[0]
    for eye in (right, left):
        assert eye.contour.shape == (topology.EYE_CONTOUR_POINTS, 3)
        assert not eye.contour.flags.writeable
        assert np.all(eye.upper_lid[:, 1] < eye.lower_lid[:, 1])  # image y grows downwards


def test_extract_eye_openness_matches_the_synthetic_aperture() -> None:
    for configured in (0.1, 0.3, 0.4):
        right, left = _eyes(synthetic_landmarks(eye_openness=configured), SQUARE)
        assert right.openness == pytest.approx(configured, rel=0.05)
        assert left.openness == pytest.approx(configured, rel=0.05)


def test_extract_eye_openness_is_a_pixel_ratio() -> None:
    """Both terms are in pixels, so a non-square frame scales the ratio by height/width."""

    right, _ = _eyes(synthetic_landmarks(eye_openness=0.3), WIDE)
    assert right.openness == pytest.approx(0.3 * WIDE.height / WIDE.width, rel=0.05)


def test_extract_eye_width_px_follows_the_geometry() -> None:
    right_small, _ = _eyes(synthetic_landmarks(), WIDE)
    right_large, _ = _eyes(synthetic_landmarks(), FrameGeometry(1280, 960))

    outer, inner = right_small.outer_corner, right_small.inner_corner
    expected = math.hypot((outer[0] - inner[0]) * WIDE.width, (outer[1] - inner[1]) * WIDE.height)
    assert right_small.width_px == pytest.approx(expected, rel=1e-5)
    assert right_large.width_px == pytest.approx(2.0 * right_small.width_px, rel=1e-5)
    assert right_small.valid and right_large.valid


def test_extract_eye_is_invalid_when_narrower_than_the_minimum_width() -> None:
    right, left = _eyes(synthetic_landmarks(), WIDE, AnalysisSettings(min_eye_width_px=1000.0))
    assert right.width_px < 1000.0
    assert not right.valid and not left.valid

    tiny_right, tiny_left = _eyes(synthetic_landmarks(face_height=0.05), WIDE)
    assert tiny_right.width_px < AnalysisSettings().min_eye_width_px
    assert not tiny_right.valid and not tiny_left.valid

    exact_right, _ = _eyes(synthetic_landmarks(), WIDE, AnalysisSettings(min_eye_width_px=right.width_px))
    assert exact_right.valid  # the minimum is inclusive


def test_extract_eye_is_invalid_when_contour_points_leave_the_frame() -> None:
    # Face centred on the left edge: the subject's right eye (image left) is
    # partly outside, the left eye stays inside.
    right, left = _eyes(synthetic_landmarks(center=(0.06, 0.5)), WIDE)
    assert np.any(right.contour[:, 0] < 0.0)
    assert not right.valid
    assert left.valid and left.width_px >= AnalysisSettings().min_eye_width_px


def test_extract_eye_is_invalid_when_only_the_iris_leaves_the_frame() -> None:
    points = synthetic_landmarks()
    points[topology.RIGHT_IRIS_CONTOUR[0], 1] = -0.01
    right, left = _eyes(points, WIDE)
    assert np.all(right.contour[:, 1] >= 0.0)
    assert not right.valid
    assert left.valid


def test_extract_eye_has_no_iris_for_468_point_sets() -> None:
    right, left = _eyes(synthetic_landmarks(count=468), WIDE)
    assert right.iris is None and left.iris is None
    assert right.iris_center is None
    assert right.valid and left.valid


def test_extract_eye_iris_is_centred_in_the_eye() -> None:
    right, left = _eyes(synthetic_landmarks(), WIDE)
    for eye in (right, left):
        assert eye.iris is not None and eye.iris.shape == (topology.IRIS_POINTS_PER_EYE, 3)
        assert not eye.iris.flags.writeable
        centre = (eye.outer_corner[:2] + eye.inner_corner[:2]) / 2.0
        assert eye.iris_center is not None
        assert eye.iris_center[:2] == pytest.approx(centre, abs=1e-6)
        assert np.all(np.hypot(*(eye.iris[1:, :2] - eye.iris[0, :2]).T) > 0.0)


def test_extract_eye_rejects_unknown_sides() -> None:
    points, iris_available = validate_landmarks(synthetic_landmarks())
    with pytest.raises(ValueError):
        extract_eye(points, "up", WIDE, AnalysisSettings(), iris_available)  # type: ignore[arg-type]


# --- compute_quality ---


def test_quality_of_an_in_frame_face_of_default_size_is_one() -> None:
    quality = compute_quality(synthetic_landmarks(face_height=0.3), WIDE, AnalysisSettings(), THRESHOLDS)

    assert quality.score == 1.0
    assert quality.in_frame_fraction == 1.0
    assert quality.face_height_fraction == pytest.approx(0.3, abs=1e-6)
    assert quality.backend_thresholds == THRESHOLDS
    assert quality.provenance.startswith("heuristic")


def test_quality_size_term_rises_linearly_between_floor_and_full() -> None:
    settings = AnalysisSettings(size_floor_fraction=0.10, size_full_fraction=0.20)

    half = compute_quality(synthetic_landmarks(face_height=0.15), WIDE, settings, THRESHOLDS)
    assert half.in_frame_fraction == 1.0
    assert half.score == pytest.approx(0.5, abs=1e-5)

    at_floor = compute_quality(synthetic_landmarks(face_height=0.10), WIDE, settings, THRESHOLDS)
    assert at_floor.score == pytest.approx(0.0, abs=1e-5)

    below_floor = compute_quality(synthetic_landmarks(face_height=0.05), WIDE, settings, THRESHOLDS)
    assert below_floor.score == 0.0

    huge = compute_quality(synthetic_landmarks(face_height=0.6), WIDE, settings, THRESHOLDS)
    assert huge.score == 1.0


def test_quality_size_term_is_one_when_the_span_is_degenerate() -> None:
    settings = AnalysisSettings(size_floor_fraction=0.2, size_full_fraction=0.2)
    quality = compute_quality(synthetic_landmarks(face_height=0.05), WIDE, settings, THRESHOLDS)
    assert quality.score == 1.0


def test_quality_of_a_face_half_outside_is_the_in_frame_fraction() -> None:
    quality = compute_quality(synthetic_landmarks(center=(0.0, 0.5)), WIDE, AnalysisSettings(), THRESHOLDS)

    assert 0.3 < quality.in_frame_fraction < 0.7
    assert quality.score == min(quality.in_frame_fraction, 1.0)
    assert quality.score == quality.in_frame_fraction


def test_quality_takes_the_minimum_of_both_terms() -> None:
    quality = compute_quality(synthetic_landmarks(center=(0.5, 0.0), face_height=0.15), WIDE, AnalysisSettings(), THRESHOLDS)

    assert quality.in_frame_fraction < 1.0
    assert quality.score == pytest.approx(min(quality.in_frame_fraction, 0.5), abs=1e-5)


def test_quality_height_ignores_iris_points_but_in_frame_counts_them() -> None:
    points = synthetic_landmarks()
    points[topology.LEFT_IRIS_CENTER] = (0.5, 5.0, 0.0)
    quality = compute_quality(points, WIDE, AnalysisSettings(), THRESHOLDS)

    assert quality.face_height_fraction == pytest.approx(0.3, abs=1e-6)
    assert quality.in_frame_fraction == pytest.approx(477 / 478)


# --- head_pose_from_matrix ---


def _rx(degrees: float) -> np.ndarray:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _ry(degrees: float) -> np.ndarray:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def _rz(degrees: float) -> np.ndarray:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _transform(rotation: np.ndarray, translation: tuple[float, float, float] = (0.0, 0.0, -45.0)) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = translation
    return matrix.astype(np.float32)


def _angles(pose: HeadPose | None) -> tuple[float, float, float]:
    assert pose is not None
    return pose.yaw_deg, pose.pitch_deg, pose.roll_deg


def test_identity_transform_gives_zero_angles_and_keeps_the_translation() -> None:
    pose = head_pose_from_matrix(identity_transform())

    assert pose is not None
    assert _angles(pose) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert np.array_equal(pose.rotation, np.eye(3, dtype=np.float32))
    assert np.array_equal(pose.translation_cm, np.array([0.0, 0.0, -45.0], dtype=np.float32))
    assert pose.rotation.dtype == np.float32 and not pose.rotation.flags.writeable
    assert pose.translation_cm.dtype == np.float32 and not pose.translation_cm.flags.writeable


def test_rotation_about_camera_z_is_roll() -> None:
    assert _angles(head_pose_from_matrix(_transform(_rz(10.0)))) == pytest.approx((0.0, 0.0, 10.0), abs=1e-4)


def test_rotation_about_camera_y_is_yaw() -> None:
    assert _angles(head_pose_from_matrix(_transform(_ry(20.0)))) == pytest.approx((20.0, 0.0, 0.0), abs=1e-4)


def test_rotation_about_camera_x_is_pitch() -> None:
    assert _angles(head_pose_from_matrix(_transform(_rx(15.0)))) == pytest.approx((0.0, 15.0, 0.0), abs=1e-4)


def test_combined_rotation_is_decomposed_as_rz_ry_rx() -> None:
    rotation = _rz(-12.0) @ _ry(25.0) @ _rx(-8.0)
    pose = head_pose_from_matrix(_transform(rotation, (1.5, -2.0, -50.0)))

    assert _angles(pose) == pytest.approx((25.0, -8.0, -12.0), abs=1e-4)
    assert pose is not None
    assert pose.translation_cm == pytest.approx((1.5, -2.0, -50.0), abs=1e-6)
    assert pose.rotation == pytest.approx(rotation.astype(np.float32), abs=1e-6)


def test_three_by_three_matrix_is_accepted_with_zero_translation() -> None:
    pose = head_pose_from_matrix(_ry(20.0))

    assert pose is not None
    assert _angles(pose) == pytest.approx((20.0, 0.0, 0.0), abs=1e-4)
    assert np.array_equal(pose.translation_cm, np.zeros(3, dtype=np.float32))
    assert pose.translation_cm.shape == (3,)


def test_gimbal_lock_at_ninety_degrees_yaw_does_not_raise() -> None:
    pose = head_pose_from_matrix(_transform(_ry(90.0)))
    assert pose is not None
    assert pose.yaw_deg == pytest.approx(90.0, abs=1e-3)
    assert math.isfinite(pose.pitch_deg) and math.isfinite(pose.roll_deg)


@pytest.mark.parametrize(
    ("description", "matrix"),
    [
        ("3x4", np.eye(4)[:3]),
        ("2x2", np.eye(2)),
        ("vector", np.zeros(16)),
        ("5x5", np.eye(5)),
        ("nan rotation", _transform(_rx(15.0)) * np.float32(math.nan)),
        ("nan translation", _transform(_rx(15.0), (math.nan, 0.0, -45.0))),
        ("inf entry", _transform(_rx(15.0), (math.inf, 0.0, -45.0))),
        ("scaled, det 8", _transform(2.0 * np.eye(3))),
        ("reflection, det -1", _transform(np.diag([-1.0, 1.0, 1.0]))),
        ("zeros", np.zeros((4, 4))),
        ("non-numeric", "not a matrix"),
        ("none", None),
    ],
)
def test_unusable_matrices_give_none(description: str, matrix: object) -> None:
    assert head_pose_from_matrix(matrix) is None


def test_mirrored_pose_negates_yaw_and_roll_only() -> None:
    rotation = _rz(10.0) @ _ry(20.0) @ _rx(15.0)
    pose = head_pose_from_matrix(_transform(rotation, (3.0, -1.0, -45.0)))
    assert pose is not None

    mirrored = pose.mirrored()

    assert mirrored.yaw_deg == pytest.approx(-20.0, abs=1e-4)
    assert mirrored.pitch_deg == pytest.approx(15.0, abs=1e-4)
    assert mirrored.roll_deg == pytest.approx(-10.0, abs=1e-4)
    assert mirrored.translation_cm == pytest.approx((-3.0, -1.0, -45.0), abs=1e-6)
    flip = np.diag([-1.0, 1.0, 1.0])
    assert mirrored.rotation == pytest.approx(flip @ pose.rotation @ flip, abs=1e-6)
    assert not mirrored.rotation.flags.writeable and not mirrored.translation_cm.flags.writeable
    # The mirrored rotation decomposes to the mirrored angles: the two views agree.
    assert _angles(head_pose_from_matrix(mirrored.rotation)) == pytest.approx((-20.0, 15.0, -10.0), abs=1e-3)
    # Mirroring twice restores the original.
    assert _angles(mirrored.mirrored()) == pytest.approx(_angles(pose), abs=1e-9)


# --- face_bbox / face_center_and_area ---


def test_face_bbox_spans_the_synthetic_oval() -> None:
    x0, y0, x1, y1 = face_bbox(synthetic_landmarks(center=(0.4, 0.6), face_height=0.3, aspect=0.75))

    assert (x0, x1) == pytest.approx((0.4 - 0.1125, 0.4 + 0.1125), abs=1e-6)
    assert (y0, y1) == pytest.approx((0.6 - 0.15, 0.6 + 0.15), abs=1e-6)
    assert all(isinstance(value, float) for value in (x0, y0, x1, y1))


def test_face_bbox_ignores_iris_points() -> None:
    points = synthetic_landmarks()
    reference = face_bbox(points)
    points[topology.LANDMARK_COUNT_WITHOUT_IRIS:, :2] = 5.0
    assert face_bbox(points) == reference


def test_face_center_and_area_follow_the_bbox() -> None:
    points = synthetic_landmarks(center=(0.3, 0.7), face_height=0.2, aspect=0.5)

    (cx, cy), area = face_center_and_area(points)

    assert (cx, cy) == pytest.approx((0.3, 0.7), abs=1e-6)
    assert area == pytest.approx(0.1 * 0.2, abs=1e-6)
    assert face_center_and_area(shift(points, 0.1, -0.2))[0] == pytest.approx((0.4, 0.5), abs=1e-6)


def test_face_center_and_area_of_a_degenerate_face_is_zero() -> None:
    points = np.full((478, 3), 0.25, dtype=np.float32)
    (cx, cy), area = face_center_and_area(points)
    assert (cx, cy) == (0.25, 0.25)
    assert area == 0.0
