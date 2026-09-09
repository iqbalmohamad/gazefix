"""Minimal ISO-BMFF (MP4) reading, sufficient to time frames on the wire.

Why this exists. The Maxine Eye Contact ``RedirectGaze`` RPC does not carry
frames; it carries **MP4 container bytes** (``RedirectGazeRequest.video_file_data``
and ``RedirectGazeResponse.video_file_data``). To answer a *per-frame* latency
question about a *byte* stream, the harness has to know which byte ranges hold
which frame, and at what presentation time. That is what this module recovers,
from the container itself, without decoding pixels.

Two layouts matter:

``moov``-first, non-fragmented ("faststart"/streamable)
    The sample table arrives before the media. Every sample's absolute file
    offset, size and presentation time are known up front, so a sample is
    fully received the moment the received byte count passes its end offset.

``moov``-first, fragmented (``mvex`` present; ``moof``/``mdat`` pairs)
    The sample table arrives per fragment. Sizes and durations come from each
    ``trun``; the fragment's base decode time comes from ``tfdt``.

``moov``-last ("transactional")
    Nothing is indexable until the whole file has arrived. Detecting this case
    is itself a load-bearing result, so it is reported rather than worked
    around.

Scope limits, stated rather than hidden: only the first video track is indexed,
edit lists (``elst``) are ignored, and presentation time is
``decode time + ctts offset``. For the constant-frame-rate, single-track H.264
material this experiment uses, those simplifications do not move a timestamp.
Variable frame rate is out of scope because the NIM does not support it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterator, Sequence

class Mp4Error(Exception):
    """Raised when a byte range is not the MP4 structure it claims to be."""


@dataclass(frozen=True)
class Atom:
    """One ISO-BMFF box header and its position in the enclosing byte range."""

    type: str
    offset: int
    """Absolute offset of the box header."""
    header_size: int
    size: int
    """Total box size including the header."""

    @property
    def body_offset(self) -> int:
        return self.offset + self.header_size

    @property
    def end(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class Sample:
    """One coded video sample (one frame) located in the container."""

    index: int
    offset: int
    size: int
    pts_ticks: int
    timescale: int

    @property
    def end(self) -> int:
        return self.offset + self.size

    @property
    def pts_seconds(self) -> float:
        return self.pts_ticks / self.timescale


@dataclass
class VideoTrackIndex:
    """A complete, byte-addressable index of the first video track."""

    timescale: int
    samples: list[Sample] = field(default_factory=list)
    width: int = 0
    height: int = 0
    codec: str = ""
    """Sample-entry 4CC, e.g. ``avc1``/``avc3`` for H.264, ``hvc1``/``hev1`` for HEVC."""
    durations: list[int] = field(default_factory=list)
    """Per-sample decode durations from ``stts``, in timescale ticks."""

    def frame_count(self) -> int:
        return len(self.samples)

    def nominal_fps(self) -> float | None:
        """Frames per second implied by the sample durations, or ``None``.

        Returned only when the presentation times are evenly spaced, because a
        single averaged number would otherwise hide the variable-frame-rate
        case the NIM refuses.
        """
        if len(self.samples) < 2:
            return None
        if self.durations:
            # Decode durations, not composition-time differences. A file with
            # B-frames has non-monotonic PTS in decode order, so differencing
            # PTS would report ordinary constant-rate material as variable and
            # trigger a spurious VFR warning about the one thing the NIM refuses.
            # The final sample's duration is allowed to differ; it routinely does.
            deltas = set(self.durations[:-1]) or {self.durations[-1]}
        else:
            deltas = {
                self.samples[i + 1].pts_ticks - self.samples[i].pts_ticks
                for i in range(len(self.samples) - 1)
            }
        if len(deltas) != 1:
            return None
        delta = deltas.pop()
        if delta <= 0:
            return None
        return self.timescale / delta


def iter_atoms(data: bytes, start: int = 0, end: int | None = None) -> Iterator[Atom]:
    """Walk the boxes in ``data[start:end]``.

    Stops cleanly at a truncated trailing header, so the same function works on
    a complete file and on a growing prefix.
    """
    limit = len(data) if end is None else min(end, len(data))
    offset = start
    while offset + 8 <= limit:
        size = struct.unpack_from(">I", data, offset)[0]
        atom_type = data[offset + 4 : offset + 8].decode("latin-1")
        header_size = 8
        if size == 1:
            if offset + 16 > limit:
                return
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header_size = 16
        elif size == 0:
            size = limit - offset
        if size < header_size:
            raise Mp4Error(f"box {atom_type!r} at {offset} declares size {size}")
        yield Atom(atom_type, offset, header_size, size)
        offset += size


def find_atom(data: bytes, atom_type: str, start: int = 0, end: int | None = None) -> Atom | None:
    for atom in iter_atoms(data, start, end):
        if atom.type == atom_type:
            return atom
    return None


@dataclass(frozen=True)
class TopLevelLayout:
    """What the first boxes of a file say about how it can be consumed."""

    atoms: tuple[str, ...]
    moov_first: bool
    """``ftyp`` is followed by ``moov`` — the NIM's ``--streaming`` precondition."""
    fragmented: bool
    """``moov`` contains ``mvex``: media arrives as ``moof``/``mdat`` fragments."""
    complete: bool
    """A ``moov`` box was found in the inspected prefix."""


