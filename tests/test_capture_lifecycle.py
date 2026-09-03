"""Lifecycle hardening tests for the capture worker driven through PipelineRuntime."""

from __future__ import annotations

from dataclasses import replace
from threading import Event
import time

import numpy as np

from camera_fakes import FakeCameraSource, fake_open_result, factory_for, wait_until
from gazefix.camera.models import CameraDevice, CaptureState, CaptureStatus
from gazefix.camera.source import PreparedCamera
from gazefix.config import AppSettings
from gazefix.pipeline.processor import ProcessedFrame
from gazefix.pipeline.runtime import PipelineRuntime


def fast_settings(**overrides: object) -> AppSettings:
    base = dict(
        reconnect_delay_s=0.01,
        read_retry_delay_s=0.001,
        worker_join_timeout_s=1.0,
        transient_read_failures=2,
    )
    base.update(overrides)
    return replace(AppSettings(), **base)  # type: ignore[arg-type]


def frames_after(runtime: PipelineRuntime, timeout: float) -> list[int]:
    """Collect the pixel value of every frame the runtime yields for ``timeout``."""

    seen: list[int] = []
    last_sequence = 0
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        item = runtime.consume_latest_output(last_sequence)
        if item is not None:
            last_sequence = item.sequence
            seen.append(int(item.value.frame[0, 0, 0]))
        time.sleep(0.002)
    return seen


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


def test_every_idle_request_emits_its_own_idle_status() -> None:
    """Regression: the UI refresh flow waits for IDLE after select_camera(None).

    Before the fix an identical IDLE status for a new request was de-duplicated
    away, so a Refresh pressed while already idle never started discovery.
    """

    statuses: list[CaptureStatus] = []
    runtime = PipelineRuntime(
        fast_settings(), on_status=statuses.append, source_factory=factory_for([])
    )
    runtime.start()
    try:
        first = runtime.select_camera(None)
        assert wait_until(
            lambda: any(s.state is CaptureState.IDLE and s.request_id == first for s in statuses)
        )
        second = runtime.select_camera(None)
        assert second != first
        assert wait_until(
            lambda: any(s.state is CaptureState.IDLE and s.request_id == second for s in statuses)
        ), [(s.state, s.request_id) for s in statuses]
    finally:
        assert runtime.stop()


def test_frame_read_before_switch_is_never_delivered_after_switch() -> None:
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(fast_settings(), source_factory=factory_for(sources))
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(1))
        wait_for_pixel(runtime, 1)
        old = sources[-1]
        # Hold the next read of camera 1 open across the switch request.
        gate = Event()
        old.read_started.clear()
        old.read_gate = gate
        assert old.read_started.wait(1.0)

        runtime.select_camera(CameraDevice(2))
        gate.set()  # the stale frame from camera 1 now returns to the worker

        seen = frames_after(runtime, 0.3)
        assert 2 in seen
        assert 1 not in seen, seen
        assert wait_until(lambda: old.closed)
    finally:
        assert runtime.stop()


def test_runtime_rejects_output_tagged_with_a_previous_generation() -> None:
    runtime = PipelineRuntime(fast_settings(), source_factory=factory_for([]))
    current = runtime.select_camera(CameraDevice(0))
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    stale = ProcessedFrame(frame, 0, 0, camera_request_id=current - 1)
    fresh = ProcessedFrame(frame, 0, 0, camera_request_id=current)

    runtime._output_buffer.publish(stale)
    assert runtime.consume_latest_output(0) is None
    runtime._output_buffer.publish(fresh)
    item = runtime.consume_latest_output(0)
    assert item is not None and item.value.camera_request_id == current
    assert runtime.stop()


def test_switch_during_blocked_open_interrupts_it_without_stale_statuses() -> None:
    sources: list[FakeCameraSource] = []
    statuses: list[CaptureStatus] = []
    blocking = FakeCameraSource(sources, block_open=True)
    ready = FakeCameraSource(sources)
    queue = [blocking, ready]
    runtime = PipelineRuntime(
        fast_settings(reconnect_delay_s=2.0),
        on_status=statuses.append,
        source_factory=lambda _settings: queue.pop(0),
    )
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(7))
        assert blocking.open_started.wait(1.0)
        switched_at = time.perf_counter()
        second = runtime.select_camera(CameraDevice(8))
        wait_for_pixel(runtime, 8)
        switch_s = time.perf_counter() - switched_at

        assert blocking.interrupt_calls == 1
        assert switch_s < 1.0, f"switch took {switch_s:.2f}s; the blocked open was not interrupted"
        stale = [
            s for s in statuses
            if s.camera == CameraDevice(7) and s.state in {CaptureState.ERROR, CaptureState.RUNNING}
        ]
        assert not stale, [(s.state, s.message) for s in stale]
        assert any(s.state is CaptureState.RUNNING and s.request_id == second for s in statuses)
    finally:
        assert runtime.stop()


