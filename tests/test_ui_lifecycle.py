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
