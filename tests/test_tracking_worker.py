"""TrackingProcessor + TrackerWorker: threads, bounds, recovery, identity."""

from __future__ import annotations

import logging
from threading import Event
import time

import numpy as np
import pytest

from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.processor import FrameContext
from gazefix.tracking.models import TrackingStatus
from gazefix.tracking.processor import TrackingProcessor
from gazefix.tracking.tracker import RawFace
from tracker_fakes import (
    ScriptedFactory,
    ScriptedTracker,
    blank_frame,
    face,
    init_error,
    synthetic_face,
    tracking_settings,
    wait_until,
)


class Driver:
    """Feeds frames with increasing sequence numbers to a processor."""

    def __init__(self, processor: TrackingProcessor, frame: np.ndarray | None = None) -> None:
        self.processor = processor
        self.frame = blank_frame() if frame is None else frame
        self.sequence = 0

    def frame_once(self, generation: int = 1, frame: np.ndarray | None = None):  # type: ignore[no-untyped-def]
        self.sequence += 1
        context = FrameContext(self.sequence, time.perf_counter_ns(), generation)
        return self.processor.process(self.frame if frame is None else frame, context), context

    def until_status(self, status: TrackingStatus, generation: int = 1, attempts: int = 200):  # type: ignore[no-untyped-def]
        last = None
        for _ in range(attempts):
            output, context = self.frame_once(generation)
            last = output
            if output.tracking is not None and output.tracking.status is status:
                return output, context
            time.sleep(0.005)
        raise AssertionError(f"never reached {status}; last {last.tracking.status if last and last.tracking else None}")


def ready_processor(factory=None, **overrides):  # type: ignore[no-untyped-def]
    factory = factory or ScriptedFactory()
    processor = TrackingProcessor(factory, tracking_settings(**overrides), PipelineMetrics())
    processor.start()
    assert wait_until(lambda: processor.status().state == "ready")
    return processor, factory


def test_tracked_result_belongs_to_its_frame_and_frame_object_is_untouched() -> None:
    processor, factory = ready_processor()
    driver = Driver(processor)
    try:
        output, context = driver.until_status(TrackingStatus.TRACKED)
        tracking = output.tracking
        assert tracking is not None
        assert tracking.belongs_to(context.capture_sequence, context.camera_request_id)
        assert tracking.captured_at_ns == context.captured_at_ns
        assert output.frame is driver.frame  # overlay off: the input object itself
        assert tracking.face_valid and tracking.eyes_valid and tracking.iris_available
        assert tracking.pose is not None and tracking.quality is not None
        assert tracking.right_eye is not None and tracking.left_eye is not None
        assert tracking.right_eye.outer_corner[0] < tracking.left_eye.outer_corner[0]  # anatomical
        assert tracking.timing.waited_ms < tracking_settings().tracking_wait_ms
        assert tracking.timing.inference_ms == pytest.approx(1.0)
        tracker = factory.trackers[0]
        assert set(tracker.threads) == {"gazefix-tracker"}
        assert tracker.timestamps == sorted(tracker.timestamps) and len(set(tracker.timestamps)) == len(tracker.timestamps)
    finally:
        processor.close()
    assert not processor.worker_alive
    assert factory.trackers[0].close_calls == 1
    assert factory.trackers[0].close_thread == "gazefix-tracker"


def test_overlay_on_returns_a_new_array_and_never_writes_the_input() -> None:
    processor, _ = ready_processor()
    driver = Driver(processor)
    try:
        before = driver.frame.copy()
        processor.set_overlay_enabled(True)
        output, _ = driver.until_status(TrackingStatus.TRACKED)
        assert output.frame is not driver.frame
        assert output.frame.flags.writeable and output.frame.shape == driver.frame.shape
        assert np.array_equal(driver.frame, before) and not driver.frame.flags.writeable
        assert not np.array_equal(output.frame, before)  # something was drawn
        processor.set_overlay_enabled(False)
        output, _ = driver.until_status(TrackingStatus.TRACKED)
        assert output.frame is driver.frame
    finally:
        processor.close()


