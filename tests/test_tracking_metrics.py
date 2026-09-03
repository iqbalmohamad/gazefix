from gazefix.tracking.metrics import TrackingMetrics
from gazefix.tracking.models import (
    ReliabilityStatus,
    TrackingReliability,
    TrackingResult,
    TrackingState,
)


def result(state: TrackingState, duration: float) -> TrackingResult:
    return TrackingResult(
        state=state,
        frame_sequence=1,
        timestamp_ns=1,
        frame_width=10,
        frame_height=10,
        faces=(),
        primary_face_index=None,
        reliability=TrackingReliability(ReliabilityStatus.UNAVAILABLE),
        processing_time_ms=duration,
    )


def test_tracking_metrics_count_failure_states_and_latency() -> None:
    metrics = TrackingMetrics()
    metrics.record(result(TrackingState.NO_FACE, 2.0))
    metrics.record(result(TrackingState.TEMPORARILY_LOST, 4.0))
    metrics.record(result(TrackingState.INVALID_FRAME, 6.0))
    metrics.record(result(TrackingState.TRACKER_ERROR, 8.0))

    snapshot = metrics.snapshot()
    assert snapshot.frames_seen == 4
    assert snapshot.no_face_frames == 1
    assert snapshot.temporary_losses == 1
    assert snapshot.invalid_frames == 1
    assert snapshot.tracker_errors == 1
    assert snapshot.average_processing_ms == 4.096
    assert snapshot.last_state is TrackingState.TRACKER_ERROR
