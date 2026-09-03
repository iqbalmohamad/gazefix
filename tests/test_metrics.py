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