def test_rapid_repeated_selection_settles_on_last_request_and_closes_the_rest() -> None:
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(fast_settings(), source_factory=factory_for(sources))
    runtime.start()
    try:
        last = 0
        for step in range(40):
            last = step % 3 + 1
            runtime.select_camera(CameraDevice(last))
        wait_for_pixel(runtime, last)
        seen = frames_after(runtime, 0.2)
        assert set(seen) <= {last}, seen
        assert wait_until(lambda: sum(not s.closed for s in sources) == 1)
        live = [s for s in sources if not s.closed]
        assert live[0].index == last
    finally:
        assert runtime.stop()
        assert all(s.closed for s in sources)


def test_shutdown_during_retry_wait_returns_promptly() -> None:
    sources: list[FakeCameraSource] = []
    statuses: list[CaptureStatus] = []
    runtime = PipelineRuntime(
        fast_settings(reconnect_delay_s=5.0, worker_join_timeout_s=2.0),
        on_status=statuses.append,
        source_factory=factory_for(sources, openable=set()),
    )
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: any(s.state is CaptureState.ERROR for s in statuses))

    started = time.perf_counter()
    assert runtime.stop()
    assert time.perf_counter() - started < 1.0
    assert not runtime.workers_alive
    assert statuses[-1].state is CaptureState.STOPPED


def test_shutdown_during_reopen_after_read_failures_returns_promptly() -> None:
    sources: list[FakeCameraSource] = []
    statuses: list[CaptureStatus] = []
    runtime = PipelineRuntime(
        fast_settings(reconnect_delay_s=5.0, worker_join_timeout_s=2.0),
        on_status=statuses.append,
        source_factory=factory_for(sources, fail_reads=True),
    )
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: any(s.state is CaptureState.RETRYING for s in statuses))

    started = time.perf_counter()
    assert runtime.stop()
    assert time.perf_counter() - started < 1.0
    assert all(s.closed for s in sources)


def test_read_exception_is_a_recoverable_read_failure() -> None:
    sources: list[FakeCameraSource] = []
    statuses: list[CaptureStatus] = []
    attempts = 0

    def create(_settings: AppSettings) -> FakeCameraSource:
        nonlocal attempts
        attempts += 1
        exc = RuntimeError("backend read exploded") if attempts == 1 else None
        return FakeCameraSource(sources, read_exception=exc)

    runtime = PipelineRuntime(fast_settings(), on_status=statuses.append, source_factory=create)
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(3))
        wait_for_pixel(runtime, 3)
        states = [s.state for s in statuses]
        assert CaptureState.DEGRADED in states
        assert CaptureState.RETRYING in states
        assert runtime.workers_alive
        assert attempts >= 2
    finally:
        assert runtime.stop()


def test_close_exception_during_switch_does_not_kill_the_worker() -> None:
    sources: list[FakeCameraSource] = []
    first = FakeCameraSource(sources, close_exception=RuntimeError("release failed"))
    second = FakeCameraSource(sources)
    queue = [first, second]
    runtime = PipelineRuntime(
        fast_settings(), source_factory=lambda _settings: queue.pop(0)
    )
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(1))
        wait_for_pixel(runtime, 1)
        runtime.select_camera(CameraDevice(2))
        wait_for_pixel(runtime, 2)
        assert first.close_calls == 1
        assert runtime.workers_alive
    finally:
        assert runtime.stop()


def test_prepared_camera_is_adopted_without_a_second_open() -> None:
    created: list[FakeCameraSource] = []
    warm = FakeCameraSource()
    device = CameraDevice(0)
    result = warm.open(device)
    prepared = PreparedCamera(device, warm, result)
    statuses: list[CaptureStatus] = []
    runtime = PipelineRuntime(
        fast_settings(), on_status=statuses.append, source_factory=factory_for(created)
    )
    runtime.start()
    try:
        runtime.select_camera(device, prepared)
        wait_for_pixel(runtime, 0)
        assert created == []  # no fresh source, hence no second open
        assert warm.open_calls == 1
        assert not prepared.is_pending
        assert any(s.state is CaptureState.RUNNING and s.open_result == result for s in statuses)
        assert not any(s.state is CaptureState.STARTING for s in statuses)

        runtime.select_camera(CameraDevice(1))
        wait_for_pixel(runtime, 1)
        assert warm.closed
        assert len(created) == 1
    finally:
        assert runtime.stop()


