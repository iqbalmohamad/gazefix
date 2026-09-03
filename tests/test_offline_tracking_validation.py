from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np
import pytest

from gazefix.tracking.metrics import TrackingMetricsSnapshot
from gazefix.tracking.models import (
    NormalizedLandmark,
    ReliabilityStatus,
    TrackedFace,
    TrackingReliability,
    TrackingResult,
    TrackingState,
)
from gazefix.tracking.offline_validation import (
    OfflineInputKind,
    OfflineValidationError,
    _percentile,
    run_offline_validation,
)


class FakeTracker:
    def __init__(self, states_and_latencies: Sequence[tuple[TrackingState, float]]) -> None:
        self._responses = list(states_and_latencies)
        self.initialize_calls = 0
        self.shutdown_calls = 0
        self.frames: list[np.ndarray] = []

    def initialize(self) -> None:
        self.initialize_calls += 1

    def track(
        self,
        frame: np.ndarray,
        *,
        frame_sequence: int | None = None,
        timestamp_ns: int | None = None,
    ) -> TrackingResult:
        self.frames.append(frame)
        state, latency = self._responses.pop(0)
        face = _face() if state in {TrackingState.TRACKED, TrackingState.LOW_CONFIDENCE} else None
        reliability_status = (
            ReliabilityStatus.LOW_CONFIDENCE
            if state is TrackingState.LOW_CONFIDENCE
            else (
                ReliabilityStatus.ACCEPTED
                if face is not None
                else ReliabilityStatus.UNAVAILABLE
            )
        )
        return TrackingResult(
            state=state,
            frame_sequence=frame_sequence or 0,
            timestamp_ns=timestamp_ns or 0,
            frame_width=frame.shape[1],
            frame_height=frame.shape[0],
            faces=(face,) if face is not None else (),
            primary_face_index=0 if face is not None else None,
            reliability=TrackingReliability(status=reliability_status),
            processing_time_ms=latency,
        )

    def metrics_snapshot(self) -> TrackingMetricsSnapshot:
        raise AssertionError("The file harness does not depend on provider metrics")

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _face() -> TrackedFace:
    points = (
        NormalizedLandmark(0, 0.2, 0.2, 0.0),
        NormalizedLandmark(1, 0.8, 0.8, 0.0),
    )
    return TrackedFace(source_index=0, landmarks=points)


def test_image_harness_writes_detached_overlay_and_preserves_input(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "portrait.png"
    overlay_path = tmp_path / "output" / "overlay.png"
    source = np.full((48, 64, 3), (20, 40, 60), dtype=np.uint8)
    assert cv2.imwrite(str(input_path), source)
    original_bytes = input_path.read_bytes()
    tracker = FakeTracker([(TrackingState.TRACKED, 3.5)])

    report = run_offline_validation(
        input_path,
        tracker,
        overlay_output_path=overlay_path,
    )

    assert report.input_kind == "image"
    assert report.total_frames_processed == 1
    assert report.frames_with_face == 1
    assert report.frames_with_no_face == 0
    assert report.mean_tracking_latency_ms == pytest.approx(3.5)
    assert report.effective_processing_throughput_frames_per_second is None
    assert input_path.read_bytes() == original_bytes
    assert overlay_path.is_file()
    assert tracker.initialize_calls == 1
    assert tracker.shutdown_calls == 1


def test_video_harness_reports_loss_recovery_latency_and_throughput(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "sequence.avi"
    writer = cv2.VideoWriter(
        str(input_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        20.0,
        (32, 24),
    )
    assert writer.isOpened()
    try:
        for value in (20, 40, 60, 80):
            writer.write(np.full((24, 32, 3), value, dtype=np.uint8))
    finally:
        writer.release()

    tracker = FakeTracker(
        [
            (TrackingState.TRACKED, 1.0),
            (TrackingState.TEMPORARILY_LOST, 2.0),
            (TrackingState.TEMPORARILY_LOST, 3.0),
            (TrackingState.TRACKED, 4.0),
        ]
    )

    report = run_offline_validation(
        input_path,
        tracker,
        input_kind=OfflineInputKind.VIDEO,
    )

    assert report.total_frames_processed == 4
    assert report.frames_with_face == 2
    assert report.frames_with_no_face == 2
    assert report.temporary_tracking_loss_frames == 2
    assert report.temporary_tracking_loss_events == 1
    assert report.tracking_recovery_events == 1
    assert report.mean_tracking_latency_ms == pytest.approx(2.5)
    assert report.median_tracking_latency_ms == pytest.approx(2.5)
    assert report.p95_tracking_latency_ms == pytest.approx(3.85)
    assert report.effective_processing_throughput_frames_per_second is not None
    assert report.effective_processing_throughput_frames_per_second > 0
    assert report.source_video_frame_rate == pytest.approx(20.0)
    assert tracker.shutdown_calls == 1


def test_harness_releases_tracker_when_decode_fails(tmp_path: Path) -> None:
    input_path = tmp_path / "broken.jpg"
    input_path.write_bytes(b"not an image")
    tracker = FakeTracker([])

    with pytest.raises(OfflineValidationError, match="Could not decode image"):
        run_offline_validation(
            input_path,
            tracker,
            input_kind=OfflineInputKind.IMAGE,
        )

    assert tracker.initialize_calls == 1
    assert tracker.shutdown_calls == 1


def test_harness_refuses_to_overwrite_source(tmp_path: Path) -> None:
    input_path = tmp_path / "portrait.png"
    assert cv2.imwrite(str(input_path), np.zeros((4, 4, 3), dtype=np.uint8))
    tracker = FakeTracker([(TrackingState.NO_FACE, 1.0)])

    with pytest.raises(OfflineValidationError, match="must not overwrite"):
        run_offline_validation(
            input_path,
            tracker,
            overlay_output_path=input_path,
        )

    assert tracker.initialize_calls == 0
    assert tracker.shutdown_calls == 0


def test_percentile_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="At least one"):
        _percentile([], 0.95)
    with pytest.raises(ValueError, match="between"):
        _percentile([1.0], 1.1)
