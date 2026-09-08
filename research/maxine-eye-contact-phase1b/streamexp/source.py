"""Stage A's source: a completed MP4, fed at the cadence of its own timestamps.

Stage A deliberately keeps the *source* simple — a known-good file in the
format the NIM supports — so that the only thing under test is whether a
continuously-open RPC returns usable output while input is still arriving. The
one thing that must not be simple is the delivery schedule: sending the file as
fast as the disk allows would answer a batch-throughput question and tell us
nothing about live capture.

The rule applied here is the physical one. A byte belonging to the frame shown
at t = 1.4 s cannot exist before 1.4 s of capture has happened, so it is not
handed to the RPC before then. Header bytes (``ftyp`` and ``moov``) are the one
exception: in a fragmented live stream the initialisation segment genuinely is
available at t = 0, so they are sent immediately.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import mp4
from .session import SendUnit


@dataclass(frozen=True)
class SourceProfile:
    """What a source file is, measured from the container rather than assumed."""

    path: Path
    sha256: str
    size_bytes: int
    layout: str
    streamable: bool
    fragmented: bool
    width: int
    height: int
    frame_count: int
    nominal_fps: float | None
    duration_seconds: float | None

    def describe(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "top_level_atoms": self.layout,
            "streamable_moov_first": self.streamable,
            "fragmented": self.fragmented,
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "nominal_fps": self.nominal_fps,
            "duration_seconds": self.duration_seconds,
        }


def probe(path: Path) -> tuple[SourceProfile, mp4.VideoTrackIndex]:
    """Index a source file and report what the container actually says."""
    data = path.read_bytes()
    layout = mp4.inspect_layout(data)
    index = mp4.index_video_track(data)
    fps = index.nominal_fps()
    duration = None
    if index.samples and fps:
        duration = index.frame_count() / fps
    profile = SourceProfile(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        layout=",".join(layout.atoms),
        streamable=layout.moov_first,
        fragmented=layout.fragmented,
        width=index.width,
        height=index.height,
        frame_count=index.frame_count(),
        nominal_fps=fps,
        duration_seconds=duration,
    )
    return profile, index


def paced_units(
    path: Path, index: mp4.VideoTrackIndex, chunk_size: int
) -> Iterator[SendUnit]:
    """Yield the file as writes whose media times follow the sample table.

    Each sample's byte range is emitted at that sample's presentation time and
    split into pieces of at most ``chunk_size``; the final piece of a range
    carries the frame index it completes.
    """
    data = path.read_bytes()
    samples = sorted(index.samples, key=lambda s: s.end)
    if not samples:
        raise ValueError(f"{path} has no indexable video samples")

    boundaries: list[tuple[int, int, float, int | None]] = []
    first_media_offset = min(s.offset for s in samples)
    if first_media_offset > 0:
        boundaries.append((0, first_media_offset, 0.0, None))
    position = first_media_offset
    for sample in samples:
        if sample.end > position:
            boundaries.append((position, sample.end, sample.pts_seconds, sample.index))
            position = sample.end
    if position < len(data):
        boundaries.append((position, len(data), samples[-1].pts_seconds, None))

    for start, end, media_time, frame_index in boundaries:
        offset = start
        while offset < end:
            stop = min(offset + chunk_size, end)
            is_last = stop >= end
            yield SendUnit(
                payload=data[offset:stop],
                media_time=media_time,
                frame_indices=(frame_index,) if (is_last and frame_index is not None) else (),
            )
            offset = stop
