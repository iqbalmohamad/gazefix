"""Headless Qt regression tests for the main window's camera lifecycle."""

from __future__ import annotations

from dataclasses import replace
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtTest import QTest  # noqa: E402

from camera_fakes import FakeCameraSource, factory_for  # noqa: E402
from gazefix.config import AppSettings  # noqa: E402
from gazefix.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # type: ignore[no-untyped-def]
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def pump_until(predicate, timeout: float = 3.0) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        QTest.qWait(10)
        if predicate():
            return True
    return bool(predicate())


def settings(probe_limit: int) -> AppSettings:
    return replace(
        AppSettings(),
        camera_probe_limit=probe_limit,
        reconnect_delay_s=0.01,
        read_retry_delay_s=0.001,
        worker_join_timeout_s=1.0,
        preview_poll_ms=5,
    )


def test_refresh_while_idle_runs_discovery_again(qapp) -> None:  # type: ignore[no-untyped-def]
    """Regression: a second Refresh with no camera used to disable the button forever."""

    sources: list[FakeCameraSource] = []
    window = MainWindow(settings(2), "log", source_factory=factory_for(sources, openable=set()))
    try:
        assert pump_until(lambda: window._refresh_button.isEnabled())
        assert len(sources) == 2
        assert "no camera" in window._status.text()

        window.refresh_cameras()
        assert not window._refresh_button.isEnabled()
        assert pump_until(lambda: window._refresh_button.isEnabled()), window._status.text()
        assert len(sources) == 4  # discovery really ran a second time
        assert "no camera" in window._status.text()
    finally:
        window.close()
        assert not window._runtime.workers_alive


def test_discovery_handoff_presents_frames_without_second_open(qapp) -> None:  # type: ignore[no-untyped-def]
    sources: list[FakeCameraSource] = []
    window = MainWindow(settings(3), "log", source_factory=factory_for(sources, openable={0}))
    try:
        assert pump_until(lambda: window._first_frame_presented)
        opened = [s for s in sources if s.index == 0]
        assert len(opened) == 1 and opened[0].open_calls == 1
        assert not opened[0].closed
        assert all(s.closed for s in sources if s is not opened[0])
        assert window._status.text().startswith("Status: Running on FAKE")
        assert window._camera_selector.isEnabled()
    finally:
        window.close()
        assert not window._runtime.workers_alive
        assert not window._discovery.is_running
        assert all(s.closed for s in sources)


def test_refresh_while_running_releases_then_reuses_the_new_probe(qapp) -> None:  # type: ignore[no-untyped-def]
    sources: list[FakeCameraSource] = []
    window = MainWindow(settings(1), "log", source_factory=factory_for(sources))
    try:
        assert pump_until(lambda: window._first_frame_presented)
        first = sources[0]
        window._first_frame_presented = False
        window.refresh_cameras()
        assert pump_until(lambda: window._first_frame_presented)
        assert first.closed
        assert len(sources) == 2 and not sources[1].closed
        assert sources[1].open_calls == 1
    finally:
        window.close()
        assert all(s.closed for s in sources)


def test_refresh_keeps_the_selected_camera_and_reuses_its_probe(qapp) -> None:  # type: ignore[no-untyped-def]
    sources: list[FakeCameraSource] = []
    window = MainWindow(settings(2), "log", source_factory=factory_for(sources))
    try:
        assert pump_until(lambda: window._first_frame_presented)
        assert window._camera_selector.currentIndex() == 0
        window._camera_selector.setCurrentIndex(1)  # user picks the second camera
        assert pump_until(lambda: any(s.index == 1 and not s.closed and s.reads > 0 for s in sources))
        assert pump_until(lambda: window._status.text().startswith("Status: Running on FAKE"))

        window.refresh_cameras()
        assert pump_until(lambda: window._refresh_button.isEnabled())
        assert window._camera_selector.currentIndex() == 1
        live = [s for s in sources if not s.closed]
        assert len(live) == 1 and live[0].index == 1
        assert live[0].open_calls == 1  # the refresh probe was handed over, not reopened
    finally:
        window.close()
        assert all(s.closed for s in sources)