def test_frames_pass_through_immediately_while_the_tracker_initializes() -> None:
    gate = Event()
    factory = ScriptedFactory(gate=gate)
    processor = TrackingProcessor(factory, tracking_settings(), PipelineMetrics())
    driver = Driver(processor)
    try:
        started = time.perf_counter()
        output, context = driver.frame_once()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        assert output.tracking is not None
        assert output.tracking.status is TrackingStatus.INITIALIZING
        assert output.tracking.belongs_to(context.capture_sequence, context.camera_request_id)
        assert output.frame is driver.frame
        assert elapsed_ms < tracking_settings().tracking_wait_ms / 2
        assert set(factory.threads) == {"gazefix-tracker"}  # never on the caller's thread
        gate.set()
        driver.until_status(TrackingStatus.TRACKED)
    finally:
        gate.set()
        processor.close()


def test_generation_change_resets_the_tracker_and_never_attaches_old_results() -> None:
    processor, factory = ready_processor()
    driver = Driver(processor)
    try:
        driver.until_status(TrackingStatus.TRACKED, generation=1)
        tracker = factory.trackers[0]
        output, context = driver.until_status(TrackingStatus.TRACKED, generation=2)
        assert output.tracking is not None and output.tracking.camera_request_id == 2
        # The backend instance is kept; its temporal state is flushed on the
        # tracker thread before the first frame of the new generation.
        assert tracker.reset_calls == 1 and tracker.reset_threads == ["gazefix-tracker"]
        assert tracker.close_calls == 0 and len(factory.trackers) == 1
        # Every result published for generation 2 names generation 2 and its own frame.
        for _ in range(5):
            out, ctx = driver.frame_once(generation=2)
            assert out.tracking is not None
            assert out.tracking.belongs_to(ctx.capture_sequence, 2)
    finally:
        processor.close()
    assert tracker.close_calls == 1


def test_long_frame_gap_resets_temporal_state_without_rebuilding() -> None:
    processor, factory = ready_processor(tracking_reset_gap_s=0.05)
    driver = Driver(processor)
    try:
        driver.until_status(TrackingStatus.TRACKED)
        tracker = factory.trackers[0]
        time.sleep(0.12)  # a capture gap longer than the reset threshold
        driver.until_status(TrackingStatus.TRACKED)
        assert tracker.reset_calls >= 1 and tracker.close_calls == 0
    finally:
        processor.close()


def test_rebuild_budget_is_bounded_per_generation() -> None:
    processor, factory = ready_processor(tracking_max_rebuilds=1, tracking_max_consecutive_errors=1)
    driver = Driver(processor)
    try:
        driver.until_status(TrackingStatus.TRACKED)
        factory.trackers[0].failure = RuntimeError("boom")
        driver.until_status(TrackingStatus.ERROR)
        assert wait_until(lambda: len(factory.trackers) == 2)  # first rebuild
        factory.trackers[1].failure = RuntimeError("boom again")
        driver.until_status(TrackingStatus.ERROR)
        output, _ = driver.until_status(TrackingStatus.UNAVAILABLE)
        assert "rebuilt 1 times" in output.tracking.message
        time.sleep(0.15)
        assert len(factory.trackers) == 2  # no further rebuilds
        assert factory.trackers[1].close_calls == 1
        # A camera change re-arms the rebuild budget.
        driver.until_status(TrackingStatus.TRACKED, generation=2)
        assert len(factory.trackers) == 3
    finally:
        processor.close()


