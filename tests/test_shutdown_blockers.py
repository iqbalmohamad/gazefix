"""Regression coverage for the three shutdown-lifecycle blockers from the PR #3 review.

1. Partial startup: a worker launched before a later launch failed used to be
   leaked while the runtime still read ``NEW`` and ``stop()`` returned ``True``.
2. Unbounded prepared cleanup: ``stop()`` used to release unadopted prepared
   cameras on the calling (Qt) thread with no bound.
3. Stale liveness snapshot: ``stop()`` used to return the join results even
   when the worker exited between the join and the return.

Every test drives the race with events; none relies on a sleep to line up.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from threading import Event
import time

import pytest

from camera_fakes import FakeCameraSource, factory_for, fake_open_result, wait_until
from gazefix.camera.discovery import CameraDiscoveryService, DiscoveryResult
from gazefix.camera.models import CameraDevice, CameraOpenResult
from gazefix.camera.source import PreparedCamera, PreparedCameraCloser
from gazefix.config import AppSettings
from gazefix.pipeline.runtime import PipelineRuntime, RuntimeState


DEADLINE_S = 0.05
SLACK_S = 0.3  # scheduling headroom on top of the configured deadline


def settings(**overrides: object) -> AppSettings:
    base = dict(
        reconnect_delay_s=0.01,
        read_retry_delay_s=0.001,
        worker_join_timeout_s=DEADLINE_S,
    )
    base.update(overrides)
    return replace(AppSettings(), **base)  # type: ignore[arg-type]


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == name]


def settle(runtime: PipelineRuntime, timeout: float = 3.0) -> None:
    """Wait, bounded, until nothing the runtime owns is alive or outstanding."""

    assert wait_until(lambda: not runtime.workers_alive, timeout=timeout)
    assert runtime.prepared_closer.join(timeout)


def gated_prepared(index: int, close_gate: Event) -> tuple[FakeCameraSource, PreparedCamera]:
    """A validated prepared camera whose release blocks until ``close_gate`` opens."""

    warm = FakeCameraSource(close_gate=close_gate)
    device = CameraDevice(index)
    return warm, PreparedCamera(device, warm, warm.open(device))


class GatedOpenSource(FakeCameraSource):
    """A driver open that ignores interrupts and returns only when the test lets it."""

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
        self.interrupt_calls += 1  # flag only, like OpenCVCameraSource


def raise_on_start() -> None:
    raise RuntimeError("can't start new thread")


# --- Blocker 1: partial startup -------------------------------------------------


def test_partial_start_winds_down_the_started_worker_and_raises(caplog: pytest.LogCaptureFixture, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.INFO, logger="gazefix.pipeline.runtime")
    runtime = PipelineRuntime(settings(worker_join_timeout_s=2.0), source_factory=factory_for([]))
    seen: dict[str, bool] = {}

    def capture_start_fails() -> None:
        seen["processor_alive_at_failure"] = runtime._processor.is_alive
        raise_on_start()

    monkeypatch.setattr(runtime._capture, "start", capture_start_fails)
    with pytest.raises(RuntimeError, match="can't start new thread"):
        runtime.start()

    assert seen["processor_alive_at_failure"] is True  # the leak the fix must prevent
    assert not runtime.workers_alive  # ...and it was signalled and joined before start() returned
    assert runtime._processor.started and not runtime._capture.started
    assert runtime.state is RuntimeState.STOPPED
    failed = events(caplog, "pipeline_start_failed")
    assert len(failed) == 1 and failed[0].stopped is True  # type: ignore[attr-defined]
    assert failed[0].processor_started is True and failed[0].capture_started is False  # type: ignore[attr-defined]

    assert runtime.stop() is True  # nothing owned is alive; consistent with state
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        runtime.start()  # spent: single-use semantics preserved
    assert runtime.state is RuntimeState.STOPPED and not runtime.workers_alive


def test_first_launch_failure_starts_nothing_and_leaves_the_runtime_spent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    monkeypatch.setattr(runtime._processor, "start", raise_on_start)
    with pytest.raises(RuntimeError, match="can't start new thread"):
        runtime.start()
    assert not runtime._processor.started and not runtime._capture.started
    assert runtime.state is RuntimeState.STOPPED and not runtime.workers_alive
    assert runtime.stop() is True
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        runtime.start()


def test_partial_start_never_reports_new_or_success_while_the_started_worker_lives(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """If the started worker cannot be stopped in time, the runtime must say so."""

    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    monkeypatch.setattr(runtime._capture, "start", raise_on_start)
    real_processor_stop = runtime._processor.stop
    monkeypatch.setattr(runtime._processor, "stop", lambda: None)  # the stop signal is lost
    started = time.perf_counter()
    with pytest.raises(RuntimeError):
        runtime.start()
    assert time.perf_counter() - started < DEADLINE_S + SLACK_S  # wind-down stayed bounded
    try:
        assert runtime._processor.is_alive  # the leak, now visible instead of hidden
        assert runtime.state is RuntimeState.STOPPING  # never NEW with a live worker
        assert runtime.stop() is False  # never success while it lives
    finally:
        monkeypatch.setattr(runtime._processor, "stop", real_processor_stop)
    runtime.stop()  # now the signal reaches the worker
    settle(runtime)
    assert runtime.stop() is True
    assert runtime.state is RuntimeState.STOPPED and not runtime.workers_alive


def test_partial_start_hands_a_pending_prepared_camera_to_cleanup(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    gate = Event()
    warm, prepared = gated_prepared(0, gate)
    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    runtime.select_camera(CameraDevice(0), prepared)  # queued before start
    monkeypatch.setattr(runtime._capture, "start", raise_on_start)
    started = time.perf_counter()
    with pytest.raises(RuntimeError):
        runtime.start()
    assert time.perf_counter() - started < DEADLINE_S + SLACK_S
    assert runtime.state is RuntimeState.STOPPING  # release still outstanding
    assert runtime.prepared_closer.outstanding == 1
    gate.set()
    assert wait_until(lambda: warm.closed)
    settle(runtime)
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED
    assert warm.close_calls == 1


# --- Blocker 2: bounded prepared-camera cleanup ----------------------------------


def test_stop_with_a_blocked_prepared_release_stays_bounded_and_tracks_the_cleanup(caplog: pytest.LogCaptureFixture) -> None:  # type: ignore[no-untyped-def]
    """The review's reproduction: a 0.05 s deadline and a release that takes longer."""

    caplog.set_level(logging.INFO, logger="gazefix.pipeline.runtime")
    gate = Event()
    warm, prepared = gated_prepared(0, gate)
    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    runtime.select_camera(CameraDevice(0), prepared)  # never started: stays unadopted

    for _ in range(2):  # a first stop and a repeated one, both bounded
        started = time.perf_counter()
        assert runtime.stop() is False
        assert time.perf_counter() - started < DEADLINE_S + SLACK_S
        assert runtime.state is RuntimeState.STOPPING
        assert runtime.prepared_closer.outstanding == 1
        assert wait_until(lambda: warm.close_calls == 1) and not warm.closed  # in flight, off this thread
    record = events(caplog, "pipeline_shutdown_timeout")[-1]
    assert record.cleanup_outstanding == 1 and record.deadline_exhausted is True  # type: ignore[attr-defined]
    assert record.capture_alive is False and record.processor_alive is False  # type: ignore[attr-defined]

    gate.set()
    assert runtime.prepared_closer.join(2.0)
    assert warm.closed and warm.close_calls == 1 and not prepared.is_pending
    assert runtime.state is RuntimeState.STOPPED
    assert runtime.stop() is True
    assert len(events(caplog, "pipeline_stopped")) == 1


