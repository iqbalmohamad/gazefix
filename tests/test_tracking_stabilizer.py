"""Velocity-adaptive landmark smoothing."""

from __future__ import annotations

import numpy as np
import pytest

from gazefix.tracking.stabilizer import LandmarkStabilizer
from tracking_fakes import shift, synthetic_landmarks


def _expected(previous: np.ndarray, current: np.ndarray, smoothing: float, motion_scale: float) -> np.ndarray:
    """The documented blend: per-point weight from ``1 - 0.7 * smoothing`` up to 1 at ``motion_scale``."""

    alpha_min = 1.0 - 0.7 * smoothing
    delta = current.astype(np.float64) - previous.astype(np.float64)
    displacement = np.hypot(delta[:, 0], delta[:, 1])
    alpha = np.clip(alpha_min + displacement / motion_scale, alpha_min, 1.0)
    return previous + alpha[:, None] * delta


def test_zero_smoothing_disables_the_filter_and_returns_the_same_object() -> None:
    stabilizer = LandmarkStabilizer(smoothing=0.0)
    assert not stabilizer.enabled

    first = synthetic_landmarks()
    second = shift(first, 0.001, 0.0)
    assert stabilizer.apply(first) is first
    assert stabilizer.apply(second) is second  # never blended, even after a first frame


def test_first_frame_passes_through_unchanged() -> None:
    stabilizer = LandmarkStabilizer(smoothing=0.8)
    assert stabilizer.enabled
    first = synthetic_landmarks()
    before = first.copy()

    output = stabilizer.apply(first)

    assert np.array_equal(output, before)
    assert output.shape == first.shape and output.dtype == np.float32


def test_small_jitter_is_damped_toward_the_previous_position() -> None:
    stabilizer = LandmarkStabilizer(smoothing=1.0, motion_scale=0.02)
    first = synthetic_landmarks()
    jittered = shift(first, 0.001, -0.0005)
    stabilizer.apply(first)

    output = stabilizer.apply(jittered)

    to_previous = np.hypot(*(output[:, :2] - first[:, :2]).T)
    to_input = np.hypot(*(output[:, :2] - jittered[:, :2]).T)
    jitter = np.hypot(*(jittered[:, :2] - first[:, :2]).T)
    assert np.all(to_previous < to_input)  # closer to the previous output than to the raw input
    assert np.all(to_previous < jitter)  # and moved less than the raw jitter
    assert output == pytest.approx(_expected(first, jittered, 1.0, 0.02), abs=1e-6)


def test_moderate_smoothing_uses_the_documented_minimum_weight() -> None:
    stabilizer = LandmarkStabilizer(smoothing=0.5, motion_scale=0.02)
    first = synthetic_landmarks()
    stabilizer.apply(first)
    jittered = shift(first, 0.002, 0.0)  # alpha = 0.65 + 0.002 / 0.02 = 0.75

    output = stabilizer.apply(jittered)

    assert output[:, 0] == pytest.approx(first[:, 0] + 0.75 * 0.002, abs=1e-6)
    assert output == pytest.approx(_expected(first, jittered, 0.5, 0.02), abs=1e-6)


def test_large_motion_passes_through_almost_unfiltered() -> None:
    stabilizer = LandmarkStabilizer(smoothing=1.0, motion_scale=0.02)
    first = synthetic_landmarks()
    stabilizer.apply(first)

    at_scale = shift(first, 0.02, 0.0)
    assert stabilizer.apply(at_scale) == pytest.approx(at_scale, abs=1e-4)

    far = shift(at_scale, 0.15, -0.1)
    assert stabilizer.apply(far) == pytest.approx(far, abs=1e-4)


def test_weights_are_per_point() -> None:
    stabilizer = LandmarkStabilizer(smoothing=1.0, motion_scale=0.02)
    first = synthetic_landmarks()
    stabilizer.apply(first)
    current = shift(first, 0.001, 0.0)
    current[5, :2] = first[5, :2] + np.float32(0.1)  # one point jumps

    output = stabilizer.apply(current)

    assert output[5] == pytest.approx(current[5], abs=1e-4)
    others = np.delete(np.arange(len(first)), 5)
    assert np.all(np.abs(output[others, 0] - first[others, 0]) < 0.0005)  # alpha 0.35 of 0.001