def test_stalled_tracker_times_out_once_then_passes_through_without_waiting() -> None:
    gate = Event()
    processor, factory = ready_processor()
    driver = Driver(processor)
    metrics = processor._metrics  # noqa: SLF001  (test inspects counters)
    try:
        driver.until_status(TrackingStatus.TRACKED)
        tracker = factory.trackers[0]
        tracker.gate = gate
        started = time.perf_counter()
        output, _ = driver.frame_once()
        waited_ms = (time.perf_counter() - started) * 1000.0
        assert output.tracking is not None and output.tracking.status is TrackingStatus.TIMEOUT
        assert waited_ms >= tracking_settings().tracking_wait_ms * 0.9
        assert output.frame is driver.frame
        # The tracker is still inside the (fake) native call: later frames do
        # not each wait the full budget; the preview keeps flowing.
        started = time.perf_counter()
        statuses = [driver.frame_once()[0].tracking.status for _ in range(5)]
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        assert statuses == [TrackingStatus.TIMEOUT] * 5
        assert elapsed_ms < tracking_settings().tracking_wait_ms
        gate.set()
        tracker.gate = None
        output, context = driver.until_status(TrackingStatus.TRACKED)
        assert output.tracking is not None and output.tracking.capture_sequence == context.capture_sequence
        snapshot = metrics.snapshot()
        assert snapshot.tracking_timeouts >= 6
        assert snapshot.tracking_replaced >= 1  # frames replaced in the tracker's slot while stalled
    finally:
        gate.set()
        processor.close()


def test_inference_errors_are_bounded_rebuild_the_tracker_and_log_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="gazefix.tracking.worker")
    processor, factory = ready_processor()
    driver = Driver(processor)
    try:
        driver.until_status(TrackingStatus.TRACKED)
        tracker = factory.trackers[0]
        tracker.failure = RuntimeError("boom")
        statuses = []
        for _ in range(3):
            out, ctx = driver.frame_once()
            assert wait_until(lambda: tracker.calls >= 0)
            statuses.append(out.tracking.status if out.tracking else None)
        assert wait_until(lambda: tracker.close_calls == 1)
        assert TrackingStatus.ERROR in statuses
        assert out.frame is driver.frame
        assert wait_until(lambda: len(factory.trackers) == 2)
        driver.until_status(TrackingStatus.TRACKED)
        error_logs = [r for r in caplog.records if getattr(r, "event", None) == "tracker_inference_error"]
        assert len(error_logs) == 1  # rate-limited, not per frame
        # A result built without inference carries no invented timing.
        tracker2 = factory.trackers[1]
        tracker2.gate = Event()
        out, _ = driver.frame_once()
        assert out.tracking is not None and out.tracking.status is TrackingStatus.TIMEOUT
        assert out.tracking.timing.inference_ms is None and out.tracking.timing.total_ms is None
        tracker2.gate.set()
    finally:
        processor.close()


def test_non_retryable_init_failure_gives_up_until_the_camera_changes(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="gazefix.tracking.worker")
    factory = ScriptedFactory(failures=[init_error("model missing"), init_error("model missing")])
    processor = TrackingProcessor(factory, tracking_settings(), PipelineMetrics())
    driver = Driver(processor)
    try:
        output, _ = driver.until_status(TrackingStatus.UNAVAILABLE)
        assert "model missing" in output.tracking.message
        for _ in range(20):
            out, _ = driver.frame_once()
            assert out.tracking is not None and out.tracking.status is TrackingStatus.UNAVAILABLE
            assert out.frame is driver.frame
        time.sleep(0.1)
        assert factory.attempts == 1  # no retry storm for a condition a retry cannot fix
        # A camera change re-arms the budget for exactly one more attempt; the
        # second scripted (non-retryable) failure exhausts it again.
        driver.until_status(TrackingStatus.UNAVAILABLE, generation=2)
        assert wait_until(lambda: factory.attempts == 2)
        time.sleep(0.1)
        assert factory.attempts == 2
        # The next camera change tries again and the factory now succeeds.
        driver.until_status(TrackingStatus.TRACKED, generation=3)
        assert factory.attempts == 3
        failures = [r for r in caplog.records if getattr(r, "event", None) == "tracker_init_failed"]
        assert len(failures) == 2
    finally:
        processor.close()


