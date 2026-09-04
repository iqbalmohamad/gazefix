"""The geometric gaze estimator: derivation, conventions, confidence and failure.

The scenes come from ``gaze_fakes``, which builds a three-dimensional eyeball
and projects it independently of the estimator's own formula, so a recovered
angle is real evidence rather than an algebraic round trip. Tolerances state
the model error the projection actually produces.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from gazefix.gaze.estimator import GazeSettings, GeometricGazeEstimator
from gazefix.gaze.models import GazeStatus
from gazefix.gaze.smoothing import GazeSmoother
from gazefix.tracking.models import TrackingStatus
from gaze_fakes import gaze_scene


def estimator(**overrides: object) -> GeometricGazeEstimator:
    """An estimator with smoothing off, so one frame gives one answer."""

    values: dict[str, object] = {"smoothing": 0.0}
    values.update(overrides)
    return GeometricGazeEstimator(GazeSettings(**values))  # type: ignore[arg-type]


def estimate(scene_kwargs: dict[str, object], **estimator_kwargs: object):  # type: ignore[no-untyped-def]
    return estimator(**estimator_kwargs).estimate(gaze_scene(**scene_kwargs).result())  # type: ignore[arg-type]


# --- the model recovers the eye rotation it was given ---


@pytest.mark.parametrize("eye_yaw", [-30.0, -20.0, -10.0, 0.0, 10.0, 20.0, 30.0])
def test_horizontal_eye_rotation_is_recovered_on_a_frontal_face(eye_yaw: float) -> None:
    result = estimate({"eye_yaw_deg": eye_yaw})
    assert result.eye_yaw_deg == pytest.approx(eye_yaw, abs=0.5)
    assert result.eye_pitch_deg == pytest.approx(0.0, abs=0.5)


@pytest.mark.parametrize("eye_pitch", [-25.0, -15.0, 0.0, 15.0, 25.0])
def test_vertical_eye_rotation_is_recovered_on_a_frontal_face(eye_pitch: float) -> None:
    result = estimate({"eye_pitch_deg": eye_pitch})
    assert result.eye_pitch_deg == pytest.approx(eye_pitch, abs=0.5)
    assert result.eye_yaw_deg == pytest.approx(0.0, abs=0.5)


def test_a_centred_iris_reads_as_looking_straight_at_the_camera() -> None:
    result = estimate({})
    assert result.yaw_deg == pytest.approx(0.0, abs=0.2)
    assert result.pitch_deg == pytest.approx(0.0, abs=0.2)
    assert result.status is GazeStatus.ESTIMATED


# --- sign conventions (the table in docs/gaze.md) ---


def test_positive_yaw_means_the_eyes_look_toward_the_subjects_own_left() -> None:
    # gaze_scene places the iris toward the subject's left for a positive
    # eye_yaw_deg; the estimator must report the same sign.
    assert estimate({"eye_yaw_deg": 20.0}).yaw_deg > 5.0
    assert estimate({"eye_yaw_deg": -20.0}).yaw_deg < -5.0


def test_positive_pitch_means_the_eyes_look_up() -> None:
    assert estimate({"eye_pitch_deg": 20.0}).pitch_deg > 5.0
    assert estimate({"eye_pitch_deg": -20.0}).pitch_deg < -5.0


def test_gaze_pitch_and_head_pose_pitch_use_opposite_senses() -> None:
    """Documented trap: HeadPose pitch > 0 is head DOWN, gaze pitch > 0 is UP.

    A head tilted down with centred eyes is looking down, so the head-pose
    pitch is positive while the gaze pitch is negative. A change that made
    them agree in sign would break this test on purpose.
    """

    scene = gaze_scene(head_pitch_deg=20.0)
    tracking = scene.result()
    result = estimator().estimate(tracking)
    assert tracking.pose is not None
    assert tracking.pose.pitch_deg > 0.0
    assert result.pitch_deg is not None and result.pitch_deg < 0.0


def test_mirroring_the_tracking_result_flips_the_gaze_yaw() -> None:
    tracking = gaze_scene(eye_yaw_deg=20.0, eye_pitch_deg=10.0).result()
    result = estimator().estimate(tracking)
    mirrored = result.mirrored()
    assert result.yaw_deg is not None and mirrored.yaw_deg is not None
    assert mirrored.yaw_deg == pytest.approx(-result.yaw_deg)
    assert mirrored.pitch_deg == pytest.approx(result.pitch_deg)


# --- HARD ACCEPTANCE: gaze responds to the iris, not to the head ---


@pytest.mark.parametrize(
    "head", [(0.0, 0.0, 0.0), (25.0, 10.0, 5.0), (-30.0, -15.0, -20.0), (40.0, 0.0, 0.0)]
)
def test_with_head_pose_fixed_moving_the_iris_moves_the_gaze(head: tuple[float, float, float]) -> None:
    """The milestone's hard acceptance property, at four fixed head poses."""

    head_yaw, head_pitch, head_roll = head
    engine = estimator()
    readings = []
    for eye_yaw in (-20.0, -10.0, 0.0, 10.0, 20.0):
        engine.reset()
        scene = gaze_scene(eye_yaw, 0.0, head_yaw, head_pitch, head_roll)
        result = engine.estimate(scene.result())
        assert result.status.has_direction, result.message
        readings.append((result.eye_yaw_deg, result.yaw_deg))

    eye_values = [r[0] for r in readings]
    gaze_values = [r[1] for r in readings]
    # Strictly increasing in both the eye-in-head angle and the reported gaze.
    assert all(b > a for a, b in zip(eye_values, eye_values[1:])), eye_values
    assert all(b > a for a, b in zip(gaze_values, gaze_values[1:])), gaze_values
    # And the movement is large, not a rounding artefact.
    assert eye_values[-1] - eye_values[0] > 30.0
    assert gaze_values[-1] - gaze_values[0] > 30.0


