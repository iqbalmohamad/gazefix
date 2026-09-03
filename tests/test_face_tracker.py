from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from gazefix.tracking.interfaces import FaceTracker
from gazefix.tracking.mediapipe_tracker import (
    LEFT_EYE_INDICES,
    LEFT_IRIS_INDICES,
    RIGHT_EYE_INDICES,
    RIGHT_IRIS_INDICES,
    MediaPipeFaceTracker,
    MediaPipeTrackerConfig,
    TrackerInitializationError,
    _BackendFace,
)
from gazefix.tracking.models import NormalizedLandmark, TrackingState


class FakeBackend:
    def __init__(self) -> None:
        self.initialize_calls = 0
        self.detect_calls = 0
        self.close_calls = 0
        self.responses: list[Sequence[_BackendFace] | Exception] = []
        self.received_frames: list[np.ndarray] = []
        self.received_timestamps: list[int] = []

    def initialize(self) -> None:
        self.initialize_calls += 1

    def detect(
        self, rgb_frame: np.ndarray, timestamp_ms: int
    ) -> Sequence[_BackendFace]:
        self.detect_calls += 1
        self.received_frames.append(rgb_frame)
        self.received_timestamps.append(timestamp_ms)
        response = self.responses.pop(0) if self.responses else ()
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        self.close_calls += 1


def make_landmarks(
    count: int = 478,
    *,
    left: float = 0.2,
    top: float = 0.2,
    right: float = 0.8,
    bottom: float = 0.8,
) -> tuple[NormalizedLandmark, ...]:
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    points = [
        NormalizedLandmark(index=i, x=center_x, y=center_y, z=-i / 1000)
        for i in range(count)
    ]
    if count >= 4:
        points[0] = NormalizedLandmark(index=0, x=left, y=top, z=0.0)
        points[1] = NormalizedLandmark(index=1, x=right, y=top, z=0.0)
        points[2] = NormalizedLandmark(index=2, x=right, y=bottom, z=0.0)
        points[3] = NormalizedLandmark(index=3, x=left, y=bottom, z=0.0)
    return tuple(points)


def make_tracker(
    backend: FakeBackend, **overrides: object
) -> MediaPipeFaceTracker:
    config_values: dict[str, object] = {
        "model_path": Path("unused-by-fake.task"),
        "temporary_loss_frames": 2,
    }
    config_values.update(overrides)
    return MediaPipeFaceTracker(
        MediaPipeTrackerConfig(**config_values),  # type: ignore[arg-type]
        backend_factory=lambda _config: backend,
    )


def test_tracker_satisfies_protocol_and_has_idempotent_lifecycle() -> None:
    backend = FakeBackend()
    tracker = make_tracker(backend)

    assert isinstance(tracker, FaceTracker)
    before_initialization = tracker.track(np.zeros((2, 2, 3), dtype=np.uint8))
    assert before_initialization.state is TrackingState.NOT_INITIALIZED

    tracker.initialize()
    tracker.initialize()
    tracker.shutdown()
    tracker.shutdown()

    assert backend.initialize_calls == 1
    assert backend.close_calls == 1
    after_shutdown = tracker.track(np.zeros((2, 2, 3), dtype=np.uint8))
    assert after_shutdown.state is TrackingState.SHUTDOWN
    with pytest.raises(TrackerInitializationError, match="shut down"):
        tracker.initialize()


def test_tracker_extracts_eye_and_iris_landmarks_without_provider_objects() -> None:
    backend = FakeBackend()
    backend.responses.append((_BackendFace(make_landmarks()),))
    tracker = make_tracker(backend)
    tracker.initialize()

    result = tracker.track(
        np.zeros((48, 64, 3), dtype=np.uint8),
        frame_sequence=8,
        timestamp_ns=2_000_000,
    )

    assert result.state is TrackingState.TRACKED
    assert result.frame_sequence == 8
    assert result.frame_width == 64
    assert result.frame_height == 48
    assert len(result.face_landmarks) == 478
    assert tuple(point.index for point in result.left_eye_landmarks) == LEFT_EYE_INDICES
    assert tuple(point.index for point in result.right_eye_landmarks) == RIGHT_EYE_INDICES
    assert tuple(point.index for point in result.left_iris_landmarks) == LEFT_IRIS_INDICES
    assert tuple(point.index for point in result.right_iris_landmarks) == RIGHT_IRIS_INDICES
    assert result.reliability.confidence is None


def test_tracker_omits_iris_subset_when_backend_does_not_support_it() -> None:
    backend = FakeBackend()
    backend.responses.append((_BackendFace(make_landmarks(468)),))
    tracker = make_tracker(backend)
    tracker.initialize()

    result = tracker.track(np.zeros((8, 8, 3), dtype=np.uint8))

    assert result.face_detected
    assert result.left_iris_landmarks == ()
    assert result.right_iris_landmarks == ()


