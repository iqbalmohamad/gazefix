"""The gaze contract: statuses, conventions, mirroring and the angle helpers."""

from __future__ import annotations

import math

import numpy as np
import pytest

from gazefix.gaze.models import (
    CONFIDENCE_PROVENANCE,
    EyeGaze,
    GazeConfidence,
    GazeResult,
    GazeStatus,
    angles_from_direction,
    direction_from_angles,
    unavailable,
)


def confidence(score: float = 0.8, **overrides: object) -> GazeConfidence:
    values: dict[str, object] = {
        "score": score,
        "tracking_quality": 1.0,
        "openness_term": 1.0,
        "agreement_term": 1.0,
        "pose_term": 1.0,
        "offset_term": 1.0,
        "eyes_used": 2,
        "head_pose_applied": True,
    }
    values.update(overrides)
    return GazeConfidence(**values)  # type: ignore[arg-type]


# --- direction and angle conventions ---


def test_looking_into_the_camera_is_the_positive_z_axis() -> None:
    assert np.allclose(direction_from_angles(0.0, 0.0), [0.0, 0.0, 1.0], atol=1e-6)


def test_positive_yaw_points_toward_the_image_right_which_is_the_subjects_left() -> None:
    # The gaze frame matches HeadPose: x toward the image's right. An
    # unmirrored frame shows the subject's own left on the image's right.
    assert float(direction_from_angles(30.0, 0.0)[0]) > 0.0


def test_positive_pitch_points_up() -> None:
    assert float(direction_from_angles(0.0, 20.0)[1]) > 0.0


def test_negative_pitch_points_down() -> None:
    assert float(direction_from_angles(0.0, -20.0)[1]) < 0.0


@pytest.mark.parametrize("yaw", [-70.0, -30.0, 0.0, 15.0, 60.0])
@pytest.mark.parametrize("pitch", [-40.0, -10.0, 0.0, 25.0])
def test_angles_and_direction_round_trip(yaw: float, pitch: float) -> None:
    recovered = angles_from_direction(direction_from_angles(yaw, pitch))
    assert recovered[0] == pytest.approx(yaw, abs=1e-4)
    assert recovered[1] == pytest.approx(pitch, abs=1e-4)


def test_direction_is_a_readonly_unit_vector() -> None:
    direction = direction_from_angles(20.0, -10.0)
    assert direction.dtype == np.float32
    assert not direction.flags.writeable
    assert float(np.linalg.norm(direction)) == pytest.approx(1.0, abs=1e-6)


def test_angles_normalise_a_non_unit_direction() -> None:
    # A rotation matrix that is only approximately orthonormal can scale the
    # composed direction; asin must not be pushed out of its domain.
    yaw, pitch = angles_from_direction(np.array([0.0, 1.06, 0.0], dtype=np.float32))
    assert pitch == pytest.approx(90.0, abs=1e-6)
    assert math.isfinite(yaw)


def test_straight_up_has_no_defined_yaw_and_reports_zero() -> None:
    assert angles_from_direction(np.array([0.0, 1.0, 0.0], dtype=np.float32)) == (0.0, 90.0)


@pytest.mark.parametrize("bad", [[0.0, 0.0, 0.0], [float("nan"), 0.0, 1.0], [float("inf"), 0.0, 0.0]])
def test_angles_reject_a_degenerate_direction(bad: list[float]) -> None:
    with pytest.raises(ValueError):
        angles_from_direction(np.array(bad, dtype=np.float32))


# --- statuses ---


def test_only_estimated_and_low_confidence_carry_a_direction() -> None:
    assert GazeStatus.ESTIMATED.has_direction
    assert GazeStatus.LOW_CONFIDENCE.has_direction
    assert not GazeStatus.UNAVAILABLE.has_direction


def test_available_is_true_only_for_estimated() -> None:
    for status in (GazeStatus.ESTIMATED, GazeStatus.LOW_CONFIDENCE, GazeStatus.UNAVAILABLE):
        result = GazeResult(status=status, confidence=confidence(), yaw_deg=1.0, pitch_deg=2.0)
        assert result.available is (status is GazeStatus.ESTIMATED)