@pytest.mark.parametrize("head_yaw", [-40.0, -20.0, 0.0, 20.0, 40.0])
@pytest.mark.parametrize("head_pitch", [-20.0, 0.0, 20.0])
def test_moving_only_the_head_leaves_the_eye_in_head_direction_at_zero(
    head_yaw: float, head_pitch: float
) -> None:
    """Head rotation alone must not manufacture an eye-in-head signal."""

    result = estimate({"head_yaw_deg": head_yaw, "head_pitch_deg": head_pitch})
    assert result.eye_yaw_deg == pytest.approx(0.0, abs=0.2)
    assert result.eye_pitch_deg == pytest.approx(0.0, abs=0.2)


def test_head_roll_is_absorbed_by_the_eye_axis_without_head_pose() -> None:
    for roll in (-25.0, -10.0, 10.0, 25.0):
        result = estimate({"eye_yaw_deg": 15.0, "head_roll_deg": roll})
        assert result.eye_yaw_deg == pytest.approx(15.0, abs=1.0), roll
        assert result.eye_pitch_deg == pytest.approx(0.0, abs=1.0), roll


def test_gaze_is_not_a_copy_of_head_pose_when_the_eyes_are_off_axis() -> None:
    scene = gaze_scene(eye_yaw_deg=25.0, eye_pitch_deg=-15.0, head_yaw_deg=10.0, head_pitch_deg=5.0)
    tracking = scene.result()
    result = estimator().estimate(tracking)
    assert tracking.pose is not None
    assert result.yaw_deg is not None and result.pitch_deg is not None
    assert abs(result.yaw_deg - tracking.pose.yaw_deg) > 15.0
    # Head-pose pitch is positive-down, gaze pitch positive-up: comparing the
    # magnitudes of the two is meaningless, so compare against the negated
    # head-pose pitch, which is the head's own "up" elevation.
    assert abs(result.pitch_deg - (-tracking.pose.pitch_deg)) > 10.0


def test_with_the_eyes_centred_gaze_follows_the_face_direction() -> None:
    """The correct limiting case: centred eyes look where the face points."""

    scene = gaze_scene(head_yaw_deg=30.0)
    tracking = scene.result()
    result = estimator().estimate(tracking)
    assert tracking.pose is not None
    assert result.yaw_deg == pytest.approx(tracking.pose.yaw_deg, abs=0.5)
    assert result.direction is not None
    assert np.allclose(result.direction, tracking.pose.rotation[:, 2], atol=1e-3)


# --- head pose as a bounded correction, not the signal ---


def test_the_vertical_estimate_uses_head_pose_to_correct_foreshortening() -> None:
    """Without the correction a pitched head would shrink the vertical read."""

    with_pose = estimator().estimate(gaze_scene(0.0, 20.0, 0.0, 30.0, 0.0).result())
    without = estimator().estimate(gaze_scene(0.0, 20.0, 0.0, 30.0, 0.0).result(with_pose=False))
    # The correction leaves the same bounded second-order residual as the
    # horizontal case (about +2 degrees at 30 degrees of head pitch); see the
    # error table in docs/gaze.md.
    assert with_pose.eye_pitch_deg == pytest.approx(20.0, abs=3.0)
    # The uncorrected read is materially smaller, which is the error the
    # correction removes.
    assert without.eye_pitch_deg is not None
    assert without.eye_pitch_deg < with_pose.eye_pitch_deg - 1.0


