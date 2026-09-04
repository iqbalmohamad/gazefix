"""``TrackingProcessor``: the M1 tracking and M2 gaze implementation of the seam.

Runs on the M0 processor thread. For every captured frame it hands the frame
to the tracker thread, waits a bounded time for that frame's own result,
and publishes the frame with either that result or an explicit untracked
status (initialising, unavailable, timed out). It never blocks the preview
on tracking for longer than ``tracking_wait_ms`` and never mutates the
input array: the overlay, when enabled, is drawn on a copy.

The M2 gaze estimate rides on the tracking result, computed on the tracker
thread right after analysis, so it shares that result's frame identity and
adds no wait of its own to this stage.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from threading import Lock
import time

from gazefix.config import AppSettings
from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.processor import Frame, FrameContext, ProcessorOutput
from gazefix.tracking.models import FrameGeometry, TrackingStatus, TrackingTiming, untracked
from gazefix.tracking.overlay import OverlayStyle, render_overlay
from gazefix.tracking.tracker import TrackerFactory
from gazefix.tracking.worker import STATE_INITIALIZING, STATE_READY, TrackerWorker


logger = logging.getLogger(__name__)

_PERSISTENT_TIMEOUT_FRAMES = 30


class TrackingProcessor:
    def __init__(
        self,
        factory: TrackerFactory,
        settings: AppSettings,
        metrics: PipelineMetrics | None = None,
        overlay_enabled: bool = False,
    ) -> None:
        self._settings = settings
        self._metrics = metrics
        self._worker = TrackerWorker(factory, settings, metrics)
        self._lock = Lock()
        self._overlay_enabled = overlay_enabled
        self._closed = False
        self._started = False
        self._consecutive_timeouts = 0
        self._timeout_logged = False

    # ------------------------------------------------------------- UI-facing
    def set_overlay_enabled(self, enabled: bool) -> None:
        """Thread-safe toggle; takes effect on the next processed frame."""

        with self._lock:
            self._overlay_enabled = bool(enabled)

    @property
    def overlay_enabled(self) -> bool:
        with self._lock:
            return self._overlay_enabled

    @property
    def worker_alive(self) -> bool:
        return self._worker.is_alive

    def status(self):  # type: ignore[no-untyped-def]
        return self._worker.status()

    # ----------------------------------------------------- processor thread
    def start(self, metrics: PipelineMetrics | None = None) -> None:
        """Start the tracker thread (idempotent); model loading begins at once.

        ``metrics`` (the pipeline's shared object, passed by the processing
        worker) is adopted when this processor was built without one.
        """

        if metrics is not None and self._metrics is None:
            self._metrics = metrics
            self._worker.metrics = metrics
        if self._closed or self._started:
            return
        try:
            self._worker.start()
        except Exception as exc:  # noqa: BLE001  (thread could not be launched)
            logger.exception(
                "Tracker thread could not be started; tracking unavailable",
                extra={"event": "tracker_thread_start_error"},
            )
            self._worker.mark_unavailable(f"tracking unavailable: tracker thread could not be started ({exc})")
        finally:
            self._started = True  # never retried per frame

    def process(self, frame: Frame, context: FrameContext) -> ProcessorOutput:
        self.start()
        started = time.perf_counter()
        self._worker.submit(frame, context)
        result, status = self._worker.wait_for(
            context.capture_sequence, self._settings.tracking_wait_ms / 1000.0
        )
        waited_ms = (time.perf_counter() - started) * 1000.0
        if result is None or not result.belongs_to(context.capture_sequence, context.camera_request_id):
            if status.stopping:
                # Shutdown cut the wait short; the tracker was not slow.
                tracking_status = TrackingStatus.UNAVAILABLE
                message = "tracking stopped"
            elif status.state == STATE_READY:
                tracking_status, message = TrackingStatus.TIMEOUT, "tracking result not ready in time"
                self._note_timeout()
            elif status.state == STATE_INITIALIZING:
                tracking_status, message = TrackingStatus.INITIALIZING, status.message
            else:
                tracking_status, message = TrackingStatus.UNAVAILABLE, status.message
            result = untracked(
                tracking_status,
                context.capture_sequence,
                context.captured_at_ns,
                context.camera_request_id,
                FrameGeometry(frame.shape[1], frame.shape[0]),
                message,
                TrackingTiming(waited_ms=waited_ms),
            )
        else:
            self._consecutive_timeouts = 0
            result = replace(result, timing=replace(result.timing, waited_ms=waited_ms))
        if self._metrics is not None:
            self._metrics.record_tracking(
                result.status.value, result.timing.inference_ms, result.timing.total_ms
            )
            if result.gaze is not None:
                self._metrics.record_gaze(result.gaze.status.value, result.gaze.estimation_ms)
        output = frame
        if self.overlay_enabled:
            output = render_overlay(
                frame,
                result,
                OverlayStyle(
                    description=self._worker.status().description,
                    gaze_description=self._worker.gaze_description,
                ),
            )
        return ProcessorOutput(output, result)

    def _note_timeout(self) -> None:
        """Say once when the tracker is persistently slower than the wait budget."""

        self._consecutive_timeouts += 1
        if self._consecutive_timeouts == _PERSISTENT_TIMEOUT_FRAMES and not self._timeout_logged:
            self._timeout_logged = True
            logger.warning(
                "Tracking results have not been ready in time for %d consecutive frames; "
                "the tracker is slower than tracking_wait_ms and tracking is effectively "
                "paused while the preview continues",
                _PERSISTENT_TIMEOUT_FRAMES,
                extra={
                    "event": "tracking_budget_exceeded",
                    "tracking_wait_ms": self._settings.tracking_wait_ms,
                    "consecutive_timeouts": self._consecutive_timeouts,
                },
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._started:
            self._worker.stop(self._settings.tracking_join_timeout_s)
