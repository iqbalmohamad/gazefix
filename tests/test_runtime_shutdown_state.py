"""Truthful shutdown-state bookkeeping for ``PipelineRuntime``.

Regression coverage for the M0 carry-forward defect: a timed-out shutdown used
to clear the runtime's started flag, so a later ``stop()`` reported success
while a worker was still alive inside a driver call. The state model is now
derived from worker-thread liveness; these tests pin that down with gated
fakes instead of wall-clock sleeps.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from threading import Event
import time

import pytest

from camera_fakes import FakeCameraSource, factory_for, fake_open_result, wait_until
from gazefix.camera.capture import CameraCaptureWorker
from gazefix.camera.models import CameraDevice, CameraOpenResult, CaptureState, CaptureStatus
from gazefix.camera.source import PreparedCamera
from gazefix.config import AppSettings
from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.frame_buffer import LatestValueBuffer
from gazefix.pipeline.runtime import PipelineRuntime, RuntimeState


JOIN_TIMEOUT_S = 0.3
SLACK_S = 0.4  # scheduling headroom on top of the configured deadline


def settings(**overrides: object) -> AppSettings:
    base = dict(
        reconnect_delay_s=0.01,
        read_retry_delay_s=0.001,
        worker_join_timeout_s=JOIN_TIMEOUT_S,
    )
    base.update(overrides)
    return replace(AppSettings(), **base)  # type: ignore[arg-type]


def wait_for_pixel(runtime: PipelineRuntime, pixel: int, timeout: float = 2.0) -> None:
    last_sequence = 0
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        item = runtime.consume_latest_output(last_sequence)
        if item is not None:
            last_sequence = item.sequence
            if int(item.value.frame[0, 0, 0]) == pixel:
                return
        time.sleep(0.002)
    raise AssertionError(f"no frame from camera {pixel} within {timeout}s")


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == name]


class GatedOpenSource(FakeCameraSource):
    """A driver open that ignores interrupts and returns only when the test lets it.

    Models the real constraint: ``cv2.VideoCapture.open`` cannot be cancelled
    from another thread, ``interrupt`` is flag-only exactly like
    ``OpenCVCameraSource``, and the owning thread releases the camera itself
    once the driver hands control back.
    """

    def __init__(self, registry: list[FakeCameraSource], gate: Event) -> None:
        super().__init__(registry)
        self.gate = gate

    def open(self, device: CameraDevice) -> CameraOpenResult:
        self.open_calls += 1
        self.open_started.set()
        self.gate.wait(10.0)
        self.index = device.index
        self.closed = False
        return fake_open_result()

    def interrupt(self) -> None:
        self.interrupt_calls += 1  # nothing to cancel; the owner checks later


class GatedProcessor:
    """A processing stage that blocks inside ``process`` until released."""

    def __init__(self, gate: Event) -> None:
        self.gate = gate
        self.entered = Event()

    def process(self, frame):  # type: ignore[no-untyped-def]
        self.entered.set()
        self.gate.wait(10.0)
        return frame


def prepared_camera(index: int) -> tuple[FakeCameraSource, PreparedCamera]:
    warm = FakeCameraSource()
    device = CameraDevice(index)
    return warm, PreparedCamera(device, warm, warm.open(device))


def test_clean_shutdown_is_stopped_and_a_repeated_stop_stays_truthful(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="gazefix.pipeline.runtime")
    sources: list[FakeCameraSource] = []
    statuses: list[CaptureStatus] = []
    runtime = PipelineRuntime(settings(), on_status=statuses.append, source_factory=factory_for(sources))
    assert runtime.state is RuntimeState.NEW
    runtime.start()
    assert runtime.state is RuntimeState.RUNNING
    runtime.select_camera(CameraDevice(1))
    wait_for_pixel(runtime, 1)

    started = time.perf_counter()
    assert runtime.stop() is True
    assert time.perf_counter() - started < JOIN_TIMEOUT_S + SLACK_S
    assert runtime.state is RuntimeState.STOPPED
    assert not runtime.workers_alive
    assert all(s.closed for s in sources)
    assert statuses[-1].state is CaptureState.STOPPED

    assert runtime.stop() is True  # idempotent and still derived from liveness
    assert runtime.state is RuntimeState.STOPPED
    assert len(events(caplog, "pipeline_stopped")) == 1  # finalized exactly once
    assert len(events(caplog, "pipeline_stop_repeated")) == 1
    assert events(caplog, "pipeline_shutdown_timeout") == []


def test_timed_out_stop_reports_false_until_the_capture_worker_really_exits(caplog: pytest.LogCaptureFixture) -> None:
    """The core regression: a worker abandoned in a driver call is never reported stopped."""

    caplog.set_level(logging.INFO, logger="gazefix.pipeline.runtime")
    gate = Event()
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(settings(), source_factory=lambda _s: GatedOpenSource(sources, gate))
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: bool(sources) and sources[0].open_started.is_set())
    try:
        for _ in range(2):  # the first stop, then a repeated stop after its timeout
            started = time.perf_counter()
            assert runtime.stop() is False
            elapsed = time.perf_counter() - started
            assert JOIN_TIMEOUT_S * 0.5 < elapsed < JOIN_TIMEOUT_S + SLACK_S, elapsed  # waited, but bounded
            assert runtime.state is RuntimeState.STOPPING
            assert runtime.workers_alive
        assert sources[0].interrupt_calls >= 1  # flagged, never released from here
        assert not sources[0].closed

        timeouts = events(caplog, "pipeline_shutdown_timeout")
        assert len(timeouts) == 2 and all(r.levelno == logging.ERROR for r in timeouts)
        assert timeouts[0].capture_alive is True and timeouts[0].processor_alive is False  # type: ignore[attr-defined]
        assert all(r.deadline_exhausted for r in timeouts)  # type: ignore[attr-defined]
        assert [r.repeated_stop for r in timeouts] == [False, True]  # type: ignore[attr-defined]
        assert events(caplog, "pipeline_stopped") == []
    finally:
        gate.set()  # the driver returns; the worker sees the stop and winds down itself

    assert wait_until(lambda: not runtime.workers_alive, timeout=3.0)
    assert sources[0].closed  # released by its owning thread
    assert runtime.state is RuntimeState.STOPPED  # liveness-derived, before any finalizing call
    started = time.perf_counter()
    assert runtime.stop() is True
    assert time.perf_counter() - started < SLACK_S
    stopped = events(caplog, "pipeline_stopped")
    assert len(stopped) == 1 and stopped[0].after_timeout is True  # type: ignore[attr-defined]


def test_timed_out_stop_tracks_a_stuck_processing_worker_independently(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="gazefix.pipeline.runtime")
    gate = Event()
    processor = GatedProcessor(gate)
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(settings(), processor=processor, source_factory=factory_for(sources))
    runtime.start()
    runtime.select_camera(CameraDevice(2))
    assert processor.entered.wait(2.0)
    try:
        started = time.perf_counter()
        assert runtime.stop() is False
        assert time.perf_counter() - started < JOIN_TIMEOUT_S + SLACK_S
        assert runtime.state is RuntimeState.STOPPING
        assert not runtime._capture.is_alive and runtime._processor.is_alive
        assert all(s.closed for s in sources)  # capture released its camera on its own thread
        record = events(caplog, "pipeline_shutdown_timeout")[-1]
        assert record.capture_alive is False and record.processor_alive is True  # type: ignore[attr-defined]
        assert runtime.stop() is False  # still truthful while the stage is blocked
    finally:
        gate.set()
    assert wait_until(lambda: not runtime.workers_alive, timeout=3.0)
    assert runtime.stop() is True
    assert runtime.state is RuntimeState.STOPPED


def test_timed_out_stop_still_closes_a_prepared_camera_the_worker_can_no_longer_adopt() -> None:
    gate = Event()
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(settings(), source_factory=lambda _s: GatedOpenSource(sources, gate))
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: bool(sources) and sources[0].open_started.is_set())
    warm, prepared = prepared_camera(5)
    runtime.select_camera(CameraDevice(5), prepared)  # lands while the worker is inside the driver open
    try:
        assert runtime.stop() is False
        # Taken from the worker by stop() (it may never reach its own cleanup)
        # and released on the cleanup thread, never on the caller's.
        assert runtime._capture.take_pending_prepared() == []
        assert wait_until(lambda: warm.closed) and not prepared.is_pending
    finally:
        gate.set()
    assert wait_until(lambda: not runtime.workers_alive, timeout=3.0)
    assert runtime.stop() is True
    assert sources[0].closed
    assert warm.close_calls == 1  # the worker's own cleanup found nothing left to close


def test_camera_requests_after_stop_are_refused_and_their_prepared_cameras_closed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="gazefix.pipeline.runtime")
    gate = Event()
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(settings(), source_factory=lambda _s: GatedOpenSource(sources, gate))
    runtime.start()
    first = runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: bool(sources) and sources[0].open_started.is_set())
    try:
        assert runtime.stop() is False  # STOPPING: worker alive inside the driver call
        warm, prepared = prepared_camera(3)
        assert runtime.select_camera(CameraDevice(3), prepared) == first  # no new generation
        assert wait_until(lambda: warm.closed) and not prepared.is_pending
        assert runtime.current_request_id == first
    finally:
        gate.set()
    assert wait_until(lambda: not runtime.workers_alive, timeout=3.0)
    assert runtime.stop() is True

    warm, prepared = prepared_camera(4)  # STOPPED: refused just the same
    assert runtime.select_camera(CameraDevice(4), prepared) == first
    assert wait_until(lambda: warm.closed) and not prepared.is_pending
    assert runtime.join_cleanup(2.0)
    assert runtime.select_camera(None) == first
    assert len(sources) == 1  # nothing was ever opened for a refused request
    refused = events(caplog, "camera_switch_refused")
    states = [r.runtime_state for r in refused]  # type: ignore[attr-defined]
    # The second refusal hands its token to the cleanup thread, so at the
    # moment it is logged that release may still be outstanding.
    assert states[0] == "stopping" and states[1] in {"stopping", "stopped"} and states[2] == "stopped"


def test_stop_before_start_is_stopped_and_start_is_then_refused() -> None:
    warm, prepared = prepared_camera(0)
    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    runtime.select_camera(CameraDevice(0), prepared)
    assert runtime.state is RuntimeState.NEW
    assert runtime.stop() is True
    assert warm.closed and not prepared.is_pending
    assert runtime.state is RuntimeState.STOPPED and not runtime.workers_alive
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        runtime.start()
    assert runtime.state is RuntimeState.STOPPED and not runtime.workers_alive


def test_runtime_is_single_use_and_does_not_pretend_to_restart() -> None:
    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    runtime.start()
    runtime.start()  # a second start while running is a no-op
    assert runtime.state is RuntimeState.RUNNING
    assert runtime.stop() is True
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        runtime.start()
    assert runtime.state is RuntimeState.STOPPED and not runtime.workers_alive


def test_capture_worker_refuses_prepared_cameras_once_stopped() -> None:
    """Ownership rule at the worker level: it owns prepared tokens only while running."""

    worker = CameraCaptureWorker(
        settings(), LatestValueBuffer(), PipelineMetrics(), source_factory=factory_for([])
    )
    worker.start()
    worker.stop()
    assert worker.join(2.0)
    warm, prepared = prepared_camera(1)
    assert worker.request_camera(CameraDevice(1), prepared) == 0  # generation unchanged
    assert warm.closed and not prepared.is_pending
    assert worker.request_camera(CameraDevice(2)) == 0
    worker.close_pending_prepared()  # nothing left behind
    assert warm.close_calls == 1