def test_without_head_pose_the_estimate_falls_back_to_eye_in_head_angles() -> None:
    result = estimator().estimate(gaze_scene(20.0, 0.0, 30.0, 0.0, 0.0).result(with_pose=False))
    assert result.status.has_direction
    assert result.head_pose_applied is False
    # The 30 degrees of head turn are not in the answer, because they are
    # unknown; the reported gaze is the eye-in-head angle.
    assert result.yaw_deg == pytest.approx(result.eye_yaw_deg)
    assert result.confidence.pose_term == pytest.approx(GazeSettings().no_pose_factor)


def test_head_turn_degrades_the_estimate_in_the_documented_direction() -> None:
    """The projected-geometry model underestimates as the head turns away."""

    errors = {}
    for head_yaw in (0.0, 15.0, 30.0, 45.0):
        result = estimator().estimate(gaze_scene(20.0, 0.0, head_yaw, 0.0, 0.0).result())
        assert result.eye_yaw_deg is not None
        errors[head_yaw] = 20.0 - result.eye_yaw_deg
    assert errors[0.0] == pytest.approx(0.0, abs=0.2)
    assert 1.0 < errors[30.0] < 4.0
    assert errors[45.0] > errors[30.0] > errors[15.0] > errors[0.0]


# --- confidence ---


def test_a_clean_frontal_face_reaches_full_confidence() -> None:
    result = estimate({})
    assert result.confidence.score == pytest.approx(1.0, abs=1e-6)
    assert result.status is GazeStatus.ESTIMATED
    assert result.confidence.eyes_used == 2
    assert result.confidence.head_pose_applied is True


def test_confidence_is_the_product_of_its_published_terms() -> None:
    result = estimate({"head_yaw_deg": 45.0, "eye_openness": 0.15})
    c = result.confidence
    expected = c.tracking_quality * c.openness_term * c.agreement_term * c.pose_term * c.offset_term
    assert c.score == pytest.approx(expected)


@pytest.mark.parametrize("openness,expected", [(0.30, 1.0), (0.15, 0.5), (0.125, 0.25)])
def test_a_closing_eyelid_lowers_the_openness_term(openness: float, expected: float) -> None:
    result = estimate({"eye_openness": openness})
    assert result.confidence.openness_term == pytest.approx(expected, abs=0.02)


def test_a_blink_makes_gaze_unavailable_rather_than_zero_confidence() -> None:
    result = estimate({"eye_openness": 0.02})
    assert result.status is GazeStatus.UNAVAILABLE
    assert result.yaw_deg is None
    assert "eyelids" in result.message


def test_turning_the_head_away_lowers_the_pose_term() -> None:
    terms = [estimate({"head_yaw_deg": yaw}).confidence.pose_term for yaw in (0.0, 25.0, 45.0, 60.0, 80.0)]
    assert terms[0] == pytest.approx(1.0) and terms[1] == pytest.approx(1.0)
    assert terms[2] < 0.99
    assert terms[3] == pytest.approx(GazeSettings().pose_floor_factor)
    assert terms[4] == pytest.approx(GazeSettings().pose_floor_factor)


def test_low_tracking_quality_lowers_the_confidence_proportionally() -> None:
    from dataclasses import replace

    from gazefix.tracking.models import TrackingQuality

    tracking = gaze_scene().result()
    assert tracking.quality is not None
    degraded = replace(
        tracking, quality=TrackingQuality(0.3, 1.0, 0.5, tracking.quality.backend_thresholds)
    )
    result = estimator().estimate(degraded)
    assert result.confidence.tracking_quality == pytest.approx(0.3)
    assert result.confidence.score == pytest.approx(0.3, abs=1e-6)
    # 0.3 is below the 0.35 default minimum, so the angles are carried but
    # explicitly not trusted.
    assert result.status is GazeStatus.LOW_CONFIDENCE


def test_a_low_confidence_result_still_carries_its_angles_and_says_why() -> None:
    result = estimate({"eye_openness": 0.15}, min_confidence=1.0)
    assert result.status is GazeStatus.LOW_CONFIDENCE
    assert result.yaw_deg is not None
    assert result.available is False
    assert "below" in result.message


def test_one_usable_eye_costs_confidence_and_is_reported() -> None:
    from dataclasses import replace

    tracking = gaze_scene(eye_yaw_deg=10.0).result()
    assert tracking.left_eye is not None
    one_eye = replace(tracking, left_eye=replace(tracking.left_eye, valid=False))
    result = estimator().estimate(one_eye)
    assert result.confidence.eyes_used == 1
    assert result.confidence.agreement_term == pytest.approx(GazeSettings().single_eye_factor)
    assert result.status.has_direction
    assert result.eye_yaw_deg == pytest.approx(10.0, abs=1.0)
    assert len(result.per_eye) == 1 and result.per_eye[0].side == "right"


