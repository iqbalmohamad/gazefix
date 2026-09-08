"""Build a fragmented MP4 one frame at a time, in-process.

Why not just let ffmpeg do it. It can, and the harness offers that path — but
measured on this hardware ffmpeg's MP4 muxer holds each encoded frame for about
two frame intervals (~73 ms at 30 FPS) before the bytes reach the pipe, because
it waits for the following packet. Against the PRD's ``<100 ms`` end-to-end
budget that would leave almost nothing to attribute to the network and the NIM,
and a Stage C result would say more about the harness than about Maxine.

Writing the container here removes that wait: an access unit becomes a
``moof``/``mdat`` pair the instant the encoder emits it.

The layout is the one NVIDIA's streaming mode requires — ``ftyp``, then a
``moov`` carrying ``mvex`` and empty sample tables, then one fragment per
frame — so ``moov`` precedes all media and the file satisfies exactly the
condition NVIDIA's own ``check_streamable`` tests. Whether the NIM's demuxer
accepts a *progressively delivered* fragmented MP4 is the Stage B question and
is not assumed here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .h264 import AccessUnit, avcc_record

BRAND = b"iso5"
TRACK_ID = 1


def box(box_type: bytes, *payload: bytes) -> bytes:
    body = b"".join(payload)
    return struct.pack(">I", 8 + len(body)) + box_type + body


def full_box(box_type: bytes, version: int, flags: int, *payload: bytes) -> bytes:
    return box(box_type, bytes([version]) + flags.to_bytes(3, "big"), *payload)


@dataclass
class FragmentedMp4Writer:
    """Serialise access units into a progressively readable fragmented MP4."""

    width: int
    height: int
    timescale: int
    """Media timescale. Using the frame rate keeps every duration an integer."""
    sps: bytes
    pps: bytes
    sequence: int = field(default=0, init=False)
    decode_time: int = field(default=0, init=False)
    frames_written: int = field(default=0, init=False)

    def initialization_segment(self) -> bytes:
        """``ftyp`` + ``moov``. Available before a single frame is encoded."""
        ftyp = box(b"ftyp", BRAND, struct.pack(">I", 512), BRAND, b"iso6", b"mp41", b"avc1")
        return ftyp + self._moov()

    def fragment(self, unit: AccessUnit, duration: int = 1) -> bytes:
        """One ``moof``/``mdat`` pair carrying exactly one coded picture."""
        payload = unit.to_avcc()
        self.sequence += 1
        moof = self._moof(len(payload), duration, unit.is_idr)
        self.decode_time += duration
        self.frames_written += 1
        return moof + box(b"mdat", payload)

    # -- moov ------------------------------------------------------------

    def _moov(self) -> bytes:
        mvhd = full_box(
            b"mvhd", 0, 0,
            struct.pack(">IIII", 0, 0, self.timescale, 0),  # times, timescale, duration 0
            struct.pack(">i", 0x00010000),                  # rate 1.0
            struct.pack(">h", 0x0100),                      # volume 1.0
            b"\x00" * 10,
            _UNITY_MATRIX,
            b"\x00" * 24,
            struct.pack(">I", TRACK_ID + 1),                # next_track_ID
        )
        tkhd = full_box(
            b"tkhd", 0, 0x000007,                           # enabled | in movie | in preview
            struct.pack(">IIIII", 0, 0, TRACK_ID, 0, 0),    # times, id, reserved, duration 0
            b"\x00" * 8,
            struct.pack(">hhhh", 0, 0, 0, 0),               # layer, alt group, volume, reserved
            _UNITY_MATRIX,
            struct.pack(">II", self.width << 16, self.height << 16),
        )
        mdhd = full_box(
            b"mdhd", 0, 0,
            struct.pack(">IIII", 0, 0, self.timescale, 0),
            struct.pack(">HH", 0x55C4, 0),                  # language "und"
        )
        hdlr = full_box(
            b"hdlr", 0, 0,
            struct.pack(">I", 0), b"vide", b"\x00" * 12, b"GazeFix Phase 1B\x00",
        )
        vmhd = full_box(b"vmhd", 0, 1, struct.pack(">HHHH", 0, 0, 0, 0))
        dinf = box(b"dinf", full_box(b"dref", 0, 0, struct.pack(">I", 1),
                                     full_box(b"url ", 0, 1)))
        stbl = box(
            b"stbl",
            full_box(b"stsd", 0, 0, struct.pack(">I", 1), self._avc1()),
            full_box(b"stts", 0, 0, struct.pack(">I", 0)),
            full_box(b"stsc", 0, 0, struct.pack(">I", 0)),
            full_box(b"stsz", 0, 0, struct.pack(">II", 0, 0)),
            full_box(b"stco", 0, 0, struct.pack(">I", 0)),
        )
        minf = box(b"minf", vmhd, dinf, stbl)
        mdia = box(b"mdia", mdhd, hdlr, minf)
        trak = box(b"trak", tkhd, mdia)
        mvex = box(
            b"mvex",
            full_box(b"trex", 0, 0, struct.pack(">IIIII", TRACK_ID, 1, 0, 0, 0)),
        )
        return box(b"moov", mvhd, trak, mvex)

    def _avc1(self) -> bytes:
        return box(
            b"avc1",
            b"\x00" * 6,
            struct.pack(">H", 1),                            # data_reference_index
            struct.pack(">HH", 0, 0),                        # pre_defined, reserved
            b"\x00" * 12,
            struct.pack(">HH", self.width, self.height),
            struct.pack(">II", 0x00480000, 0x00480000),      # 72 dpi
            struct.pack(">I", 0),
            struct.pack(">H", 1),                            # frame_count
            b"\x00" * 32,                                    # compressor name
            struct.pack(">H", 0x0018),                       # depth
            struct.pack(">h", -1),
            box(b"avcC", avcc_record(self.sps, self.pps)),
        )

    # -- moof ------------------------------------------------------------

    def _moof(self, payload_size: int, duration: int, is_sync: bool) -> bytes:
        mfhd = full_box(b"mfhd", 0, 0, struct.pack(">I", self.sequence))
        # default-base-is-moof, so trun's data_offset is relative to the moof.
        tfhd = full_box(b"tfhd", 0, 0x020000, struct.pack(">I", TRACK_ID))
        tfdt = full_box(b"tfdt", 1, 0, struct.pack(">Q", self.decode_time))
        # data-offset | sample-duration | sample-size | sample-flags present
        flags = 0x000001 | 0x000100 | 0x000200 | 0x000400
        sample_flags = 0x02000000 if is_sync else 0x01010000
        trun_size = 8 + 4 + 4 + 4 + 12  # header, version/flags, count, offset, one sample
        traf_size = 8 + len(tfhd) + len(tfdt) + trun_size
        moof_size = 8 + len(mfhd) + traf_size
        data_offset = moof_size + 8  # past the mdat header
        trun = full_box(
            b"trun", 0, flags,
            struct.pack(">I", 1),
            struct.pack(">i", data_offset),
            struct.pack(">III", duration, payload_size, sample_flags),
        )
        assert len(trun) == trun_size, "trun size assumption broke the data offset"
        traf = box(b"traf", tfhd, tfdt, trun)
        return box(b"moof", mfhd, traf)


_UNITY_MATRIX = struct.pack(
    ">9i", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000
)
