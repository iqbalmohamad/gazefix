"""Gaze in the live pipeline: frame identity, resets, metrics and continuity.

These exercise the real ``TrackerWorker``/``TrackingProcessor`` path with a
scripted tracker, so the gaze stage is verified where it actually runs: on the
tracker thread, attached to the frame it describes.
"""

from __future__ import annotations

from dataclasses import replace
import logging
import time

import numpy as np
import pytest

from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.gaze.models import GazeResult, GazeStatus, unavailable
from gazefix.pipeline.processor import FrameContext
from gazefix.tracking.models import TrackingStatus
from gazefix.tracking.processor import TrackingProcessor
from gazefix.tracking.tracker import RawFace
from gaze_fakes import gaze_scene
from tracker_fakes import (
    ScriptedFactory,
    blank_frame,
    init_error,
    tracking_settings,
    wait_until,
)


FRAME = blank_frame(1280, 720)


def scene_face(**kwargs: object) -> RawFace:
    """A ``RawFace`` whose eyes look where ``gaze_scene`` was asked to look."""

    scene = gaze_scene(**kwargs)  # type: ignore[arg-type]
    return RawFace(landmarks=scene.landmarks, transform=scene.transform)


def ready_processor(factory: ScriptedFactory, **overrides: object):  # type: ignore[no-untyped-def]
    metrics = PipelineMetrics()
    processor = TrackingProcessor(factory, tracking_settings(**overrides), metrics)
    processor.start()
    assert wait_until(lambda: processor.status().state == "ready")
    return processor, metrics


class Driver:
    def __init__(self, processor: TrackingProcessor) -> None:
        self.processor = processor
        self.sequence = 0

    def once(self, generation: int = 1):  # type: ignore[no-untyped-def]
        self.sequence += 1
        context = FrameContext(self.sequence, time.perf_counter_ns(), generation)
        return self.processor.process(FRAME, context), context

    def until_tracked(self, generation: int = 1, attempts: int = 200):  # type: ignore[no-untyped-def]
        for _ in range(attempts):
            output, context = self.once(generation)
            if output.tracking is not None and output.tracking.status is TrackingStatus.TRACKED:
                return output, context
            time.sleep(0.005)
        raise AssertionError("never reached TRACKED")


# --- gaze rides on the tracking result ---


def test_a_tracked_frame_carries_a_gaze_estimate_for_that_same_frame() -> None:
    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(eye_yaw_deg=20.0),)})
    processor, _ = ready_processor(factory)
    try:
        output, context = Driver(processor).until_tracked()
        tracking = output.tracking
        assert tracking is not None and tracking.gaze is not None
        assert tracking.belongs_to(context.capture_sequence, context.camera_request_id)
        assert tracking.gaze.status is GazeStatus.ESTIMATED
        assert tracking.gaze.eye_yaw_deg == pytest.approx(20.0, abs=1.5)
        assert tracking.gaze_available is True
    finally:
        processor.close()


def test_the_gaze_estimate_moves_with_the_iris_through_the_real_pipeline() -> None:
    """The hard acceptance property, verified end to end rather than in isolation."""

    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(eye_yaw_deg=-20.0),)})
    processor, _ = ready_processor(factory)
    try:
        driver = Driver(processor)
        looking_right = driver.until_tracked()[0].tracking
        # Same head pose, different iris position.
        factory.trackers[0].faces = (scene_face(eye_yaw_deg=20.0),)
        looking_left = driver.until_tracked()[0].tracking
        assert looking_right is not None and looking_right.gaze is not None
        assert looking_left is not None and looking_left.gaze is not None
        assert looking_right.pose is not None and looking_left.pose is not None
        # The head did not move...
        assert looking_left.pose.yaw_deg == pytest.approx(looking_right.pose.yaw_deg, abs=0.01)
        # ...but the gaze did, by a lot.
        assert looking_left.gaze.eye_yaw_deg - looking_right.gaze.eye_yaw_deg > 30.0
        assert looking_left.gaze.yaw_deg - looking_right.gaze.yaw_deg > 30.0
    finally:
        processor.close()


