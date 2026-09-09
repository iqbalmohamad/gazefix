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
    codec: str
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
            "video_codec_4cc": self.codec or "UNKNOWN",
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "nominal_fps": self.nominal_fps,
            "duration_seconds": self.duration_seconds,
        }


class SourceUnsuitable(RuntimeError):
    """The source file cannot answer the question, and the service is not at fault.

    Raised before the RPC is opened. Every message says what is wrong with the
    *file*, because a run that dies on bad input must never be mistaken for
    evidence about Maxine.
    """


def probe(path: Path) -> tuple[SourceProfile, mp4.VideoTrackIndex]:
    """Index a source file and report what the container actually says."""
    if not path.is_file():
        raise SourceUnsuitable(f"{path} does not exist")
    data = path.read_bytes()
    if data.startswith(b"version https://git-lfs"):
        raise SourceUnsuitable(
            f"{path} is a {len(data)}-byte Git LFS pointer, not video. Run "
            "'git lfs install && git lfs pull' inside the clone that holds it."
        )
    if len(data) < 8 or data[4:8] != b"ftyp":
        raise SourceUnsuitable(
            f"{path} does not begin with an MP4 'ftyp' box ({len(data)} bytes). "
            "The NIM accepts MP4 with H.264 only."
        )
    layout = mp4.inspect_layout(data)
    try:
        index = mp4.index_video_track(data)
    except mp4.Mp4Error as exc:
        raise SourceUnsuitable(f"{path} has no indexable video track: {exc}") from exc
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
        codec=index.codec,
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
    latest_pts = 0.0
    for sample in samples:
        # Running maximum: a live encoder could not have produced these bytes
        # before the newest picture among them was captured. For B-frame
        # material the raw PTS goes backwards in decode order, and using it
        # directly would set deadlines already in the past.
        latest_pts = max(latest_pts, sample.pts_seconds)
        if sample.end > position:
            boundaries.append((position, sample.end, latest_pts, sample.index))
            position = sample.end
    if position < len(data):
        boundaries.append((position, len(data), latest_pts, None))

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
