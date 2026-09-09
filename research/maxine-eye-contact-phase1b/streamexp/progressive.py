"""Turn a growing MP4 byte stream into per-frame availability events.

The experiment's key metric is the *age of a corrected frame when it becomes
usable on the client*. The RPC delivers container bytes, so "usable" has to be
derived: a coded frame is usable once the container has described it and every
byte of it has arrived.

:class:`ProgressiveMp4Reader` is fed the response bytes exactly as they leave
the socket and reports, per frame, the wall-clock instant at which that
condition became true. It never buffers the whole stream — that would be the
unbounded queue the assignment forbids the harness from building — and it
reports the ``moov``-last case as *not indexable before EOS* rather than
silently waiting for the file to finish.

What the reported instant does and does not mean, stated plainly:

VERIFIED by construction
    Every byte of coded frame *n* has been received, and the container's sample
    table says where those bytes are and what their presentation time is.

NOT established
    That a decoder has produced a picture. For an H.264 stream with in-order
    output that is the same instant to within decoder call overhead, but a
    stream with B-frame reordering can need a later frame first. The harness
    therefore corroborates the first usable frame with a real decode
    (:mod:`streamexp.decode`) instead of asserting equivalence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import mp4


class Layout(str, Enum):
    UNKNOWN = "UNKNOWN"
    PROGRESSIVE = "MOOV_FIRST_NON_FRAGMENTED"
    FRAGMENTED = "MOOV_FIRST_FRAGMENTED"
    MOOV_LAST = "MOOV_LAST_NOT_INDEXABLE_BEFORE_EOS"


@dataclass(frozen=True)
class FrameEvent:
    """A coded frame whose bytes have all arrived."""

    index: int
    pts_seconds: float
    byte_end: int
    at: float
    """Monotonic clock reading when the last byte of the frame arrived."""


@dataclass
class ProgressiveMp4Reader:
    """Incremental, memory-bounded index of an arriving MP4 stream."""

    layout: Layout = Layout.UNKNOWN
    received: int = 0
    first_byte_at: float | None = None
    header_complete_at: float | None = None
    frames: list[FrameEvent] = field(default_factory=list)
    width: int = 0
    height: int = 0
    nominal_fps: float | None = None

    _buffer: bytearray = field(default_factory=bytearray, repr=False)
    _buffer_base: int = 0
    _cursor: int = 0
    _pending: list[mp4.Sample] = field(default_factory=list, repr=False)
    _next_frame_index: int = 0
    _timescale: int = 0
    _saw_media_before_moov: bool = False
    _unclassified_cap: int = 8 * 1024 * 1024

    # -- feeding ---------------------------------------------------------

    def feed(self, chunk: bytes, at: float) -> list[FrameEvent]:
        """Append received bytes and return the frames completed by them."""
        if not chunk:
            return []
        if self.first_byte_at is None:
            self.first_byte_at = at
        self._buffer.extend(chunk)
        self.received += len(chunk)

        if self.layout is Layout.UNKNOWN:
            self._try_read_header(at)
            if self.layout is Layout.UNKNOWN and len(self._buffer) > self._unclassified_cap:
                # A container this harness cannot classify must not become the
                # unbounded queue the experiment forbids. Stop retaining, keep
                # counting bytes, and let the complete output be analysed offline.
                self.layout = Layout.MOOV_LAST
                self._discard_to(self.received)
        elif self.layout is Layout.FRAGMENTED:
            self._scan_fragments(at)
        elif self.layout is Layout.PROGRESSIVE:
            # The sample table is already known; the payload itself is never
            # needed again, only the count of bytes seen.
            self._discard_to(self.received)

        if self.layout is Layout.MOOV_LAST:
            # Nothing is indexable until EOS; hold no payload.
            self._discard_to(self.received)
            return []

        return self._complete_frames(at)

    def close(self, at: float) -> list[FrameEvent]:
        """Signal end of stream and index whatever only a complete file allows."""
        if self.layout is Layout.MOOV_LAST:
            # The whole file is required, and the harness deliberately did not
            # retain it, so completion is recorded without per-frame timing.
            self.header_complete_at = at
        return self._complete_frames(at)

    # -- header ----------------------------------------------------------

    def _try_read_header(self, at: float) -> None:
        buffer = bytes(self._buffer)
        moov: mp4.Atom | None = None
        try:
            for atom in mp4.iter_atoms(buffer):
                if atom.type in ("mdat", "moof") and moov is None:
                    self._saw_media_before_moov = True
                if atom.type == "moov":
                    if atom.end > len(buffer):
                        return  # keep buffering; the moov is still arriving
                    moov = atom
                    break
        except mp4.Mp4Error:
            return

        if moov is None:
            if self._saw_media_before_moov:
                self.layout = Layout.MOOV_LAST
            return

        if self._saw_media_before_moov:
            self.layout = Layout.MOOV_LAST
            return

        self.header_complete_at = at
        index = mp4.index_video_track(buffer, moov)
        self._timescale = index.timescale
        self.width, self.height = index.width, index.height
        if index.samples:
            self.layout = Layout.PROGRESSIVE
            self.nominal_fps = index.nominal_fps()
            self._pending = sorted(index.samples, key=lambda s: s.end)
            self._discard_to(self.received)
        else:
            self.layout = Layout.FRAGMENTED
            self._cursor = moov.end
            self._scan_fragments(at)

    # -- fragments -------------------------------------------------------

    def _scan_fragments(self, at: float) -> None:
        # Drop anything before the cursor first: while a large mdat is still
        # arriving the reader needs none of it, only the count of bytes seen.
        self._discard_to(self._cursor)
        while True:
            local = self._cursor - self._buffer_base
            if local < 0:
                self._cursor = self._buffer_base
                local = 0
            if local + 8 > len(self._buffer):
                return
            buffer = bytes(self._buffer)
            try:
                atom = next(mp4.iter_atoms(buffer, local), None)
            except mp4.Mp4Error:
                return
            if atom is None:
                return
            absolute = mp4.Atom(atom.type, self._cursor, atom.header_size, atom.size)

            if atom.type == "moof":
                if atom.end > len(buffer):
                    return  # a moof is small; wait for all of it
                fragment = mp4.parse_fragment(
                    buffer, atom, self._timescale or 1, self._next_frame_index
                )
                shift = self._buffer_base
                self._pending.extend(
                    mp4.Sample(s.index, s.offset + shift, s.size, s.pts_ticks, s.timescale)
                    for s in fragment.samples
                )
                self._pending.sort(key=lambda s: s.end)
                self._next_frame_index += len(fragment.samples)

            self._cursor = absolute.end
            self._discard_to(self._cursor)

    # -- completion ------------------------------------------------------

    def _complete_frames(self, at: float) -> list[FrameEvent]:
        completed: list[FrameEvent] = []
        while self._pending and self._pending[0].end <= self.received:
            sample = self._pending.pop(0)
            event = FrameEvent(sample.index, sample.pts_seconds, sample.end, at)
            self.frames.append(event)
            completed.append(event)
        return completed

    def _discard_to(self, absolute_offset: int) -> None:
        """Drop buffered bytes the reader will never need again."""
        keep_from = max(absolute_offset, self._buffer_base)
        drop = min(keep_from - self._buffer_base, len(self._buffer))
        if drop > 0:
            del self._buffer[:drop]
            self._buffer_base += drop

    @property
    def buffered_bytes(self) -> int:
        """Bytes currently held. The harness asserts this stays bounded."""
        return len(self._buffer)