def test_gaze_is_estimated_on_the_tracker_thread_not_the_processor_thread() -> None:
    """Blocking work stays off the processor thread; gaze adds no wait there."""

    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(),)})
    processor, _ = ready_processor(factory)
    try:
        output, _ = Driver(processor).until_tracked()
        tracking = output.tracking
        assert tracking is not None and tracking.gaze is not None
        # The gaze time is inside the tracker's total, not added to the wait.
        assert tracking.gaze.estimation_ms is not None
        assert tracking.timing.total_ms is not None
        assert tracking.gaze.estimation_ms <= tracking.timing.total_ms + 1.0
    finally:
        processor.close()


# --- results without landmarks still carry an explicit gaze ---


def test_an_initializing_frame_carries_an_unavailable_gaze_not_a_missing_one() -> None:
    from threading import Event

    gate = Event()
    factory = ScriptedFactory(gate=gate)
    processor = TrackingProcessor(factory, tracking_settings(), PipelineMetrics())
    try:
        output, _ = Driver(processor).once()
        tracking = output.tracking
        assert tracking is not None
        assert tracking.status is TrackingStatus.INITIALIZING
        assert tracking.gaze is not None
        assert tracking.gaze.status is GazeStatus.UNAVAILABLE
        assert tracking.gaze.yaw_deg is None
        assert tracking.gaze_available is False
    finally:
        gate.set()
        processor.close()


def test_a_no_face_frame_reports_gaze_unavailable() -> None:
    factory = ScriptedFactory(tracker_kwargs={"faces": ()})
    processor, _ = ready_processor(factory)
    try:
        for _ in range(50):
            output, _ = Driver(processor).once()
            tracking = output.tracking
            if tracking is not None and tracking.status is TrackingStatus.NO_FACE:
                assert tracking.gaze is not None
                assert tracking.gaze.status is GazeStatus.UNAVAILABLE
                assert tracking.gaze.confidence.score == 0.0
                return
            time.sleep(0.005)
        raise AssertionError("never reached NO_FACE")
    finally:
        processor.close()


def test_an_unavailable_tracker_still_publishes_frames_with_an_unavailable_gaze() -> None:
    """Stream continuity: a failed tracker must not stop the preview."""

    factory = ScriptedFactory(failures=[init_error()])
    processor = TrackingProcessor(factory, tracking_settings(), PipelineMetrics())
    try:
        driver = Driver(processor)
        for _ in range(200):
            output, _ = driver.once()
            tracking = output.tracking
            assert output.frame is FRAME  # the frame itself always gets through
            if tracking is not None and tracking.status is TrackingStatus.UNAVAILABLE:
                assert tracking.gaze is not None
                assert tracking.gaze.status is GazeStatus.UNAVAILABLE
                return
            time.sleep(0.005)
        raise AssertionError("never reached UNAVAILABLE")
    finally:
        processor.close()


# --- temporal state is reset with everything else the tracker learned ---


# The smoother is velocity-adaptive: a large step passes through unfiltered
# whether or not the reset happened, so a test that swings the eye from +25 to
# -25 degrees proves nothing about resetting. These use a step INSIDE the
# filtered band, where a stale previous sample changes the answer measurably:
# settling at SETTLED and then jumping to TARGET reads TARGET exactly if the
# filter was cleared, and about 1.66 degrees if it was not.
SETTLED_DEG = 3.0
TARGET_DEG = 1.5
UNRESET_DEG = 1.66  # what a filter still primed with SETTLED_DEG would report


def test_a_camera_generation_change_clears_the_gaze_smoother() -> None:
    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(eye_yaw_deg=SETTLED_DEG),)})
    processor, _ = ready_processor(factory, gaze_smoothing=0.9)
    try:
        driver = Driver(processor)
        for _ in range(4):
            driver.until_tracked(generation=1)
        factory.trackers[0].faces = (scene_face(eye_yaw_deg=TARGET_DEG),)
        # A new generation resets every piece of temporal state, so the first
        # frame of the new camera is not blended with the old eye position.
        fresh = driver.until_tracked(generation=2)[0].tracking
        assert fresh is not None and fresh.gaze is not None
        assert fresh.gaze.eye_yaw_deg == pytest.approx(TARGET_DEG, abs=0.05)
        assert abs(fresh.gaze.eye_yaw_deg - UNRESET_DEG) > 0.1
    finally:
        processor.close()