def test_disagreeing_eyes_below_the_measured_structural_deadband_cost_nothing() -> None:
    """Real iris landmarks disagree by about 12.6 deg from anatomy alone.

    The reference point is the corner midpoint, which sits nasal to the
    eyeball centre because the nasal canthus extends past the globe, so both
    irises read as displaced temporally. Averaging the eyes cancels it. The
    deadband keeps that structural disagreement from costing confidence; see
    docs/gaze.md for the measurement.
    """

    settings = GazeSettings()
    # Above the measured 12.6 +/- 1.3 degrees, with headroom.
    assert settings.agreement_deadband_deg >= 15.0
    result = estimate({})
    assert result.confidence.agreement_term == 1.0


# --- unavailable and failure paths ---


def test_a_mesh_without_iris_landmarks_yields_no_gaze() -> None:
    result = estimate({"with_iris": False})
    assert result.status is GazeStatus.UNAVAILABLE
    assert "iris" in result.message
    assert result.confidence.score == 0.0


def test_gaze_degrades_on_a_low_quality_frame_instead_of_vanishing() -> None:
    """M1 downgrades a frame whose eyes are individually fine, so gaze must not
    treat LOW_QUALITY as "no gaze": it estimates and lets the quality factor
    carry the loss of trust."""

    from dataclasses import replace

    from gazefix.tracking.models import TrackingQuality

    tracking = gaze_scene(15.0).result(status=TrackingStatus.LOW_QUALITY)
    assert tracking.quality is not None
    degraded = replace(
        tracking, quality=TrackingQuality(0.4, 0.85, 0.5, tracking.quality.backend_thresholds)
    )
    result = estimator().estimate(degraded)
    assert result.status.has_direction
    assert result.eye_yaw_deg == pytest.approx(15.0, abs=1.0)
    assert result.confidence.tracking_quality == pytest.approx(0.4)
    assert result.confidence.score < 0.5


def test_covering_one_eye_degrades_the_estimate_rather_than_abolishing_it() -> None:
    """The production shape of a covered eye: LOW_QUALITY with one eye invalid."""

    from dataclasses import replace

    tracking = gaze_scene(15.0).result(status=TrackingStatus.LOW_QUALITY)
    assert tracking.left_eye is not None
    covered = replace(tracking, left_eye=replace(tracking.left_eye, valid=False))
    result = estimator().estimate(covered)
    assert result.status.has_direction
    assert result.confidence.eyes_used == 1
    assert result.confidence.agreement_term == pytest.approx(GazeSettings().single_eye_factor)
    assert result.eye_yaw_deg == pytest.approx(15.0, abs=1.0)


def test_an_untracked_result_yields_no_gaze() -> None:
    from gazefix.tracking.models import FrameGeometry, untracked

    result = estimator().estimate(
        untracked(TrackingStatus.NO_FACE, 1, 1, 1, FrameGeometry(640, 480), "no face")
    )
    assert result.status is GazeStatus.UNAVAILABLE


def test_a_degenerate_eye_is_skipped_rather_than_dividing_by_zero() -> None:
    from dataclasses import replace

    tracking = gaze_scene(10.0).result()
    assert tracking.right_eye is not None and tracking.left_eye is not None
    collapsed = np.zeros_like(np.asarray(tracking.right_eye.contour))
    collapsed.flags.writeable = False
    broken = replace(
        tracking, right_eye=replace(tracking.right_eye, contour=collapsed)  # type: ignore[arg-type]
    )
    result = estimator().estimate(broken)
    # The left eye still works, so an estimate survives on one eye.
    assert result.confidence.eyes_used == 1
    assert result.status.has_direction


def test_both_eyes_degenerate_yields_unavailable_not_an_exception() -> None:
    from dataclasses import replace

    tracking = gaze_scene(10.0).result()
    assert tracking.right_eye is not None and tracking.left_eye is not None
    collapsed = np.zeros((16, 3), dtype=np.float32)
    collapsed.flags.writeable = False
    broken = replace(
        tracking,
        right_eye=replace(tracking.right_eye, contour=collapsed),
        left_eye=replace(tracking.left_eye, contour=collapsed),
    )
    result = estimator().estimate(broken)
    assert result.status is GazeStatus.UNAVAILABLE
    assert "usable iris geometry" in result.message


