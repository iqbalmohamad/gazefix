"""Process-level shutdown behaviour with a tracker stuck in a native call.

A clean-exit test proves nothing about this path, so these tests start a real
child process, wedge the tracker thread inside a call that never returns, and
assert on how the process actually ends. The tracker thread is a daemon and
the tracking backend adds no Python threads of its own (see
``tests/test_real_model_tracking.py`` for the assertion against the real
backend), so a wedged native call must not hold the process open and no
forced termination is needed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent

# Long enough that a process kept alive by a non-daemon thread would blow it,
# short enough to stay a fast test.
EXIT_BUDGET_S = 25.0


def _run_child(body: str) -> subprocess.CompletedProcess[str]:
    script = textwrap.dedent(
        f"""
        import os, sys
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {str(TESTS_DIR)!r})
        {textwrap.indent(textwrap.dedent(body), " " * 8).strip()}
        """
    )
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=EXIT_BUDGET_S,
        cwd=REPO_ROOT,
    )
    completed.elapsed = time.perf_counter() - started  # type: ignore[attr-defined]
    return completed


def test_process_exits_although_the_tracker_thread_is_wedged_in_a_call() -> None:
    """The daemon tracker thread must not keep the interpreter alive."""

    result = _run_child(
        """
        from threading import Event

        from camera_fakes import factory_for
        from tracker_fakes import ScriptedFactory, tracking_settings
        from gazefix.pipeline.runtime import PipelineRuntime
        from gazefix.camera.models import CameraDevice
        from gazefix.tracking.processor import TrackingProcessor

        never = Event()  # never set: detect() blocks forever, like a hung native call
        factory = ScriptedFactory(tracker_kwargs={"gate": never})
        settings = tracking_settings(tracking_join_timeout_s=0.3, worker_join_timeout_s=1.0)
        processor = TrackingProcessor(factory, settings)
        runtime = PipelineRuntime(settings, processor=processor, source_factory=factory_for([]))
        runtime.start()
        runtime.select_camera(CameraDevice(1))

        deadline = __import__("time").perf_counter() + 5.0
        while __import__("time").perf_counter() < deadline:
            if factory.trackers and factory.trackers[0].detect_started.is_set():
                break
            __import__("time").sleep(0.01)
        assert factory.trackers and factory.trackers[0].detect_started.is_set(), "tracker never entered detect()"

        stopped = runtime.stop()
        print("WEDGED", processor.worker_alive, "STOPPED", stopped, flush=True)
        """
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert "WEDGED True" in result.stdout, result.stdout
    # No forced termination: a plain return from the interpreter, well inside
    # the budget even though a thread is still inside the wedged call.
    assert result.elapsed < EXIT_BUDGET_S  # type: ignore[attr-defined]
    assert "forced_exit" not in result.stderr


def test_camera_is_released_even_though_the_tracker_is_wedged() -> None:
    """A wedged tracker must not delay or block the camera release path."""

    result = _run_child(
        """
        from threading import Event

        from camera_fakes import FakeCameraSource, factory_for, wait_until
        from tracker_fakes import ScriptedFactory, tracking_settings
        from gazefix.pipeline.runtime import PipelineRuntime, RuntimeState
        from gazefix.camera.models import CameraDevice
        from gazefix.tracking.processor import TrackingProcessor

        sources: list[FakeCameraSource] = []
        never = Event()
        factory = ScriptedFactory(tracker_kwargs={"gate": never})
        settings = tracking_settings(tracking_join_timeout_s=0.3, worker_join_timeout_s=1.0)
        processor = TrackingProcessor(factory, settings)
        runtime = PipelineRuntime(settings, processor=processor, source_factory=factory_for(sources))
        runtime.start()
        runtime.select_camera(CameraDevice(2))
        assert wait_until(lambda: bool(sources) and sources[0].reads > 0, timeout=5.0)
        assert wait_until(
            lambda: bool(factory.trackers) and factory.trackers[0].detect_started.is_set(), timeout=5.0
        )

        stopped = runtime.stop()
        released = all(s.closed for s in sources)
        print("RELEASED", released, "STATE", runtime.state.value, "STOPPED", stopped, flush=True)
        """
    )
    assert result.returncode == 0, result.stderr[-3000:]
    # The camera is owned and released by the capture worker, which the wedged
    # tracker thread does not touch.
    assert "RELEASED True" in result.stdout, result.stdout
    assert result.elapsed < EXIT_BUDGET_S  # type: ignore[attr-defined]


def test_runtime_reports_stopping_rather_than_claiming_clean_cleanup() -> None:
    """``stop()`` must not report success while owned work is still running."""

    result = _run_child(
        """
        from threading import Event

        from camera_fakes import FakeCameraSource, factory_for, wait_until
        from tracker_fakes import tracking_settings
        from gazefix.pipeline.runtime import PipelineRuntime, RuntimeState
        from gazefix.camera.models import CameraDevice

        sources: list[FakeCameraSource] = []
        settings = tracking_settings(
            worker_join_timeout_s=0.4, tracking_join_timeout_s=0.1, tracking_enabled=False
        )
        runtime = PipelineRuntime(settings, source_factory=factory_for(sources))
        runtime.start()
        runtime.select_camera(CameraDevice(3))
        assert wait_until(lambda: bool(sources) and sources[0].reads > 0, timeout=5.0)

        gate = Event()  # from here the capture worker is wedged inside a driver read
        sources[0].read_started.clear()
        sources[0].read_gate = gate
        assert wait_until(lambda: sources[0].read_started.is_set(), timeout=5.0)

        stopped = runtime.stop()
        print("STOPPED", stopped, "STATE", runtime.state.value, flush=True)
        gate.set()
        """
    )
    assert result.returncode == 0, result.stderr[-3000:]
    # Truthful: a worker still inside a driver call is reported, never
    # presented as a completed cleanup.
    assert "STOPPED False STATE stopping" in result.stdout, result.stdout