def test_stop_takes_pending_tokens_from_an_abandoned_worker_without_blocking() -> None:
    open_gate, close_gate = Event(), Event()
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(settings(), source_factory=lambda _s: GatedOpenSource(sources, open_gate))
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: bool(sources) and sources[0].open_started.is_set())
    warm, prepared = gated_prepared(5, close_gate)
    runtime.select_camera(CameraDevice(5), prepared)  # lands while the worker is inside the driver open
    try:
        started = time.perf_counter()
        assert runtime.stop() is False
        assert time.perf_counter() - started < DEADLINE_S + SLACK_S
        assert runtime._capture.take_pending_prepared() == []  # taken by stop()
        assert runtime.prepared_closer.outstanding == 1
        assert wait_until(lambda: warm.close_calls == 1) and not warm.closed
    finally:
        open_gate.set()
    assert wait_until(lambda: not runtime.workers_alive, timeout=3.0)
    assert sources[0].closed  # the worker released its own camera on its own thread
    assert runtime.state is RuntimeState.STOPPING  # the token's release is still outstanding
    assert runtime.stop() is False
    close_gate.set()
    assert wait_until(lambda: warm.closed)
    settle(runtime)
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED
    assert warm.close_calls == 1 and not prepared.is_pending


def test_a_token_refused_after_stop_is_released_off_the_caller_thread() -> None:
    runtime = PipelineRuntime(settings(worker_join_timeout_s=2.0), source_factory=factory_for([]))
    runtime.start()
    assert runtime.stop() is True
    gate = Event()
    warm, prepared = gated_prepared(3, gate)
    started = time.perf_counter()
    runtime.select_camera(CameraDevice(3), prepared)
    assert time.perf_counter() - started < SLACK_S  # returned while the release still blocks
    assert runtime.state is RuntimeState.STOPPING and runtime.prepared_closer.outstanding == 1
    assert wait_until(lambda: warm.close_calls == 1) and not warm.closed
    started = time.perf_counter()
    assert runtime.stop() is False  # truthful: owned cleanup outstanding
    assert time.perf_counter() - started < 2.0 + SLACK_S
    gate.set()
    assert runtime.prepared_closer.join(2.0) and warm.closed
    assert runtime.state is RuntimeState.STOPPED and runtime.stop() is True
    assert warm.close_calls == 1