def test_losing_the_face_clears_the_gaze_smoother() -> None:
    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(eye_yaw_deg=SETTLED_DEG),)})
    processor, _ = ready_processor(factory, gaze_smoothing=0.9)
    try:
        driver = Driver(processor)
        for _ in range(4):
            driver.until_tracked()
        factory.trackers[0].faces = ()
        for _ in range(50):
            output, _ = driver.once()
            if output.tracking is not None and output.tracking.status is TrackingStatus.NO_FACE:
                break
            time.sleep(0.005)
        factory.trackers[0].faces = (scene_face(eye_yaw_deg=TARGET_DEG),)
        reacquired = driver.until_tracked()[0].tracking
        assert reacquired is not None and reacquired.gaze is not None
        assert reacquired.gaze.eye_yaw_deg == pytest.approx(TARGET_DEG, abs=0.05)
        assert abs(reacquired.gaze.eye_yaw_deg - UNRESET_DEG) > 0.1
    finally:
        processor.close()


def test_the_gaze_smoother_really_does_hold_state_between_frames() -> None:
    """Guards the two tests above from becoming vacuous if the filter changes.

    If smoothing ever stopped affecting a step of this size, both would pass
    against a gutted reset without anyone noticing.
    """

    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(eye_yaw_deg=SETTLED_DEG),)})
    processor, _ = ready_processor(factory, gaze_smoothing=0.9)
    try:
        driver = Driver(processor)
        for _ in range(4):
            driver.until_tracked()
        factory.trackers[0].faces = (scene_face(eye_yaw_deg=TARGET_DEG),)
        blended = driver.until_tracked()[0].tracking
        assert blended is not None and blended.gaze is not None
        assert blended.gaze.eye_yaw_deg == pytest.approx(UNRESET_DEG, abs=0.1)
    finally:
        processor.close()


# --- settings ---


def test_gaze_can_be_disabled_and_then_no_gaze_code_runs_on_the_frame() -> None:
    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(eye_yaw_deg=20.0),)})
    processor, _ = ready_processor(factory, gaze_enabled=False)
    try:
        output, _ = Driver(processor).until_tracked()
        tracking = output.tracking
        assert tracking is not None and tracking.gaze is not None
        assert tracking.gaze.status is GazeStatus.UNAVAILABLE
        assert "disabled" in tracking.gaze.message
    finally:
        processor.close()


def test_the_worker_reports_the_gaze_algorithm_for_the_overlay() -> None:
    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(),)})
    processor, _ = ready_processor(factory)
    try:
        assert "uncalibrated" in processor._worker.gaze_description
    finally:
        processor.close()
    disabled, _ = ready_processor(ScriptedFactory(), gaze_enabled=False)
    try:
        assert disabled._worker.gaze_description == "gaze estimation disabled"
    finally:
        disabled.close()


# --- metrics ---


def test_gaze_outcomes_and_latency_are_recorded_in_the_metrics() -> None:
    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(eye_yaw_deg=15.0),)})
    processor, metrics = ready_processor(factory)
    try:
        driver = Driver(processor)
        for _ in range(5):
            driver.until_tracked()
        snapshot = metrics.snapshot()
        assert snapshot.gaze_estimated_frames >= 5
        assert snapshot.gaze_estimation_ms > 0.0
        # The gaze stage is a small fraction of the tracking stage it sits in.
        assert snapshot.gaze_estimation_ms < 50.0
    finally:
        processor.close()


def test_unavailable_gaze_frames_are_counted_separately() -> None:
    metrics = PipelineMetrics()
    metrics.record_gaze("estimated", 0.2)
    metrics.record_gaze("low_confidence", 0.3)
    metrics.record_gaze("unavailable", None)
    metrics.record_gaze("unavailable", None)
    snapshot = metrics.snapshot()
    assert snapshot.gaze_estimated_frames == 1
    assert snapshot.gaze_low_confidence_frames == 1
    assert snapshot.gaze_unavailable_frames == 2
    assert snapshot.gaze_estimation_ms > 0.0


