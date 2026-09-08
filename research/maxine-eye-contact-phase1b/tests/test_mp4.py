"""The container indexing every latency number depends on."""

from __future__ import annotations

import struct

import pytest
from conftest import TIMESCALE, build_progressive_mp4

from streamexp import mp4


def test_top_level_walk_lists_boxes_in_order():
    data = build_progressive_mp4([100, 120, 140])
    assert [atom.type for atom in mp4.iter_atoms(data)] == ["ftyp", "moov", "mdat"]


def test_walk_stops_at_a_truncated_trailing_header():
    """A growing prefix must not raise; the reader feeds partial buffers."""
    data = build_progressive_mp4([100, 120])
    atoms = list(mp4.iter_atoms(data[: len(data) - 4]))
    assert [atom.type for atom in atoms] == ["ftyp", "moov", "mdat"]
    assert list(mp4.iter_atoms(data[:6])) == []


def test_sixty_four_bit_box_size_is_honoured():
    body = b"payload"
    large = struct.pack(">I", 1) + b"mdat" + struct.pack(">Q", 16 + len(body)) + body
    atom = next(mp4.iter_atoms(large))
    assert (atom.type, atom.header_size, atom.size) == ("mdat", 16, 16 + len(body))


def test_a_box_smaller_than_its_header_is_rejected():
    with pytest.raises(mp4.Mp4Error):
        list(mp4.iter_atoms(struct.pack(">I", 4) + b"moov"))


def test_layout_distinguishes_streamable_from_transactional():
    streamable = mp4.inspect_layout(build_progressive_mp4([64, 64]))
    assert streamable.moov_first and not streamable.fragmented and streamable.complete

    transactional = mp4.inspect_layout(build_progressive_mp4([64, 64], moov_first=False))
    assert not transactional.moov_first
    assert transactional.atoms == ("ftyp", "mdat", "moov")


def test_is_streamable_matches_nvidias_rule():
    """NVIDIA's client accepts streaming mode when moov follows ftyp directly."""
    assert mp4.is_streamable(build_progressive_mp4([64]))
    assert not mp4.is_streamable(build_progressive_mp4([64], moov_first=False))


def test_sample_table_gives_byte_ranges_and_presentation_times():
    sizes = [300, 250, 275, 310]
    data = build_progressive_mp4(sizes)
    index = mp4.index_video_track(data)

    assert index.timescale == TIMESCALE
    assert [s.size for s in index.samples] == sizes
    assert [s.pts_ticks for s in index.samples] == [0, 1, 2, 3]
    assert index.nominal_fps() == pytest.approx(TIMESCALE)

    # Samples are contiguous, and the first begins inside the mdat payload.
    for earlier, later in zip(index.samples, index.samples[1:]):
        assert later.offset == earlier.end
    mdat = next(a for a in mp4.iter_atoms(data) if a.type == "mdat")
    assert index.samples[0].offset == mdat.body_offset
    assert index.samples[-1].end == len(data)


def test_sample_bytes_are_where_the_index_says_they_are():
    sizes = [50, 60, 70]
    data = build_progressive_mp4(sizes)
    for sample in mp4.index_video_track(data).samples:
        chunk = data[sample.offset : sample.end]
        assert chunk == bytes([(sample.index + 1) % 256]) * sample.size


def test_variable_frame_rate_refuses_to_report_a_single_fps():
    """The NIM rejects VFR, so an averaged number would hide a real problem."""
    index = mp4.VideoTrackIndex(
        timescale=30,
        samples=[
            mp4.Sample(0, 0, 10, 0, 30),
            mp4.Sample(1, 10, 10, 1, 30),
            mp4.Sample(2, 20, 10, 5, 30),
        ],
    )
    assert index.nominal_fps() is None


def test_a_file_without_a_video_track_is_an_error():
    with pytest.raises(mp4.Mp4Error):
        mp4.index_video_track(b"".join([struct.pack(">I", 8), b"ftyp"]))
