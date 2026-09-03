from dataclasses import FrozenInstanceError

import pytest

from gazefix.tracking.models import (
    CoordinateSpace,
    FaceBounds,
    NormalizedLandmark,
    ReliabilityStatus,
    TrackedFace,
    TrackingReliability,
    TrackingResult,
    TrackingState,
)
from gazefix.tracking.selection import select_primary_face


def landmark(index: int, x: float, y: float, z: float = 0.0) -> NormalizedLandmark:
    return NormalizedLandmark(index=index, x=x, y=y, z=z)


def face(
    source_index: int,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> TrackedFace:
    return TrackedFace(
        source_index=source_index,
        landmarks=(
            landmark(0, left, top),
            landmark(1, right, top),
            landmark(2, right, bottom),
            landmark(3, left, bottom),
        ),
    )


def test_normalized_landmark_coordinate_conversion_is_explicit_and_clipped() -> None:
    point = NormalizedLandmark(index=7, x=0.5, y=1.2, z=-0.1)

    assert point.to_pixel(101, 51) == (50, 50)
    assert point.to_pixel(101, 51, clip=False) == (50, 60)
    assert CoordinateSpace.NORMALIZED_IMAGE.value == "normalized_image"


def test_tracking_domain_values_are_immutable_and_validate_probabilities() -> None:
    point = landmark(0, 0.2, 0.3)
    with pytest.raises(FrozenInstanceError):
        point.x = 0.4  # type: ignore[misc]
    with pytest.raises(ValueError, match="confidence"):
        TrackingReliability(ReliabilityStatus.ACCEPTED, confidence=1.1)


def test_no_face_result_contains_no_fabricated_landmarks() -> None:
    result = TrackingResult(
        state=TrackingState.NO_FACE,
        frame_sequence=3,
        timestamp_ns=10,
        frame_width=640,
        frame_height=480,
        faces=(),
        primary_face_index=None,
        reliability=TrackingReliability(ReliabilityStatus.UNAVAILABLE),
        processing_time_ms=0.1,
    )

    assert not result.face_detected
    assert result.face_landmarks == ()
    assert result.left_eye_landmarks == ()
    assert result.right_eye_landmarks == ()
    assert result.left_iris_landmarks == ()
    assert result.right_iris_landmarks == ()


def test_face_bounds_allow_predictions_outside_the_image() -> None:
    bounds = FaceBounds.from_landmarks(
        (landmark(0, -0.1, 0.2), landmark(1, 1.1, 0.8))
    )

    assert bounds.left == pytest.approx(-0.1)
    assert bounds.right == pytest.approx(1.1)
    assert bounds.area == pytest.approx(0.72)


def test_primary_face_selection_prefers_area_then_center_independent_of_order() -> None:
    small_centered = face(0, 0.3, 0.3, 0.7, 0.7)
    large_offset = face(1, 0.0, 0.0, 0.8, 0.8)
    same_size_far = face(2, 0.0, 0.0, 0.4, 0.4)
    same_size_center = face(3, 0.3, 0.3, 0.7, 0.7)

    assert select_primary_face((small_centered, large_offset)) == 1
    assert select_primary_face((large_offset, small_centered)) == 0
    assert select_primary_face((same_size_far, same_size_center)) == 1


def test_primary_face_selection_uses_source_index_for_exact_geometric_ties() -> None:
    later_source = face(9, 0.2, 0.2, 0.8, 0.8)
    earlier_source = face(2, 0.2, 0.2, 0.8, 0.8)

    selected = select_primary_face((later_source, earlier_source))

    assert selected == 1


def test_tracking_result_rejects_invalid_primary_face_index() -> None:
    with pytest.raises(ValueError, match="Primary face index"):
        TrackingResult(
            state=TrackingState.TRACKED,
            frame_sequence=1,
            timestamp_ns=1,
            frame_width=10,
            frame_height=10,
            faces=(face(0, 0.1, 0.1, 0.9, 0.9),),
            primary_face_index=2,
            reliability=TrackingReliability(ReliabilityStatus.ACCEPTED),
            processing_time_ms=1.0,
        )


def test_tracking_result_rejects_tracked_state_without_a_face() -> None:
    with pytest.raises(ValueError, match="must contain a face"):
        TrackingResult(
            state=TrackingState.TRACKED,
            frame_sequence=1,
            timestamp_ns=1,
            frame_width=10,
            frame_height=10,
            faces=(),
            primary_face_index=None,
            reliability=TrackingReliability(ReliabilityStatus.ACCEPTED),
            processing_time_ms=1.0,
        )
