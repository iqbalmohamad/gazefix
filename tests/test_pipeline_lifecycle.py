from __future__ import annotations

from dataclasses import replace
from threading import Event
import time

import numpy as np

from gazefix.camera.models import (
    CameraBackend,
    CameraDevice,
    CameraOpenResult,
    CaptureState,
)
from gazefix.config import AppSettings
from gazefix.pipeline.runtime import PipelineRuntime


class FakeCameraSource:
    def __init__(self, registry: list["FakeCameraSource"]) -> None:
        self.registry = registry
        self.registry.append(self)
        self.index: int | None = None
        self.closed = False
        self.interrupt_calls = 0

    def open(self, device: CameraDevice) -> CameraOpenResult:
        self.index = device.index
        self.closed = False
        return CameraOpenResult(
            CameraBackend(0, "FAKE"), "FAKE", width=2, height=2, fps=30.0
        )

    def read(self):  # type: ignore[no-untyped-def]
        time.sleep(0.002)
        if self.closed or self.index is None:
            return False, None
        frame = np.full((2, 2, 3), self.index, dtype=np.uint8)
        frame.setflags(write=False)
        return True, frame

    def close(self) -> None:
        self.closed = True

    def interrupt(self) -> None:
        self.interrupt_calls += 1
        self.closed = True


def _wait_for_camera_frame(
    runtime: PipelineRuntime, expected_pixel: int, timeout: float = 1.0
) -> None:
    deadline = time.perf_counter() + timeout
    last_sequence = 0
    while time.perf_counter() < deadline:
        item = runtime.consume_latest_output(last_sequence)
        if item is not None:
            last_sequence = item.sequence
            if int(item.value.frame[0, 0, 0]) == expected_pixel:
                return
        time.sleep(0.005)
    raise AssertionError(f"No frame arrived from fake camera {expected_pixel}")


def test_camera_switch_and_shutdown_are_managed_without_ui_thread_reads() -> None:
    sources: list[FakeCameraSource] = []
    statuses = []
    settings = replace(
        AppSettings(),
        reconnect_delay_s=0.01,
        read_retry_delay_s=0.001,
        worker_join_timeout_s=1.0,
    )
    runtime = PipelineRuntime(
        settings,
        on_status=statuses.append,
        source_factory=lambda _settings: FakeCameraSource(sources),
    )

    runtime.start()
    runtime.select_camera(CameraDevice(1))
    _wait_for_camera_frame(runtime, 1)
    runtime.select_camera(CameraDevice(2))
    _wait_for_camera_frame(runtime, 2)

    assert runtime.stop()
    assert not runtime.workers_alive
    assert all(source.closed for source in sources)
    assert all(source.interrupt_calls == 0 for source in sources)
    assert any(status.state is CaptureState.RUNNING for status in statuses)
    assert statuses[-1].state is CaptureState.STOPPED


class BlockingOpenSource:
    def __init__(self, started: Event) -> None:
        self.started = started
        self.interrupted = Event()

    def open(self, device: CameraDevice) -> CameraOpenResult:
        self.started.set()
        self.interrupted.wait(2.0)
        raise RuntimeError("open interrupted")

    def read(self):  # type: ignore[no-untyped-def]
        return False, None

    def close(self) -> None:
        pass

    def interrupt(self) -> None:
        self.interrupted.set()


def test_shutdown_interrupts_a_blocked_camera_open() -> None:
    started = Event()
    runtime = PipelineRuntime(
        replace(AppSettings(), worker_join_timeout_s=1.0),
        source_factory=lambda _settings: BlockingOpenSource(started),
    )
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert started.wait(0.5)

    assert runtime.stop()
    assert not runtime.workers_alive


class RecoveringCameraSource:
    def __init__(self, attempt: int) -> None:
        self.attempt = attempt
        self.closed = False

    def open(self, device: CameraDevice) -> CameraOpenResult:
        return CameraOpenResult(
            CameraBackend(0, "FAKE"), "FAKE", width=2, height=2, fps=30.0
        )

    def read(self):  # type: ignore[no-untyped-def]
        time.sleep(0.001)
        if self.closed or self.attempt == 0:
            return False, None
        frame = np.full((2, 2, 3), 7, dtype=np.uint8)
        frame.setflags(write=False)
        return True, frame

    def close(self) -> None:
        self.closed = True

    def interrupt(self) -> None:
        self.closed = True


def test_repeated_read_failure_reopens_and_recovers() -> None:
    attempts = 0
    statuses = []

    def create_source(_settings: AppSettings) -> RecoveringCameraSource:
        nonlocal attempts
        source = RecoveringCameraSource(attempts)
        attempts += 1
        return source

    runtime = PipelineRuntime(
        replace(
            AppSettings(),
            transient_read_failures=2,
            read_retry_delay_s=0.001,
            reconnect_delay_s=0.001,
            worker_join_timeout_s=1.0,
        ),
        on_status=statuses.append,
        source_factory=create_source,
    )
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    _wait_for_camera_frame(runtime, 7)

    assert runtime.stop()
    states = [status.state for status in statuses]
    assert CaptureState.DEGRADED in states
    assert CaptureState.RETRYING in states
    assert CaptureState.RUNNING in states
    assert attempts >= 2
