"""The container the live path builds must be the one the API expects."""

from __future__ import annotations

from streamexp import mp4
from streamexp.fmp4 import FragmentedMp4Writer
from streamexp.h264 import AccessUnit

SPS = bytes([0x67, 0x42, 0xC0, 0x1E, 0xAA, 0xBB])
PPS = bytes([0x68, 0xCE, 0x3C, 0x80])


def writer() -> FragmentedMp4Writer:
    return FragmentedMp4Writer(width=1280, height=720, timescale=30, sps=SPS, pps=PPS)


def test_initialisation_segment_is_moov_first_and_fragmented():
    """This is the exact property NVIDIA's streaming mode checks for."""
    layout = mp4.inspect_layout(writer().initialization_segment())
    assert layout.atoms == ("ftyp", "moov")
    assert layout.moov_first
    assert layout.fragmented, "mvex must be present or the file is not fragmented"
    assert mp4.is_streamable(writer().initialization_segment())


def test_initialisation_segment_carries_no_media():
    """A live client must be able to send the header before it has a frame."""
    segment = writer().initialization_segment()
    assert not any(atom.type in ("mdat", "moof") for atom in mp4.iter_atoms(segment))
    index = mp4.index_video_track(segment)
    assert index.samples == []
    assert (index.width, index.height, index.timescale) == (1280, 720, 30)


def test_each_fragment_describes_exactly_one_frame_at_the_right_offset():
    write = writer()
    stream = bytearray(write.initialization_segment())
    payloads = [b"\x01" * 90, b"\x02" * 110, b"\x03" * 70]

    for position, payload in enumerate(payloads):
        unit = AccessUnit([payload], is_idr=(position == 0))
        stream.extend(write.fragment(unit, duration=1))

    data = bytes(stream)
    moofs = [atom for atom in mp4.iter_atoms(data) if atom.type == "moof"]
    assert len(moofs) == len(payloads)

    for position, moof in enumerate(moofs):
        fragment = mp4.parse_fragment(data, moof, timescale=30, first_index=position)
        assert len(fragment.samples) == 1
        sample = fragment.samples[0]
        # to_avcc prefixes each NAL with a four-byte length.
        assert sample.size == len(payloads[position]) + 4
        assert data[sample.offset + 4 : sample.end] == payloads[position]
        assert sample.pts_ticks == position


def test_decode_times_advance_by_the_declared_duration():
    write = writer()
    write.initialization_segment()
    for _ in range(4):
        write.fragment(AccessUnit([b"\x00" * 16], is_idr=False), duration=2)
    assert write.decode_time == 8
    assert write.frames_written == 4
    assert write.sequence == 4


def test_the_whole_live_stream_reads_back_as_fragmented():
    write = writer()
    stream = bytearray(write.initialization_segment())
    for position in range(5):
        stream.extend(write.fragment(AccessUnit([b"\x07" * 40], position == 0), 1))
    layout = mp4.inspect_layout(bytes(stream))
    assert layout.moov_first and layout.fragmented
    assert layout.atoms[:4] == ("ftyp", "moov", "moof", "mdat")