def test_retryable_init_failures_back_off_and_stop_at_the_attempt_limit() -> None:
    factory = ScriptedFactory(failures=[init_error("transient", retryable=True, kind="create")] * 10)
    processor = TrackingProcessor(factory, tracking_settings(tracking_init_max_attempts=3), PipelineMetrics())
    driver = Driver(processor)
    try:
        processor.start()
        assert wait_until(lambda: factory.attempts == 3, timeout=2.0)
        time.sleep(0.2)
        assert factory.attempts == 3  # bounded: no attempt after the limit
        out, _ = driver.frame_once()
        assert out.tracking is not None and out.tracking.status is TrackingStatus.UNAVAILABLE
        assert "no further attempts" in out.tracking.message
    finally:
        processor.close()


def test_close_during_a_blocked_initialization_is_bounded_and_releases_later() -> None:
    gate = Event()
    factory = ScriptedFactory(gate=gate)
    settings = tracking_settings(tracking_join_timeout_s=0.2)
    processor = TrackingProcessor(factory, settings, PipelineMetrics())
    processor.start()
    assert wait_until(lambda: factory.attempts == 1)
    started = time.perf_counter()
    processor.close()
    elapsed = time.perf_counter() - started
    assert elapsed < settings.tracking_join_timeout_s + 0.3
    assert processor.worker_alive  # truthfully still inside the "native" call
    gate.set()
    assert wait_until(lambda: not processor.worker_alive)
    assert factory.trackers and factory.trackers[0].close_calls == 1  # released by the thread itself


def test_close_during_a_blocked_inference_is_bounded() -> None:
    gate = Event()
    processor, factory = ready_processor(tracking_join_timeout_s=0.2)
    driver = Driver(processor)
    driver.until_status(TrackingStatus.TRACKED)
    tracker = factory.trackers[0]
    tracker.gate = gate
    tracker.detect_started.clear()
    driver.frame_once()
    assert tracker.detect_started.wait(1.0)
    started = time.perf_counter()
    processor.close()
    assert time.perf_counter() - started < 0.6
    assert processor.worker_alive
    gate.set()
    assert wait_until(lambda: not processor.worker_alive)
    assert tracker.close_calls == 1


def test_no_face_then_reentry_and_malformed_landmarks() -> None:
    processor, factory = ready_processor()
    driver = Driver(processor)
    try:
        driver.until_status(TrackingStatus.TRACKED)
        tracker = factory.trackers[0]
        tracker.faces = ()
        output, _ = driver.until_status(TrackingStatus.NO_FACE)
        assert output.tracking is not None and output.tracking.landmarks is None
        assert output.tracking.faces_detected == 0 and output.tracking.message
        tracker.faces = (RawFace(landmarks=np.zeros((100, 3), dtype=np.float32)),)
        output, _ = driver.until_status(TrackingStatus.ERROR)
        assert "malformed" in output.tracking.message and output.tracking.landmarks is None
        tracker.faces = (face(),)
        driver.until_status(TrackingStatus.TRACKED)
    finally:
        processor.close()


def test_partial_face_is_low_quality_and_never_valid() -> None:
    processor, factory = ready_processor()
    driver = Driver(processor)
    try:
        driver.until_status(TrackingStatus.TRACKED)
        factory.trackers[0].faces = (face(center=(0.02, 0.5)),)  # left half outside the frame
        output, _ = driver.until_status(TrackingStatus.LOW_QUALITY)
        tracking = output.tracking
        assert tracking is not None and tracking.landmarks is not None
        assert not tracking.face_valid and not tracking.eyes_valid
        assert tracking.quality is not None and tracking.quality.in_frame_fraction < 1.0
        assert tracking.message
    finally:
        processor.close()


def test_without_iris_landmarks_iris_is_reported_unavailable() -> None:
    factory = ScriptedFactory(
        tracker_kwargs={"faces": (RawFace(landmarks=synthetic_face(count=468)),)}
    )
    processor, _ = ready_processor(factory, tracking_min_eye_width_px=0.0)
    driver = Driver(processor)
    try:
        output, _ = driver.until_status(TrackingStatus.TRACKED)
        tracking = output.tracking
        assert tracking is not None and not tracking.iris_available
        assert tracking.left_eye is not None and tracking.left_eye.iris is None
        assert tracking.pose is None  # no transform supplied
    finally:
        processor.close()


