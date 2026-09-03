"""Configurable fake camera sources shared by the lifecycle tests."""

from __future__ import annotations

from threading import Event
import time

import numpy as np

from gazefix.camera.models import CameraBackend, CameraDevice, CameraOpenResult
from gazefix.config import AppSettings


FAKE_BACKEND = CameraBackend(0, "FAKE")


def fake_open_result() -> CameraOpenResult:
    return CameraOpenResult(FAKE_BACKEND, "FAKE", width=2, height=2, fps=30.0)


class FakeCameraSource:
    """A scriptable CameraSource whose frames carry the camera index as pixel value."""

    def __init__(
        self,
        registry: list["FakeCameraSource"] | None = None,
        *,
        openable: set[int] | None = None,
        block_open: bool = False,
        read_delay: float = 0.002,
        read_exception: Exception | None = None,
        close_exception: Exception | None = None,
        fail_reads: bool = False,
    ) -> None:
        if registry is not None:
            registry.append(self)
        self.openable = openable
        self.block_open = block_open
        self.read_delay = read_delay
        self.read_exception = read_exception
        self.close_exception = close_exception
        self.fail_reads = fail_reads
        self.index: int | None = None
        self.open_calls = 0
        self.reads = 0
        self.closed = False
        self.close_calls = 0
        self.interrupt_calls = 0
        self.interrupted = Event()
        self.open_started = Event()
        self.read_started = Event()
        self.read_gate: Event | None = None

    def open(self, device: CameraDevice) -> CameraOpenResult:
        self.open_calls += 1
        self.open_started.set()
        if self.block_open:
            self.interrupted.wait(5.0)
            raise RuntimeError("open interrupted")
        if self.openable is not None and device.index not in self.openable:
            raise RuntimeError(f"no camera at index {device.index}")
        self.index = device.index
        self.closed = False
        return fake_open_result()

    def read(self):  # type: ignore[no-untyped-def]
        self.read_started.set()
        if self.read_gate is not None:
            self.read_gate.wait(5.0)
        else:
            time.sleep(self.read_delay)
        if self.read_exception is not None:
            raise self.read_exception
        if self.closed or self.index is None or self.fail_reads:
            return False, None
        self.reads += 1
        frame = np.full((2, 2, 3), self.index, dtype=np.uint8)
        frame.setflags(write=False)
        return True, frame

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        if self.close_exception is not None:
            raise self.close_exception

    def interrupt(self) -> None:
        self.interrupt_calls += 1
        self.interrupted.set()


def factory_for(
    registry: list[FakeCameraSource], **kwargs: object
):  # type: ignore[no-untyped-def]
    def create(_settings: AppSettings) -> FakeCameraSource:
        return FakeCameraSource(registry, **kwargs)  # type: ignore[arg-type]

    return create


def wait_until(predicate, timeout: float = 2.0, interval: float = 0.005) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())
