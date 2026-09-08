"""Just enough H.264 bitstream handling to package frames as they are encoded.

The low-latency Stage B/C path takes an Annex-B elementary stream straight from
the encoder and muxes it in-process, because ffmpeg's own MP4 muxer holds each
frame back until it has seen the next one — measured at roughly two frame
intervals, which would consume most of the PRD's whole latency budget before
any byte reached the network.

Only two things are needed for that: split an encoded packet into its NAL units,
and build the ``avcC`` record the MP4 sample entry requires. No decoding, and no
SPS geometry parsing — the frame size is already fixed by the capture
configuration, so recovering it from the bitstream would add risk without adding
information.

Note what is *not* here: no incremental Annex-B framing. A picture's end cannot
be known from an Annex-B byte stream until the next picture starts, so framing a
live pipe would either add a frame of delay or guess. The live path instead takes
whole packets from the encoder, where the boundary is exact, and the harness
checks the frames it muxed against the frames it captured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

NAL_IDR = 5
NAL_SPS = 7
NAL_PPS = 8


def parameter_sets(nals: list[tuple[int, bytes]]) -> tuple[bytes | None, bytes | None]:
    """Pull the SPS and PPS out of a parsed packet, if it carries them."""
    sps = next((nal for nal_type, nal in nals if nal_type == NAL_SPS), None)
    pps = next((nal for nal_type, nal in nals if nal_type == NAL_PPS), None)
    return sps, pps


def find_start_codes(data: bytes) -> list[tuple[int, int]]:
    """Locate every Annex-B start code.

    Returns ``(payload_start, start_code_length)`` pairs, in order. Working in
    offsets rather than in extracted byte strings matters: a NAL's bytes can
    legitimately reoccur later in the stream, so searching for them by value
    would eventually mis-frame a picture.
    """
    positions: list[tuple[int, int]] = []
    length = len(data)
    i = 0
    while i + 3 <= length:
        if data[i] == 0 and data[i + 1] == 0:
            if data[i + 2] == 1:
                positions.append((i + 3, 3))
                i += 3
                continue
            if i + 4 <= length and data[i + 2] == 0 and data[i + 3] == 1:
                positions.append((i + 4, 4))
                i += 4
                continue
        i += 1
    return positions


def iter_nal_units(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield ``(nal_type, nal_bytes)`` for each complete NAL unit in ``data``.

    ``nal_bytes`` excludes the start code and keeps the NAL header byte. The
    last NAL is included, so this is for a byte range already known to be
    complete; the incremental case is :class:`AccessUnitAssembler`.
    """
    positions = find_start_codes(data)
    for index, (payload_start, _length) in enumerate(positions):
        if index + 1 < len(positions):
            next_start, next_length = positions[index + 1]
            end = next_start - next_length
        else:
            end = len(data)
        nal = data[payload_start:end]
        if nal:
            yield nal[0] & 0x1F, nal


@dataclass
class AccessUnit:
    """One coded picture, as the NAL units that make it up."""

    nals: list[bytes]
    is_idr: bool

    def to_avcc(self, length_size: int = 4) -> bytes:
        """Length-prefixed form, which is how MP4 stores samples."""
        out = bytearray()
        for nal in self.nals:
            out += len(nal).to_bytes(length_size, "big")
            out += nal
        return bytes(out)


def avcc_record(sps: bytes, pps: bytes, length_size: int = 4) -> bytes:
    """Build the ``AVCDecoderConfigurationRecord`` for an ``avc1`` sample entry."""
    if len(sps) < 4:
        raise ValueError("SPS too short to build an avcC record")
    out = bytearray()
    out.append(1)                      # configurationVersion
    out.append(sps[1])                 # AVCProfileIndication
    out.append(sps[2])                 # profile_compatibility
    out.append(sps[3])                 # AVCLevelIndication
    out.append(0xFC | (length_size - 1))
    out.append(0xE0 | 1)               # one SPS
    out += len(sps).to_bytes(2, "big")
    out += sps
    out.append(1)                      # one PPS
    out += len(pps).to_bytes(2, "big")
    out += pps
    return bytes(out)
