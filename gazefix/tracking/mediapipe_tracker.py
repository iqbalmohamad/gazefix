"""MediaPipe Face Landmarker adapter behind GazeFix-owned data structures."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
from numbers import Integral
from pathlib import Path
from threading import Lock
import time
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from gazefix.tracking.metrics import TrackingMetrics, TrackingMetricsSnapshot
from gazefix.tracking.models import (
    NormalizedLandmark,
    ReliabilityStatus,
    TrackedFace,
    TrackingReliability,
    TrackingResult,
    TrackingState,
)
from gazefix.tracking.selection import select_primary_face


logger = logging.getLogger(__name__)
Frame = NDArray[np.uint8]

# MediaPipe Face Landmarker topology. The iris center is included before its
# four contour points. These constants remain application-owned so no
# MediaPipe connection object escapes the adapter.
LEFT_EYE_INDICES = (
    263,
    249,
    390,
    373,
    374,
    380,
    381,
    382,
    362,
    398,
    384,
    385,
    386,
    387,
    388,
    466,
)
RIGHT_EYE_INDICES = (
    33,
    7,
    163,
    144,
    145,
    153,
    154,
    155,
    133,
    173,
    157,
    158,
    159,
    160,
    161,
    246,
)
LEFT_IRIS_INDICES = (473, 474, 475, 476, 477)
RIGHT_IRIS_INDICES = (468, 469, 470, 471, 472)


class TrackerInitializationError(RuntimeError):
    """Raised when tracker resources cannot be created."""


@dataclass(frozen=True, slots=True)
class MediaPipeTrackerConfig:
    """Configuration for a CPU MediaPipe Face Landmarker instance."""

    model_path: Path
    max_faces: int = 1
    min_face_detection_confidence: float = 0.5
    min_face_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    low_confidence_threshold: float = 0.5
    temporary_loss_frames: int = 5

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_path", Path(self.model_path))
        if self.max_faces < 1:
            raise ValueError("max_faces must be positive")
        for name in (
            "min_face_detection_confidence",
            "min_face_presence_confidence",
            "min_tracking_confidence",
            "low_confidence_threshold",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.temporary_loss_frames < 0:
            raise ValueError("temporary_loss_frames cannot be negative")


@dataclass(frozen=True, slots=True)
class _BackendFace:
    landmarks: tuple[NormalizedLandmark, ...]
    confidence: float | None = None


class _LandmarkBackend(Protocol):
    def initialize(self) -> None: ...

    def detect(self, rgb_frame: Frame, timestamp_ms: int) -> Sequence[_BackendFace]: ...

    def close(self) -> None: ...


BackendFactory = Callable[[MediaPipeTrackerConfig], _LandmarkBackend]


class _MediaPipeBackend:
    """Thin private wrapper around MediaPipe Tasks objects."""

    def __init__(self, config: MediaPipeTrackerConfig) -> None:
        self._config = config
        self._mediapipe: object | None = None
        self._landmarker: object | None = None

    def initialize(self) -> None:
        if not self._config.model_path.is_file():
            raise TrackerInitializationError(
                f"MediaPipe model not found: {self._config.model_path}"
            )
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise TrackerInitializationError(
                "MediaPipe is not installed; install the declared project dependencies"
            ) from exc

        try:
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(self._config.model_path),
                    delegate=mp.tasks.BaseOptions.Delegate.CPU,
                ),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_faces=self._config.max_faces,
                min_face_detection_confidence=(
                    self._config.min_face_detection_confidence
                ),
                min_face_presence_confidence=(
                    self._config.min_face_presence_confidence
                ),
                min_tracking_confidence=self._config.min_tracking_confidence,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
            self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(
                options
            )
            self._mediapipe = mp
        except Exception as exc:
            raise TrackerInitializationError(
                f"Could not initialize MediaPipe Face Landmarker: {exc}"
            ) from exc

    def detect(self, rgb_frame: Frame, timestamp_ms: int) -> Sequence[_BackendFace]:
        if self._landmarker is None or self._mediapipe is None:
            raise RuntimeError("MediaPipe backend is not initialized")
        mp = self._mediapipe
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        faces: list[_BackendFace] = []
        for provider_landmarks in result.face_landmarks:
            landmarks = tuple(
                NormalizedLandmark(
                    index=index,
                    x=float(point.x),
                    y=float(point.y),
                    z=float(point.z),
                    visibility=_optional_probability(point, "visibility"),
                    presence=_optional_probability(point, "presence"),
                )
                for index, point in enumerate(provider_landmarks)
            )
            if landmarks:
                # Face Landmarker applies configured confidence thresholds but
                # does not expose a per-result face/tracking confidence score.
                faces.append(_BackendFace(landmarks=landmarks, confidence=None))
        return faces

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
        self._landmarker = None
        self._mediapipe = None


def _optional_probability(value: object, name: str) -> float | None:
    candidate = getattr(value, name, None)
    if candidate is None:
        return None
    candidate = float(candidate)
    return candidate if 0.0 <= candidate <= 1.0 else None


class MediaPipeFaceTracker:
    """Stateful, failure-tolerant adapter for MediaPipe Face Landmarker.

    Inputs are OpenCV-style BGR uint8 frames. The adapter creates a private RGB
    copy for MediaPipe, so neither inference nor callers can mutate the source.
    """

    def __init__(
        self,
        config: MediaPipeTrackerConfig,
        *,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self._config = config
        self._backend_factory = backend_factory or _MediaPipeBackend
        self._backend: _LandmarkBackend | None = None
        self._metrics = TrackingMetrics()
        self._lock = Lock()
        self._next_sequence = 1
        self._last_backend_timestamp_ms = -1
        self._ever_detected = False
        self._consecutive_misses = 0
        self._shutdown = False

    def initialize(self) -> None:
        with self._lock:
            if self._shutdown:
                raise TrackerInitializationError(
                    "A shut down tracker cannot be initialized again"
                )
            if self._backend is not None:
                return
            backend = self._backend_factory(self._config)
            try:
                backend.initialize()
            except Exception:
                try:
                    backend.close()
                except Exception:
                    logger.exception(
                        "Tracker backend cleanup failed after initialization error",
                        extra={"event": "tracker_initialize_cleanup_failed"},
                    )
                raise
            self._backend = backend
            logger.info(
                "Face tracker initialized",
                extra={
                    "event": "tracker_initialized",
                    "provider": "mediapipe",
                    "max_faces": self._config.max_faces,
                },
            )

    def track(
        self,
        frame: Frame,
        *,
        frame_sequence: int | None = None,
        timestamp_ns: int | None = None,
    ) -> TrackingResult:
        with self._lock:
            started_ns = time.perf_counter_ns()
            sequence_error = _non_negative_integer_error(
                "Frame sequence", frame_sequence
            )
            requested_sequence = (
                None
                if frame_sequence is None or sequence_error
                else int(frame_sequence)
            )
            sequence = self._allocate_sequence(requested_sequence)
            timestamp_error = _non_negative_integer_error(
                "Frame timestamp", timestamp_ns
            )
            timestamp = (
                time.perf_counter_ns()
                if timestamp_ns is None or timestamp_error
                else int(timestamp_ns)
            )

            metadata_error = sequence_error or timestamp_error
            if metadata_error:
                return self._record_failure(
                    state=TrackingState.INVALID_FRAME,
                    sequence=sequence,
                    timestamp_ns=timestamp,
                    error=metadata_error,
                    started_ns=started_ns,
                )
            if self._shutdown:
                return self._record_failure(
                    state=TrackingState.SHUTDOWN,
                    sequence=sequence,
                    timestamp_ns=timestamp,
                    error="Tracker has been shut down",
                    started_ns=started_ns,
                )
            if self._backend is None:
                return self._record_failure(
                    state=TrackingState.NOT_INITIALIZED,
                    sequence=sequence,
                    timestamp_ns=timestamp,
                    error="Tracker is not initialized",
                    started_ns=started_ns,
                )

            frame_error = _frame_validation_error(frame)
            if frame_error is not None:
                return self._record_failure(
                    state=TrackingState.INVALID_FRAME,
                    sequence=sequence,
                    timestamp_ns=timestamp,
                    error=frame_error,
                    started_ns=started_ns,
                )

            height, width = frame.shape[:2]
            # Reversing channels creates a negative-stride view; ascontiguousarray
            # necessarily materializes provider-owned RGB storage.
            rgb_frame = np.ascontiguousarray(frame[:, :, ::-1])
            backend_timestamp_ms = self._monotonic_timestamp_ms(timestamp)
            try:
                backend_faces = self._backend.detect(rgb_frame, backend_timestamp_ms)
                faces = tuple(
                    _to_tracked_face(face, source_index=index)
                    for index, face in enumerate(backend_faces)
                    if face.landmarks
                )
            except Exception as exc:
                logger.exception(
                    "Face tracker inference failed",
                    extra={"event": "tracker_inference_failed", "sequence": sequence},
                )
                return self._record_failure(
                    state=TrackingState.TRACKER_ERROR,
                    sequence=sequence,
                    timestamp_ns=timestamp,
                    error=f"Tracker inference failed: {exc}",
                    started_ns=started_ns,
                    frame_width=width,
                    frame_height=height,
                )

            if not faces:
                self._consecutive_misses += 1
                temporarily_lost = (
                    self._ever_detected
                    and self._consecutive_misses <= self._config.temporary_loss_frames
                )
                state = (
                    TrackingState.TEMPORARILY_LOST
                    if temporarily_lost
                    else TrackingState.NO_FACE
                )
                if not temporarily_lost:
                    self._ever_detected = False
                return self._record_result(
                    state=state,
                    sequence=sequence,
                    timestamp_ns=timestamp,
                    frame_width=width,
                    frame_height=height,
                    faces=(),
                    primary_face_index=None,
                    reliability=TrackingReliability(
                        status=ReliabilityStatus.UNAVAILABLE,
                        reason="No face landmarks were returned",
                    ),
                    started_ns=started_ns,
                )

            self._ever_detected = True
            self._consecutive_misses = 0
            primary_index = select_primary_face(faces)
            assert primary_index is not None
            confidence = faces[primary_index].confidence
            low_confidence = (
                confidence is not None
                and confidence < self._config.low_confidence_threshold
            )
            if low_confidence:
                state = TrackingState.LOW_CONFIDENCE
                reliability = TrackingReliability(
                    status=ReliabilityStatus.LOW_CONFIDENCE,
                    confidence=confidence,
                    reason=(
                        "Backend confidence is below the configured application "
                        "threshold"
                    ),
                )
            else:
                state = TrackingState.TRACKED
                reliability = TrackingReliability(
                    status=ReliabilityStatus.ACCEPTED,
                    confidence=confidence,
                    reason=(
                        "MediaPipe accepted the result at configured detection, "
                        "presence, and tracking thresholds; its Tasks API does not "
                        "expose per-result confidence"
                        if confidence is None
                        else "Backend confidence met the application threshold"
                    ),
                )
            return self._record_result(
                state=state,
                sequence=sequence,
                timestamp_ns=timestamp,
                frame_width=width,
                frame_height=height,
                faces=faces,
                primary_face_index=primary_index,
                reliability=reliability,
                started_ns=started_ns,
            )

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            backend, self._backend = self._backend, None
            self._shutdown = True
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    logger.exception(
                        "Face tracker shutdown failed",
                        extra={"event": "tracker_shutdown_failed"},
                    )
            logger.info(
                "Face tracker shut down", extra={"event": "tracker_shutdown"}
            )

    def metrics_snapshot(self) -> TrackingMetricsSnapshot:
        return self._metrics.snapshot()

    def __enter__(self) -> "MediaPipeFaceTracker":
        self.initialize()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.shutdown()

    def _allocate_sequence(self, requested: int | None) -> int:
        if requested is None:
            sequence = self._next_sequence
            self._next_sequence += 1
            return sequence
        self._next_sequence = max(self._next_sequence, requested + 1)
        return requested

    def _monotonic_timestamp_ms(self, timestamp_ns: int) -> int:
        candidate = timestamp_ns // 1_000_000
        candidate = max(candidate, self._last_backend_timestamp_ms + 1)
        self._last_backend_timestamp_ms = candidate
        return candidate

    def _record_failure(
        self,
        *,
        state: TrackingState,
        sequence: int,
        timestamp_ns: int,
        error: str,
        started_ns: int,
        frame_width: int | None = None,
        frame_height: int | None = None,
    ) -> TrackingResult:
        return self._record_result(
            state=state,
            sequence=sequence,
            timestamp_ns=timestamp_ns,
            frame_width=frame_width,
            frame_height=frame_height,
            faces=(),
            primary_face_index=None,
            reliability=TrackingReliability(
                status=ReliabilityStatus.UNAVAILABLE,
                reason=error,
            ),
            error=error,
            started_ns=started_ns,
        )

    def _record_result(
        self,
        *,
        state: TrackingState,
        sequence: int,
        timestamp_ns: int,
        frame_width: int | None,
        frame_height: int | None,
        faces: tuple[TrackedFace, ...],
        primary_face_index: int | None,
        reliability: TrackingReliability,
        started_ns: int,
        error: str | None = None,
    ) -> TrackingResult:
        duration_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        result = TrackingResult(
            state=state,
            frame_sequence=sequence,
            timestamp_ns=timestamp_ns,
            frame_width=frame_width,
            frame_height=frame_height,
            faces=faces,
            primary_face_index=primary_face_index,
            reliability=reliability,
            processing_time_ms=duration_ms,
            error=error,
        )
        self._metrics.record(result)
        return result


def _frame_validation_error(frame: object) -> str | None:
    if not isinstance(frame, np.ndarray):
        return "Frame must be a NumPy array"
    if frame.dtype != np.uint8:
        return "Frame dtype must be uint8"
    if frame.ndim != 3 or frame.shape[2] != 3:
        return "Frame must have shape (height, width, 3)"
    if frame.shape[0] <= 0 or frame.shape[1] <= 0:
        return "Frame dimensions must be positive"
    return None


def _non_negative_integer_error(name: str, value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        return f"{name} must be a non-negative integer"
    return None


def _to_tracked_face(face: _BackendFace, source_index: int) -> TrackedFace:
    landmarks = tuple(face.landmarks)
    by_index = {point.index: point for point in landmarks}

    def subset(indices: tuple[int, ...]) -> tuple[NormalizedLandmark, ...]:
        # Missing topology points produce a smaller/empty subset; they are never
        # synthesized. This allows future models without iris support.
        return tuple(by_index[index] for index in indices if index in by_index)

    return TrackedFace(
        source_index=source_index,
        landmarks=landmarks,
        left_eye_landmarks=subset(LEFT_EYE_INDICES),
        right_eye_landmarks=subset(RIGHT_EYE_INDICES),
        left_iris_landmarks=subset(LEFT_IRIS_INDICES),
        right_iris_landmarks=subset(RIGHT_IRIS_INDICES),
        confidence=face.confidence,
    )
