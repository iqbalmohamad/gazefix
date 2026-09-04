"""Regression coverage for the QA findings F2, F4 and F5.

Each test fails on the behaviour that was reported and passes on the fix, so
the finding cannot silently come back.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.processor import FrameContext
from gazefix.tracking.models import FrameGeometry, TrackingStatus
from gazefix.tracking.overlay import OverlayStyle, _clip_segment, _draw_polyline, render_overlay
from gazefix.tracking.processor import TrackingProcessor
from gazefix.tracking.worker import STATE_READY, STATE_UNAVAILABLE, TrackerWorker, WorkerStatus
from tracker_fakes import ScriptedFactory, blank_frame, tracking_settings, wait_until
from tracking_fakes import synthetic_landmarks, tracked_result


# --------------------------------------------------------------- F2


def test_failure_obtaining_the_next_frame_is_not_blamed_on_the_previous_frame(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """F2: the loop variable must be cleared before each iteration.

    A crash while fetching the next submission used to leave the previous
    iteration's frame in scope, so the recovery path published an ``ERROR``
    result for a frame that had already been tracked and published.
    """

    factory = ScriptedFactory()
    processor = TrackingProcessor(factory, tracking_settings(), PipelineMetrics())
    processor.start()
    assert wait_until(lambda: processor.status().state == STATE_READY)
    worker = processor._worker  # noqa: SLF001  (the loop under test)
    frame = blank_frame()
    try:
        sequence = 0
        good = None
        for _ in range(200):
            sequence += 1
            output = processor.process(frame, FrameContext(sequence, time.perf_counter_ns(), 1))
            if output.tracking is not None and output.tracking.status is TrackingStatus.TRACKED:
                good = output.tracking
                break
            time.sleep(0.005)
        assert good is not None, "never reached a tracked frame"

        handed_to_recovery: list[object] = []
        original_recover = worker._recover_from_crash  # noqa: SLF001

        def recording_recover(exc, submission):  # type: ignore[no-untyped-def]
            handed_to_recovery.append(submission)
            return original_recover(exc, submission)

        monkeypatch.setattr(worker, "_recover_from_crash", recording_recover)

        calls = {"n": 0}
        original_next = worker._next_submission  # noqa: SLF001

        def failing_next():  # type: ignore[no-untyped-def]
            # The worker is currently blocked inside the original call; this
            # runs on the NEXT loop iteration, i.e. after a frame was handled
            # and answered.
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("bookkeeping failed while fetching the next frame")
            return original_next()

        monkeypatch.setattr(worker, "_next_submission", failing_next)

        # Wake the loop with one more frame; the worker answers it and then
        # hits the injected failure while fetching the following one.
        sequence += 1
        last = processor.process(frame, FrameContext(sequence, time.perf_counter_ns(), 1))
        assert wait_until(lambda: bool(handed_to_recovery), timeout=5.0), "the injected failure never ran"

        # The recovery path was handed no frame at all, so it published
        # nothing for the frame the previous iteration already answered.
        assert handed_to_recovery[0] is None
        latest = worker._latest  # noqa: SLF001
        assert latest is not None
        assert latest.status is not TrackingStatus.ERROR, (
            f"an error result was published for already-answered frame {latest.capture_sequence}"
        )
        assert last.tracking is not None
    finally:
        processor.close()


# --------------------------------------------------------------- F4


def test_segment_crossing_the_image_is_drawn_through_it_not_along_the_border() -> None:
    """F4: both vertices off-screen, but the segment crosses the frame."""

    canvas = np.zeros((180, 320, 3), dtype=np.uint8)
    points = np.array([[-500.0, 90.0], [820.0, 90.0]], dtype=np.float32)
    _draw_polyline(canvas, points, (255, 255, 255), closed=False)
    painted = np.argwhere(canvas.max(axis=2) > 0)
    assert len(painted) > 0, "the visible part of the segment was dropped"
    rows = set(painted[:, 0])
    assert rows <= {89, 90, 91}, f"the line was not drawn where it really crosses: rows {sorted(rows)}"
    # It spans the width rather than collapsing onto an edge.
    assert painted[:, 1].min() <= 2 and painted[:, 1].max() >= 317


def test_segment_entirely_outside_the_image_paints_nothing() -> None:
    canvas = np.zeros((180, 320, 3), dtype=np.uint8)
    _draw_polyline(canvas, np.array([[-500.0, -500.0], [-400.0, -300.0]], dtype=np.float32), (255, 255, 255), False)
    assert canvas.max() == 0


def test_partly_visible_segment_follows_its_true_geometry() -> None:
    """The reported symptom, precisely: a clamped vertex moved the line.

    One endpoint is inside and the other is far off to the right. Clamping
    that far endpoint to the image corner swings the segment steeply
    downwards; clipping keeps its real, nearly horizontal path.
    """

    canvas = np.zeros((180, 320, 3), dtype=np.uint8)
    # The far vertex is outside on both axes, so clamping it to the image
    # corner changes the segment's slope, not just its length.
    inside, far = (10.0, 90.0), (5000.0, 3000.0)
    _draw_polyline(canvas, np.array([inside, far], dtype=np.float32), (255, 255, 255), closed=False)
    painted = np.argwhere(canvas.max(axis=2) > 0)
    assert len(painted) > 0, "the visible part of the segment was dropped"

    # The true segment leaves through the bottom edge at x ~= 163. Clamping the
    # far vertex to the corner would instead carry the line to x ~= 317.
    assert painted[:, 1].max() <= 175, (
        f"the segment was drawn to x={painted[:, 1].max()}, far past where it truly leaves the "
        "frame; the off-screen vertex was clamped instead of the segment being clipped"
    )
    assert painted[:, 1].max() >= 150  # it does reach the bottom edge
    assert painted[:, 0].max() >= 175


def test_far_off_screen_contour_does_not_paint_the_border() -> None:
    canvas = np.zeros((180, 320, 3), dtype=np.uint8)
    # A closed quad wholly to the right of the image.
    quad = np.array([[900.0, 40.0], [1200.0, 40.0], [1200.0, 140.0], [900.0, 140.0]], dtype=np.float32)
    _draw_polyline(canvas, quad, (255, 255, 255), closed=True)
    assert canvas.max() == 0, "an off-screen contour was pinned onto the image border"


def test_clip_segment_keeps_the_true_crossing_point() -> None:
    # A diagonal entering the image: the clipped end must sit on the border
    # at the geometrically correct place, not at a clamped vertex.
    visible = _clip_segment(-10.0, -10.0, 90.0, 90.0, 320, 180)
    assert visible is not None
    x0, y0, x1, y1 = visible
    assert x0 == pytest.approx(0.0) and y0 == pytest.approx(0.0)
    assert x1 == pytest.approx(90.0) and y1 == pytest.approx(90.0)
    assert _clip_segment(float("nan"), 0.0, 10.0, 10.0, 320, 180) is None
    assert _clip_segment(-5.0, 90.0, -1.0, 90.0, 320, 180) is None


def test_overlay_with_a_face_off_to_the_side_leaves_the_border_clean() -> None:
    geometry = FrameGeometry(320, 180)
    landmarks = synthetic_landmarks(center=(0.5, 0.5), face_height=0.5).copy()
    landmarks[:, 0] += 4.0  # the whole face far off the right edge
    result = tracked_result(landmarks, geometry)
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    canvas = render_overlay(frame, result, OverlayStyle(text=False))
    assert canvas.max() == 0, "off-screen landmarks were drawn onto the image edge"


# --------------------------------------------------------------- F5


class _StubWorker:
    """A worker whose wait outcome and status the test dictates."""

    def __init__(self, status: WorkerStatus) -> None:
        self._status = status
        self.metrics = None

    def start(self) -> None:
        return None

    def submit(self, frame, context) -> None:  # type: ignore[no-untyped-def]
        return None

    def wait_for(self, sequence, timeout_s):  # type: ignore[no-untyped-def]
        return None, self._status

    def status(self) -> WorkerStatus:
        return self._status

    def stop(self, timeout: float) -> bool:
        return True

    @property
    def is_alive(self) -> bool:
        return False


def _process_once(status: WorkerStatus):  # type: ignore[no-untyped-def]
    metrics = PipelineMetrics()
    processor = TrackingProcessor(ScriptedFactory(), tracking_settings(), metrics)
    processor._worker = _StubWorker(status)  # noqa: SLF001
    frame = blank_frame()
    output = processor.process(frame, FrameContext(1, 1000, 1))
    return output, metrics.snapshot()


def test_shutdown_during_the_wait_is_reported_as_unavailable_not_a_timeout() -> None:
    """F5: ``stop()`` sets the event before the state changes.

    A frame that finds no result in that window was cut short by shutdown,
    not by a slow tracker, and must not be labelled or counted as a timeout.
    """

    output, snapshot = _process_once(
        WorkerStatus(STATE_READY, "", "", 1, stopping=True)
    )
    assert output.tracking is not None
    assert output.tracking.status is TrackingStatus.UNAVAILABLE
    assert output.tracking.message == "tracking stopped"
    assert snapshot.tracking_timeouts == 0
    assert snapshot.tracking_unavailable == 1
    assert snapshot.tracking_errors == 0


def test_a_genuine_timeout_is_still_a_timeout() -> None:
    output, snapshot = _process_once(WorkerStatus(STATE_READY, "", "", 1, stopping=False))
    assert output.tracking is not None and output.tracking.status is TrackingStatus.TIMEOUT
    assert snapshot.tracking_timeouts == 1
    assert snapshot.tracking_unavailable == 0


def test_unavailable_tracking_is_counted_apart_from_inference_errors() -> None:
    output, snapshot = _process_once(
        WorkerStatus(STATE_UNAVAILABLE, "face_landmarker.task not found", "", 1, stopping=False)
    )
    assert output.tracking is not None and output.tracking.status is TrackingStatus.UNAVAILABLE
    assert "not found" in output.tracking.message
    assert snapshot.tracking_unavailable == 1
    assert snapshot.tracking_errors == 0
    assert snapshot.tracking_timeouts == 0


def test_worker_status_reports_stopping_from_the_stop_event() -> None:
    worker = TrackerWorker(ScriptedFactory(), tracking_settings())
    assert worker.status().stopping is False
    worker.stop(0.1)
    assert worker.status().stopping is True
