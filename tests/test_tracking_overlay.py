import numpy as np
import pytest

from gazefix.tracking.models import (
    NormalizedLandmark,
    ReliabilityStatus,
    TrackedFace,
    TrackingReliability,
    TrackingResult,
    TrackingState,
)
from gazefix.tracking.overlay import DebugOverlayRenderer


def tracked_result() -> TrackingResult:
    face = TrackedFace(
        source_index=0,
        landmarks=(
            NormalizedLandmark(0, 0.2, 0.2, 0.0),
            NormalizedLandmark(1, 0.8, 0.8, 0.0),
        ),
        left_eye_landmarks=(
            NormalizedLandmark(2, 0.3, 0.4, 0.0),
            NormalizedLandmark(3, 0.4, 0.4, 0.0),
        ),
        right_eye_landmarks=(
            NormalizedLandmark(4, 0.6, 0.4, 0.0),
            NormalizedLandmark(5, 0.7, 0.4, 0.0),
        ),
        left_iris_landmarks=(NormalizedLandmark(473, 0.35, 0.4, 0.0),),
        right_iris_landmarks=(NormalizedLandmark(468, 0.65, 0.4, 0.0),),
    )
    return TrackingResult(
        state=TrackingState.TRACKED,
        frame_sequence=1,
        timestamp_ns=1,
        frame_width=100,
        frame_height=80,
        faces=(face,),
        primary_face_index=0,
        reliability=TrackingReliability(ReliabilityStatus.ACCEPTED),
        processing_time_ms=1.0,
    )


def test_overlay_returns_detached_render_without_mutating_source() -> None:
    source = np.zeros((80, 100, 3), dtype=np.uint8)
    original = source.copy()

    output = DebugOverlayRenderer().render(source, tracked_result())

    assert output is not source
    assert np.array_equal(source, original)
    assert np.count_nonzero(output) > 0


def test_overlay_handles_no_face_result_and_still_preserves_source() -> None:
    source = np.zeros((40, 120, 3), dtype=np.uint8)
    result = TrackingResult(
        state=TrackingState.NO_FACE,
        frame_sequence=2,
        timestamp_ns=2,
        frame_width=120,
        frame_height=40,
        faces=(),
        primary_face_index=None,
        reliability=TrackingReliability(ReliabilityStatus.UNAVAILABLE),
        processing_time_ms=0.1,
    )

    output = DebugOverlayRenderer().render(source, result)

    assert not np.shares_memory(output, source)
    assert np.count_nonzero(source) == 0
    assert np.count_nonzero(output) > 0


def test_overlay_rejects_result_for_a_different_frame_size() -> None:
    source = np.zeros((40, 40, 3), dtype=np.uint8)

    with pytest.raises(ValueError, match="dimensions"):
        DebugOverlayRenderer().render(source, tracked_result())
