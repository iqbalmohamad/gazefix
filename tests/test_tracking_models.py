"""The TrackingResult contract: statuses, validity flags, pixel mapping and mirroring."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from gazefix.tracking import landmarks as topology
from gazefix.tracking.models import (
    EyeLandmarks,
    FrameGeometry,
    TrackingQuality,
    TrackingResult,
    TrackingStatus,
    TrackingTiming,
    in_frame,
    pixel_distance,
    readonly,
    untracked,
)
from tracking_fakes import identity_transform, synthetic_landmarks, tracked_result


GEOMETRY = FrameGeometry(640, 480)
LANDMARK_STATUSES = (TrackingStatus.TRACKED, TrackingStatus.LOW_QUALITY)


def test_only_tracked_and_low_quality_carry_landmarks() -> None:
    for status in TrackingStatus:
        assert status.has_landmarks == (status in LANDMARK_STATUSES), status


def test_untracked_rejects_landmark_bearing_statuses() -> None:
    for status in LANDMARK_STATUSES:
        with pytest.raises(ValueError):
            untracked(status, 1, 10, 1, GEOMETRY)


def test_untracked_builds_a_result_without_landmarks() -> None:
    for status in TrackingStatus:
        if status.has_landmarks:
            continue
        result = untracked(status, 7, 123, 2, GEOMETRY, message="why", faces_detected=3)

        assert result.status is status
        assert (result.capture_sequence, result.captured_at_ns, result.camera_request_id) == (7, 123, 2)
        assert result.geometry == GEOMETRY
        assert result.message == "why"
        assert result.faces_detected == 3
        assert result.timing == TrackingTiming()
        assert result.landmarks is None and result.left_eye is None and result.right_eye is None
        assert result.pose is None and result.quality is None
        assert not result.iris_available and not result.stabilized
        assert not result.face_valid and not result.eyes_valid and not result.pose_available
        assert result.landmark_pixels() is None


def test_untracked_keeps_an_explicit_timing() -> None:
    timing = TrackingTiming(inference_ms=1.0, total_ms=2.0, waited_ms=0.5)
    assert untracked(TrackingStatus.NO_FACE, 1, 1, 1, GEOMETRY, timing=timing).timing == timing


def test_belongs_to_requires_both_sequence_and_camera_generation() -> None:
    result = untracked(TrackingStatus.NO_FACE, capture_sequence=5, captured_at_ns=1, camera_request_id=3, geometry=GEOMETRY)

    assert result.belongs_to(5, 3)
    assert not result.belongs_to(6, 3)
    assert not result.belongs_to(5, 4)
    assert not result.belongs_to(6, 4)


def test_landmark_pixels_scale_by_the_frame_geometry() -> None:
    result = tracked_result(synthetic_landmarks(), GEOMETRY)
    assert result.landmarks is not None

    pixels = result.landmark_pixels()

    assert pixels is not None
    assert pixels.shape == (478, 2) and pixels.dtype == np.float32
    assert not pixels.flags.writeable
    assert pixels[:, 0] == pytest.approx(result.landmarks[:, 0] * 640, rel=1e-6)
    assert pixels[:, 1] == pytest.approx(result.landmarks[:, 1] * 480, rel=1e-6)
    nose = pixels[topology.NOSE_TIP]
    assert nose == pytest.approx((320.0, 240.0), abs=1e-3)


def test_face_valid_only_when_tracked() -> None:
    tracked = tracked_result(synthetic_landmarks(), GEOMETRY)
    assert tracked.face_valid
    assert tracked.eyes_valid

    low_quality = replace(tracked, status=TrackingStatus.LOW_QUALITY)
    assert not low_quality.face_valid
    assert low_quality.landmarks is not None  # still carries the raw landmarks
    for status in TrackingStatus:
        if not status.has_landmarks:
            assert not untracked(status, 1, 1, 1, GEOMETRY).face_valid


def test_eyes_valid_requires_both_eyes_present_and_valid() -> None:
    tracked = tracked_result(synthetic_landmarks(), GEOMETRY)
    assert tracked.left_eye is not None and tracked.right_eye is not None
    assert tracked.eyes_valid

    assert not replace(tracked, left_eye=None).eyes_valid
    assert not replace(tracked, right_eye=None).eyes_valid
    assert not replace(tracked, left_eye=replace(tracked.left_eye, valid=False)).eyes_valid
    assert not replace(tracked, right_eye=replace(tracked.right_eye, valid=False)).eyes_valid
    # eyes_valid is the safe consumer check: it also requires face_valid, while
    # the per-eye geometric flag stays as computed on a LOW_QUALITY result.
    low_quality = replace(tracked, status=TrackingStatus.LOW_QUALITY)
    assert not low_quality.eyes_valid
    assert low_quality.left_eye is not None and low_quality.left_eye.valid


def test_eye_landmark_accessors_follow_the_contour_positions() -> None:
    result = tracked_result(synthetic_landmarks(), GEOMETRY)
    eye = result.right_eye
    assert eye is not None

    assert np.array_equal(eye.outer_corner, eye.contour[topology.CONTOUR_OUTER_CORNER_POSITION])
    assert np.array_equal(eye.inner_corner, eye.contour[topology.CONTOUR_INNER_CORNER_POSITION])
    assert eye.lower_lid.shape == (7, 3) and eye.upper_lid.shape == (7, 3)
    assert np.array_equal(eye.lower_lid, eye.contour[1:8])
    assert np.array_equal(eye.upper_lid, eye.contour[9:16])
    assert eye.iris is not None
    assert np.array_equal(eye.iris_center, eye.iris[0])
    assert replace(eye, iris=None).iris_center is None


def test_mirrored_flips_x_and_keeps_anatomical_sides() -> None:
    original = tracked_result(synthetic_landmarks(center=(0.4, 0.5)), GEOMETRY, transform=identity_transform())
    assert original.landmarks is not None
    assert original.left_eye is not None and original.right_eye is not None
    assert original.pose is not None
    landmarks_before = original.landmarks.copy()

    mirrored = original.mirrored()

    assert mirrored is not original
    assert mirrored.geometry == FrameGeometry(640, 480, mirrored=True)
    assert not original.geometry.mirrored
    assert mirrored.landmarks is not None
    assert mirrored.landmarks[:, 0] == pytest.approx(1.0 - original.landmarks[:, 0], abs=1e-7)
    assert np.array_equal(mirrored.landmarks[:, 1:], original.landmarks[:, 1:])
    assert mirrored.landmarks.dtype == np.float32 and not mirrored.landmarks.flags.writeable
    assert np.array_equal(original.landmarks, landmarks_before)  # the source is untouched

    assert mirrored.left_eye is not None and mirrored.right_eye is not None
    for before, after in ((original.left_eye, mirrored.left_eye), (original.right_eye, mirrored.right_eye)):
        assert after.side == before.side
        assert after.contour[:, 0] == pytest.approx(1.0 - before.contour[:, 0], abs=1e-7)
        assert np.array_equal(after.contour[:, 1:], before.contour[:, 1:])
        assert before.iris is not None and after.iris is not None
        assert after.iris[:, 0] == pytest.approx(1.0 - before.iris[:, 0], abs=1e-7)
        assert np.array_equal(after.iris[:, 1:], before.iris[:, 1:])
        assert not after.contour.flags.writeable and not after.iris.flags.writeable
        assert (after.openness, after.width_px, after.valid) == (before.openness, before.width_px, before.valid)
    # In the mirrored image the subject's right eye now appears on the image's right.
    assert mirrored.right_eye.outer_corner[0] > mirrored.left_eye.outer_corner[0]

    assert mirrored.pose is not None
    assert mirrored.pose.yaw_deg == -original.pose.yaw_deg
    assert mirrored.pose.roll_deg == -original.pose.roll_deg
    assert mirrored.pose.pitch_deg == original.pose.pitch_deg
    assert mirrored.pose.translation == pytest.approx((-0.0, 0.0, -45.0))

    for field in ("status", "capture_sequence", "captured_at_ns", "camera_request_id", "timing", "message",
                  "faces_detected", "iris_available", "quality", "stabilized"):
        assert getattr(mirrored, field) == getattr(original, field), field


def test_mirrored_pose_flips_yaw_and_roll_signs() -> None:
    original = tracked_result(synthetic_landmarks(), GEOMETRY, transform=identity_transform())
    assert original.pose is not None
    posed = replace(original, pose=replace(original.pose, yaw_deg=20.0, pitch_deg=15.0, roll_deg=-10.0))

    mirrored = posed.mirrored()

    assert mirrored.pose is not None
    assert (mirrored.pose.yaw_deg, mirrored.pose.pitch_deg, mirrored.pose.roll_deg) == (-20.0, 15.0, 10.0)


def test_mirrored_without_landmarks_only_flags_the_geometry() -> None:
    mirrored = untracked(TrackingStatus.NO_FACE, 1, 1, 1, GEOMETRY).mirrored()
    assert mirrored.geometry.mirrored
    assert mirrored.landmarks is None and mirrored.left_eye is None and mirrored.pose is None


def test_mirroring_twice_is_rejected() -> None:
    mirrored = tracked_result(synthetic_landmarks(), GEOMETRY).mirrored()
    with pytest.raises(ValueError):
        mirrored.mirrored()
    with pytest.raises(ValueError):
        untracked(TrackingStatus.NO_FACE, 1, 1, 1, FrameGeometry(640, 480, mirrored=True)).mirrored()


def test_readonly_returns_a_non_writeable_float32_copy() -> None:
    source = np.arange(6, dtype=np.float64).reshape(2, 3)

    array = readonly(source, (2, 3))

    assert array.dtype == np.float32
    assert not array.flags.writeable
    assert array is not source
    source[0, 0] = 99.0
    assert array[0, 0] == 0.0
    with pytest.raises(ValueError):
        array[0, 0] = 1.0
    assert readonly([1, 2, 3]).shape == (3,)  # shape check is optional


@pytest.mark.parametrize("shape", [(3, 2), (6,), (2, 3, 1), (1, 6)])
def test_readonly_rejects_wrong_shapes(shape: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        readonly(np.zeros((2, 3)), shape)


def test_in_frame_is_inclusive_on_the_edges_and_ignores_depth() -> None:
    points = np.array(
        [
            [0.0, 0.0, -0.5],
            [1.0, 1.0, 0.5],
            [0.5, 0.5, 99.0],
            [1.0001, 0.5, 0.0],
            [-0.0001, 0.5, 0.0],
            [0.5, 1.0001, 0.0],
            [0.5, -0.0001, 0.0],
        ],
        dtype=np.float32,
    )
    assert in_frame(points).tolist() == [True, True, True, False, False, False, False]


def test_pixel_distance_uses_the_frame_size_per_axis() -> None:
    a = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 1.0, 5.0], dtype=np.float32)  # depth is ignored
    assert pixel_distance(a, b, GEOMETRY) == pytest.approx(math.hypot(640, 480))
    assert pixel_distance(a, b, GEOMETRY) == pytest.approx(800.0)

    c = np.array([0.25, 0.5, 0.0], dtype=np.float32)
    d = np.array([0.75, 0.5, 0.0], dtype=np.float32)
    assert pixel_distance(c, d, GEOMETRY) == pytest.approx(320.0)
    assert pixel_distance(d, c, GEOMETRY) == pytest.approx(320.0)
    assert pixel_distance(c, c, GEOMETRY) == 0.0


def test_result_dataclasses_are_frozen() -> None:
    result = untracked(TrackingStatus.NO_FACE, 1, 1, 1, GEOMETRY)
    with pytest.raises((AttributeError, TypeError)):
        result.status = TrackingStatus.TRACKED  # type: ignore[misc]
    quality = TrackingQuality(1.0, 1.0, 0.3, (0.5, 0.5, 0.5))
    with pytest.raises((AttributeError, TypeError)):
        quality.score = 0.0  # type: ignore[misc]
    eye = EyeLandmarks("left", readonly(np.zeros((16, 3))), None, 0.3, 20.0, True)
    with pytest.raises((AttributeError, TypeError)):
        eye.valid = False  # type: ignore[misc]
