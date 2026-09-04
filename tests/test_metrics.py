import pytest

from gazefix.diagnostics.metrics import FrameRateMeter, PipelineMetrics


def test_frame_rate_uses_observed_event_intervals() -> None:
    meter = FrameRateMeter(window_seconds=2.0)
    meter.record(10.0)
    meter.record(10.5)
    meter.record(11.0)

    assert meter.rate(11.0) == pytest.approx(2.0)


def test_metrics_snapshot_keeps_counts_and_replacements() -> None:
    metrics = PipelineMetrics()
    metrics.record_capture()
    metrics.record_display()
    metrics.record_processing(2.5)
    metrics.record_read_failure()

    snapshot = metrics.snapshot(capture_replacements=3, output_replacements=4)
    assert snapshot.captured_frames == 1
    assert snapshot.displayed_frames == 1
    assert snapshot.processing_ms == pytest.approx(2.5)
    assert snapshot.read_failures == 1
    assert snapshot.capture_replacements == 3
    assert snapshot.output_replacements == 4



@pytest.mark.parametrize(
    ("status", "field"),
    [
        ("tracked", "tracked_frames"),
        ("low_quality", "low_quality_frames"),
        ("no_face", "no_face_frames"),
        ("timeout", "tracking_timeouts"),
        ("error", "tracking_errors"),
        ("unavailable", "tracking_errors"),
        ("initializing", None),
    ],
)
def test_tracking_outcomes_increment_exactly_one_counter(status: str, field: str | None) -> None:
    metrics = PipelineMetrics()
    metrics.record_tracking(status, None, None)
    snapshot = metrics.snapshot()
    counters = {
        name: getattr(snapshot, name)
        for name in ("tracked_frames", "low_quality_frames", "no_face_frames", "tracking_timeouts", "tracking_errors")
    }
    assert sum(counters.values()) == (0 if field is None else 1)
    if field is not None:
        assert counters[field] == 1


def test_tracking_durations_are_smoothed_only_when_measured() -> None:
    metrics = PipelineMetrics()
    metrics.record_tracking("timeout", None, None)
    metrics.record_tracking("tracked", 0.0, 0.0)  # zero is "not a measurement"
    assert metrics.snapshot().tracking_inference_ms == 0.0
    metrics.record_tracking("tracked", 10.0, 12.0)
    metrics.record_tracking("tracked", 20.0, 22.0)
    snapshot = metrics.snapshot()
    assert snapshot.tracking_inference_ms == pytest.approx(0.2 * 20.0 + 0.8 * 10.0)
    assert snapshot.tracking_total_ms == pytest.approx(0.2 * 22.0 + 0.8 * 12.0)
    metrics.record_tracking_replaced()
    metrics.record_pipeline_latency(30.0)
    snapshot = metrics.snapshot()
    assert snapshot.tracking_replaced == 1 and snapshot.pipeline_latency_ms == pytest.approx(30.0)