def test_an_unknown_gaze_status_is_ignored_rather_than_miscounted() -> None:
    metrics = PipelineMetrics()
    metrics.record_gaze("something-else", 1.0)
    snapshot = metrics.snapshot()
    assert snapshot.gaze_estimated_frames == 0
    assert snapshot.gaze_low_confidence_frames == 0
    assert snapshot.gaze_unavailable_frames == 0


# --- the tracking contract itself ---


def test_untracked_results_always_carry_an_explicit_unavailable_gaze() -> None:
    from gazefix.tracking.models import FrameGeometry, untracked

    for status in (
        TrackingStatus.NO_FACE,
        TrackingStatus.INITIALIZING,
        TrackingStatus.UNAVAILABLE,
        TrackingStatus.ERROR,
        TrackingStatus.TIMEOUT,
    ):
        result = untracked(status, 1, 1, 1, FrameGeometry(640, 480), "why")
        assert result.gaze is not None
        assert result.gaze.status is GazeStatus.UNAVAILABLE
        assert status.value in result.gaze.message
        assert result.gaze_available is False


def test_untracked_accepts_a_caller_supplied_gaze() -> None:
    from gazefix.tracking.models import FrameGeometry, untracked

    supplied = unavailable("custom reason")
    result = untracked(
        TrackingStatus.NO_FACE, 1, 1, 1, FrameGeometry(640, 480), "why", gaze=supplied
    )
    assert result.gaze is supplied


def test_mirroring_a_tracking_result_mirrors_its_gaze() -> None:
    from gazefix.gaze.models import direction_from_angles

    tracking = gaze_scene(eye_yaw_deg=20.0).result()
    gaze = GazeResult(
        status=GazeStatus.ESTIMATED,
        confidence=unavailable("x").confidence,
        yaw_deg=20.0,
        pitch_deg=5.0,
        eye_yaw_deg=20.0,
        eye_pitch_deg=5.0,
        direction=direction_from_angles(20.0, 5.0),
    )
    mirrored = replace(tracking, gaze=gaze).mirrored()
    assert mirrored.gaze is not None
    assert mirrored.gaze.yaw_deg == -20.0
    assert mirrored.gaze.pitch_deg == 5.0


def test_a_tracking_result_without_a_gaze_field_mirrors_cleanly() -> None:
    tracking = gaze_scene(eye_yaw_deg=20.0).result()
    assert tracking.gaze is None
    assert tracking.mirrored().gaze is None


def test_gaze_available_requires_an_estimated_status() -> None:
    tracking = gaze_scene().result()
    for status, expected in (
        (GazeStatus.ESTIMATED, True),
        (GazeStatus.LOW_CONFIDENCE, False),
        (GazeStatus.UNAVAILABLE, False),
    ):
        gaze = replace(unavailable("x"), status=status)
        assert replace(tracking, gaze=gaze).gaze_available is expected


# --- settings validation ---


def test_gaze_settings_are_validated_by_app_settings() -> None:
    from dataclasses import replace as dc_replace

    from gazefix.config import AppSettings

    for overrides in (
        {"gaze_min_confidence": 1.5},
        {"gaze_smoothing": -0.2},
        {"gaze_eye_model_ratio": 0.0},
    ):
        with pytest.raises(ValueError):
            dc_replace(AppSettings(), **overrides).validated()  # type: ignore[arg-type]


def test_app_settings_carry_the_documented_gaze_defaults() -> None:
    from gazefix.config import AppSettings

    settings = AppSettings().validated()
    assert settings.gaze_enabled is True
    assert settings.gaze_eye_model_ratio == pytest.approx(1.25)
    assert 0.0 < settings.gaze_min_confidence < 1.0


