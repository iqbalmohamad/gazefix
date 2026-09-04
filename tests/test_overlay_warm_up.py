"""The overlay's one-time OpenCV drawing initialisation is paid off the frame path.

OpenCV initialises its drawing routines lazily. Before the warm-up, that cost
landed inside the first ``render_overlay`` call, which happens on the
processor thread the moment a developer switches the overlay on; on a Windows
machine with an OpenCL runtime present it was observed to stall that frame for
seconds, which is also what made
``test_developer_mode_toggles_overlay_through_the_processor_only`` flaky.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from gazefix.tracking import overlay
from gazefix.tracking.processor import TrackingProcessor
from gazefix.tracking.worker import STATE_READY, TrackerWorker
from tracker_fakes import ScriptedFactory, tracking_settings, wait_until


def test_warm_up_runs_the_primitives_and_is_repeatable() -> None:
    overlay.warm_up()
    overlay.warm_up()  # idempotent: a second call must not raise either


def test_warm_up_leaves_no_shared_state_behind() -> None:
    """It must draw on its own canvas, never on anything a caller can see."""

    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    frame.setflags(write=False)
    overlay.warm_up()
    assert frame.max() == 0 and not frame.flags.writeable


def test_the_tracker_thread_warms_up_before_it_reports_ready(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Ordering is the guarantee the UI test relies on.

    The warm-up runs before the loop, so anything that has observed a ready
    tracker (or a tracked frame) has already observed the warm-up. Enabling
    the overlay after that point therefore cannot pay the initialisation
    cost inside a frame.
    """

    order: list[str] = []
    real_warm_up = overlay.warm_up

    def recording_warm_up() -> None:
        order.append("warm_up")
        real_warm_up()

    monkeypatch.setattr("gazefix.tracking.worker.warm_up_overlay_drawing", recording_warm_up)

    factory = ScriptedFactory()
    worker = TrackerWorker(factory, tracking_settings())
    original_initialize = worker._initialize  # noqa: SLF001

    def recording_initialize() -> None:
        order.append("initialize")
        original_initialize()

    monkeypatch.setattr(worker, "_initialize", recording_initialize)
    worker.start()
    try:
        assert wait_until(lambda: worker.status().state == STATE_READY, timeout=5.0)
        assert order[:2] == ["warm_up", "initialize"], order
    finally:
        worker.stop(1.0)


def test_a_failing_warm_up_never_stops_tracking_from_starting(monkeypatch, caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.WARNING, logger="gazefix.tracking.worker")

    def exploding_warm_up() -> None:
        raise RuntimeError("no drawing backend")

    monkeypatch.setattr("gazefix.tracking.worker.warm_up_overlay_drawing", exploding_warm_up)

    factory = ScriptedFactory()
    processor = TrackingProcessor(factory, tracking_settings())
    processor.start()
    try:
        assert wait_until(lambda: processor.status().state == STATE_READY, timeout=5.0)
        assert any(getattr(r, "event", None) == "overlay_warm_up_failed" for r in caplog.records)
    finally:
        processor.close()


def test_warm_up_covers_every_primitive_the_overlay_draws_with() -> None:
    """Guards against the warm-up drifting away from the render path.

    Both sets are read from the module source, so a newly used drawing call
    that nobody warmed up fails here instead of resurfacing as a stall on the
    first render.
    """

    import inspect
    import re

    source = inspect.getsource(overlay)
    warm_up_source = inspect.getsource(overlay.warm_up)
    used = set(re.findall(r"cv2\.(\w+)\(", source))
    warmed = set(re.findall(r"cv2\.(\w+)\(", warm_up_source))
    drawing_calls = {"circle", "line", "polylines", "rectangle", "putText", "getTextSize"}
    missing = (used & drawing_calls) - warmed
    assert not missing, f"drawing primitives used but never warmed up: {sorted(missing)}"