def inspect_layout(prefix: bytes) -> TopLevelLayout:
    """Classify a file (or a growing prefix of one) without needing all of it."""
    names: list[str] = []
    moov: Atom | None = None
    for atom in iter_atoms(prefix):
        names.append(atom.type)
        if atom.type == "moov" and atom.end <= len(prefix):
            moov = atom
    moov_first = len(names) >= 2 and names[0] == "ftyp" and names[1] == "moov"
    fragmented = False
    if moov is not None:
        fragmented = find_atom(prefix, "mvex", moov.body_offset, moov.end) is not None
    return TopLevelLayout(tuple(names), moov_first, fragmented, moov is not None)


def is_streamable(prefix: bytes) -> bool:
    """Mirror NVIDIA's ``utils.check_streamable`` — ``moov`` directly after ``ftyp``.

    Reimplemented here only so the harness can classify a *growing* buffer,
    which NVIDIA's file-path version cannot do. The acceptance rule is the same
    one their client applies, deliberately.
    """
    return inspect_layout(prefix).moov_first


def _parse_full_box(data: bytes, atom: Atom) -> tuple[int, int, int]:
    """Return ``(version, flags, body_start)`` for a FullBox."""
    pos = atom.body_offset
    version = data[pos]
    flags = int.from_bytes(data[pos + 1 : pos + 4], "big")
    return version, flags, pos + 4


def _parse_stts(data: bytes, atom: Atom) -> list[int]:
    _, _, pos = _parse_full_box(data, atom)
    count = struct.unpack_from(">I", data, pos)[0]
    pos += 4
    deltas: list[int] = []
    for _ in range(count):
        sample_count, sample_delta = struct.unpack_from(">II", data, pos)
        pos += 8
        deltas.extend([sample_delta] * sample_count)
    return deltas


def _parse_ctts(data: bytes, atom: Atom) -> list[int]:
    version, _, pos = _parse_full_box(data, atom)
    count = struct.unpack_from(">I", data, pos)[0]
    pos += 4
    offsets: list[int] = []
    for _ in range(count):
        sample_count = struct.unpack_from(">I", data, pos)[0]
        if version == 1:
            offset = struct.unpack_from(">i", data, pos + 4)[0]
        else:
            offset = struct.unpack_from(">I", data, pos + 4)[0]
        pos += 8
        offsets.extend([offset] * sample_count)
    return offsets


def _parse_stsz(data: bytes, atom: Atom) -> list[int]:
    _, _, pos = _parse_full_box(data, atom)
    uniform_size, count = struct.unpack_from(">II", data, pos)
    pos += 8
    if uniform_size:
        return [uniform_size] * count
    return list(struct.unpack_from(f">{count}I", data, pos))


