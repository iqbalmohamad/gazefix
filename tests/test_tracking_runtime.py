"""TrackingProcessor inside the M0 runtime: identity, generations, shutdown."""

from __future__ import annotations

import time

import numpy as np

from camera_fakes import FakeCameraSource, factory_for
from gazefix.camera.models import CameraDevice
from gazefix.pipeline.runtime import PipelineRuntime, RuntimeState
from gazefix.tracking.models import TrackingStatus
from gazefix.tracking.processor import TrackingProcessor
from tracker_fakes import ScriptedFactory, tracking_settings, wait_until


def _outputs_until(runtime: PipelineRuntime, predicate, timeout: float = 3.0):  # type: ignore[no-untyped-def]
    """Collect published outputs until ``predicate(processed)`` holds."""

    deadline = time.perf_counter() + timeout
    last_sequence = 0
    seen = []
    while time.perf_counter() < deadline:
        item = runtime.consume_latest_output(last_sequence)
        if item is not None:
            last_sequence = item.sequence
            seen.append(item.value)
            if predicate(item.value):
                return seen
        time.sleep(0.005)
    raise AssertionError(f"condition not met; last statuses {[getattr(v.tracking, 'status', None) for v in seen[-5:]]}")


def test_results_are_tied_to_the_displayed_frame_and_generation() -> None:
    sources: list[FakeCameraSource] = []
    factory = ScriptedFactory()
    settings = tracking_settings(tracking_min_eye_width_px=0.0)
    processor = TrackingProcessor(factory, settings)
    runtime = PipelineRuntime(settings, processor=processor, source_factory=factory_for(sources))
    runtime.start()
    try:
        first_request = runtime.select_camera(CameraDevice(1))
        outputs = _outputs_until(
            runtime,
            lambda p: p.tracking is not None and p.tracking.status is TrackingStatus.TRACKED,
        )
        processed = outputs[-1]
        assert processed.camera_request_id == first_request
        assert processed.tracking.belongs_to(processed.capture_sequence, first_request)
        assert processed.tracking.captured_at_ns == processed.captured_at_ns
        assert int(processed.frame[0, 0, 0]) == 1  # original pixels of camera 1
        # Every published frame carries a result that names that frame.
        for value in outputs:
            assert value.tracking is not None
            assert value.tracking.belongs_to(value.capture_sequence, value.camera_request_id)

        second_request = runtime.select_camera(CameraDevice(2))
        outputs = _outputs_until(
            runtime,
            lambda p: p.tracking is not None
            and p.tracking.status is TrackingStatus.TRACKED
            and p.camera_request_id == second_request,
        )
        for value in outputs:
            # consume_latest_output already drops the old generation; what
            # reaches a consumer after the switch is generation 2 only.
            assert value.camera_request_id == second_request
            assert value.tracking is not None and value.tracking.camera_request_id == second_request
            assert int(value.frame[0, 0, 0]) == 2
        assert wait_until(lambda: factory.trackers[0].reset_calls == 1)
        assert len(factory.trackers) == 1 and factory.trackers[0].close_calls == 0
        snapshot = runtime.metrics()
        assert snapshot.tracked_frames > 0 and snapshot.pipeline_latency_ms > 0
    finally:
        assert runtime.stop()
    assert runtime.state is RuntimeState.STOPPED
    assert not processor.worker_alive
    assert all(t.close_calls == 1 for t in factory.trackers)
    assert all(s.closed for s in sources)


def test_tracker_failures_never_interrupt_the_original_preview() -> None:
    sources: list[FakeCameraSource] = []
    factory = ScriptedFactory()
    settings = tracking_settings(tracking_min_eye_width_px=0.0)
    runtime = PipelineRuntime(settings, processor=TrackingProcessor(factory, settings), source_factory=factory_for(sources))
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(3))
        _outputs_until(runtime, lambda p: p.tracking is not None and p.tracking.status is TrackingStatus.TRACKED)
        factory.trackers[0].failure = RuntimeError("inference exploded")
        outputs = _outputs_until(runtime, lambda p: p.tracking is not None and p.tracking.status is TrackingStatus.ERROR)
        assert all(int(v.frame[0, 0, 0]) == 3 for v in outputs)  # frames keep flowing untouched
        # The worker rebuilds the tracker after the bounded error count and recovers.
        assert wait_until(lambda: len(factory.trackers) == 2, timeout=3.0)
        _outputs_until(runtime, lambda p: p.tracking is not None and p.tracking.status is TrackingStatus.TRACKED, timeout=4.0)
    finally:
        assert runtime.stop()


def test_unavailable_tracker_leaves_the_pipeline_fully_functional() -> None:
    from tracker_fakes import init_error

    sources: list[FakeCameraSource] = []
    factory = ScriptedFactory(failures=[init_error("model missing")])
    settings = tracking_settings()
    runtime = PipelineRuntime(settings, processor=TrackingProcessor(factory, settings), source_factory=factory_for(sources))
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(4))
        outputs = _outputs_until(runtime, lambda p: p.tracking is not None and p.tracking.status is TrackingStatus.UNAVAILABLE)
        processed = outputs[-1]
        assert "model missing" in processed.tracking.message
        assert int(processed.frame[0, 0, 0]) == 4
        assert processed.tracking.landmarks is None
        capture_before = runtime.metrics().captured_frames
        time.sleep(0.1)
        assert runtime.metrics().captured_frames > capture_before  # capture unaffected
        assert factory.attempts == 1
    finally:
        assert runtime.stop()
    assert runtime.state is RuntimeState.STOPPED


def test_passthrough_processor_output_remains_metadata_free() -> None:
    from gazefix.pipeline.processor import PassthroughProcessor

    sources: list[FakeCameraSource] = []
    settings = tracking_settings()
    runtime = PipelineRuntime(settings, processor=PassthroughProcessor(), source_factory=factory_for(sources))
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(5))
        outputs = _outputs_until(runtime, lambda p: int(p.frame[0, 0, 0]) == 5)
        assert all(v.tracking is None for v in outputs)
        assert outputs[-1].capture_sequence > 0
    finally:
        assert runtime.stop()
