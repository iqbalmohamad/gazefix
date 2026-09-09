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
    grpc_status: str | None = None
    """The server's gRPC status code name, when the call ended non-OK."""
    grpc_details: str | None = None
    interrupted: bool = False
    sender_incomplete: bool = False
    config_echo: dict[str, Any] = field(default_factory=dict)
    """The configuration the server echoed back — what it says it applied."""
    reader_error: str | None = None
    output_path: Path | None = None
    fed_at: dict[int, float] = field(default_factory=dict)
    """Source frame index -> seconds since RPC start at which its last byte was sent."""
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

        The question is whether *usable corrected output* appeared while the
        client was still sending. Three cases, and the third is the one that
        matters most:

        - A frame became usable before the client finished sending: ``YES``.
          That remains true even if the call later failed, because it already
          happened.
        - Sending finished and no frame was ever usable: ``NO``.
        - The call failed and no frame was ever usable: ``NOT MEASURED``. A
          ``NO`` here would read as "Maxine cannot stream" when all that is
          known is that the RPC did not complete — exactly the false failure
          this experiment must not produce.
        """
        first = self.first_usable_frame_at
        eos = self.input_eos_at
        if first is not None:
            return "YES" if (eos is None or first < eos) else "NO"
        if self.error or self.sender_incomplete:
            return "NOT MEASURED"
        if eos is None:
            return "NOT MEASURED"
        return "NO"


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
        timeout_s: float | None = 600.0,
    ) -> None:
        self._pb2 = interfaces.pb2
        self._stub = stub
        self._send_config = send_config
        self._config_params = dict(config_params or {})
        self._metadata = tuple(metadata) if metadata else None
        self._backlog_interval = backlog_interval_s
        self._output_path = output_path
        # A deadline on the whole call. The experiment is meant to be run once,
        # unattended, by an operator who is not watching it: a server that
        # accepts the stream and then never answers would otherwise block
        # forever and produce no record at all. On expiry gRPC raises
        # DEADLINE_EXCEEDED, which is caught and kept as the run's result
        # alongside every timing already collected.
        self._timeout = timeout_s

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
        result.fed_at = fed_at
        sender_error: list[BaseException] = []
        sending_done = threading.Event()

        timeline.mark("rpc_start")
        stop_sampling = threading.Event()
        sampler = threading.Thread(
            target=self._sample_backlog,
            args=(result, reader, fed_at, timeline, stop_sampling),
            daemon=True,
        )
        sampler.start()
        sink: BinaryIO | None = None
        if self._output_path is not None:
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            sink = self._output_path.open("wb")
            result.output_path = self._output_path

        def requests() -> Iterator[Any]:
            completed_normally = False
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
                    # Record the feed instant BEFORE handing the bytes to gRPC.
                    # Recording it after would race the response: gRPC drains
                    # this generator on its own thread, so a fast server's reply
                    # can be indexed on the reading thread before this line ran,
                    # leaving the frame with no age at all. Doing it first also
                    # attributes any flow-control blocking to the frame's age,
                    # where it belongs, instead of hiding it. With this ordering
                    # a negative age is impossible from the harness's own timing,
                    # so any negative age means output frame n is not the
                    # correction of input frame n.
                    sent_at = monotonic() - timeline.started_monotonic
                    for index in unit.frame_indices:
                        fed_at.setdefault(index, sent_at)
                    yield self._pb2.RedirectGazeRequest(video_file_data=unit.payload)
                    result.units_sent += 1
                    result.bytes_sent += len(unit.payload)
                completed_normally = True
            except GeneratorExit:
                # gRPC closes the request iterator when it abandons the call —
                # after a server error, for instance. That is the RPC dying, not
                # the sender failing, and recording it as a sender fault would
                # put "sender: GeneratorExit" in front of the server's real
                # status in the one artifact an operator reads.
                raise
            except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised to gRPC
                sender_error.append(exc)
                raise
            finally:
                if completed_normally:
                    timeline.mark("input_eos", bytes_sent=result.bytes_sent,
                                  units_sent=result.units_sent)
                else:
                    # Marking input_eos here would be a lie with consequences:
                    # output_before_eos() would compare against a moment the
                    # client never reached and report NO — reading as "Maxine
                    # cannot stream" when the truth is that the call failed.
                    timeline.mark("input_aborted", bytes_sent=result.bytes_sent,
                                  units_sent=result.units_sent)
                sending_done.set()

        try:
            responses = self._stub.RedirectGaze(
                requests(), metadata=self._metadata, timeout=self._timeout
            )
            self._consume(responses, result, timeline, reader, fed_at, sink)
        except BaseException as exc:  # noqa: BLE001 - even Ctrl-C must not lose the record
            result.error = f"{type(exc).__name__}: {exc}"
            code = getattr(exc, "code", None)
            if callable(code):
                try:
                    result.grpc_status = exc.code().name
                    result.grpc_details = exc.details()
                except Exception:  # noqa: BLE001 - best effort on a dying call
                    pass
            result.interrupted = isinstance(exc, KeyboardInterrupt)
            timeline.mark("rpc_error", error=result.error,
                          grpc_status=result.grpc_status or "")
        finally:
            if sink is not None:
                sink.close()

        stop_sampling.set()
        sampler.join(timeout=5.0)
        if not sending_done.wait(timeout=30.0):
            # The sender is still asleep in wait_until() while everything else
            # has stopped. Anything derived from a half-collected record would
            # be a determination about the harness, so say so instead.
            timeline.mark("sender_still_running")
            result.sender_incomplete = True
        if sender_error:
            detail = f"sender: {type(sender_error[0]).__name__}: {sender_error[0]}"
            timeline.mark("sender_error", error=detail)
            result.error = detail if result.error is None else f"{detail} | rpc: {result.error}"

        timeline.mark("rpc_end")
        try:
            closing_events = reader.close(monotonic())
        except Exception as exc:  # noqa: BLE001 - same reasoning as the feed path
            closing_events = []
            if result.reader_error is None:
                result.reader_error = f"{type(exc).__name__}: {exc}"
        for event in closing_events:
            self._record_frame(result, timeline, event, fed_at)
        self._reconcile_ages(result, fed_at)
        result.schedule_statistics = schedule.statistics()
        return result

    @staticmethod
    def _reconcile_ages(result: SessionResult, fed_at: dict[int, float]) -> None:
        """Fill in feed times that were not yet known when a frame arrived.

        A corrected frame is recorded the instant its bytes complete, and at that
        instant the matching source frame may not have been sent yet — either
        because the sender thread had not reached it, or because the output does
        not actually correspond 1:1 to the input. Dropping those frames would
        silently narrow the sample the percentiles are drawn from, so the feed
        map is consulted once more now that it is complete. An age that comes out
        negative is kept as such: it is the signal that correspondence broke, and
        :func:`~streamexp.timing.summarise_ages` reports it rather than averaging
        it away.
        """
        for position, record in enumerate(result.frames):
            if record.fed_at_s is not None:
                continue
            fed = fed_at.get(record.output_index)
            if fed is None:
                continue
            result.frames[position] = FrameRecord(
                output_index=record.output_index,
                output_pts_s=record.output_pts_s,
                fed_at_s=fed,
                usable_at_s=record.usable_at_s,
                byte_end=record.byte_end,
            )

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
        for response in responses:
            now = monotonic()
            result.responses += 1
            if result.responses == 1:
                timeline.mark("first_response", at=now)

            if response.HasField("config"):
                result.config_echoed = True
                try:
                    from google.protobuf import json_format  # noqa: PLC0415

                    result.config_echo = json_format.MessageToDict(response.config)
                except Exception:  # noqa: BLE001 - the echo is evidence, not a dependency
                    result.config_echo = {"note": "echo received but could not be rendered"}
                timeline.mark("config_echo", at=now)
                continue
            if response.HasField("keepalive"):
                result.keepalives += 1
                timeline.mark("keepalive", at=now, index=result.keepalives)
                continue
            if not response.HasField("video_file_data"):
                continue

            chunk = response.video_file_data
            if not chunk:
                # The oneof case is set but carries nothing. Stamping
                # first_output_bytes here would date the response stream from a
                # message that delivered no media.
                continue
            if result.bytes_received == 0:
                timeline.mark("first_output_bytes", at=now, bytes=len(chunk))
            result.bytes_received += len(chunk)
            if sink is not None:
                sink.write(chunk)

            try:
                events = reader.feed(chunk, now)
            except Exception as exc:  # noqa: BLE001 - a parse fault is not a transport fault
                # Maxine's container is written by NVIDIA's encoder and has never
                # been through this parser. One unfamiliar box must not be
                # recorded as an RPC failure, and must not stop the remaining
                # output from being received and saved for offline analysis.
                events = []
                if result.reader_error is None:
                    result.reader_error = f"{type(exc).__name__}: {exc}"
                    timeline.mark("reader_error", at=now, error=result.reader_error)
            for event in events:
                self._record_frame(result, timeline, event, fed_at)

            result.max_reader_buffer_bytes = max(
                result.max_reader_buffer_bytes, reader.buffered_bytes
            )
            if reader.layout is not Layout.UNKNOWN and timeline.first("output_layout") is None:
                timeline.mark("output_layout", at=now, layout=reader.layout.value)


    def _sample_backlog(
        self,
        result: SessionResult,
        reader: ProgressiveMp4Reader,
        fed_at: dict[int, float],
        timeline: Timeline,
        stop: threading.Event,
    ) -> None:
        """Record the send/receive gap at a fixed cadence for the whole call."""
        while not stop.is_set():
            result.backlog_samples.append(
                {
                    "t_s": round(monotonic() - timeline.started_monotonic, 4),
                    "bytes_sent": result.bytes_sent,
                    "bytes_received": result.bytes_received,
                    "bytes_outstanding": result.bytes_sent - result.bytes_received,
                    "frames_fed": len(fed_at),
                    "frames_usable": len(result.frames),
                    "frames_outstanding": len(fed_at) - len(result.frames),
                    "reader_buffer_bytes": reader.buffered_bytes,
                }
            )
            stop.wait(self._backlog_interval)

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
