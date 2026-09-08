"""End-to-end behaviour of the instrument, against the mock.

Nothing here says anything about Maxine. These tests pin the four harness
behaviours every Phase 1B number rests on: one open RPC, paced input, responses
read while still sending, and honest detection of a service that needs the whole
input before it will emit.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import build_progressive_mp4

from streamexp import mockserver, source
from streamexp.clock import RealtimeSchedule
from streamexp.session import RedirectGazeSession, SendUnit


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    # 30 frames at timescale 30: one second of media.
    path = tmp_path / "clip.mp4"
    path.write_bytes(build_progressive_mp4([900] * 30))
    return path


def run_against(interfaces, mode: str, clip: Path, tmp_path: Path, **mock_options):
    import grpc

    server, port = mockserver.serve(
        interfaces, mockserver.MockConfig(mode=mode, **mock_options)
    )
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            _profile, index = source.probe(clip)
            session = RedirectGazeSession(
                interfaces,
                interfaces.stub(channel),
                output_path=tmp_path / f"{mode}.mp4",
            )
            return session.run(
                source.paced_units(clip, index, 4096), RealtimeSchedule()
            )
    finally:
        server.stop(0).wait()


def test_a_progressive_service_yields_usable_output_before_eos(interfaces, clip, tmp_path):
    result = run_against(interfaces, "streaming", clip, tmp_path)
    assert result.error is None
    assert result.output_before_eos() == "YES"
    assert result.first_usable_frame_at < result.input_eos_at
    assert len(result.frames) == 30


def test_a_batching_service_is_detected_not_waited_out(interfaces, clip, tmp_path):
    """The Stage A kill condition must be produced by measurement, not by timeout."""
    result = run_against(interfaces, "transactional", clip, tmp_path)
    assert result.error is None
    assert result.output_before_eos() == "NO"
    assert result.first_usable_frame_at >= result.input_eos_at
    assert len(result.frames) == 30


def test_the_input_is_paced_by_media_timestamps(interfaces, clip, tmp_path):
    """One second of media must take about one second to feed."""
    result = run_against(interfaces, "streaming", clip, tmp_path)
    eos = result.timeline.elapsed("input_eos")
    assert 0.7 <= eos <= 1.8, f"one second of media fed in {eos:.3f} s"


def test_responses_are_read_while_input_is_still_being_sent(interfaces, clip, tmp_path):
    result = run_against(interfaces, "streaming", clip, tmp_path)
    first_output = result.timeline.elapsed("first_output_bytes")
    eos = result.timeline.elapsed("input_eos")
    assert first_output < eos / 2, "output arrived only after sending finished"


def test_the_config_message_is_sent_first_and_echoed(interfaces, clip, tmp_path):
    result = run_against(interfaces, "streaming", clip, tmp_path)
    assert result.config_echoed
    names = [event.name for event in result.timeline.events]
    assert names.index("config_sent") < names.index("config_echo")


def test_frame_ages_are_measured_against_when_the_frame_was_fed(interfaces, clip, tmp_path):
    result = run_against(interfaces, "streaming", clip, tmp_path)
    ages = [record.age_s for record in result.frames if record.age_s is not None]
    assert len(ages) == 30
    assert all(age >= 0 for age in ages)
    assert max(ages) < 0.5, "a zero-work mock should not add half a second"


def test_the_corrected_output_is_written_where_the_result_says(interfaces, clip, tmp_path):
    result = run_against(interfaces, "streaming", clip, tmp_path)
    assert result.output_path.is_file()
    assert result.output_path.stat().st_size == result.bytes_received
    assert result.first_usable_byte_end <= result.bytes_received


def test_the_harness_retains_a_bounded_amount_regardless_of_stream_length(
    interfaces, clip, tmp_path
):
    result = run_against(interfaces, "streaming", clip, tmp_path)
    assert result.max_reader_buffer_bytes <= 1 << 20
    assert result.bytes_received > 20 * 1024


def test_backlog_is_sampled_over_the_run(interfaces, clip, tmp_path):
    result = run_against(interfaces, "streaming", clip, tmp_path)
    assert result.backlog_samples
    for sample in result.backlog_samples:
        assert sample["bytes_received"] <= sample["bytes_sent"]


def test_a_failed_transport_is_reported_as_a_result_not_an_exception(interfaces, tmp_path):
    import grpc

    with grpc.insecure_channel("127.0.0.1:1") as channel:
        session = RedirectGazeSession(interfaces, interfaces.stub(channel))
        result = session.run(
            [SendUnit(payload=b"\x00" * 16, media_time=0.0)], RealtimeSchedule()
        )
    assert result.error is not None
    assert result.output_before_eos() in ("NO", "NOT MEASURED")
    assert not result.frames


def test_a_source_that_raises_mid_stream_surfaces_the_sender_error(interfaces, tmp_path):
    def failing_units():
        yield SendUnit(payload=b"\x00" * 32, media_time=0.0)
        raise RuntimeError("capture device disappeared")

    server, port = mockserver.serve(interfaces, mockserver.MockConfig(mode="streaming"))
    import grpc

    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            session = RedirectGazeSession(interfaces, interfaces.stub(channel))
            result = session.run(failing_units(), RealtimeSchedule())
    finally:
        server.stop(0).wait()

    assert result.error is not None
    assert "capture device disappeared" in result.error


def test_server_work_shows_up_as_frame_age(interfaces, clip, tmp_path):
    """A slow service must raise the measured age, not vanish into throughput."""
    quick = run_against(interfaces, "streaming", clip, tmp_path)
    slow = run_against(
        interfaces, "streaming", clip, tmp_path, first_output_delay_ms=250.0
    )
    assert slow.timeline.elapsed("first_output_bytes") > quick.timeline.elapsed(
        "first_output_bytes"
    ) + 0.2
    assert max(r.age_s for r in slow.frames) > max(r.age_s for r in quick.frames)


def test_keepalives_are_counted_and_never_mistaken_for_media(interfaces, tmp_path):
    """The response oneof includes a keepalive that carries no video at all."""
    server, port = mockserver.serve(interfaces, mockserver.MockConfig(mode="streaming"))
    import grpc

    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            session = RedirectGazeSession(interfaces, interfaces.stub(channel))
            result = session.run(
                [SendUnit(payload=b"\x00" * 8, media_time=None)], RealtimeSchedule()
            )
    finally:
        server.stop(0).wait()
    assert result.keepalives == 0
    assert result.bytes_received == 8
    assert not result.frames, "eight arbitrary bytes are not a decodable frame"


def test_units_with_no_media_time_are_sent_without_waiting(interfaces, tmp_path):
    server, port = mockserver.serve(interfaces, mockserver.MockConfig(mode="streaming"))
    import grpc

    units = [SendUnit(payload=b"\x00" * 64, media_time=None) for _ in range(20)]
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            session = RedirectGazeSession(interfaces, interfaces.stub(channel))
            started = time.perf_counter()
            result = session.run(units, RealtimeSchedule())
    finally:
        server.stop(0).wait()
    assert time.perf_counter() - started < 2.0
    assert result.units_sent == 20