def test_smoothed_output_becomes_the_next_reference() -> None:
    stabilizer = LandmarkStabilizer(smoothing=0.7, motion_scale=0.02)
    frames = [synthetic_landmarks()]
    for step in range(1, 4):
        frames.append(shift(frames[0], 0.001 * step, 0.0))
    stabilizer.apply(frames[0])

    reference = frames[0].astype(np.float64)
    for frame in frames[1:]:
        output = stabilizer.apply(frame)
        reference = _expected(reference, frame, 0.7, 0.02)
        assert output == pytest.approx(reference, abs=1e-6)


def test_reset_makes_the_next_frame_pass_through() -> None:
    stabilizer = LandmarkStabilizer(smoothing=1.0)
    first = synthetic_landmarks()
    stabilizer.apply(first)
    jittered = shift(first, 0.001, 0.001)
    assert not np.array_equal(stabilizer.apply(jittered), jittered)  # smoothed before the reset

    stabilizer.reset()

    output = stabilizer.apply(jittered)
    assert np.array_equal(output, jittered)
    # And the pass-through frame is the new reference.
    next_frame = shift(jittered, 0.001, 0.0)
    assert stabilizer.apply(next_frame) == pytest.approx(_expected(jittered, next_frame, 1.0, 0.02), abs=1e-6)


def test_landmark_count_change_resets_the_filter() -> None:
    stabilizer = LandmarkStabilizer(smoothing=1.0)
    stabilizer.apply(synthetic_landmarks(count=478))

    without_iris = synthetic_landmarks(count=468)
    output = stabilizer.apply(without_iris)
    assert np.array_equal(output, without_iris)

    jittered = shift(without_iris, 0.001, 0.0)
    assert stabilizer.apply(jittered) == pytest.approx(_expected(without_iris, jittered, 1.0, 0.02), abs=1e-6)


def test_smoothed_output_is_a_readonly_float32_array() -> None:
    stabilizer = LandmarkStabilizer(smoothing=0.5)
    first = synthetic_landmarks()
    stabilizer.apply(first)

    output = stabilizer.apply(shift(first, 0.001, 0.0))

    assert output.dtype == np.float32
    assert output.shape == first.shape
    assert not output.flags.writeable
    with pytest.raises(ValueError):
        output[0, 0] = 0.0


@pytest.mark.parametrize("smoothing", [-0.01, 1.01, 2.0, float("nan")])
def test_invalid_smoothing_is_rejected(smoothing: float) -> None:
    with pytest.raises(ValueError):
        LandmarkStabilizer(smoothing=smoothing)


@pytest.mark.parametrize("motion_scale", [0.0, -0.02])
def test_invalid_motion_scale_is_rejected(motion_scale: float) -> None:
    with pytest.raises(ValueError):
        LandmarkStabilizer(smoothing=0.5, motion_scale=motion_scale)


def test_boundary_smoothing_values_are_accepted() -> None:
    assert not LandmarkStabilizer(smoothing=0.0).enabled
    assert LandmarkStabilizer(smoothing=1.0).enabled
    assert LandmarkStabilizer(smoothing=0.001).enabled


def test_input_arrays_are_never_mutated() -> None:
    stabilizer = LandmarkStabilizer(smoothing=1.0)
    frames = [synthetic_landmarks()]
    frames.append(shift(frames[0], 0.001, 0.0))
    frames.append(shift(frames[0], 0.05, 0.0))
    frames.append(shift(frames[0], 0.002, 0.002))
    copies = [frame.copy() for frame in frames]

    outputs = [stabilizer.apply(frame) for frame in frames]

    for frame, copy in zip(frames, copies):
        assert np.array_equal(frame, copy)
    for output in outputs[1:]:
        assert output is not frames[0]


def test_readonly_input_is_accepted() -> None:
    stabilizer = LandmarkStabilizer(smoothing=1.0)
    first = synthetic_landmarks()
    first.setflags(write=False)
    second = shift(first, 0.001, 0.0)
    second.setflags(write=False)

    assert stabilizer.apply(first) is first
    output = stabilizer.apply(second)
    assert output == pytest.approx(_expected(first, second, 1.0, 0.02), abs=1e-6)
