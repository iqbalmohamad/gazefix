"""NAL framing and the avcC record the MP4 sample entry needs."""

from __future__ import annotations

import pytest

from streamexp import h264

SPS = bytes([0x67, 0x64, 0x00, 0x1F, 0xAC, 0xD9])
PPS = bytes([0x68, 0xEB, 0xE3, 0xCB])
IDR = bytes([0x65, 0x88, 0x84, 0x00])
SLICE = bytes([0x41, 0x9A, 0x02, 0x00])


def annexb(*nals: bytes, four_byte: bool = True) -> bytes:
    prefix = b"\x00\x00\x00\x01" if four_byte else b"\x00\x00\x01"
    return b"".join(prefix + nal for nal in nals)


def test_three_and_four_byte_start_codes_are_both_recognised():
    stream = b"\x00\x00\x00\x01" + SPS + b"\x00\x00\x01" + PPS
    assert [nal for _type, nal in h264.iter_nal_units(stream)] == [SPS, PPS]


def test_nal_types_come_from_the_header_byte():
    stream = annexb(SPS, PPS, IDR)
    assert [nal_type for nal_type, _ in h264.iter_nal_units(stream)] == [7, 8, 5]


def test_a_nal_containing_a_start_code_pattern_is_framed_by_position():
    """NAL payloads recur; framing must use offsets, not a byte search."""
    tricky = bytes([0x41, 0x00, 0x00, 0x02, 0x41])
    stream = annexb(tricky, SLICE)
    assert [nal for _type, nal in h264.iter_nal_units(stream)] == [tricky, SLICE]


def test_an_empty_stream_yields_nothing():
    assert list(h264.iter_nal_units(b"")) == []
    assert list(h264.iter_nal_units(b"\x00\x00\x00\x01")) == []


def test_parameter_sets_are_picked_out_of_a_packet():
    nals = list(h264.iter_nal_units(annexb(SPS, PPS, IDR)))
    assert h264.parameter_sets(nals) == (SPS, PPS)


def test_a_packet_without_parameter_sets_reports_none():
    nals = list(h264.iter_nal_units(annexb(SLICE)))
    assert h264.parameter_sets(nals) == (None, None)


def test_access_unit_is_stored_length_prefixed():
    unit = h264.AccessUnit([SPS, PPS, IDR], is_idr=True)
    sample = unit.to_avcc()
    assert sample[:4] == len(SPS).to_bytes(4, "big")
    assert sample[4 : 4 + len(SPS)] == SPS
    assert len(sample) == sum(4 + len(nal) for nal in (SPS, PPS, IDR))


def test_avcc_record_carries_the_profile_bytes_from_the_sps():
    record = h264.avcc_record(SPS, PPS)
    assert record[0] == 1                       # configurationVersion
    assert record[1:4] == SPS[1:4]              # profile, compatibility, level
    assert record[4] & 0x03 == 3                # four-byte NAL lengths
    assert record[5] & 0x1F == 1                # exactly one SPS
    assert SPS in record and PPS in record


def test_a_truncated_sps_cannot_produce_an_avcc_record():
    with pytest.raises(ValueError):
        h264.avcc_record(bytes([0x67, 0x64]), PPS)
