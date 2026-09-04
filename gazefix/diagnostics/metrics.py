"""Thread-safe frame-rate and processing-time metrics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
import time


class FrameRateMeter:
    """Measure event frequency over a bounded rolling time window."""

    def __init__(self, window_seconds: float = 2.0) -> None:
        if window_seconds <= 0:
            raise ValueError("Window must be positive")
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = Lock()

    def record(self, timestamp: float | None = None) -> None:
        now = time.perf_counter() if timestamp is None else timestamp
        with self._lock:
            self._timestamps.append(now)
            self._trim(now)

    def rate(self, timestamp: float | None = None) -> float:
        now = time.perf_counter() if timestamp is None else timestamp
        with self._lock:
            self._trim(now)
            if len(self._timestamps) < 2:
                return 0.0
            elapsed = self._timestamps[-1] - self._timestamps[0]
            return (len(self._timestamps) - 1) / elapsed if elapsed > 0 else 0.0

    def _trim(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """Rolling rates, smoothed durations (ms) and counters.

    Duration boundaries: ``processing_ms`` is the time inside the processing
    stage (for M1 that includes the bounded wait for the frame's tracking
    result and overlay rendering); ``tracking_inference_ms`` is the backend
    call on the tracker thread; ``tracking_total_ms`` runs from the processor
    handing a frame to the tracker until its result was available;
    ``pipeline_latency_ms`` runs from capture timestamp to the processed
    frame being published (it excludes camera driver latency and preview
    presentation).
    """

    capture_fps: float
    display_fps: float
    processing_ms: float
    captured_frames: int
    displayed_frames: int
    read_failures: int
    capture_replacements: int
    output_replacements: int
    pipeline_latency_ms: float = 0.0
    tracking_inference_ms: float = 0.0
    tracking_total_ms: float = 0.0
    tracked_frames: int = 0
    low_quality_frames: int = 0
    no_face_frames: int = 0
    tracking_timeouts: int = 0
    tracking_errors: int = 0
    tracking_unavailable: int = 0
    tracking_replaced: int = 0


class PipelineMetrics:
    def __init__(self) -> None:
        self.capture_rate = FrameRateMeter()
        self.display_rate = FrameRateMeter()
        self._lock = Lock()
        self._processing_ms = 0.0
        self._captured_frames = 0
        self._displayed_frames = 0
        self._read_failures = 0
        self._pipeline_latency_ms = 0.0
        self._tracking_inference_ms = 0.0
        self._tracking_total_ms = 0.0
        self._tracked_frames = 0
        self._low_quality_frames = 0
        self._no_face_frames = 0
        self._tracking_timeouts = 0
        self._tracking_errors = 0
        self._tracking_unavailable = 0
        self._tracking_replaced = 0

    def record_capture(self) -> None:
        self.capture_rate.record()
        with self._lock:
            self._captured_frames += 1

    def record_display(self) -> None:
        self.display_rate.record()
        with self._lock:
            self._displayed_frames += 1

    def record_processing(self, duration_ms: float) -> None:
        with self._lock:
            self._processing_ms = _smooth(self._processing_ms, duration_ms)

    def record_pipeline_latency(self, duration_ms: float) -> None:
        with self._lock:
            self._pipeline_latency_ms = _smooth(self._pipeline_latency_ms, duration_ms)

    def record_read_failure(self) -> None:
        with self._lock:
            self._read_failures += 1

    def record_tracking(
        self,
        status: str,
        inference_ms: float | None = None,
        total_ms: float | None = None,
    ) -> None:
        """Count one tracking outcome by status value and smooth its durations."""

        with self._lock:
            if status == "tracked":
                self._tracked_frames += 1
            elif status == "low_quality":
                self._low_quality_frames += 1
            elif status == "no_face":
                self._no_face_frames += 1
            elif status == "timeout":
                self._tracking_timeouts += 1
            elif status == "error":
                self._tracking_errors += 1
            elif status == "unavailable":
                # A tracker that cannot run at all (no model, failed start,
                # shutdown) is a different operational condition from a
                # backend that ran and raised; keeping them apart makes the
                # diagnostics and the milestone report truthful.
                self._tracking_unavailable += 1
            if inference_ms is not None and inference_ms > 0:
                self._tracking_inference_ms = _smooth(self._tracking_inference_ms, inference_ms)
            if total_ms is not None and total_ms > 0:
                self._tracking_total_ms = _smooth(self._tracking_total_ms, total_ms)

    def record_tracking_replaced(self) -> None:
        """A frame handed to the tracker was replaced before it was processed."""

        with self._lock:
            self._tracking_replaced += 1

    def snapshot(
        self, capture_replacements: int = 0, output_replacements: int = 0
    ) -> MetricsSnapshot:
        with self._lock:
            return MetricsSnapshot(
                capture_fps=self.capture_rate.rate(),
                display_fps=self.display_rate.rate(),
                processing_ms=self._processing_ms,
                captured_frames=self._captured_frames,
                displayed_frames=self._displayed_frames,
                read_failures=self._read_failures,
                capture_replacements=capture_replacements,
                output_replacements=output_replacements,
                pipeline_latency_ms=self._pipeline_latency_ms,
                tracking_inference_ms=self._tracking_inference_ms,
                tracking_total_ms=self._tracking_total_ms,
                tracked_frames=self._tracked_frames,
                low_quality_frames=self._low_quality_frames,
                no_face_frames=self._no_face_frames,
                tracking_timeouts=self._tracking_timeouts,
                tracking_errors=self._tracking_errors,
                tracking_unavailable=self._tracking_unavailable,
                tracking_replaced=self._tracking_replaced,
            )


def _smooth(current: float, sample: float) -> float:
    return sample if current == 0.0 else 0.2 * sample + 0.8 * current