def test_primary_face_is_the_largest_and_stays_stable() -> None:
    small = face(center=(0.25, 0.5), face_height=0.25)
    large = face(center=(0.7, 0.5), face_height=0.45)
    factory = ScriptedFactory(tracker_kwargs={"faces": (small, large)})
    processor, factory = ready_processor(factory)
    driver = Driver(processor)
    try:
        output, _ = driver.until_status(TrackingStatus.TRACKED)
        assert output.tracking is not None and output.tracking.faces_detected == 2
        assert abs(float(output.tracking.landmarks[1, 0]) - 0.7) < 0.02  # nose tip of the large face
        # The primary shrinks a little and the other face grows past it, but the
        # primary is still nearby and of comparable size: identity is kept.
        factory.trackers[0].faces = (face(center=(0.25, 0.5), face_height=0.36), face(center=(0.72, 0.5), face_height=0.34))
        output, _ = driver.until_status(TrackingStatus.TRACKED)
        assert abs(float(output.tracking.landmarks[1, 0]) - 0.72) < 0.02
    finally:
        processor.close()


def test_metrics_count_outcomes_by_status() -> None:
    metrics = PipelineMetrics()
    factory = ScriptedFactory()
    processor = TrackingProcessor(factory, tracking_settings(), metrics)
    processor.start()
    assert wait_until(lambda: processor.status().state == "ready")
    driver = Driver(processor)
    try:
        for _ in range(3):
            driver.until_status(TrackingStatus.TRACKED)
        factory.trackers[0].faces = ()
        driver.until_status(TrackingStatus.NO_FACE)
        snapshot = metrics.snapshot()
        assert snapshot.tracked_frames >= 3 and snapshot.no_face_frames >= 1
        assert snapshot.tracking_inference_ms == pytest.approx(1.0)
        assert snapshot.tracking_total_ms > 0
    finally:
        processor.close()


def test_smoothing_resets_on_loss_and_camera_change_even_for_tiny_steps() -> None:
    """A step below the stabiliser's motion scale would be blended (not passed
    through) unless the filter was reset; the exact position proves the reset."""

    processor, factory = ready_processor(tracking_smoothing=0.8)
    driver = Driver(processor)
    try:
        output, _ = driver.until_status(TrackingStatus.TRACKED)
        assert output.tracking is not None and output.tracking.stabilized
        tracker = factory.trackers[0]
        nose_x = float(output.tracking.landmarks[1, 0])
        # Same face, a sub-motion-scale step, no reset: the output lags.
        tracker.faces = (face(center=(0.5 + 0.005, 0.5)),)
        output, _ = driver.until_status(TrackingStatus.TRACKED)
        lagged = float(output.tracking.landmarks[1, 0])
        assert nose_x < lagged < 0.505 - 1e-4
        # Loss then re-entry with another tiny step: exact, no bleed.
        tracker.faces = ()
        driver.until_status(TrackingStatus.NO_FACE)
        tracker.faces = (face(center=(0.51, 0.5)),)
        output, _ = driver.until_status(TrackingStatus.TRACKED)
        assert float(output.tracking.landmarks[1, 0]) == pytest.approx(0.51, abs=1e-6)
        # Camera change with a tiny step: exact again.
        tracker.faces = (face(center=(0.515, 0.5)),)
        output, _ = driver.until_status(TrackingStatus.TRACKED, generation=2)
        assert float(output.tracking.landmarks[1, 0]) == pytest.approx(0.515, abs=1e-6)
    finally:
        processor.close()


def test_processor_close_is_idempotent_and_safe_before_start() -> None:
    processor = TrackingProcessor(ScriptedFactory(), tracking_settings(), PipelineMetrics())
    processor.close()
    processor.close()
    assert not processor.worker_alive
    processor.start()  # after close: no thread is started
    assert not processor.worker_alive
