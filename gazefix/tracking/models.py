"""Provider-neutral tracking-domain values and explicit coordinate semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class CoordinateSpace(str, Enum):
    """Coordinate system used by every landmark in a tracking result."""

    NORMALIZED_IMAGE = "normalized_image"


class TrackingState(str, Enum):
    TRACKED = "tracked"
    LOW_CONFIDENCE = "low_confidence"
    NO_FACE = "no_face"
    TEMPORARILY_LOST = "temporarily_lost"
    INVALID_FRAME = "invalid_frame"
    TRACKER_ERROR = "tracker_error"
    NOT_INITIALIZED = "not_initialized"
    SHUTDOWN = "shutdown"


class ReliabilityStatus(str, Enum):
    """Whether a backend accepted a result, rejected it, or exposed no score."""

    ACCEPTED = "accepted"
    LOW_CONFIDENCE = "low_confidence"
    UNAVAILABLE = "unavailable"


def _validate_probability(name: str, value: float | None) -> None:
    if value is not None and (not math.isfinite(value) or not 0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be finite and between 0 and 1")


@dataclass(frozen=True, slots=True)
class NormalizedLandmark:
    """A provider-neutral landmark in normalized image coordinates.

    ``x`` and ``y`` are normalized by image width and height. They are allowed
    outside ``[0, 1]`` because inference can legitimately predict beyond a frame
    edge. ``z`` is provider-relative depth, normalized approximately to image
    width; it is not a metric distance and must not be interpreted as gaze.
    """

    index: int
    x: float
    y: float
    z: float
    visibility: float | None = None
    presence: float | None = None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("Landmark index cannot be negative")
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError("Landmark coordinates must be finite")
        _validate_probability("visibility", self.visibility)
        _validate_probability("presence", self.presence)

    def to_pixel(self, width: int, height: int, *, clip: bool = True) -> tuple[int, int]:
        """Convert normalized x/y to a pixel index for a known frame size."""

        if width <= 0 or height <= 0:
            raise ValueError("Frame dimensions must be positive")
        x = round(self.x * (width - 1))
        y = round(self.y * (height - 1))
        if clip:
            x = min(max(x, 0), width - 1)
            y = min(max(y, 0), height - 1)
        return x, y


@dataclass(frozen=True, slots=True)
class FaceBounds:
    """Axis-aligned bounds expressed in normalized image coordinates."""

    left: float
    top: float
    right: float
    bottom: float

    @classmethod
    def from_landmarks(cls, landmarks: tuple[NormalizedLandmark, ...]) -> "FaceBounds":
        if not landmarks:
            raise ValueError("At least one landmark is required")
        return cls(
            left=min(point.x for point in landmarks),
            top=min(point.y for point in landmarks),
            right=max(point.x for point in landmarks),
            bottom=max(point.y for point in landmarks),
        )

    @property
    def area(self) -> float:
        return max(0.0, self.right - self.left) * max(0.0, self.bottom - self.top)

    @property
    def center(self) -> tuple[float, float]:
        return (self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0


@dataclass(frozen=True, slots=True)
class TrackedFace:
    """One detected face and application-owned facial feature subsets."""

    source_index: int
    landmarks: tuple[NormalizedLandmark, ...]
    left_eye_landmarks: tuple[NormalizedLandmark, ...] = ()
    right_eye_landmarks: tuple[NormalizedLandmark, ...] = ()
    left_iris_landmarks: tuple[NormalizedLandmark, ...] = ()
    right_iris_landmarks: tuple[NormalizedLandmark, ...] = ()
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.source_index < 0:
            raise ValueError("Face source index cannot be negative")
        if not self.landmarks:
            raise ValueError("A tracked face must contain landmarks")
        _validate_probability("confidence", self.confidence)

    @property
    def bounds(self) -> FaceBounds:
        return FaceBounds.from_landmarks(self.landmarks)


@dataclass(frozen=True, slots=True)
class TrackingReliability:
    """Backend confidence data without inventing unavailable scores."""

    status: ReliabilityStatus
    confidence: float | None = None
    detection_confidence: float | None = None
    presence_confidence: float | None = None
    tracking_confidence: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_probability("confidence", self.confidence)
        _validate_probability("detection_confidence", self.detection_confidence)
        _validate_probability("presence_confidence", self.presence_confidence)
        _validate_probability("tracking_confidence", self.tracking_confidence)


@dataclass(frozen=True, slots=True)
class TrackingResult:
    """Tracking metadata for a single source frame.

    The source image is deliberately absent: consumers retain their own frame,
    and debug rendering is a separate opt-in operation.
    """

    state: TrackingState
    frame_sequence: int
    timestamp_ns: int
    frame_width: int | None
    frame_height: int | None
    faces: tuple[TrackedFace, ...]
    primary_face_index: int | None
    reliability: TrackingReliability
    processing_time_ms: float
    error: str | None = None
    coordinate_space: CoordinateSpace = CoordinateSpace.NORMALIZED_IMAGE

    def __post_init__(self) -> None:
        if self.frame_sequence < 0 or self.timestamp_ns < 0:
            raise ValueError("Frame sequence and timestamp cannot be negative")
        if (self.frame_width is None) != (self.frame_height is None):
            raise ValueError("Frame width and height must both be present or absent")
        if self.frame_width is not None and (
            self.frame_width <= 0 or self.frame_height is None or self.frame_height <= 0
        ):
            raise ValueError("Frame dimensions must be positive")
        if not math.isfinite(self.processing_time_ms) or self.processing_time_ms < 0:
            raise ValueError("Processing time must be finite and non-negative")
        if self.faces:
            if self.primary_face_index is None:
                raise ValueError("A result with faces must select a primary face")
            if not 0 <= self.primary_face_index < len(self.faces):
                raise ValueError("Primary face index is out of range")
        elif self.primary_face_index is not None:
            raise ValueError("A result without faces cannot select a primary face")
        face_states = {TrackingState.TRACKED, TrackingState.LOW_CONFIDENCE}
        if self.state in face_states and not self.faces:
            raise ValueError(f"{self.state.value} result must contain a face")
        if self.state not in face_states and self.faces:
            raise ValueError(f"{self.state.value} result cannot contain faces")
        if (
            self.state is TrackingState.LOW_CONFIDENCE
            and self.reliability.status is not ReliabilityStatus.LOW_CONFIDENCE
        ):
            raise ValueError("Low-confidence state requires low-confidence reliability")

    @property
    def face_detected(self) -> bool:
        return self.primary_face is not None

    @property
    def primary_face(self) -> TrackedFace | None:
        if self.primary_face_index is None:
            return None
        return self.faces[self.primary_face_index]

    @property
    def face_landmarks(self) -> tuple[NormalizedLandmark, ...]:
        return self.primary_face.landmarks if self.primary_face else ()

    @property
    def left_eye_landmarks(self) -> tuple[NormalizedLandmark, ...]:
        return self.primary_face.left_eye_landmarks if self.primary_face else ()

    @property
    def right_eye_landmarks(self) -> tuple[NormalizedLandmark, ...]:
        return self.primary_face.right_eye_landmarks if self.primary_face else ()

    @property
    def left_iris_landmarks(self) -> tuple[NormalizedLandmark, ...]:
        return self.primary_face.left_iris_landmarks if self.primary_face else ()

    @property
    def right_iris_landmarks(self) -> tuple[NormalizedLandmark, ...]:
        return self.primary_face.right_iris_landmarks if self.primary_face else ()
