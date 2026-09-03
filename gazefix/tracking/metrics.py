"""Thread-safe tracker-specific diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from gazefix.tracking.models import TrackingResult, TrackingState


@dataclass(frozen=True, slots=True)
class TrackingMetricsSnapshot:
    frames_seen: int
    tracked_frames: int
    detected_faces: int
    no_face_frames: int
    temporary_losses: int
    low_confidence_frames: int
    invalid_frames: int
    tracker_errors: int
    average_processing_ms: float
    last_state: TrackingState | None


class TrackingMetrics:
    """Collect counters and an EWMA of per-frame tracker latency."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._frames_seen = 0
        self._tracked_frames = 0
        self._detected_faces = 0
        self._no_face_frames = 0
        self._temporary_losses = 0
        self._low_confidence_frames = 0
        self._invalid_frames = 0
        self._tracker_errors = 0
        self._average_processing_ms = 0.0
        self._last_state: TrackingState | None = None

    def record(self, result: TrackingResult) -> None:
        with self._lock:
            self._frames_seen += 1
            self._last_state = result.state
            self._detected_faces += len(result.faces)
            if result.state is TrackingState.TRACKED:
                self._tracked_frames += 1
            elif result.state is TrackingState.LOW_CONFIDENCE:
                self._tracked_frames += 1
                self._low_confidence_frames += 1
            elif result.state is TrackingState.NO_FACE:
                self._no_face_frames += 1
            elif result.state is TrackingState.TEMPORARILY_LOST:
                self._temporary_losses += 1
            elif result.state is TrackingState.INVALID_FRAME:
                self._invalid_frames += 1
            elif result.state is TrackingState.TRACKER_ERROR:
                self._tracker_errors += 1

            duration = result.processing_time_ms
            if self._frames_seen == 1:
                self._average_processing_ms = duration
            else:
                self._average_processing_ms = (
                    0.2 * duration + 0.8 * self._average_processing_ms
                )

    def snapshot(self) -> TrackingMetricsSnapshot:
        with self._lock:
            return TrackingMetricsSnapshot(
                frames_seen=self._frames_seen,
                tracked_frames=self._tracked_frames,
                detected_faces=self._detected_faces,
                no_face_frames=self._no_face_frames,
                temporary_losses=self._temporary_losses,
                low_confidence_frames=self._low_confidence_frames,
                invalid_frames=self._invalid_frames,
                tracker_errors=self._tracker_errors,
                average_processing_ms=self._average_processing_ms,
                last_state=self._last_state,
            )