def test_every_site_that_drops_landmark_history_drops_the_gaze_filter_too() -> None:
    """Structural guard on the call sites; the behaviour is covered above.

    This counts call sites, so it cannot notice a ``reset()`` that does
    nothing — that is what the behavioural tests are for. It exists to stop a
    future reset path being added for the stabiliser and forgotten for gaze.
    """

    import inspect

    from gazefix.tracking import worker as module

    source = inspect.getsource(module.TrackerWorker)
    stabiliser_resets = source.count("self._stabilizer.reset()")
    # The guarded helper, not the raw call: a raw ``self._gaze.reset()`` on a
    # lifecycle path is exactly the ARCH-01 defect, so it must appear only
    # inside ``_reset_gaze`` itself.
    gaze_resets = source.count("self._reset_gaze()")
    assert gaze_resets >= stabiliser_resets, (
        f"{stabiliser_resets} stabiliser resets but only {gaze_resets} gaze resets; "
        "every site that drops landmark history must drop the gaze filter too"
    )
    assert source.count("self._gaze.reset()") == 1, (
        "the estimator's reset must be reached only through _reset_gaze, which "
        "contains a raising implementation instead of letting it kill the thread"
    )


def test_a_low_quality_frame_still_carries_a_gaze_estimate_through_the_pipeline() -> None:
    """A covered eye downgrades tracking, and gaze must degrade rather than stop."""

    from gazefix.tracking import landmarks as topology

    scene = gaze_scene(eye_yaw_deg=15.0)
    landmarks = np.array(scene.landmarks, dtype=np.float32)
    # Push the subject's left eye out of the frame so M1 marks it invalid and
    # downgrades the frame to LOW_QUALITY, exactly as covering it would.
    for index in topology.eye_contour("left") + topology.iris_indices("left"):
        landmarks[index, 0] = np.float32(-0.05)
    factory = ScriptedFactory(
        tracker_kwargs={"faces": (RawFace(landmarks=landmarks, transform=scene.transform),)}
    )
    processor, _ = ready_processor(factory)
    try:
        driver = Driver(processor)
        for _ in range(200):
            output, _ = driver.once()
            tracking = output.tracking
            if tracking is not None and tracking.status is TrackingStatus.LOW_QUALITY:
                assert tracking.gaze is not None
                assert tracking.gaze.status.has_direction, tracking.gaze.message
                assert tracking.gaze.confidence.eyes_used == 1
                assert tracking.gaze.eye_yaw_deg == pytest.approx(15.0, abs=2.0)
                return
            time.sleep(0.005)
        raise AssertionError("never reached LOW_QUALITY")
    finally:
        processor.close()


def test_the_tracking_total_time_includes_the_gaze_stage_it_claims_to() -> None:
    """``tracking_total_ms`` is documented as covering the whole tracker span.

    It used to be sampled before analysis and gaze ran, so a slow estimator
    was invisible in the metric that claims to contain it.
    """

    from gazefix.gaze.models import unavailable as gaze_unavailable

    class SlowEstimator:
        description = "deliberately slow test estimator"

        def estimate(self, result):  # type: ignore[no-untyped-def]
            deadline = time.perf_counter() + 0.02
            while time.perf_counter() < deadline:
                pass
            return gaze_unavailable("slow test estimator")

        def reset(self) -> None:
            return None

    from gazefix.tracking.worker import TrackerWorker

    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(),)})
    settings = tracking_settings(tracking_wait_ms=200)
    processor = TrackingProcessor(factory, settings, PipelineMetrics())
    processor._worker = TrackerWorker(
        factory, settings, processor._metrics, gaze_estimator=SlowEstimator()
    )
    processor.start()
    try:
        assert wait_until(lambda: processor.status().state == "ready")
        output, _ = Driver(processor).until_tracked()
        tracking = output.tracking
        assert tracking is not None and tracking.timing.total_ms is not None
        assert tracking.timing.total_ms >= 20.0, tracking.timing.total_ms
    finally:
        processor.close()


