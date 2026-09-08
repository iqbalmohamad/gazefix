"""Drive one continuously-open ``RedirectGaze`` RPC and time what comes back.

This is the measuring instrument. It does exactly one thing:

1. opens a single ``RedirectGaze`` invocation;
2. feeds it container bytes on a realtime schedule, from a generator gRPC
   consumes on its own thread;
3. reads responses concurrently on the calling thread, indexing them into
   :class:`~streamexp.progressive.ProgressiveMp4Reader` as they arrive;
4. records when each thing happened.

Concurrency, and why it is real rather than assumed. ``stub.RedirectGaze(it)``
returns immediately and gRPC drains ``it`` on an internal thread, so the reader
loop below is genuinely running while the sender is still sending. This is the
same structure NVIDIA's own ``eye-contact.py`` uses; the difference is that
NVIDIA's generator reads the file as fast as the disk allows, and this one is
paced by media timestamps.

The harness holds no queue of its own between the socket and the index: each
response is consumed on arrival and the reader's retained bytes are asserted to
stay bounded. If a backlog appears it is therefore the service's or the
transport's, not an artifact of the experiment.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Iterator, Sequence

from .clock import RealtimeSchedule
from .progressive import FrameEvent, Layout, ProgressiveMp4Reader
from .timing import FrameRecord, Timeline, monotonic


@dataclass(frozen=True)
class SendUnit:
    """One paced write to the RPC.

    ``media_time`` is when this unit's content is due in the source's own
    timeline; the schedule turns it into a wall-clock deadline. ``None`` means
    send as soon as the unit exists — the correct setting when the pacing has
    already been applied upstream, as it is in Stage B where a live encoder,
    not the sender, sets the cadence.

    ``frame_indices`` lists the source frames whose final byte this unit
    completes. That is what makes a per-frame age computable later, and it is a
    tuple because one 64 KiB write can finish more than one 720p frame.
    """

    payload: bytes
    media_time: float | None
    frame_indices: tuple[int, ...] = ()


@dataclass
class SessionResult:
    """Everything one RPC produced, measured rather than inferred."""

    timeline: Timeline
    reader: ProgressiveMp4Reader
    frames: list[FrameRecord] = field(default_factory=list)
    bytes_sent: int = 0
    bytes_received: int = 0
    units_sent: int = 0
    responses: int = 0
    keepalives: int = 0
    config_echoed: bool = False
    error: str | None = None
    schedule_statistics: dict[str, Any] = field(default_factory=dict)
    max_reader_buffer_bytes: int = 0
    backlog_samples: list[dict[str, float]] = field(default_factory=list)
    output_path: Path | None = None
    first_usable_byte_end: int | None = None
    """Received byte count at the moment the first frame became usable.

    Truncating the saved output here reproduces exactly what the client held at
    that instant, which is what :mod:`streamexp.decode` decodes to corroborate
    the container-level criterion.
    """

    # -- the load-bearing determinations --------------------------------

    @property
    def input_eos_at(self) -> float | None:
        event = self.timeline.first("input_eos")
        return None if event is None else event.at

    @property
    def first_output_bytes_at(self) -> float | None:
        event = self.timeline.first("first_output_bytes")
        return None if event is None else event.at

    @property
    def first_usable_frame_at(self) -> float | None:
        event = self.timeline.first("first_usable_frame")
        return None if event is None else event.at

    def output_before_eos(self) -> str:
        """``YES`` / ``NO`` / ``NOT MEASURED`` for Stage A's kill condition.

        The question is specifically about *usable corrected output*, so an
        arrival of raw bytes that never became an indexable frame is not a YES.
        """
        first = self.first_usable_frame_at
        eos = self.input_eos_at
        if first is None:
            return "NO" if eos is not None else "NOT MEASURED"
        if eos is None:
            return "NOT MEASURED"
        return "YES" if first < eos else "NO"


class RedirectGazeSession:
    """One continuously-open ``RedirectGaze`` invocation."""

    def __init__(
        self,
        interfaces: Any,
        stub: Any,
        *,
        send_config: bool = True,
        config_params: dict[str, Any] | None = None,
        metadata: Sequence[tuple[str, str]] | None = None,
        backlog_interval_s: float = 0.5,
        output_path: Path | None = None,
    ) -> None:
        self._pb2 = interfaces.pb2
        self._stub = stub
        self._send_config = send_config
        self._config_params = dict(config_params or {})
        self._metadata = tuple(metadata) if metadata else None
        self._backlog_interval = backlog_interval_s
        self._output_path = output_path

    def run(
        self,
        units: Iterable[SendUnit],
        schedule: RealtimeSchedule,
        fed_at: dict[int, float] | None = None,
    ) -> SessionResult:
        """Run the RPC to completion.

        ``fed_at`` maps source frame index to seconds-since-RPC-start at which
        that frame's last byte was written. Callers whose unit generator learns
        frame boundaries as it goes may pass their own dict and fill it there.
        """
        timeline = Timeline()
        reader = ProgressiveMp4Reader()
        result = SessionResult(timeline=timeline, reader=reader)
        fed_at = {} if fed_at is None else fed_at
        sender_error: list[BaseException] = []
        sending_done = threading.Event()

        timeline.mark("rpc_start")
        sink: BinaryIO | None = None
        if self._output_path is not None:
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            sink = self._output_path.open("wb")
            result.output_path = self._output_path

        def requests() -> Iterator[Any]:
            try:
                if self._send_config:
                    timeline.mark("config_sent")
                    yield self._pb2.RedirectGazeRequest(
                        config=self._pb2.RedirectGazeConfig(**self._config_params)
                    )
                for unit in units:
                    if unit.media_time is None:
                        released = monotonic()
                    else:
                        released = schedule.wait_until(unit.media_time)
                    if result.units_sent == 0:
                        timeline.mark(
                            "first_input_bytes", at=released, media_time=unit.media_time
                        )
                    yield self._pb2.RedirectGazeRequest(video_file_data=unit.payload)
                    result.units_sent += 1
                    result.bytes_sent += len(unit.payload)
                    sent_at = monotonic() - timeline.started_monotonic
                    for index in unit.frame_indices:
                        fed_at.setdefault(index, sent_at)
            except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised to gRPC
                sender_error.append(exc)
                raise
            finally:
                timeline.mark("input_eos", bytes_sent=result.bytes_sent,
                              units_sent=result.units_sent)
                sending_done.set()

        try:
            responses = self._stub.RedirectGaze(requests(), metadata=self._metadata)
            self._consume(responses, result, timeline, reader, fed_at, sink)
        except Exception as exc:  # noqa: BLE001 - a transport failure is a result
            result.error = f"{type(exc).__name__}: {exc}"
            timeline.mark("rpc_error", error=result.error)
        finally:
            if sink is not None:
                sink.close()

        sending_done.wait(timeout=5.0)
        if sender_error:
            detail = f"sender: {type(sender_error[0]).__name__}: {sender_error[0]}"
            timeline.mark("sender_error", error=detail)
            result.error = detail if result.error is None else f"{detail} | rpc: {result.error}"

        timeline.mark("rpc_end")
        for event in reader.close(monotonic()):
            self._record_frame(result, timeline, event, fed_at)
        result.schedule_statistics = schedule.statistics()
        return result

    # -- response side ---------------------------------------------------

    def _consume(
        self,
        responses: Iterable[Any],
        result: SessionResult,
        timeline: Timeline,
        reader: ProgressiveMp4Reader,
        fed_at: dict[int, float],
        sink: BinaryIO | None,
    ) -> None:
        next_backlog_sample = 0.0
        for response in responses:
            now = monotonic()
            result.responses += 1
            if result.responses == 1:
                timeline.mark("first_response", at=now)

            if response.HasField("config"):
                result.config_echoed = True
                timeline.mark("config_echo", at=now)
                continue
            if response.HasField("keepalive"):
                result.keepalives += 1
                timeline.mark("keepalive", at=now, index=result.keepalives)
                continue
            if not response.HasField("video_file_data"):
                continue

            chunk = response.video_file_data
            if result.bytes_received == 0:
                timeline.mark("first_output_bytes", at=now, bytes=len(chunk))
            result.bytes_received += len(chunk)
            if sink is not None:
                sink.write(chunk)

            for event in reader.feed(chunk, now):
                self._record_frame(result, timeline, event, fed_at)

            result.max_reader_buffer_bytes = max(
                result.max_reader_buffer_bytes, reader.buffered_bytes
            )
            if reader.layout is not Layout.UNKNOWN and timeline.first("output_layout") is None:
                timeline.mark("output_layout", at=now, layout=reader.layout.value)

            since_start = now - timeline.started_monotonic
            if since_start >= next_backlog_sample:
                next_backlog_sample = since_start + self._backlog_interval
                result.backlog_samples.append(
                    {
                        "t_s": round(since_start, 4),
                        "bytes_sent": result.bytes_sent,
                        "bytes_received": result.bytes_received,
                        "frames_fed": len(fed_at),
                        "frames_usable": len(result.frames),
                        "reader_buffer_bytes": reader.buffered_bytes,
                    }
                )

    def _record_frame(
        self,
        result: SessionResult,
        timeline: Timeline,
        event: FrameEvent,
        fed_at: dict[int, float],
    ) -> None:
        usable_at = event.at - timeline.started_monotonic
        if not result.frames:
            result.first_usable_byte_end = result.bytes_received
            timeline.mark(
                "first_usable_frame",
                at=event.at,
                output_index=event.index,
                output_pts_s=round(event.pts_seconds, 6),
            )
        result.frames.append(
            FrameRecord(
                output_index=event.index,
                output_pts_s=event.pts_seconds,
                fed_at_s=fed_at.get(event.index),
                usable_at_s=usable_at,
                byte_end=event.byte_end,
            )
        )
