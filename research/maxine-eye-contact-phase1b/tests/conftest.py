"""Shared fixtures and MP4 builders for the Phase 1B harness tests.

The builders here construct containers byte by byte so the tests can assert on
exact byte ranges and need neither ffmpeg nor a network. Where a test genuinely
needs a real encoder or a real gRPC stack, it skips rather than pretending.
"""

from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from streamexp.fmp4 import box, full_box  # noqa: E402

TIMESCALE = 30


def _stbl(sizes: list[int], chunk_offset: int, width: int, height: int) -> bytes:
    stsd = full_box(
        b"stsd", 0, 0, struct.pack(">I", 1),
        box(
            b"avc1",
            b"\x00" * 6, struct.pack(">H", 1), struct.pack(">HH", 0, 0), b"\x00" * 12,
            struct.pack(">HH", width, height),
            struct.pack(">II", 0x00480000, 0x00480000), struct.pack(">I", 0),
            struct.pack(">H", 1), b"\x00" * 32, struct.pack(">H", 0x0018),
            struct.pack(">h", -1),
        ),
    )
    stts = full_box(b"stts", 0, 0, struct.pack(">I", 1), struct.pack(">II", len(sizes), 1))
    stsc = full_box(b"stsc", 0, 0, struct.pack(">I", 1), struct.pack(">III", 1, len(sizes), 1))
    stsz = full_box(
        b"stsz", 0, 0, struct.pack(">II", 0, len(sizes)),
        b"".join(struct.pack(">I", size) for size in sizes),
    )
    stco = full_box(b"stco", 0, 0, struct.pack(">I", 1), struct.pack(">I", chunk_offset))
    return box(b"stbl", stsd, stts, stsc, stsz, stco)


def build_progressive_mp4(sizes: list[int], width: int = 64, height: int = 48,
                          moov_first: bool = True) -> bytes:
    """A non-fragmented MP4 with a real sample table over synthetic media bytes.

    The media is filler: these tests are about locating samples in a byte
    stream, never about decoding them.
    """
    ftyp = box(b"ftyp", b"isom", struct.pack(">I", 512), b"isom", b"avc1")
    media = b"".join(bytes([(index + 1) % 256]) * size for index, size in enumerate(sizes))

    def assemble(chunk_offset: int) -> bytes:
        mvhd = full_box(
            b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, TIMESCALE, len(sizes)),
            struct.pack(">i", 0x00010000), struct.pack(">h", 0x0100), b"\x00" * 10,
            struct.pack(">9i", 65536, 0, 0, 0, 65536, 0, 0, 0, 1 << 30),
            b"\x00" * 24, struct.pack(">I", 2),
        )
        tkhd = full_box(
            b"tkhd", 0, 7, struct.pack(">IIIII", 0, 0, 1, 0, len(sizes)), b"\x00" * 8,
            struct.pack(">hhhh", 0, 0, 0, 0),
            struct.pack(">9i", 65536, 0, 0, 0, 65536, 0, 0, 0, 1 << 30),
            struct.pack(">II", width << 16, height << 16),
        )
        mdhd = full_box(b"mdhd", 0, 0, struct.pack(">IIII", 0, 0, TIMESCALE, len(sizes)),
                        struct.pack(">HH", 0x55C4, 0))
        hdlr = full_box(b"hdlr", 0, 0, struct.pack(">I", 0), b"vide", b"\x00" * 12, b"t\x00")
        minf = box(b"minf", full_box(b"vmhd", 0, 1, struct.pack(">HHHH", 0, 0, 0, 0)),
                   _stbl(sizes, chunk_offset, width, height))
        mdia = box(b"mdia", mdhd, hdlr, minf)
        return box(b"moov", mvhd, box(b"trak", tkhd, mdia))

    if moov_first:
        # The chunk offset depends on the moov's own size, so build it once to
        # learn that size and again with the offset it implies.
        provisional = assemble(0)
        offset = len(ftyp) + len(provisional) + 8
        moov = assemble(offset)
        assert len(moov) == len(provisional), "moov size changed with the chunk offset"
        return ftyp + moov + box(b"mdat", media)

    offset = len(ftyp) + 8
    return ftyp + box(b"mdat", media) + assemble(offset)


def sample_offsets(sizes: list[int], moov_first: bool = True) -> list[int]:
    """End offsets of each sample in :func:`build_progressive_mp4`'s output."""
    data = build_progressive_mp4(sizes, moov_first=moov_first)
    from streamexp import mp4  # noqa: PLC0415

    return [sample.end for sample in mp4.index_video_track(data).samples]


@pytest.fixture(scope="session")
def nvidia_clone() -> Path:
    """A clone of NVIDIA's nim-clients, or a skip when it is not present."""
    candidates = [
        PACKAGE_ROOT.parents[1] / "experiments" / "maxine-phase1b" / "nvidia-client",
        PACKAGE_ROOT / "nvidia-client",
    ]
    for candidate in candidates:
        if (candidate / "eye-contact" / "protos").is_dir():
            return candidate
    pytest.skip("NVIDIA nim-clients clone not present; see RUNBOOK.md")


@pytest.fixture(scope="session")
def interfaces(nvidia_clone: Path):
    pytest.importorskip("grpc")
    from streamexp import proto  # noqa: PLC0415

    return proto.load(nvidia_clone)


@pytest.fixture(scope="session")
def ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if binary is None:
        pytest.skip("ffmpeg is not on PATH")
    return binary


@pytest.fixture(scope="session")
def real_clip(ffmpeg: str, tmp_path_factory) -> Path:
    """A genuinely encoded H.264 faststart MP4.

    The hand-built fixtures above carry an ``avc1`` sample entry but no real
    bitstream, so a decoder rejects them outright — which is now correctly
    reported as AMBIGUOUS rather than as zero frames. Tests about what a decoder
    *sees* therefore need real media.
    """
    import subprocess

    path = tmp_path_factory.mktemp("media") / "real.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=128x96:rate=30", "-t", "1",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-g", "30", "-movflags", "+faststart", str(path)],
        check=True, capture_output=True, timeout=180,
    )
    return path


@pytest.fixture(scope="session")
def metadata_only_prefix(real_clip: Path, tmp_path_factory) -> Path:
    """The head of a real clip: ftyp and moov, but no media payload.

    This is the shape of the 1367 bytes the first real Stage A run held when it
    finished sending — a container a decoder can describe but not decode a
    single frame from.
    """
    data = real_clip.read_bytes()
    cut = data.find(b"mdat")
    assert cut > 0, "the fixture clip has no mdat box"
    path = tmp_path_factory.mktemp("media") / "prefix.mp4"
    path.write_bytes(data[: cut + 4])
    return path
