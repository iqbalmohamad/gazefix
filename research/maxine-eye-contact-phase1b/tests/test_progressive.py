"""The reader that decides when a corrected frame became usable."""

from __future__ import annotations

from conftest import build_progressive_mp4

from streamexp.fmp4 import FragmentedMp4Writer
from streamexp.h264 import AccessUnit
from streamexp.progressive import Layout, ProgressiveMp4Reader

SPS = bytes([0x67, 0x42, 0xC0, 0x1E, 0xAA, 0xBB])
PPS = bytes([0x68, 0xCE, 0x3C, 0x80])


def feed_in_chunks(reader: ProgressiveMp4Reader, data: bytes, size: int,
                   clock_start: float = 0.0, step: float = 1.0):
    """Feed ``data`` in fixed-size pieces, one clock tick apart."""
    events = []
    at = clock_start
    for offset in range(0, len(data), size):
        events.extend(reader.feed(data[offset : offset + size], at))
        at += step
    events.extend(reader.close(at))
    return events


def test_a_frame_becomes_usable_on_the_chunk_that_completes_its_last_byte():
    sizes = [200, 200, 200]
    data = build_progressive_mp4(sizes)
    reader = ProgressiveMp4Reader()
    events = feed_in_chunks(reader, data, size=64)

    assert reader.layout is Layout.PROGRESSIVE
    assert [event.index for event in events] == [0, 1, 2]
    for event in events:
        # The chunk carrying the final byte is the one that made it usable.
        assert event.byte_end <= 64 * (int(event.at) + 1)
        assert event.byte_end > 64 * int(event.at)


def test_nothing_is_reported_usable_before_its_bytes_arrive():
    data = build_progressive_mp4([500, 500])
    reader = ProgressiveMp4Reader()
    first_half = reader.feed(data[: len(data) // 2], 0.0)
    assert first_half == [] or all(e.byte_end <= len(data) // 2 for e in first_half)
    assert reader.received == len(data) // 2


def test_presentation_times_survive_the_stream():
    data = build_progressive_mp4([120, 120, 120, 120])
    events = feed_in_chunks(ProgressiveMp4Reader(), data, size=97)
    assert [round(event.pts_seconds, 4) for event in events] == [
        round(index / 30, 4) for index in range(4)
    ]


def test_a_moov_last_stream_is_reported_not_indexable_rather_than_waited_out():
    """This is the Stage A kill signal and it must be detected, not endured."""
    data = build_progressive_mp4([300, 300], moov_first=False)
    reader = ProgressiveMp4Reader()
    events = feed_in_chunks(reader, data, size=64)
    assert reader.layout is Layout.MOOV_LAST
    assert events == []


def test_retention_stays_bounded_across_a_long_progressive_stream():
    """The harness must not be the thing that builds an unbounded queue."""
    data = build_progressive_mp4([256] * 400)
    reader = ProgressiveMp4Reader()
    peak = 0
    for offset in range(0, len(data), 512):
        reader.feed(data[offset : offset + 512], offset / 512)
        peak = max(peak, reader.buffered_bytes)
    assert reader.frames and len(reader.frames) == 400
    assert peak <= 4096, f"retained {peak} bytes while indexing {len(data)}"


def _fragmented_stream(count: int, payload_size: int = 128) -> bytes:
    writer = FragmentedMp4Writer(width=320, height=240, timescale=30, sps=SPS, pps=PPS)
    stream = bytearray(writer.initialization_segment())
    for position in range(count):
        stream.extend(
            writer.fragment(AccessUnit([bytes([position % 256]) * payload_size],
                                       is_idr=position == 0), 1)
        )
    return bytes(stream)


def test_fragments_are_indexed_as_they_arrive():
    data = _fragmented_stream(6)
    reader = ProgressiveMp4Reader()
    events = feed_in_chunks(reader, data, size=53)
    assert reader.layout is Layout.FRAGMENTED
    assert [event.index for event in events] == list(range(6))
    assert [round(e.pts_seconds, 4) for e in events] == [round(i / 30, 4) for i in range(6)]


def test_fragment_retention_stays_bounded():
    data = _fragmented_stream(300, payload_size = 2048)
    reader = ProgressiveMp4Reader()
    peak = 0
    for offset in range(0, len(data), 1024):
        reader.feed(data[offset : offset + 1024], offset)
        peak = max(peak, reader.buffered_bytes)
    assert len(reader.frames) == 300
    assert peak <= 8192, f"retained {peak} bytes while indexing {len(data)}"


def test_a_single_chunk_carrying_several_frames_reports_all_of_them():
    """One 64 KiB write can finish more than one 720p frame."""
    data = _fragmented_stream(4, payload_size=32)
    reader = ProgressiveMp4Reader()
    events = reader.feed(data, 7.5)
    assert [event.index for event in events] == [0, 1, 2, 3]
    assert all(event.at == 7.5 for event in events)


def test_first_byte_and_header_instants_are_recorded():
    data = _fragmented_stream(2)
    reader = ProgressiveMp4Reader()
    reader.feed(data[:8], 1.0)
    reader.feed(data[8:], 2.0)
    assert reader.first_byte_at == 1.0
    assert reader.header_complete_at == 2.0