# --- unavailable ---


def test_unavailable_carries_no_angles_so_it_cannot_read_as_looking_at_the_camera() -> None:
    result = unavailable("no iris", estimation_ms=0.4)
    assert result.status is GazeStatus.UNAVAILABLE
    assert result.yaw_deg is None and result.pitch_deg is None
    assert result.eye_yaw_deg is None and result.eye_pitch_deg is None
    assert result.direction is None
    assert result.confidence.score == 0.0
    assert result.message == "no iris"
    assert result.estimation_ms == 0.4


def test_unavailable_reports_no_head_pose_and_no_eyes() -> None:
    result = unavailable("nothing")
    assert result.confidence.eyes_used == 0
    assert result.head_pose_applied is False


# --- confidence provenance ---


def test_confidence_names_itself_a_heuristic_not_a_model_probability() -> None:
    assert "heuristic" in CONFIDENCE_PROVENANCE
    assert "probability" not in CONFIDENCE_PROVENANCE.lower()
    assert GazeConfidence(0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 2, True).provenance == CONFIDENCE_PROVENANCE


# --- mirroring ---


def full_result() -> GazeResult:
    return GazeResult(
        status=GazeStatus.ESTIMATED,
        confidence=confidence(),
        yaw_deg=25.0,
        pitch_deg=-8.0,
        eye_yaw_deg=10.0,
        eye_pitch_deg=-3.0,
        direction=direction_from_angles(25.0, -8.0),
        per_eye=(
            EyeGaze(side="right", yaw_deg=12.0, pitch_deg=-3.0, offset_u=0.1, offset_v=-0.02),
            EyeGaze(side="left", yaw_deg=8.0, pitch_deg=-3.0, offset_u=0.08, offset_v=-0.02),
        ),
    )


def test_mirroring_flips_yaw_and_leaves_pitch_alone() -> None:
    mirrored = full_result().mirrored()
    assert mirrored.yaw_deg == -25.0
    assert mirrored.pitch_deg == -8.0
    assert mirrored.eye_yaw_deg == -10.0
    assert mirrored.eye_pitch_deg == -3.0


def test_mirroring_flips_the_direction_x_component_only() -> None:
    original = full_result()
    mirrored = original.mirrored()
    assert mirrored.direction is not None and original.direction is not None
    assert float(mirrored.direction[0]) == pytest.approx(-float(original.direction[0]))
    assert float(mirrored.direction[1]) == pytest.approx(float(original.direction[1]))
    assert float(mirrored.direction[2]) == pytest.approx(float(original.direction[2]))
    assert not mirrored.direction.flags.writeable


def test_mirroring_flips_each_eye_and_keeps_the_side_anatomical() -> None:
    mirrored = full_result().mirrored()
    by_side = {eye.side: eye for eye in mirrored.per_eye}
    assert set(by_side) == {"left", "right"}
    assert by_side["right"].yaw_deg == -12.0
    assert by_side["right"].offset_u == pytest.approx(-0.1)
    assert by_side["right"].pitch_deg == -3.0
    assert by_side["right"].offset_v == pytest.approx(-0.02)


def test_mirroring_twice_returns_the_original_angles() -> None:
    original = full_result()
    twice = original.mirrored().mirrored()
    assert twice.yaw_deg == original.yaw_deg
    assert twice.pitch_deg == original.pitch_deg
    assert twice.eye_yaw_deg == original.eye_yaw_deg


def test_mirroring_an_unavailable_result_stays_unavailable_and_angle_free() -> None:
    mirrored = unavailable("no face").mirrored()
    assert mirrored.status is GazeStatus.UNAVAILABLE
    assert mirrored.yaw_deg is None and mirrored.direction is None


def test_gaze_result_is_immutable() -> None:
    with pytest.raises(Exception):
        full_result().yaw_deg = 0.0  # type: ignore[misc]