def test_prepared_camera_of_a_superseded_request_is_closed_by_the_worker() -> None:
    warm = FakeCameraSource()
    device = CameraDevice(0)
    prepared = PreparedCamera(device, warm, warm.open(device))
    created: list[FakeCameraSource] = []
    runtime = PipelineRuntime(fast_settings(), source_factory=factory_for(created))
    # Both requests land before the worker runs; only the last one is applied.
    runtime.select_camera(device, prepared)
    runtime.select_camera(CameraDevice(1))
    runtime.start()
    try:
        wait_for_pixel(runtime, 1)
        assert wait_until(lambda: warm.closed)
        assert not prepared.is_pending
    finally:
        assert runtime.stop()


def test_prepared_camera_for_a_different_device_is_closed_and_not_adopted() -> None:
    warm = FakeCameraSource()
    prepared = PreparedCamera(CameraDevice(5), warm, warm.open(CameraDevice(5)))
    created: list[FakeCameraSource] = []
    runtime = PipelineRuntime(fast_settings(), source_factory=factory_for(created))
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(6), prepared)
        wait_for_pixel(runtime, 6)
        assert warm.closed and not prepared.is_pending
        assert len(created) == 1
    finally:
        assert runtime.stop()


def test_stop_closes_a_prepared_camera_the_worker_never_adopted() -> None:
    warm = FakeCameraSource()
    device = CameraDevice(0)
    prepared = PreparedCamera(device, warm, warm.open(device))
    runtime = PipelineRuntime(fast_settings(), source_factory=factory_for([]))
    runtime.select_camera(device, prepared)  # never started
    assert runtime.stop()
    assert warm.closed


def test_stale_generation_status_carries_its_request_id() -> None:
    statuses: list[CaptureStatus] = []
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(
        fast_settings(), on_status=statuses.append, source_factory=factory_for(sources)
    )
    runtime.start()
    try:
        first = runtime.select_camera(CameraDevice(1))
        wait_for_pixel(runtime, 1)
        second = runtime.select_camera(CameraDevice(2))
        wait_for_pixel(runtime, 2)
        by_request = {s.request_id for s in statuses if s.camera is not None}
        assert {first, second} <= by_request
        assert runtime.current_request_id == second
        assert all(s.request_id == first for s in statuses if s.camera == CameraDevice(1))
    finally:
        assert runtime.stop()


def test_open_result_is_reported_in_running_status() -> None:
    statuses: list[CaptureStatus] = []
    runtime = PipelineRuntime(
        fast_settings(), on_status=statuses.append, source_factory=factory_for([])
    )
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(4))
        wait_for_pixel(runtime, 4)
        running = [s for s in statuses if s.state is CaptureState.RUNNING]
        assert running and running[0].open_result == fake_open_result()
    finally:
        assert runtime.stop()


def test_transient_failure_allowance_is_restored_after_a_reopen() -> None:
    """After a reopen, one bad read must not immediately trigger another reopen."""

    sources: list[FakeCameraSource] = []
    statuses: list[CaptureStatus] = []

    def create(_settings: AppSettings) -> FakeCameraSource:
        # First source never reads; later sources fail exactly one read then recover.
        source = FakeCameraSource(sources, fail_reads=(len(sources) == 0))
        return source

    runtime = PipelineRuntime(
        fast_settings(transient_read_failures=3),
        on_status=statuses.append,
        source_factory=create,
    )
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(2))
        assert wait_until(lambda: len(sources) == 2)
        second = sources[1]
        second.fail_reads = True
        assert wait_until(lambda: any(
            s.state is CaptureState.DEGRADED and s.message.startswith("Temporary frame-read failure (1/")
            and statuses.index(s) > 0 for s in statuses[-3:]
        ))
        second.fail_reads = False
        wait_for_pixel(runtime, 2)
        assert len(sources) == 2, "a single failed read after the reopen caused another reopen"
    finally:
        assert runtime.stop()


