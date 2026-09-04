"""Configurable fake camera sources shared by the lifecycle tests."""

from __future__ import annotations

from threading import Event
import time

import cv2
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
        close_gate: Event | None = None,
    ) -> None:
        if registry is not None:
            registry.append(self)
        self.openable = openable
        self.block_open = block_open
        self.read_delay = read_delay
        self.read_exception = read_exception
        self.close_exception = close_exception
        self.fail_reads = fail_reads
        # When set, ``close`` blocks until the gate opens (bounded), modelling
        # a driver release that does not return promptly.
        self.close_gate = close_gate
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
        if self.close_gate is not None:
            self.close_gate.wait(10.0)
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


class FakeClock:
    """Deterministic stand-in for the ``time`` module's ``perf_counter``/``sleep``.

    Monkeypatch it over ``module.time`` so measured durations are exact instead
    of wall-clock dependent; fakes advance it by their scripted costs.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def perf_counter(self) -> float:
        return self.now

    def perf_counter_ns(self) -> int:
        return int(self.now * 1_000_000_000)

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeVideoCapture:
    """Mimics the subset of ``cv2.VideoCapture`` the source and diagnostic use.

    Scripted through class attributes so both production and diagnostic code
    see the same device: ``behaviours`` maps an api id to ``"fails"``,
    ``"opens"``, or ``"no_frames"``; ``open_gate`` holds ``open`` until set;
    ``reported`` overrides the property values ``get`` returns; ``clock`` plus
    the ``*_cost_s`` attributes advance a ``FakeClock`` so timings are exact;
    ``read_exception`` makes ``read`` raise. Call ``reset`` between tests.
    Every instance records ``calls`` in order, which lets a test prove that two
    code paths drove the device identically.
    """

    behaviours: dict[int, str] = {}
    instances: list["FakeVideoCapture"] = []
    open_gate: Event | None = None
    reported: dict[int, float] = {}
    clock: FakeClock | None = None
    open_cost_s: float = 0.0
    set_cost_s: float = 0.0
    read_cost_s: float = 0.0
    release_cost_s: float = 0.0
    read_exception: BaseException | None = None

    @classmethod
    def reset(cls) -> None:
        cls.behaviours = {}
        cls.instances = []
        cls.open_gate = None
        cls.reported = {}
        cls.clock = None
        cls.open_cost_s = cls.set_cost_s = cls.read_cost_s = cls.release_cost_s = 0.0
        cls.read_exception = None

    def __init__(self) -> None:
        FakeVideoCapture.instances.append(self)
        self.opened = False
        self.released = 0
        self.api: int | None = None
        self.open_params: list[int] | None = None
        self.reads = 0
        self.props: dict[int, float] = {}
        self.calls: list[tuple[object, ...]] = []

    def open(self, index: int, api: int, params: list[int] | None = None) -> bool:
        self.api = api
        self.open_params = params
        self.calls.append(("open", index, api, params))
        if FakeVideoCapture.open_gate is not None:
            FakeVideoCapture.open_gate.wait(5.0)
        self._tick(FakeVideoCapture.open_cost_s)
        behaviour = FakeVideoCapture.behaviours.get(api, "fails")
        self.opened = behaviour != "fails"
        return self.opened

    def isOpened(self) -> bool:
        return self.opened

    def set(self, prop: int, value: float) -> bool:
        self.props[prop] = value
        self.calls.append(("set", prop, value))
        self._tick(FakeVideoCapture.set_cost_s)
        return True

    def get(self, prop: int) -> float:
        values = {
            cv2.CAP_PROP_FRAME_WIDTH: 640.0,
            cv2.CAP_PROP_FRAME_HEIGHT: 480.0,
            cv2.CAP_PROP_FPS: 30.0,
        }
        values.update(FakeVideoCapture.reported)
        return values.get(prop, 0.0)

    def getBackendName(self) -> str:
        return f"FAKE{self.api}"

    def read(self):  # type: ignore[no-untyped-def]
        self.reads += 1
        self.calls.append(("read",))
        self._tick(FakeVideoCapture.read_cost_s)
        if FakeVideoCapture.read_exception is not None:
            raise FakeVideoCapture.read_exception
        if not self.opened or FakeVideoCapture.behaviours.get(self.api) == "no_frames":
            return False, None
        return True, np.zeros((2, 2, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released += 1
        self.opened = False
        self.calls.append(("release",))
        self._tick(FakeVideoCapture.release_cost_s)

    @staticmethod
    def _tick(seconds: float) -> None:
        if FakeVideoCapture.clock is not None and seconds:
            FakeVideoCapture.clock.advance(seconds)