def test_a_direction_without_an_eye_in_head_decomposition_does_not_break_rendering() -> None:
    """The contract permits it; the overlay and the UI line run per frame."""

    from gazefix.gaze.models import GazeConfidence, GazeResult, GazeStatus, direction_from_angles
    from gazefix.tracking.overlay import _gaze_lines
    from gazefix.ui.main_window import _gaze_detail_text

    partial = GazeResult(
        status=GazeStatus.ESTIMATED,
        confidence=GazeConfidence(0.9, 1.0, 1.0, 1.0, 1.0, 1.0, 2, True),
        yaw_deg=12.0,
        pitch_deg=-4.0,
        eye_yaw_deg=None,
        eye_pitch_deg=None,
        direction=direction_from_angles(12.0, -4.0),
    )
    assert "n/a" in " ".join(_gaze_lines(partial, ""))
    assert "n/a" in _gaze_detail_text(partial)


def test_a_substitute_estimator_drives_the_whole_pipeline() -> None:
    """The boundary is real: consumers depend on GazeResult, not on the algorithm."""

    from gazefix.gaze.models import GazeConfidence, GazeResult, GazeStatus, direction_from_angles

    class ConstantEstimator:
        description = "constant test estimator"

        def __init__(self) -> None:
            self.calls = 0
            self.resets = 0

        def estimate(self, result):  # type: ignore[no-untyped-def]
            self.calls += 1
            return GazeResult(
                status=GazeStatus.ESTIMATED,
                confidence=GazeConfidence(0.9, 1.0, 1.0, 1.0, 1.0, 1.0, 2, True),
                yaw_deg=42.0,
                pitch_deg=-7.0,
                eye_yaw_deg=42.0,
                eye_pitch_deg=-7.0,
                direction=direction_from_angles(42.0, -7.0),
                estimation_ms=0.01,
            )

        def reset(self) -> None:
            self.resets += 1

    from gazefix.tracking.worker import TrackerWorker

    substitute = ConstantEstimator()
    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(),)})
    settings = tracking_settings()
    processor = TrackingProcessor(factory, settings, PipelineMetrics())
    processor._worker = TrackerWorker(
        factory, settings, processor._metrics, gaze_estimator=substitute
    )
    processor.start()
    try:
        assert wait_until(lambda: processor.status().state == "ready")
        output, _ = Driver(processor).until_tracked()
        tracking = output.tracking
        assert tracking is not None and tracking.gaze is not None
        assert tracking.gaze.yaw_deg == 42.0
        assert tracking.gaze_available is True
        assert substitute.calls >= 1
        assert "constant test estimator" in processor._worker.gaze_description
    finally:
        processor.close()


# --- a substitute estimator's failures must never cost tracking (ARCH-01/02) ---


class RaisingEstimator:
    """A conforming ``GazeEstimator`` that breaks its promise never to raise.

    The boundary exists so M3+ can swap the algorithm, so the worker cannot
    assume an implementation behaves. Both entry points are covered because
    they fail through different paths: ``estimate`` runs inside ``_analyse``,
    ``reset`` runs on the tracker's own lifecycle paths.
    """

    description = "estimator that raises"

    def __init__(self, *, on_estimate: bool = False, on_reset: bool = False) -> None:
        self.on_estimate = on_estimate
        self.on_reset = on_reset
        self.estimate_calls = 0
        self.reset_calls = 0

    def estimate(self, result):  # type: ignore[no-untyped-def]
        self.estimate_calls += 1
        if self.on_estimate:
            raise RuntimeError("gaze estimate exploded")
        return unavailable("substitute estimator")

    def reset(self) -> None:
        self.reset_calls += 1
        if self.on_reset:
            raise RuntimeError("gaze reset exploded")


def worker_with(estimator, **overrides):  # type: ignore[no-untyped-def]
    from gazefix.tracking.worker import TrackerWorker

    factory = ScriptedFactory(tracker_kwargs={"faces": (scene_face(eye_yaw_deg=15.0),)})
    settings = tracking_settings(**overrides)
    processor = TrackingProcessor(factory, settings, PipelineMetrics())
    processor._worker = TrackerWorker(
        factory, settings, processor._metrics, gaze_estimator=estimator
    )
    processor.start()
    assert wait_until(lambda: processor.status().state in ("ready", "unavailable"))
    return processor, factory