def test_tracker_represents_initial_no_face_and_temporary_loss() -> None:
    backend = FakeBackend()
    backend.responses.extend(
        [
            (),
            (_BackendFace(make_landmarks()),),
            (),
            (),
            (),
        ]
    )
    tracker = make_tracker(backend)
    tracker.initialize()
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    assert tracker.track(frame).state is TrackingState.NO_FACE
    assert tracker.track(frame).state is TrackingState.TRACKED
    assert tracker.track(frame).state is TrackingState.TEMPORARILY_LOST
    assert tracker.track(frame).state is TrackingState.TEMPORARILY_LOST
    expired = tracker.track(frame)
    assert expired.state is TrackingState.NO_FACE
    assert not expired.face_detected
    assert expired.face_landmarks == ()


@pytest.mark.parametrize(
    "invalid_frame",
    [
        None,
        np.zeros((0, 2, 3), dtype=np.uint8),
        np.zeros((2, 2), dtype=np.uint8),
        np.zeros((2, 2, 4), dtype=np.uint8),
        np.zeros((2, 2, 3), dtype=np.float32),
    ],
)
def test_invalid_frames_are_reported_without_calling_backend(
    invalid_frame: object,
) -> None:
    backend = FakeBackend()
    tracker = make_tracker(backend)
    tracker.initialize()

    result = tracker.track(invalid_frame)  # type: ignore[arg-type]

    assert result.state is TrackingState.INVALID_FRAME
    assert result.error
    assert backend.detect_calls == 0


@pytest.mark.parametrize(
    ("metadata", "expected_error"),
    [
        ({"frame_sequence": -1}, "Frame sequence"),
        ({"frame_sequence": 1.5}, "Frame sequence"),
        ({"timestamp_ns": -1}, "Frame timestamp"),
        ({"timestamp_ns": "now"}, "Frame timestamp"),
    ],
)
def test_invalid_frame_metadata_is_reported_without_calling_backend(
    metadata: dict[str, object], expected_error: str
) -> None:
    backend = FakeBackend()
    tracker = make_tracker(backend)
    tracker.initialize()

    result = tracker.track(
        np.zeros((2, 2, 3), dtype=np.uint8), **metadata  # type: ignore[arg-type]
    )

    assert result.state is TrackingState.INVALID_FRAME
    assert expected_error in (result.error or "")
    assert backend.detect_calls == 0


def test_tracker_exception_is_metadata_not_video_pipeline_failure() -> None:
    backend = FakeBackend()
    backend.responses.append(RuntimeError("synthetic inference failure"))
    tracker = make_tracker(backend)
    tracker.initialize()

    result = tracker.track(np.zeros((2, 2, 3), dtype=np.uint8))

    assert result.state is TrackingState.TRACKER_ERROR
    assert "synthetic inference failure" in (result.error or "")
    assert not result.face_detected
    assert tracker.metrics_snapshot().tracker_errors == 1


def test_tracker_uses_private_rgb_copy_and_monotonic_backend_timestamps() -> None:
    class MutatingBackend(FakeBackend):
        def detect(
            self, rgb_frame: np.ndarray, timestamp_ms: int
        ) -> Sequence[_BackendFace]:
            rgb_frame[0, 0] = (1, 2, 3)
            return super().detect(rgb_frame, timestamp_ms)

    backend = MutatingBackend()
    backend.responses.extend([(), ()])
    tracker = make_tracker(backend)
    tracker.initialize()
    frame = np.full((2, 2, 3), (10, 20, 30), dtype=np.uint8)
    original = frame.copy()

    tracker.track(frame, timestamp_ns=5_000_000)
    tracker.track(frame, timestamp_ns=4_000_000)

    assert np.array_equal(frame, original)
    assert tuple(backend.received_frames[0][1, 1]) == (30, 20, 10)
    assert backend.received_timestamps == [5, 6]


def test_low_confidence_is_explicit_and_landmarks_are_not_fabricated() -> None:
    backend = FakeBackend()
    backend.responses.append((_BackendFace(make_landmarks(), confidence=0.4),))
    tracker = make_tracker(backend, low_confidence_threshold=0.6)
    tracker.initialize()

    result = tracker.track(np.zeros((8, 8, 3), dtype=np.uint8))

    assert result.state is TrackingState.LOW_CONFIDENCE
    assert result.reliability.confidence == pytest.approx(0.4)
    assert len(result.face_landmarks) == 478
    snapshot = tracker.metrics_snapshot()
    assert snapshot.tracked_frames == 1
    assert snapshot.low_confidence_frames == 1
    assert snapshot.detected_faces == 1


def test_primary_face_selection_is_applied_to_backend_results() -> None:
    backend = FakeBackend()
    backend.responses.append(
        (
            _BackendFace(make_landmarks(left=0.4, top=0.4, right=0.6, bottom=0.6)),
            _BackendFace(make_landmarks(left=0.1, top=0.1, right=0.9, bottom=0.9)),
        )
    )
    tracker = make_tracker(backend)
    tracker.initialize()

    result = tracker.track(np.zeros((8, 8, 3), dtype=np.uint8))

    assert len(result.faces) == 2
    assert result.primary_face is not None
    assert result.primary_face.source_index == 1


def test_real_backend_fails_cleanly_when_model_file_is_missing(tmp_path: Path) -> None:
    tracker = MediaPipeFaceTracker(
        MediaPipeTrackerConfig(model_path=tmp_path / "missing.task")
    )

    with pytest.raises(TrackerInitializationError, match="model not found"):
        tracker.initialize()
