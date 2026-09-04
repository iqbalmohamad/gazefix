"""Headless Qt tests: developer panel, overlay toggle, tracking status, bounded close."""

from __future__ import annotations

from dataclasses import replace
import logging
import os
from threading import Event
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtTest import QTest  # noqa: E402

from camera_fakes import FakeCameraSource, factory_for  # noqa: E402
from gazefix.pipeline.runtime import RuntimeState  # noqa: E402
from gazefix.tracking.models import TrackingStatus  # noqa: E402
from gazefix.ui.main_window import MainWindow  # noqa: E402
from tracker_fakes import ScriptedFactory, tracking_settings, wait_until  # noqa: E402


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


def settings(**overrides):  # type: ignore[no-untyped-def]
    return tracking_settings(
        camera_probe_limit=1,
        preview_poll_ms=5,
        metrics_refresh_ms=20,
        tracking_min_eye_width_px=0.0,
        **overrides,
    )


def test_consumer_mode_has_no_debug_controls_but_shows_tracking_latency(qapp) -> None:  # type: ignore[no-untyped-def]
    sources: list[FakeCameraSource] = []
    factory = ScriptedFactory()
    window = MainWindow(settings(), "log", source_factory=factory_for(sources), tracker_factory=factory)
    try:
        assert window._overlay_checkbox is None and window._tracking_detail is None
        assert not window.overlay_enabled
        assert pump_until(lambda: window._last_tracking is not None and window._last_tracking.status is TrackingStatus.TRACKED)
        assert pump_until(lambda: "tracked" in window._tracking_ms.text())
        assert window._last_tracking.belongs_to(window._last_tracking.capture_sequence, window._runtime.current_request_id)
    finally:
        window.close()
        assert window._runtime.state is RuntimeState.STOPPED
        assert not window._tracking.worker_alive
        assert factory.trackers[0].close_calls == 1


def test_developer_mode_toggles_overlay_through_the_processor_only(qapp) -> None:  # type: ignore[no-untyped-def]
    sources: list[FakeCameraSource] = []
    factory = ScriptedFactory()
    window = MainWindow(
        settings(developer_mode=True), "log", source_factory=factory_for(sources), tracker_factory=factory
    )
    try:
        assert window._overlay_checkbox is not None and window._tracking_detail is not None
        assert not window._overlay_checkbox.isChecked() and not window.overlay_enabled
        assert pump_until(lambda: window._last_tracking is not None and window._last_tracking.status is TrackingStatus.TRACKED)
        assert pump_until(lambda: "head pose (not gaze)" in window._tracking_detail.text())
        window._overlay_checkbox.setChecked(True)
        assert window.overlay_enabled  # the flag lives on the processor
        window._first_frame_presented = False
        assert pump_until(lambda: window._first_frame_presented)
        # The overlay is rendered on the processor thread onto a copy: the fake
        # camera's frames are read-only 2x2 arrays and remain untouched.
        assert all(not s.closed for s in sources[:1])
        window._overlay_checkbox.setChecked(False)
        assert not window.overlay_enabled
    finally:
        window.close()
        assert window._runtime.state is RuntimeState.STOPPED


def test_tracking_disabled_uses_the_passthrough_processor(qapp) -> None:  # type: ignore[no-untyped-def]
    sources: list[FakeCameraSource] = []
    window = MainWindow(settings(tracking_enabled=False, developer_mode=True), "log", source_factory=factory_for(sources))
    try:
        assert window._tracking is None and window._overlay_checkbox is None
        assert window._tracking_ms.text() == "off"
        assert pump_until(lambda: window._first_frame_presented)
        assert window._last_tracking is None
    finally:
        window.close()
        assert window._runtime.state is RuntimeState.STOPPED


def test_unavailable_tracker_keeps_preview_and_reports_status(qapp) -> None:  # type: ignore[no-untyped-def]
    from tracker_fakes import init_error

    sources: list[FakeCameraSource] = []
    factory = ScriptedFactory(failures=[init_error("face_landmarker.task not found; run scripts/fetch_model.py")])
    window = MainWindow(settings(developer_mode=True), "log", source_factory=factory_for(sources), tracker_factory=factory)
    try:
        assert pump_until(lambda: window._first_frame_presented)
        assert pump_until(lambda: window._last_tracking is not None and window._last_tracking.status is TrackingStatus.UNAVAILABLE)
        assert pump_until(lambda: "fetch_model" in window._tracking_detail.text())
        assert window._tracking_ms.text().startswith("unavailable: ") and "fetch_model" in window._tracking_ms.text()
        assert window._status.text().startswith("Status: Running on FAKE")  # camera status untouched
    finally:
        window.close()
        assert window._runtime.state is RuntimeState.STOPPED


def test_close_with_a_blocked_tracker_is_bounded_and_truthful(qapp, caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.ERROR, logger="gazefix.ui.main_window")
    sources: list[FakeCameraSource] = []
    factory = ScriptedFactory()
    cfg = settings(tracking_join_timeout_s=0.2, worker_join_timeout_s=1.0)
    window = MainWindow(cfg, "log", source_factory=factory_for(sources), tracker_factory=factory)
    gate = Event()
    try:
        assert pump_until(lambda: window._last_tracking is not None and window._last_tracking.status is TrackingStatus.TRACKED)
        tracker = factory.trackers[0]
        tracker.gate = gate
        tracker.detect_started.clear()
        assert tracker.detect_started.wait(1.0)  # the tracker thread is inside a "native" call
        started = time.perf_counter()
        window.close()
        elapsed = time.perf_counter() - started
        assert elapsed < cfg.worker_join_timeout_s + 0.5, elapsed
        # The processor thread exited after its bounded join; the runtime is
        # truthfully STOPPED for what it owns, and the abandoned tracker
        # thread is reported separately.
        assert window._runtime.state is RuntimeState.STOPPED
        assert window._tracking.worker_alive
        assert any(getattr(r, "event", None) == "tracker_thread_alive_at_close" for r in caplog.records)
        assert window.tracker_thread_alive
        assert all(s.closed for s in sources)  # the camera was released normally
    finally:
        gate.set()
        assert wait_until(lambda: not window._tracking.worker_alive, timeout=3.0)
        assert factory.trackers[0].close_calls == 1


def test_camera_switch_clears_stale_tracking_from_the_window(qapp) -> None:  # type: ignore[no-untyped-def]
    sources: list[FakeCameraSource] = []
    factory = ScriptedFactory()
    cfg = replace(settings(), camera_probe_limit=2)
    window = MainWindow(cfg, "log", source_factory=factory_for(sources), tracker_factory=factory)
    try:
        assert pump_until(lambda: window._last_tracking is not None and window._last_tracking.status is TrackingStatus.TRACKED)
        window._camera_selector.setCurrentIndex(1)
        assert window._last_tracking is None  # cleared with the preview at selection time
        assert pump_until(
            lambda: window._last_tracking is not None
            and window._last_tracking.camera_request_id == window._runtime.current_request_id
            and window._last_tracking.status is TrackingStatus.TRACKED
        )
        assert wait_until(lambda: factory.trackers[0].reset_calls == 1)
    finally:
        window.close()