def test_discovery_join_hands_an_unadopted_token_to_cleanup_instead_of_blocking() -> None:
    gate = Event()
    closer = PreparedCameraCloser()
    results: list[DiscoveryResult] = []
    service = CameraDiscoveryService(
        AppSettings(camera_probe_limit=1),
        on_finished=results.append,
        on_error=lambda _message: None,
        source_factory=factory_for([], close_gate=gate),
        prepared_closer=closer,
    )
    assert service.start()
    assert wait_until(lambda: bool(results) and not service.is_running)
    prepared = results[0].prepared
    assert prepared is not None and prepared.is_pending
    service.request_stop()
    started = time.perf_counter()
    assert service.join(1.0)  # the thread is gone; the release is not performed here
    assert time.perf_counter() - started < SLACK_S
    assert closer.outstanding == 1
    assert wait_until(lambda: not prepared.is_pending)  # claimed by the closer, on its thread
    gate.set()
    assert closer.join(2.0)
    source = prepared.claim()
    assert source is None  # claimed exactly once, by the closer


def test_closer_never_double_closes_and_survives_a_bad_token(caplog: pytest.LogCaptureFixture) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.INFO, logger="gazefix.camera.source")
    closer = PreparedCameraCloser()
    adopted = FakeCameraSource()
    device = CameraDevice(1)
    token = PreparedCamera(device, adopted, adopted.open(device))
    assert token.claim() is not None  # a worker adopted it first
    closer.submit(token)
    assert closer.join(2.0)
    assert adopted.close_calls == 0  # nothing to do: the claimant owns the source

    broken = FakeCameraSource(close_exception=RuntimeError("release exploded"))
    fine = FakeCameraSource()
    closer.submit(PreparedCamera(CameraDevice(2), broken, broken.open(CameraDevice(2))))
    closer.submit(PreparedCamera(CameraDevice(3), fine, fine.open(CameraDevice(3))))
    assert closer.join(2.0)
    assert broken.close_calls == 1 and fine.closed  # the bad token did not strand the next one
    assert closer.outstanding == 0