def test_close_with_a_blocked_camera_read_is_bounded_and_reports_the_live_worker(qapp, caplog) -> None:  # type: ignore[no-untyped-def]
    """The window must never wait on a stuck driver beyond one join deadline,
    and must not claim the pipeline stopped while its worker is still alive."""

    import logging
    from threading import Event

    from camera_fakes import wait_until
    from gazefix.pipeline.runtime import RuntimeState

    caplog.set_level(logging.ERROR, logger="gazefix.ui.main_window")
    sources: list[FakeCameraSource] = []
    cfg = settings(1)
    window = MainWindow(cfg, "log", source_factory=factory_for(sources))
    gate = Event()
    try:
        assert pump_until(lambda: window._first_frame_presented)
        live = sources[0]
        live.read_started.clear()
        live.read_gate = gate
        assert live.read_started.wait(1.0)  # the worker is now inside a "driver" read

        started = time.perf_counter()
        window.close()
        elapsed = time.perf_counter() - started
        assert elapsed < cfg.worker_join_timeout_s + 0.5, elapsed
        assert window._runtime.state is RuntimeState.STOPPING
        assert window._runtime.workers_alive
        assert not live.closed  # never released from the UI thread
        records = [r for r in caplog.records if getattr(r, "event", None) == "pipeline_shutdown_timeout"]
        assert records and records[-1].runtime_state == "stopping"  # type: ignore[attr-defined]
    finally:
        gate.set()
        assert wait_until(lambda: not window._runtime.workers_alive, timeout=3.0)
        assert all(s.closed for s in sources)
        assert window._runtime.state is RuntimeState.STOPPED


def test_close_never_releases_a_pending_prepared_camera_on_the_ui_thread(qapp, caplog) -> None:  # type: ignore[no-untyped-def]
    """A request whose prepared camera the worker never got to adopt, plus a
    release that blocks: the window must still close within one deadline."""

    import logging
    from threading import Event

    from camera_fakes import wait_until
    from gazefix.camera.models import CameraDevice
    from gazefix.camera.source import PreparedCamera
    from gazefix.pipeline.runtime import RuntimeState

    caplog.set_level(logging.ERROR, logger="gazefix.ui.main_window")
    sources: list[FakeCameraSource] = []
    cfg = replace(settings(1), worker_join_timeout_s=0.3)
    window = MainWindow(cfg, "log", source_factory=factory_for(sources))
    read_gate, close_gate = Event(), Event()
    warm = FakeCameraSource(close_gate=close_gate)
    device = CameraDevice(7)
    prepared = PreparedCamera(device, warm, warm.open(device))
    try:
        assert pump_until(lambda: window._first_frame_presented)
        live = sources[0]
        live.read_started.clear()
        live.read_gate = read_gate
        assert live.read_started.wait(1.0)  # the worker is now inside a "driver" read
        window._runtime.select_camera(device, prepared)  # cannot be applied while it is

        started = time.perf_counter()
        window.close()
        elapsed = time.perf_counter() - started
        assert elapsed < cfg.worker_join_timeout_s + 0.5, elapsed
        assert window._closer.outstanding == 1  # handed off; the closer owns it now
        assert wait_until(lambda: warm.close_calls == 1) and not warm.closed  # in flight, off the UI thread
        assert window._runtime.state is RuntimeState.STOPPING
        assert {r.event for r in caplog.records} >= {"pipeline_shutdown_timeout", "prepared_cleanup_timeout"}  # type: ignore[attr-defined]
    finally:
        read_gate.set()
        close_gate.set()
        assert wait_until(lambda: not window._runtime.workers_alive, timeout=3.0)
        assert wait_until(lambda: warm.closed)
        assert all(s.closed for s in sources)
        assert warm.close_calls == 1  # exactly one release, by exactly one owner
        assert window._runtime.state is RuntimeState.STOPPED