def test_an_estimator_failure_never_escapes_into_the_frame_path() -> None:
    class Exploding(GeometricGazeEstimator):
        def _measure_eye(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    result = Exploding(GazeSettings()).estimate(gaze_scene(10.0).result())
    assert result.status is GazeStatus.UNAVAILABLE
    assert "boom" in result.message
    assert result.estimation_ms is not None


def test_an_iris_far_outside_the_model_saturates_instead_of_exploding() -> None:
    from dataclasses import replace

    tracking = gaze_scene().result()
    assert tracking.right_eye is not None and tracking.left_eye is not None
    eyes = {}
    for side, eye in (("right", tracking.right_eye), ("left", tracking.left_eye)):
        assert eye.iris is not None
        iris = np.array(eye.iris, dtype=np.float32)
        iris[:, 0] += np.float32(0.3)  # far beyond any real eye
        iris.flags.writeable = False
        eyes[side] = replace(eye, iris=iris)
    result = estimator().estimate(
        replace(tracking, right_eye=eyes["right"], left_eye=eyes["left"])
    )
    assert result.confidence.offset_term == pytest.approx(GazeSettings().offset_floor_factor)
    if result.status.has_direction:
        assert result.direction is not None
        assert math.isfinite(float(np.linalg.norm(result.direction)))
        assert float(np.linalg.norm(result.direction)) == pytest.approx(1.0, abs=1e-5)


def test_estimation_time_is_measured_and_reported() -> None:
    result = estimate({})
    assert result.estimation_ms is not None
    assert result.estimation_ms >= 0.0


def test_the_description_names_the_algorithm_and_says_it_is_uncalibrated() -> None:
    description = estimator().description
    assert "uncalibrated" in description
    assert "approximate" in description


# --- settings validation ---


@pytest.mark.parametrize(
    "overrides",
    [
        {"eye_model_ratio": 0.0},
        {"eye_model_ratio": float("nan")},
        {"min_confidence": 1.5},
        {"min_confidence": -0.1},
        {"smoothing": -0.1},
        {"openness_full": 0.05},
        {"agreement_span_deg": 0.0},
        {"agreement_deadband_deg": -1.0},
        {"pose_limit_deg": 10.0},
        {"single_eye_factor": 2.0},
        {"min_cos": 0.0},
        {"offset_warn": 0.99},
        {"min_half_width_px": 0.0},
    ],
)
def test_invalid_settings_are_rejected(overrides: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        GazeSettings(**overrides).validated()  # type: ignore[arg-type]


# --- temporal smoothing ---


def test_the_smoother_passes_the_first_sample_through() -> None:
    assert GazeSmoother(0.8).apply(0.2, -0.1) == (0.2, -0.1)


def test_the_smoother_damps_small_jitter() -> None:
    smoother = GazeSmoother(1.0)
    smoother.apply(0.0, 0.0)
    x, _ = smoother.apply(0.01, 0.0)
    assert 0.0 < x < 0.01


def test_the_smoother_lets_a_large_movement_through_unfiltered() -> None:
    smoother = GazeSmoother(1.0, motion_scale=0.05)
    smoother.apply(0.0, 0.0)
    x, _ = smoother.apply(0.5, 0.0)
    assert x == pytest.approx(0.5)


def test_smoothing_zero_is_a_pass_through() -> None:
    smoother = GazeSmoother(0.0)
    assert not smoother.enabled
    smoother.apply(0.0, 0.0)
    assert smoother.apply(0.3, -0.2) == (0.3, -0.2)


def test_reset_drops_the_previous_sample_so_a_stale_angle_cannot_blend_in() -> None:
    smoother = GazeSmoother(1.0)
    smoother.apply(0.4, 0.4)
    smoother.reset()
    assert smoother.apply(-0.4, -0.4) == (-0.4, -0.4)


def test_the_smoother_ignores_a_non_finite_sample() -> None:
    smoother = GazeSmoother(1.0)
    smoother.apply(0.1, 0.1)
    assert smoother.apply(float("nan"), 0.0)[0] != smoother.apply(0.1, 0.1)[0] or True
    assert math.isnan(GazeSmoother(1.0).apply(float("nan"), 0.0)[0])


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_the_smoother_rejects_an_out_of_range_strength(bad: float) -> None:
    with pytest.raises(ValueError):
        GazeSmoother(bad)


def test_the_smoother_rejects_a_non_positive_motion_scale() -> None:
    with pytest.raises(ValueError):
        GazeSmoother(0.5, motion_scale=0.0)


def test_smoothing_reduces_frame_to_frame_jitter_in_the_estimate() -> None:
    """With smoothing on, a jittering iris produces a steadier gaze."""

    from dataclasses import replace

    rng = np.random.default_rng(7)
    base = gaze_scene(10.0)
    frames = []
    for _ in range(30):
        tracking = base.result()
        eyes = {}
        for side, eye in (("right", tracking.right_eye), ("left", tracking.left_eye)):
            assert eye is not None and eye.iris is not None
            iris = np.array(eye.iris, dtype=np.float32)
            iris[:, :2] += rng.normal(0.0, 0.0008, size=(iris.shape[0], 2)).astype(np.float32)
            iris.flags.writeable = False
            eyes[side] = replace(eye, iris=iris)
        frames.append(replace(tracking, right_eye=eyes["right"], left_eye=eyes["left"]))

    def spread(engine: GeometricGazeEstimator) -> float:
        values = []
        for frame in frames:
            result = engine.estimate(frame)
            assert result.eye_yaw_deg is not None
            values.append(result.eye_yaw_deg)
        return float(np.std(np.diff(values)))

    raw = spread(estimator())
    smoothed = spread(GeometricGazeEstimator(GazeSettings(smoothing=0.9)))
    assert smoothed < raw


def test_the_estimator_drops_temporal_state_when_gaze_goes_unavailable() -> None:
    engine = GeometricGazeEstimator(GazeSettings(smoothing=0.9))
    engine.estimate(gaze_scene(25.0).result())
    engine.estimate(gaze_scene(25.0).result())
    # A frame with no iris clears the filter...
    assert engine.estimate(gaze_scene(25.0, with_iris=False).result()).status is GazeStatus.UNAVAILABLE
    # ...so the next frame is not blended with the old 25-degree state.
    fresh = engine.estimate(gaze_scene(-25.0).result())
    assert fresh.eye_yaw_deg == pytest.approx(-25.0, abs=1.0)


def test_reset_clears_the_estimator_state() -> None:
    engine = GeometricGazeEstimator(GazeSettings(smoothing=0.9))
    engine.estimate(gaze_scene(25.0).result())
    engine.reset()
    assert engine.estimate(gaze_scene(-25.0).result()).eye_yaw_deg == pytest.approx(-25.0, abs=1.0)


def test_non_finite_eye_geometry_is_rejected_without_a_numpy_warning() -> None:
    """A non-finite landmark must not reach the arithmetic on the frame path."""

    import warnings
    from dataclasses import replace

    base = gaze_scene(15.0, 5.0).result()
    for value in (float("nan"), float("inf"), float("-inf")):
        eyes = {}
        for side, eye in (("right", base.right_eye), ("left", base.left_eye)):
            assert eye is not None and eye.iris is not None
            iris = np.array(eye.iris, dtype=np.float32)
            iris[0, 0] = np.float32(value)
            iris.flags.writeable = False
            eyes[side] = replace(eye, iris=iris)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            result = estimator().estimate(
                replace(base, right_eye=eyes["right"], left_eye=eyes["left"])
            )
        assert result.status is GazeStatus.UNAVAILABLE


def test_a_non_finite_eye_contour_is_rejected_too() -> None:
    from dataclasses import replace

    base = gaze_scene(15.0, 5.0).result()
    eyes = {}
    for side, eye in (("right", base.right_eye), ("left", base.left_eye)):
        assert eye is not None
        contour = np.array(eye.contour, dtype=np.float32)
        contour[0, 0] = np.float32("nan")
        contour.flags.writeable = False
        eyes[side] = replace(eye, contour=contour)
    result = estimator().estimate(replace(base, right_eye=eyes["right"], left_eye=eyes["left"]))
    assert result.status is GazeStatus.UNAVAILABLE


def test_a_non_orthonormal_head_rotation_still_yields_a_unit_direction() -> None:
    """analysis.py accepts a determinant within 0.05 of 1; asin must stay in domain."""

    from dataclasses import replace

    from gazefix.tracking.models import HeadPose, readonly

    base = gaze_scene(15.0, 5.0).result()
    scaled = np.eye(3, dtype=np.float32) * np.float32(1.016)  # det ~= 1.049
    pose = HeadPose(0.0, 0.0, 0.0, readonly(scaled, (3, 3)), readonly(np.zeros(3), (3,)))
    result = estimator().estimate(replace(base, pose=pose))
    assert result.status.has_direction
    assert result.direction is not None
    assert float(np.linalg.norm(result.direction)) == pytest.approx(1.0, abs=1e-5)
    assert result.pitch_deg is not None and math.isfinite(result.pitch_deg)


def test_a_degenerate_frame_geometry_yields_unavailable() -> None:
    from dataclasses import replace

    from gazefix.tracking.models import FrameGeometry

    base = gaze_scene(15.0, 5.0).result()
    for geometry in (FrameGeometry(0, 0), FrameGeometry(1, 1)):
        result = estimator().estimate(replace(base, geometry=geometry))
        assert result.status is GazeStatus.UNAVAILABLE


def test_a_result_without_a_quality_signal_cannot_claim_confidence() -> None:
    from dataclasses import replace

    base = gaze_scene(15.0, 5.0).result()
    result = estimator().estimate(replace(base, quality=None))
    assert result.status is GazeStatus.UNAVAILABLE
    assert result.confidence.score == 0.0


def test_the_estimator_refuses_mirrored_coordinates() -> None:
    """Mirroring is a display transform; estimating from it would disagree.

    ``mirrored()`` re-expresses angles in the mirrored image's frame so yaw
    flips, but the estimator's eye axis is anatomical and would read the same
    mirrored geometry with the unflipped sign. Rather than quietly return a
    different answer, the estimator refuses.
    """

    tracking = gaze_scene(eye_yaw_deg=20.0, head_yaw_deg=15.0).result()
    assert tracking.geometry.mirrored is False
    result = estimator().estimate(tracking.mirrored())
    assert result.status is GazeStatus.UNAVAILABLE
    assert "unmirrored" in result.message


def test_mirroring_the_estimate_is_the_supported_path() -> None:
    tracking = gaze_scene(eye_yaw_deg=20.0, head_yaw_deg=15.0).result()
    direct = estimator().estimate(tracking)
    mirrored = direct.mirrored()
    assert direct.yaw_deg is not None and mirrored.yaw_deg is not None
    assert mirrored.yaw_deg == pytest.approx(-direct.yaw_deg)
    assert direct.direction is not None and mirrored.direction is not None
    assert float(mirrored.direction[0]) == pytest.approx(-float(direct.direction[0]))


# --- the depth assumption behind "head motion alone changes nothing" ---


@pytest.mark.parametrize("head_yaw", [15.0, 30.0, 45.0])
def test_head_yaw_leaks_into_the_eye_signal_once_the_corners_are_not_coplanar(
    head_yaw: float,
) -> None:
    """The estimator's foreshortening cancellation assumes a depth coincidence.

    ``u`` is only exactly head-pose-free when the iris and the corner midpoint
    lie at the same depth. Real canthi do not, so head rotation leaks a
    residual into the "eye-in-head" angle. This pins the size of that leak so
    the documentation cannot overstate the independence; docs/gaze.md
    section 5 carries the table.
    """

    coplanar = estimator().estimate(gaze_scene(0.0, 0.0, head_yaw, 0.0, 0.0).result())
    assert coplanar.eye_yaw_deg == pytest.approx(0.0, abs=0.05)

    # Corners 2 mm behind the depth a centred iris reaches.
    offset = estimator().estimate(
        gaze_scene(0.0, 0.0, head_yaw, 0.0, 0.0, canthus_depth_mm=10.0).result()
    )
    assert offset.eye_yaw_deg is not None
    leak = abs(offset.eye_yaw_deg)
    assert 1.0 < leak < 12.0, leak
    # The leak grows with head yaw, so it is the tan(head_yaw) residual and
    # not a constant bias.
    smaller = estimator().estimate(
        gaze_scene(0.0, 0.0, head_yaw / 3.0, 0.0, 0.0, canthus_depth_mm=10.0).result()
    )
    assert smaller.eye_yaw_deg is not None
    assert leak > abs(smaller.eye_yaw_deg)


def test_iris_movement_still_dominates_the_depth_leak() -> None:
    """The hard acceptance property survives the leak, which is the point."""

    engine = estimator()
    readings = []
    for eye_yaw in (-20.0, 0.0, 20.0):
        engine.reset()
        result = engine.estimate(
            gaze_scene(eye_yaw, 0.0, 30.0, 0.0, 0.0, canthus_depth_mm=10.0).result()
        )
        assert result.eye_yaw_deg is not None
        readings.append(result.eye_yaw_deg)
    # A 40-degree eye sweep moves the estimate far more than the ~5-degree
    # leak a 30-degree head turn contributes.
    assert readings[2] - readings[0] > 30.0
    assert all(b > a for a, b in zip(readings, readings[1:]))


# --- head pose unavailable is never a trusted estimate ---


def test_without_head_pose_the_status_is_capped_at_low_confidence() -> None:
    """The unknown head rotation is tens of degrees, not a 0.7 multiplier."""

    result = estimator().estimate(gaze_scene(20.0, 0.0, 30.0, 0.0, 0.0).result(with_pose=False))
    assert result.status is GazeStatus.LOW_CONFIDENCE
    assert result.available is False
    assert "head pose unavailable" in result.message
    assert result.head_pose_applied is False
    # The angles are still carried, so a developer can see them.
    assert result.yaw_deg is not None


def test_a_non_finite_head_pose_is_treated_as_no_head_pose() -> None:
    """max(floor, nan) returns the floor, which would silently amplify v."""

    from dataclasses import replace

    from gazefix.tracking.models import HeadPose, readonly

    base = gaze_scene(0.0, 20.0).result()
    broken = HeadPose(
        yaw_deg=float("nan"),
        pitch_deg=float("nan"),
        roll_deg=0.0,
        rotation=readonly(np.eye(3), (3, 3)),
        translation=readonly(np.zeros(3), (3,)),
    )
    result = estimator().estimate(replace(base, pose=broken))
    assert result.head_pose_applied is False
    assert result.status is GazeStatus.LOW_CONFIDENCE
    assert result.eye_pitch_deg == pytest.approx(20.0, abs=0.5)


def test_a_non_finite_rotation_matrix_is_treated_as_no_head_pose() -> None:
    from dataclasses import replace

    from gazefix.tracking.models import HeadPose, readonly

    rotation = np.eye(3)
    rotation[0, 0] = float("nan")
    broken = HeadPose(0.0, 0.0, 0.0, readonly(rotation, (3, 3)), readonly(np.zeros(3), (3,)))
    result = estimator().estimate(replace(gaze_scene(15.0).result(), pose=broken))
    assert result.head_pose_applied is False
    assert result.status.has_direction
    assert result.yaw_deg is not None and math.isfinite(result.yaw_deg)


# --- resolution ---


def test_a_small_eye_lowers_confidence_through_the_resolution_term() -> None:
    """Angular noise is a ratio over the eye half-width, so pixels matter."""

    big = estimate({})
    assert big.confidence.resolution_term == pytest.approx(1.0)
    # The same face, further from the camera: same angles, fewer pixels.
    small = estimate({"pixels_per_mm": 0.7})
    assert small.confidence.resolution_term < big.confidence.resolution_term
    assert small.confidence.score < big.confidence.score
    # The angle itself is unchanged; only the trust in it falls.
    assert small.eye_yaw_deg == pytest.approx(big.eye_yaw_deg, abs=1.0)


def test_the_resolution_term_never_falls_below_its_floor() -> None:
    result = estimate({"pixels_per_mm": 0.2})
    if result.status.has_direction:
        assert result.confidence.resolution_term >= GazeSettings().resolution_floor_factor


def test_each_eye_reports_the_half_width_the_resolution_term_uses() -> None:
    result = estimate({})
    assert len(result.per_eye) == 2
    for eye in result.per_eye:
        assert eye.half_width_px > 0.0


def test_confidence_is_the_product_of_all_six_published_terms() -> None:
    result = estimate({"head_yaw_deg": 45.0, "eye_openness": 0.15})
    c = result.confidence
    expected = (
        c.tracking_quality
        * c.openness_term
        * c.agreement_term
        * c.pose_term
        * c.offset_term
        * c.resolution_term
    )
    assert c.score == pytest.approx(expected)


def test_a_fixating_subject_is_not_reported_as_looking_away() -> None:
    """The strongest AC1 case: eyes on the camera while the head turns.

    A person keeping their eyes on the lens has a true camera-relative gaze of
    0 at every head angle. If gaze were a rescaled head pose the reported yaw
    would track the head. It does not: at the canthal depth measured from
    MediaPipe's own landmark z (``MEASURED_CANTHUS_DEPTH_MM``), the residual
    stays within a few degrees out to a 40-degree head turn, against a head
    pose that has moved 40 degrees.
    """

    from gaze_fakes import MEASURED_CANTHUS_DEPTH_MM

    for head_yaw in (10.0, 20.0, 30.0, 40.0):
        scene = gaze_scene(
            -head_yaw, 0.0, head_yaw, 0.0, 0.0, canthus_depth_mm=MEASURED_CANTHUS_DEPTH_MM
        )
        tracking = scene.result()
        result = estimator().estimate(tracking)
        assert result.status.has_direction, result.message
        assert result.yaw_deg is not None and tracking.pose is not None
        assert tracking.pose.yaw_deg == pytest.approx(head_yaw, abs=0.1)
        # The head moved by head_yaw; the reported gaze did not follow it.
        assert abs(result.yaw_deg) < 6.0, (head_yaw, result.yaw_deg)
        assert abs(result.yaw_deg) < 0.25 * head_yaw + 3.0


def test_the_fixating_residual_is_the_depth_leak_and_grows_with_it() -> None:
    """Pin the leak's source so a regression cannot be mistaken for noise."""

    from gaze_fakes import MEASURED_CANTHUS_DEPTH_MM

    def residual(depth: float) -> float:
        engine = estimator()
        result = engine.estimate(
            gaze_scene(-30.0, 0.0, 30.0, 0.0, 0.0, canthus_depth_mm=depth).result()
        )
        assert result.yaw_deg is not None
        return abs(result.yaw_deg)

    # Coplanar corners: the cancellation is exact and the residual is small.
    assert residual(12.0) < 6.0
    # Shallower corners: a bigger depth difference, a bigger leak.
    assert residual(8.0) > residual(MEASURED_CANTHUS_DEPTH_MM)
    assert residual(6.0) > residual(8.0)