def test_closer_restarts_its_thread_after_going_idle_and_join_is_bounded() -> None:
    closer = PreparedCameraCloser()
    first = FakeCameraSource()
    closer.submit(PreparedCamera(CameraDevice(0), first, first.open(CameraDevice(0))))
    assert closer.join(2.0) and first.closed
    assert wait_until(lambda: closer._thread is None)  # idle: the thread exited

    gate = Event()
    second, token = gated_prepared(1, gate)
    closer.submit(token)  # a fresh thread picks it up
    started = time.perf_counter()
    assert closer.join(DEADLINE_S) is False
    assert DEADLINE_S * 0.5 < time.perf_counter() - started < DEADLINE_S + SLACK_S  # waited, bounded
    assert closer.outstanding == 1
    gate.set()
    assert closer.join(2.0) and second.closed and closer.outstanding == 0


# --- Blocker 3: final liveness reconciliation ------------------------------------


def test_stop_returns_true_when_the_worker_exits_after_its_join_timed_out(caplog: pytest.LogCaptureFixture, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The join deadline runs out, the worker exits before stop() returns: True, STOPPED."""

    caplog.set_level(logging.INFO, logger="gazefix.pipeline.runtime")
    gate = Event()
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(settings(), source_factory=lambda _s: GatedOpenSource(sources, gate))
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: bool(sources) and sources[0].open_started.is_set())

    closer = runtime.prepared_closer
    original_join = closer.join
    observed: dict[str, bool] = {}

    def join_then_let_the_worker_exit(timeout: float) -> bool:
        # The last bounded wait inside stop(), after the worker joins have
        # already timed out. Let the driver return here, so the worker exits
        # between the join snapshots and the final reconciliation.
        observed["capture_alive_at_join"] = runtime._capture.is_alive
        gate.set()
        assert wait_until(lambda: not runtime.workers_alive, timeout=3.0)
        return original_join(timeout)

    monkeypatch.setattr(closer, "join", join_then_let_the_worker_exit)
    result = runtime.stop()

    assert observed["capture_alive_at_join"] is True  # the join really had timed out
    assert result is True
    assert runtime.state is RuntimeState.STOPPED and not runtime.workers_alive
    assert sources[0].closed
    assert events(caplog, "pipeline_shutdown_timeout") == []
    assert runtime.prepared_closer.outstanding == 0
    stopped = events(caplog, "pipeline_stopped")
    assert len(stopped) == 1 and stopped[0].deadline_exhausted is True  # type: ignore[attr-defined]
    assert runtime.stop() is True  # and it stays consistent


def test_stop_returns_false_only_when_owned_work_is_alive_at_the_final_check(caplog: pytest.LogCaptureFixture) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.INFO, logger="gazefix.pipeline.runtime")
    gate = Event()
    sources: list[FakeCameraSource] = []
    runtime = PipelineRuntime(settings(), source_factory=lambda _s: GatedOpenSource(sources, gate))
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: bool(sources) and sources[0].open_started.is_set())
    try:
        assert runtime.stop() is False
        assert runtime.state is RuntimeState.STOPPING  # consistent with the False
        record = events(caplog, "pipeline_shutdown_timeout")[-1]
        assert record.capture_alive is True and record.deadline_exhausted is True  # type: ignore[attr-defined]
    finally:
        gate.set()
    settle(runtime)
    assert runtime.state is RuntimeState.STOPPED
    assert runtime.stop() is True