def _parse_stz2(data: bytes, atom: Atom) -> list[int]:
    _, _, pos = _parse_full_box(data, atom)
    field_size = data[pos + 3]
    count = struct.unpack_from(">I", data, pos + 4)[0]
    pos += 8
    if field_size == 16:
        return list(struct.unpack_from(f">{count}H", data, pos))
    if field_size == 8:
        return list(data[pos : pos + count])
    if field_size == 4:
        sizes: list[int] = []
        for i in range(count):
            byte = data[pos + i // 2]
            sizes.append(byte >> 4 if i % 2 == 0 else byte & 0x0F)
        return sizes
    raise Mp4Error(f"unsupported stz2 field size {field_size}")


def _parse_stsc(data: bytes, atom: Atom) -> list[tuple[int, int]]:
    """Return ``(first_chunk, samples_per_chunk)`` entries, 1-based chunks."""
    _, _, pos = _parse_full_box(data, atom)
    count = struct.unpack_from(">I", data, pos)[0]
    pos += 4
    entries: list[tuple[int, int]] = []
    for _ in range(count):
        first_chunk, samples_per_chunk, _desc = struct.unpack_from(">III", data, pos)
        pos += 12
        entries.append((first_chunk, samples_per_chunk))
    return entries


def _parse_chunk_offsets(data: bytes, stbl: Atom) -> list[int]:
    stco = find_atom(data, "stco", stbl.body_offset, stbl.end)
    if stco is not None:
        _, _, pos = _parse_full_box(data, stco)
        count = struct.unpack_from(">I", data, pos)[0]
        return list(struct.unpack_from(f">{count}I", data, pos + 4))
    co64 = find_atom(data, "co64", stbl.body_offset, stbl.end)
    if co64 is None:
        raise Mp4Error("sample table has neither stco nor co64")
    _, _, pos = _parse_full_box(data, co64)
    count = struct.unpack_from(">I", data, pos)[0]
    return list(struct.unpack_from(f">{count}Q", data, pos + 4))


def _sample_offsets(chunk_offsets: Sequence[int], stsc: Sequence[tuple[int, int]],
                    sizes: Sequence[int]) -> list[int]:
    """Expand the chunk/sample-to-chunk tables into one absolute offset per sample."""
    offsets: list[int] = []
    sample = 0
    total = len(sizes)
    for run_index, (first_chunk, per_chunk) in enumerate(stsc):
        last_chunk = (
            stsc[run_index + 1][0] - 1 if run_index + 1 < len(stsc) else len(chunk_offsets)
        )
        for chunk in range(first_chunk, last_chunk + 1):
            if chunk - 1 >= len(chunk_offsets):
                break
            position = chunk_offsets[chunk - 1]
            for _ in range(per_chunk):
                if sample >= total:
                    return offsets
                offsets.append(position)
                position += sizes[sample]
                sample += 1
    if len(offsets) != total:
        raise Mp4Error(f"located {len(offsets)} sample offsets for {total} samples")
    return offsets


def _visual_sample_entry(data: bytes, stbl: Atom) -> tuple[str, int, int]:
    """Return ``(codec_4cc, width, height)`` from the first sample description.

    The 4CC matters as much as the size: the NIM accepts H.264 only, and an
    HEVC clip can be faststart-remuxed so it passes every other check the
    harness makes.
    """
    stsd = find_atom(data, "stsd", stbl.body_offset, stbl.end)
    if stsd is None:
        return "", 0, 0
    _, _, pos = _parse_full_box(data, stsd)
    entry_count = struct.unpack_from(">I", data, pos)[0]
    if entry_count < 1:
        return "", 0, 0
    entry = pos + 4
    codec = data[entry + 4 : entry + 8].decode("latin-1")
    # VisualSampleEntry: 8 byte box header + 6 reserved + 2 index + 16 predefined
    # then 2-byte width and 2-byte height.
    width, height = struct.unpack_from(">HH", data, entry + 8 + 24)
    return codec, width, height


def index_video_track(data: bytes, moov: Atom | None = None) -> VideoTrackIndex:
    """Build a byte-addressable index of the first video track in ``data``.

    ``data`` must contain the whole ``moov``; the media itself need not have
    arrived. Raises :class:`Mp4Error` when there is no indexable video track.
    """
    if moov is None:
        moov = find_atom(data, "moov")
    if moov is None:
        raise Mp4Error("no moov box")

    for trak in [a for a in iter_atoms(data, moov.body_offset, moov.end) if a.type == "trak"]:
        mdia = find_atom(data, "mdia", trak.body_offset, trak.end)
        if mdia is None:
            continue
        hdlr = find_atom(data, "hdlr", mdia.body_offset, mdia.end)
        if hdlr is None:
            continue
        _, _, hdlr_pos = _parse_full_box(data, hdlr)
        if data[hdlr_pos + 4 : hdlr_pos + 8] != b"vide":
            continue

        mdhd = find_atom(data, "mdhd", mdia.body_offset, mdia.end)
        if mdhd is None:
            raise Mp4Error("video track has no mdhd")
        version, _, mdhd_pos = _parse_full_box(data, mdhd)
        timescale = struct.unpack_from(">I", data, mdhd_pos + (16 if version == 1 else 8))[0]

        minf = find_atom(data, "minf", mdia.body_offset, mdia.end)
        stbl = find_atom(data, "stbl", minf.body_offset, minf.end) if minf else None
        if stbl is None:
            raise Mp4Error("video track has no stbl")

        stts = find_atom(data, "stts", stbl.body_offset, stbl.end)
        if stts is None:
            raise Mp4Error("video track has no stts")
        deltas = _parse_stts(data, stts)

        stsz = find_atom(data, "stsz", stbl.body_offset, stbl.end)
        if stsz is not None:
            sizes = _parse_stsz(data, stsz)
        else:
            stz2 = find_atom(data, "stz2", stbl.body_offset, stbl.end)
            if stz2 is None:
                raise Mp4Error("video track has neither stsz nor stz2")
            sizes = _parse_stz2(data, stz2)

        if not sizes:
            # A fragmented file carries an empty sample table by design.
            codec, width, height = _visual_sample_entry(data, stbl)
            return VideoTrackIndex(timescale=timescale, width=width, height=height,
                                   codec=codec)

        stsc_atom = find_atom(data, "stsc", stbl.body_offset, stbl.end)
        if stsc_atom is None:
            raise Mp4Error("video track has no stsc")
        offsets = _sample_offsets(_parse_chunk_offsets(data, stbl), _parse_stsc(data, stsc_atom), sizes)

        ctts_atom = find_atom(data, "ctts", stbl.body_offset, stbl.end)
        composition = _parse_ctts(data, ctts_atom) if ctts_atom is not None else []

        samples: list[Sample] = []
        decode_time = 0
        for i, size in enumerate(sizes):
            offset_ticks = composition[i] if i < len(composition) else 0
            samples.append(Sample(i, offsets[i], size, decode_time + offset_ticks, timescale))
            decode_time += deltas[i] if i < len(deltas) else (deltas[-1] if deltas else 0)

        codec, width, height = _visual_sample_entry(data, stbl)
        return VideoTrackIndex(timescale=timescale, samples=samples, width=width,
                               height=height, codec=codec,
                               durations=deltas[: len(sizes)])

    raise Mp4Error("no video track in moov")


@dataclass(frozen=True)
class FragmentSamples:
    """Samples described by one ``moof``, with their ``mdat`` byte ranges."""

    samples: tuple[Sample, ...]
    moof_offset: int


def parse_fragment(data: bytes, moof: Atom, timescale: int, first_index: int) -> FragmentSamples:
    """Index the samples of one ``moof`` and its following ``mdat``.

    ``data`` must contain the whole ``moof``. The ``mdat`` payload need not have
    arrived: the point of this call is to learn *where* each sample will land.
    """
    traf = find_atom(data, "traf", moof.body_offset, moof.end)
    if traf is None:
        raise Mp4Error("moof has no traf")

    base_decode_time = 0
    tfdt = find_atom(data, "tfdt", traf.body_offset, traf.end)
    if tfdt is not None:
        version, _, pos = _parse_full_box(data, tfdt)
        base_decode_time = struct.unpack_from(">Q" if version == 1 else ">I", data, pos)[0]

    default_duration = 0
    default_size = 0
    tfhd = find_atom(data, "tfhd", traf.body_offset, traf.end)
    if tfhd is not None:
        _, flags, pos = _parse_full_box(data, tfhd)
        pos += 4  # track_ID
        if flags & 0x000001:
            pos += 8  # base_data_offset
        if flags & 0x000002:
            pos += 4  # sample_description_index
        if flags & 0x000008:
            default_duration = struct.unpack_from(">I", data, pos)[0]
            pos += 4
        if flags & 0x000010:
            default_size = struct.unpack_from(">I", data, pos)[0]

    trun = find_atom(data, "trun", traf.body_offset, traf.end)
    if trun is None:
        raise Mp4Error("traf has no trun")
    version, flags, pos = _parse_full_box(data, trun)
    sample_count = struct.unpack_from(">I", data, pos)[0]
    pos += 4
    data_offset = 0
    if flags & 0x000001:
        data_offset = struct.unpack_from(">i", data, pos)[0]
        pos += 4
    if flags & 0x000004:
        pos += 4  # first_sample_flags

    mdat_payload = moof.offset + data_offset
    if not (flags & 0x000001):
        mdat = find_atom(data, "mdat", moof.end)
        if mdat is None:
            raise Mp4Error("fragment has neither data_offset nor a locatable mdat")
        mdat_payload = mdat.body_offset

    samples: list[Sample] = []
    decode_time = base_decode_time
    position = mdat_payload
    for i in range(sample_count):
        duration = default_duration
        size = default_size
        composition = 0
        if flags & 0x000100:
            duration = struct.unpack_from(">I", data, pos)[0]
            pos += 4
        if flags & 0x000200:
            size = struct.unpack_from(">I", data, pos)[0]
            pos += 4
        if flags & 0x000400:
            pos += 4  # sample_flags
        if flags & 0x000800:
            fmt = ">i" if version != 0 else ">I"
            composition = struct.unpack_from(fmt, data, pos)[0]
            pos += 4
        samples.append(
            Sample(first_index + i, position, size, decode_time + composition, timescale)
        )
        position += size
        decode_time += duration

    return FragmentSamples(tuple(samples), moof.offset)


def movie_timescale(data: bytes, moov: Atom) -> int:
    mvhd = find_atom(data, "mvhd", moov.body_offset, moov.end)
    if mvhd is None:
        raise Mp4Error("moov has no mvhd")
    version, _, pos = _parse_full_box(data, mvhd)
    return struct.unpack_from(">I", data, pos + (16 if version == 1 else 8))[0]


def track_timescale_for_fragments(data: bytes, moov: Atom) -> int:
    """Media timescale of the first video track, for interpreting ``tfdt``."""
    try:
        return index_video_track(data, moov).timescale
    except Mp4Error:
        return movie_timescale(data, moov)
