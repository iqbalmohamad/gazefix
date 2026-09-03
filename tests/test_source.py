"""OpenCVCameraSource behaviour against a scripted fake cv2.VideoCapture."""

from __future__ import annotations

import logging
from threading import Event, Thread
import time

import cv2
import numpy as np
import pytest

from gazefix.camera import source as source_module
from gazefix.camera.backends import default_camera_backends, ordered_backends_for_device
from gazefix.camera.environment import MSMF_HW_TRANSFORMS_ENV, apply_capture_environment
from gazefix.camera.models import CameraBackend, CameraDevice
from gazefix.camera.source import (
    CameraOpenInterrupted,
    OpenCVCameraSource,
    PreparedCamera,
)
from gazefix.config import AppSettings


BACKEND_A = CameraBackend(101, "A")
BACKEND_B = CameraBackend(102, "B")


class FakeVideoCapture:
    """Mimics the subset of cv2.VideoCapture the source uses."""

    behaviours: dict[int, str] = {}
    instances: list["FakeVideoCapture"] = []
    open_gate: Event | None = None

    def __init__(self) -> None:
        FakeVideoCapture.instances.append(self)
        self.opened = False
        self.released = 0
        self.api: int | None = None
        self.reads = 0
        self.props: dict[int, float] = {}

    def open(self, index: int, api: int) -> bool:
        self.api = api
        if FakeVideoCapture.open_gate is not None:
            FakeVideoCapture.open_gate.wait(5.0)
        behaviour = FakeVideoCapture.behaviours.get(api, "fails")
        self.opened = behaviour != "fails"
        return self.opened

    def isOpened(self) -> bool:
        return self.opened

    def set(self, prop: int, value: float) -> bool:
        self.props[prop] = value
        return True

    def get(self, prop: int) -> float:
        return {
            cv2.CAP_PROP_FRAME_WIDTH: 640.0,
            cv2.CAP_PROP_FRAME_HEIGHT: 480.0,
            cv2.CAP_PROP_FPS: 30.0,
        }.get(prop, 0.0)

    def getBackendName(self) -> str:
        return f"FAKE{self.api}"

    def read(self):  # type: ignore[no-untyped-def]
        self.reads += 1
        if not self.opened or FakeVideoCapture.behaviours.get(self.api) == "no_frames":
            return False, None
        return True, np.zeros((2, 2, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released += 1
        self.opened = False


@pytest.fixture
def fake_cv(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    FakeVideoCapture.behaviours = {}
    FakeVideoCapture.instances = []
    FakeVideoCapture.open_gate = None
    monkeypatch.setattr(source_module.cv2, "VideoCapture", FakeVideoCapture)
    monkeypatch.setattr(
        source_module,
        "ordered_backends_for_device",
        lambda _backend: (BACKEND_A, BACKEND_B),
    )
    return FakeVideoCapture


def settings() -> AppSettings:
    return AppSettings(discovery_validation_reads=2, read_retry_delay_s=0.0)


def test_open_falls_back_when_first_backend_does_not_open(fake_cv) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {BACKEND_A.api_preference: "fails", BACKEND_B.api_preference: "opens"}
    result = OpenCVCameraSource(settings()).open(CameraDevice(0))
    assert result.backend == BACKEND_B
    assert result.reported_backend == f"FAKE{BACKEND_B.api_preference}"
    assert [c.api for c in fake_cv.instances] == [BACKEND_A.api_preference, BACKEND_B.api_preference]
    assert fake_cv.instances[0].released == 1


def test_open_falls_back_when_first_backend_opens_but_delivers_no_frame(fake_cv) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {BACKEND_A.api_preference: "no_frames", BACKEND_B.api_preference: "opens"}
    source = OpenCVCameraSource(settings())
    result = source.open(CameraDevice(0))
    assert result.backend == BACKEND_B
    first, second = fake_cv.instances
    assert first.reads == 2 and first.released == 1
    assert second.reads == 1  # one validation frame consumed by open
    success, frame = source.read()
    assert success and frame is not None and not frame.flags.writeable


def test_open_reports_every_failed_backend(fake_cv) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {BACKEND_A.api_preference: "fails", BACKEND_B.api_preference: "no_frames"}
    with pytest.raises(RuntimeError) as excinfo:
        OpenCVCameraSource(settings()).open(CameraDevice(3))
    message = str(excinfo.value)
    assert "index 3" in message and "A" in message and "B (opened but produced no frame)" in message
    assert all(c.released == 1 for c in fake_cv.instances if c.api is not None)


def test_interrupt_during_open_is_flag_only_and_stops_backend_iteration(fake_cv) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {BACKEND_A.api_preference: "opens", BACKEND_B.api_preference: "opens"}
    gate = Event()
    fake_cv.open_gate = gate
    source = OpenCVCameraSource(settings())
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            source.open(CameraDevice(0))
            outcome["result"] = "opened"
        except BaseException as exc:  # noqa: BLE001
            outcome["result"] = exc

    thread = Thread(target=run)
    thread.start()
    deadline = time.perf_counter() + 1.0
    while not fake_cv.instances and time.perf_counter() < deadline:
        time.sleep(0.001)
    in_flight = fake_cv.instances[0]

    source.interrupt()  # another thread cannot cancel the driver call...
    assert in_flight.released == 0  # ...and must not touch the in-flight capture
    gate.set()
    thread.join(2.0)

    assert isinstance(outcome["result"], CameraOpenInterrupted)
    assert in_flight.released == 1  # the opening thread discards it on return
    assert len(fake_cv.instances) == 1  # backend B was never attempted


def test_interrupt_that_lands_before_open_starts_still_cancels(fake_cv) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {BACKEND_A.api_preference: "opens"}
    source = OpenCVCameraSource(settings())
    source.interrupt()
    with pytest.raises(CameraOpenInterrupted):
        source.open(CameraDevice(0))
    assert fake_cv.instances == []


def test_interrupt_outside_open_never_releases_from_the_caller(fake_cv) -> None:  # type: ignore[no-untyped-def]
    """Only the owning thread may release; a foreign release under a running
    read destroys the Media Foundation reader beneath it."""

    fake_cv.behaviours = {BACKEND_A.api_preference: "opens"}
    source = OpenCVCameraSource(settings())
    source.open(CameraDevice(0))
    capture = fake_cv.instances[0]
    source.interrupt()
    assert capture.released == 0
    assert source.read() == (False, None)  # the owner sees the flag and stops
    source.close()
    assert capture.released == 1


def test_validation_is_bounded_by_wall_clock_not_only_by_read_count(fake_cv, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """One stalled Media Foundation read already costs 10 s; do not pay it thrice."""

    fake_cv.behaviours = {BACKEND_A.api_preference: "no_frames", BACKEND_B.api_preference: "opens"}
    original_read = fake_cv.read

    def slow_failing_read(self):  # type: ignore[no-untyped-def]
        if self.api == BACKEND_A.api_preference:
            time.sleep(0.12)
        return original_read(self)

    monkeypatch.setattr(fake_cv, "read", slow_failing_read)
    cfg = AppSettings(discovery_validation_reads=5, read_retry_delay_s=0.0, open_validation_timeout_s=0.1)
    result = OpenCVCameraSource(cfg).open(CameraDevice(0))
    assert result.backend == BACKEND_B
    assert fake_cv.instances[0].reads == 1  # stopped after the first slow failure


def test_next_backend_after_rotates_within_platform_order() -> None:
    from gazefix.camera.backends import next_backend_after

    msmf, dshow = default_camera_backends("win32")
    assert next_backend_after(msmf, "win32") == dshow
    assert next_backend_after(dshow, "win32") == msmf
    assert next_backend_after(None, "win32") == msmf
    assert next_backend_after(CameraBackend(999, "OTHER"), "win32") == msmf
    only = default_camera_backends("linux")[0]
    assert next_backend_after(only, "linux") == only
    assert next_backend_after(None, "linux") == only


def test_open_and_release_log_timing_fields(fake_cv, caplog: pytest.LogCaptureFixture) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {BACKEND_A.api_preference: "opens"}
    caplog.set_level(logging.INFO, logger="gazefix.camera.source")
    source = OpenCVCameraSource(settings())
    source.open(CameraDevice(0))
    source.close()
    events = {record.event: record for record in caplog.records if hasattr(record, "event")}  # type: ignore[attr-defined]
    opened = events["camera_opened"]
    for field in ("open_ms", "configure_ms", "first_frame_ms"):
        assert isinstance(getattr(opened, field), float)
    assert isinstance(events["camera_released"].release_ms, float)  # type: ignore[attr-defined]


def test_prepared_camera_hands_over_exactly_once(fake_cv) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {BACKEND_A.api_preference: "opens"}
    source = OpenCVCameraSource(settings())
    result = source.open(CameraDevice(0))
    prepared = PreparedCamera(CameraDevice(0, BACKEND_A), source, result)
    assert prepared.is_pending
    claimed = prepared.claim()
    assert claimed is not None and claimed[0] is source and claimed[1] == result
    assert prepared.claim() is None
    assert prepared.close_if_unclaimed() is False
    assert fake_cv.instances[0].released == 0

    other = PreparedCamera(CameraDevice(0, BACKEND_A), source, result)
    assert other.close_if_unclaimed() is True
    assert fake_cv.instances[0].released == 1
    assert other.close_if_unclaimed() is False


def test_windows_backend_order_prefers_msmf_then_dshow() -> None:
    names = [b.name for b in default_camera_backends("win32")]
    assert names == ["MSMF", "DSHOW"]
    dshow = default_camera_backends("win32")[1]
    assert [b.name for b in ordered_backends_for_device(dshow, "win32")] == ["DSHOW", "MSMF"]
    assert [b.name for b in default_camera_backends("linux")] == ["ANY"]


def test_capture_environment_disables_msmf_hw_transforms_on_windows_only() -> None:
    env: dict[str, str] = {}
    assert apply_capture_environment(AppSettings(), env, platform="linux") == {}
    assert env == {}
    exported = apply_capture_environment(AppSettings(), env, platform="win32")
    assert exported == {MSMF_HW_TRANSFORMS_ENV: "0"} and env[MSMF_HW_TRANSFORMS_ENV] == "0"
    apply_capture_environment(AppSettings(msmf_hw_transforms=True), env, platform="win32")
    assert env[MSMF_HW_TRANSFORMS_ENV] == "1"


def test_format_is_set_only_where_the_camera_differs_from_the_request(fake_cv) -> None:  # type: ignore[no-untyped-def]
    """Every MSMF set() renegotiates the stream, so equal values are skipped."""

    fake_cv.behaviours = {BACKEND_A.api_preference: "opens"}
    cfg = AppSettings(capture_width=640, capture_height=720, target_fps=30.0, discovery_validation_reads=1)
    OpenCVCameraSource(cfg).open(CameraDevice(0))
    props = fake_cv.instances[0].props
    assert cv2.CAP_PROP_FRAME_WIDTH not in props  # camera already reports 640
    assert props[cv2.CAP_PROP_FRAME_HEIGHT] == 720.0  # 480 -> 720 had to be set
    assert cv2.CAP_PROP_FPS not in props  # 30 already


def test_directshow_receives_its_format_as_open_parameters(fake_cv, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dshow = CameraBackend(cv2.CAP_DSHOW, "DSHOW")
    monkeypatch.setattr(source_module, "ordered_backends_for_device", lambda _b: (dshow,))
    fake_cv.behaviours = {cv2.CAP_DSHOW: "opens"}
    seen: list[tuple[int, int, list[int] | None]] = []
    original_open = fake_cv.open

    def open_with_params(self, index, api, params=None):  # type: ignore[no-untyped-def]
        seen.append((index, api, params))
        return original_open(self, index, api)

    monkeypatch.setattr(fake_cv, "open", open_with_params)
    cfg = AppSettings(capture_width=1280, capture_height=720, target_fps=30.0, discovery_validation_reads=1)
    result = OpenCVCameraSource(cfg).open(CameraDevice(3))
    assert result.backend == dshow
    assert seen == [(3, cv2.CAP_DSHOW, [
        cv2.CAP_PROP_FRAME_WIDTH, 1280, cv2.CAP_PROP_FRAME_HEIGHT, 720, cv2.CAP_PROP_FPS, 30,
    ])]


def test_directshow_falls_back_to_plain_open_without_the_params_overload(fake_cv, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dshow = CameraBackend(cv2.CAP_DSHOW, "DSHOW")
    monkeypatch.setattr(source_module, "ordered_backends_for_device", lambda _b: (dshow,))
    fake_cv.behaviours = {cv2.CAP_DSHOW: "opens"}
    calls: list[tuple[int, int]] = []
    original_open = fake_cv.open

    def two_arg_open(self, index, api):  # type: ignore[no-untyped-def]
        calls.append((index, api))
        return original_open(self, index, api)

    monkeypatch.setattr(fake_cv, "open", two_arg_open)
    OpenCVCameraSource(AppSettings(discovery_validation_reads=1)).open(CameraDevice(0))
    assert calls == [(0, cv2.CAP_DSHOW)]


@pytest.mark.parametrize(
    "module", ["gazefix.main", "gazefix.camera.diagnostics", "gazefix.camera.environment"]
)
def test_entry_points_do_not_import_opencv_before_the_environment_is_applied(module: str) -> None:
    """A statically linked OpenCV runtime snapshots the environment at load."""

    import subprocess
    import sys as _sys

    code = f"import sys, {module}; raise SystemExit(0 if 'cv2' not in sys.modules else 1)"
    completed = subprocess.run([_sys.executable, "-c", code], capture_output=True, text=True,
                               env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"})
    assert completed.returncode == 0, completed.stderr