def test_stalled_read_reopens_immediately_instead_of_counting_as_transient() -> None:
    """A failed read that took as long as the backend's own wait is a stall."""

    sources: list[FakeCameraSource] = []
    statuses: list[CaptureStatus] = []

    def create(_settings: AppSettings) -> FakeCameraSource:
        source = FakeCameraSource(sources)
        if len(sources) == 1:
            source.fail_reads = True
            source.read_delay = 0.15  # longer than stalled_read_s below
        return source

    runtime = PipelineRuntime(
        fast_settings(transient_read_failures=5, stalled_read_s=0.1),
        on_status=statuses.append,
        source_factory=create,
    )
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(1))
        wait_for_pixel(runtime, 1, timeout=3.0)
        states = [s.state for s in statuses]
        assert CaptureState.RETRYING in states
        assert CaptureState.DEGRADED not in states
        assert sources[0].reads == 0 and sources[0].closed
        assert len(sources) == 2
    finally:
        assert runtime.stop()


def test_reopen_after_stall_rotates_backend_and_remembers_the_one_that_worked(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from gazefix.camera import capture as capture_module
    from gazefix.camera.models import CameraBackend

    alpha, beta = CameraBackend(1, "ALPHA"), CameraBackend(2, "BETA")
    monkeypatch.setattr(
        capture_module,
        "next_backend_after",
        lambda backend, platform=None: beta if backend == alpha else alpha,
    )
    opened_with: list[CameraBackend | None] = []
    sources: list[FakeCameraSource] = []

    class BackendAwareSource(FakeCameraSource):
        def open(self, device: CameraDevice) -> CameraOpenResult:
            opened_with.append(device.validated_backend)
            result = super().open(device)
            # report the backend that actually served the open
            return replace(result, backend=device.validated_backend or alpha)

    def create(_settings: AppSettings) -> BackendAwareSource:
        source = BackendAwareSource(sources)
        if len(sources) == 1:
            source.fail_reads = True
            source.read_delay = 0.15
        return source

    runtime = PipelineRuntime(
        fast_settings(stalled_read_s=0.1), source_factory=create
    )
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(0, alpha))
        wait_for_pixel(runtime, 0, timeout=3.0)
        assert opened_with == [alpha, beta]  # stall on ALPHA -> reopen prefers BETA
    finally:
        assert runtime.stop()


def test_open_failure_backoff_and_single_starting_status() -> None:
    sources: list[FakeCameraSource] = []
    statuses: list[CaptureStatus] = []
    runtime = PipelineRuntime(
        fast_settings(reconnect_delay_s=0.02, reconnect_delay_max_s=0.08, worker_join_timeout_s=2.0),
        on_status=statuses.append,
        source_factory=factory_for(sources, openable=set()),
    )
    worker = runtime._capture
    assert [worker._reconnect_delay(n) for n in range(5)] == [0.02, 0.04, 0.08, 0.08, 0.08]
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(0))
        assert wait_until(lambda: len(sources) >= 4, timeout=3.0)
        starting = [s for s in statuses if s.state is CaptureState.STARTING]
        assert len(starting) == 1
        assert statuses[-1].state is CaptureState.ERROR
    finally:
        assert runtime.stop()


def test_retry_delay_is_honoured_after_a_switch_to_a_camera_that_fails() -> None:
    """A stale command event must not turn the first retry into an immediate reopen."""

    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(
        fast_settings(reconnect_delay_s=0.3, reconnect_delay_max_s=0.3, worker_join_timeout_s=2.0),
        source_factory=factory_for(sources, openable={1}),
    )
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(1))
        wait_for_pixel(runtime, 1)
        runtime.select_camera(CameraDevice(2))  # request lands during a read
        assert wait_until(lambda: len(sources) == 2)
        time.sleep(0.15)  # well inside the first retry delay
        assert len(sources) == 2, "second open attempt started before the retry delay elapsed"
        assert wait_until(lambda: len(sources) == 3, timeout=1.0)
    finally:
        assert runtime.stop()


def test_uninterruptible_open_bounds_shutdown_and_reports_it_honestly() -> None:
    """A real driver open cannot be cancelled; stop() must give up within its
    budget and say so rather than hang or pretend."""

    class UninterruptibleOpen(FakeCameraSource):
        def open(self, device: CameraDevice) -> CameraOpenResult:
            self.open_started.set()
            time.sleep(1.5)  # simulates a driver call that ignores everything
            return super().open(device)

        def interrupt(self) -> None:
            self.interrupt_calls += 1  # flag only, like OpenCVCameraSource

    sources: list[FakeCameraSource] = []

    def create(_settings: AppSettings) -> UninterruptibleOpen:
        return UninterruptibleOpen(sources)

    runtime = PipelineRuntime(
        fast_settings(worker_join_timeout_s=0.6), source_factory=create
    )
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: bool(sources))
    assert sources[0].open_started.wait(1.0)
    started = time.perf_counter()
    clean = runtime.stop()
    elapsed = time.perf_counter() - started
    assert clean is False
    assert elapsed < 1.0
    # ...and the worker still winds down by itself once the driver returns.
    assert wait_until(lambda: not runtime.workers_alive, timeout=3.0)
    assert sources[0].closed


