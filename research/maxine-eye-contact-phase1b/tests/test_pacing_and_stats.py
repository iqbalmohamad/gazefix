"""Realtime pacing, and the statistics that summarise a run without flattering it."""

from __future__ import annotations

import time

import pytest

from streamexp.clock import RealtimeSchedule
from streamexp.timing import (
    FrameRecord,
    Timeline,
    percentile,
    summarise_ages,
)


def test_waiting_holds_until_the_media_time_is_due():
    schedule = RealtimeSchedule()
    started = time.perf_counter()
    schedule.wait_until(0.25)
    assert time.perf_counter() - started >= 0.24


def test_a_media_time_already_past_does_not_wait():
    schedule = RealtimeSchedule(origin=time.perf_counter() - 5.0)
    started = time.perf_counter()
    schedule.wait_until(1.0)
    assert time.perf_counter() - started < 0.05


def test_lateness_is_recorded_rather_than_absorbed_silently():
    """A run that failed to keep cadence must be visible in the results."""
    schedule = RealtimeSchedule(origin=time.perf_counter() - 2.0)
    schedule.wait_until(1.0)
    stats = schedule.statistics()
    assert stats["late_units"] == 1
    assert stats["max_lateness_ms"] > 900


def test_a_schedule_that_kept_up_reports_no_lateness():
    schedule = RealtimeSchedule()
    schedule.wait_until(0.01)
    assert schedule.statistics() == {
        "late_units": 0, "max_lateness_ms": 0.0, "mean_lateness_ms": 0.0,
    }


def test_lead_time_shifts_every_deadline_earlier():
    schedule = RealtimeSchedule(origin=100.0, lead_seconds=0.2)
    assert schedule.deadline(1.0) == pytest.approx(100.8)
    assert schedule.deadline(0.1) == 100.0, "a deadline never precedes the origin"


def test_percentiles_of_an_empty_series_are_absent_not_zero():
    assert percentile([], 0.5) is None


def test_percentile_uses_nearest_rank():
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 0.50) == 20.0
    assert percentile(values, 0.95) == 40.0
    assert percentile([7.0], 0.99) == 7.0


def _records(ages_ms: list[float]) -> list[FrameRecord]:
    return [
        FrameRecord(index, index / 30, 0.0, age / 1000, 100 * (index + 1))
        for index, age in enumerate(ages_ms)
    ]


def test_unmeasurable_ages_are_reported_as_not_measured():
    summary = summarise_ages([FrameRecord(0, 0.0, None, 1.0, 10)])
    assert summary["frames_with_age"] == 0
    assert summary["p50_frame_age_ms"] == "NOT MEASURED"
    assert summary["age_growth_ms_per_frame"] == "NOT MEASURED"


def test_a_steady_stream_reports_a_flat_age_trend():
    summary = summarise_ages(_records([40.0, 41.0, 39.0, 40.0, 40.5, 39.5]))
    assert summary["frames_with_age"] == 6
    assert abs(summary["age_growth_ms_per_frame"]) < 0.5


def test_growing_latency_shows_as_a_positive_slope():
    """Kill condition 4 — latency growing with stream duration — must be visible."""
    summary = summarise_ages(_records([40.0 + 5 * index for index in range(10)]))
    assert summary["age_growth_ms_per_frame"] == pytest.approx(5.0, abs=0.01)
    assert summary["max_frame_age_ms"] == 85.0


def test_a_batch_service_shows_as_a_negative_slope():
    """When output only starts at EOS, the oldest frame waited longest."""
    summary = summarise_ages(_records([1000.0 - 30 * index for index in range(20)]))
    assert summary["age_growth_ms_per_frame"] < -25


def test_timeline_reports_intervals_from_the_rpc_start():
    timeline = Timeline()
    timeline.mark("first_output_bytes")
    assert timeline.elapsed("first_output_bytes") >= 0
    assert timeline.elapsed("never_happened") is None


def test_timeline_keeps_the_first_occurrence_of_a_repeated_event():
    timeline = Timeline()
    first = timeline.mark("keepalive", index=1)
    timeline.mark("keepalive", index=2)
    assert timeline.first("keepalive") is first
    assert len(timeline.events) == 2