def test_a_gaze_estimate_that_raises_does_not_cost_the_tracker(  # ARCH-02
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A gaze failure must not reach the tracker's inference-error path.

    It used to: the exception escaped ``_analyse``, was caught as an inference
    failure, spent the consecutive-error budget and rebuilt a healthy tracker,
    so every frame came back untracked.
    """

    estimator = RaisingEstimator(on_estimate=True)
    processor, factory = worker_with(estimator)
    try:
        with caplog.at_level(logging.ERROR):
            driver = Driver(processor)
            tracked = 0
            for _ in range(12):
                output, _ = driver.once()
                if output.tracking is not None and output.tracking.status is TrackingStatus.TRACKED:
                    tracked += 1
                    assert output.tracking.gaze is not None
                    assert output.tracking.gaze.status is GazeStatus.UNAVAILABLE
                    assert "gaze" in output.tracking.gaze.message
                time.sleep(0.004)
        assert tracked >= 8, "tracking must survive a broken gaze estimator"
        assert processor._worker.is_alive
        assert processor.status().state == "ready"
        assert factory.attempts == 1, "the tracker must not have been rebuilt"
    finally:
        processor.close()
    # And it is not called on every frame forever.
    assert estimator.estimate_calls <= 12
    assert any("gaze" in record.message.lower() for record in caplog.records)


def test_a_gaze_reset_that_raises_does_not_kill_the_tracker_thread() -> None:  # ARCH-01
    """A raising ``reset`` used to end the tracker thread through a double fault.

    The exception escaped, the crash-recovery path called ``reset`` again, and
    the second raise left the thread dead: tracking never recovered.
    """

    estimator = RaisingEstimator(on_reset=True)
    processor, factory = worker_with(estimator)
    try:
        driver = Driver(processor)
        tracked = 0
        # Two generations, so the reset path is exercised for real.
        for generation in (1, 2):
            for _ in range(6):
                output, _ = driver.once(generation=generation)
                if output.tracking is not None and output.tracking.status is TrackingStatus.TRACKED:
                    tracked += 1
                time.sleep(0.004)
        assert estimator.reset_calls >= 1, "the reset path must actually have run"
        assert processor._worker.is_alive, "the tracker thread must survive"
        assert processor.status().state == "ready"
        assert tracked >= 8, "tracking must keep producing results"
        assert factory.attempts == 1, "the tracker must not have been rebuilt"
    finally:
        processor.close()


def test_a_persistently_failing_estimator_is_retired_and_says_so() -> None:
    """Bounded, like every other failure path on this thread."""

    from gazefix.tracking.worker import _GAZE_MAX_CONSECUTIVE_ERRORS

    estimator = RaisingEstimator(on_estimate=True)
    processor, _ = worker_with(estimator)
    try:
        driver = Driver(processor)
        messages = []
        for _ in range(_GAZE_MAX_CONSECUTIVE_ERRORS + 8):
            output, _ = driver.once()
            if output.tracking is not None and output.tracking.gaze is not None:
                messages.append(output.tracking.gaze.message)
            time.sleep(0.004)
        assert estimator.estimate_calls <= _GAZE_MAX_CONSECUTIVE_ERRORS
        assert any("was stopped" in message for message in messages), messages
        assert processor._worker.is_alive
    finally:
        processor.close()


def test_a_retired_estimator_gets_another_chance_on_a_new_camera() -> None:
    """The tracker re-arms its own budgets on a generation change; so does gaze."""

    from gazefix.tracking.worker import _GAZE_MAX_CONSECUTIVE_ERRORS

    estimator = RaisingEstimator(on_estimate=True)
    processor, _ = worker_with(estimator)
    try:
        driver = Driver(processor)
        for _ in range(_GAZE_MAX_CONSECUTIVE_ERRORS + 4):
            driver.once(generation=1)
            time.sleep(0.004)
        retired = estimator.estimate_calls
        assert retired <= _GAZE_MAX_CONSECUTIVE_ERRORS
        estimator.on_estimate = False  # the substitute recovers
        for _ in range(6):
            driver.once(generation=2)
            time.sleep(0.004)
        assert estimator.estimate_calls > retired, "a new camera must re-arm the stage"
    finally:
        processor.close()