class CheckpointOpenSource(FakeCameraSource):
    """Mirrors OpenCVCameraSource: the driver call cannot be cancelled, the
    interrupt flag is honoured at the checkpoint after it returns, and
    ``reinstate`` withdraws the flag."""

    driver_open_s = 0.3

    def open(self, device: CameraDevice) -> CameraOpenResult:
        self.open_calls += 1
        self.open_started.set()
        time.sleep(self.driver_open_s)  # the un-cancellable driver call
        if self.interrupted.is_set():
            self.closed = True
            raise RuntimeError("Camera open interrupted")
        self.index = device.index
        self.closed = False
        return fake_open_result()

    def interrupt(self) -> None:
        self.interrupt_calls += 1
        self.interrupted.set()

    def reinstate(self) -> None:
        self.interrupted.clear()


def test_flipping_away_and_back_during_open_keeps_the_completed_open() -> None:
    """A completed slow open of X must not be thrown away when the newest
    request is X again."""

    sources: list[CheckpointOpenSource] = []
    statuses: list[CaptureStatus] = []

    def create(_settings: AppSettings) -> CheckpointOpenSource:
        return CheckpointOpenSource(sources)

    runtime = PipelineRuntime(fast_settings(), on_status=statuses.append, source_factory=create)
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(0))
        assert wait_until(lambda: bool(sources) and sources[0].open_started.is_set())
        runtime.select_camera(CameraDevice(1))  # away...
        final = runtime.select_camera(CameraDevice(0))  # ...and back while still opening
        wait_for_pixel(runtime, 0, timeout=3.0)

        assert [s.open_calls for s in sources] == [1]  # one driver open, kept
        assert sources[0].interrupt_calls == 1 and not sources[0].interrupted.is_set()
        assert any(s.state is CaptureState.RUNNING and s.request_id == final for s in statuses)
        assert not any(s.camera == CameraDevice(1) for s in statuses)  # camera 1 never touched
    finally:
        assert runtime.stop()


def test_switching_to_another_camera_during_open_still_abandons_it() -> None:
    sources: list[CheckpointOpenSource] = []

    def create(_settings: AppSettings) -> CheckpointOpenSource:
        return CheckpointOpenSource(sources)

    runtime = PipelineRuntime(fast_settings(), source_factory=create)
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(0))
        assert wait_until(lambda: bool(sources) and sources[0].open_started.is_set())
        runtime.select_camera(CameraDevice(1))
        wait_for_pixel(runtime, 1, timeout=3.0)
        assert sources[0].interrupt_calls == 1 and sources[0].closed
        assert [s.index for s in sources if not s.closed] == [1]
    finally:
        assert runtime.stop()


def test_reselecting_the_running_camera_keeps_its_source() -> None:
    sources: list[FakeCameraSource] = []
    statuses: list[CaptureStatus] = []
    runtime = PipelineRuntime(
        fast_settings(), on_status=statuses.append, source_factory=factory_for(sources)
    )
    runtime.start()
    try:
        runtime.select_camera(CameraDevice(3))
        wait_for_pixel(runtime, 3)
        again = runtime.select_camera(CameraDevice(3))
        wait_for_pixel(runtime, 3)
        assert wait_until(lambda: any(
            s.state is CaptureState.RUNNING and s.request_id == again for s in statuses))
        assert len(sources) == 1 and not sources[0].closed
    finally:
        assert runtime.stop()


def test_terminal_statuses_arrive_in_order_from_the_worker() -> None:
    for _ in range(5):
        statuses: list[CaptureStatus] = []
        runtime = PipelineRuntime(
            fast_settings(), on_status=statuses.append, source_factory=factory_for([])
        )
        runtime.start()
        runtime.select_camera(CameraDevice(1))
        wait_for_pixel(runtime, 1)
        assert runtime.stop()
        tail = [s.state for s in statuses[-2:]]
        assert tail == [CaptureState.STOPPING, CaptureState.STOPPED], [s.state for s in statuses]
        assert CaptureState.RUNNING not in [s.state for s in statuses[statuses.index(statuses[-2]):]]
