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
    capture_fps: float
    display_fps: float
    processing_ms: float
    captured_frames: int
    displayed_frames: int
    read_failures: int
    capture_replacements: int
    output_replacements: int


class PipelineMetrics:
    def __init__(self) -> None:
        self.capture_rate = FrameRateMeter()
        self.display_rate = FrameRateMeter()
        self._lock = Lock()
        self._processing_ms = 0.0
        self._captured_frames = 0
        self._displayed_frames = 0
        self._read_failures = 0

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
            if self._processing_ms == 0.0:
                self._processing_ms = duration_ms
            else:
                self._processing_ms = 0.2 * duration_ms + 0.8 * self._processing_ms

    def record_read_failure(self) -> None:
        with self._lock:
            self._read_failures += 1

    def snapshot(
        self, capture_replacements: int = 0, output_replacements: int = 0
    ) -> MetricsSnapshot:
        with self._lock:
            processing_ms = self._processing_ms
            captured_frames = self._captured_frames
            displayed_frames = self._displayed_frames
            read_failures = self._read_failures
        return MetricsSnapshot(
            capture_fps=self.capture_rate.rate(),
            display_fps=self.display_rate.rate(),
            processing_ms=processing_ms,
            captured_frames=captured_frames,
            displayed_frames=displayed_frames,
            read_failures=read_failures,
            capture_replacements=capture_replacements,
            output_replacements=output_replacements,
        )

