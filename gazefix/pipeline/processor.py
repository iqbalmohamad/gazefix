"""Processing-stage seam and its dedicated worker.

The seam is ``FrameProcessor``: one immutable captured frame in, one
``ProcessorOutput`` out. M0 ships the passthrough implementation; M1 plugs
``gazefix.tracking.processor.TrackingProcessor`` into the same worker without
changing capture, buffering, or the UI's polling. The worker tells the
processor which frame it is handling (``FrameContext``: capture sequence,
capture timestamp, camera generation) so any metadata the processor attaches
is tied to exactly that frame and generation.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Event, Thread
import time
from typing import TYPE_CHECKING, Protocol

import numpy as np
from numpy.typing import NDArray

from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.frame_buffer import LatestValueBuffer

if TYPE_CHECKING:  # the tracking contract is data only; no runtime import cycle
    from gazefix.tracking.models import TrackingResult


logger = logging.getLogger(__name__)
Frame = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    frame: Frame
    captured_at_ns: int
    camera_request_id: int


@dataclass(frozen=True, slots=True)
class FrameContext:
    """Identity of the frame a processor is handed.

    ``capture_sequence`` is the capture buffer's sequence number (unique and
    increasing for the life of the runtime, never reset by a camera change),
    ``captured_at_ns`` the capture timestamp, ``camera_request_id`` the camera
    generation the frame belongs to.
    """

    capture_sequence: int
    captured_at_ns: int
    camera_request_id: int


@dataclass(frozen=True, slots=True)
class ProcessorOutput:
    """What a processor returns: the frame to show and optional tracking data.

    ``frame`` is the input array object itself when the processor did not
    draw on it; a processor that draws returns its own copy and never writes
    to the input. ``tracking`` belongs to the frame identified by the
    ``FrameContext`` the processor received.
    """

    frame: Frame
    tracking: "TrackingResult | None" = None


@dataclass(frozen=True, slots=True)
class ProcessedFrame:
    frame: Frame
    captured_at_ns: int
    processed_at_ns: int
    camera_request_id: int
    capture_sequence: int = 0
    tracking: "TrackingResult | None" = None


class FrameProcessor(Protocol):
    def start(self, metrics: PipelineMetrics | None = None) -> None:
        """Called once on the processing thread before the first frame.

        A processor that needs slow preparation (loading a model) starts it
        here, on its own thread, so it overlaps camera discovery instead of
        delaying the first preview frame. ``metrics`` is the pipeline's
        shared metrics object, for processors that report their own timing.
        """

    def process(self, frame: Frame, context: FrameContext) -> ProcessorOutput:
        """Process one immutable input frame; never write to ``frame``."""

    def close(self) -> None:
        """Release resources; called once, on the processing thread, at worker exit."""


class PassthroughProcessor:
    """Milestone 0 processor that deliberately performs no computer vision."""

    def start(self, metrics: PipelineMetrics | None = None) -> None:
        return None

    def process(self, frame: Frame, context: FrameContext) -> ProcessorOutput:
        return ProcessorOutput(frame)

    def close(self) -> None:
        return None


class ProcessingWorker:
    """Consume only the latest captured frame on a background thread."""

    def __init__(
        self,
        input_buffer: LatestValueBuffer[CapturedFrame],
        output_buffer: LatestValueBuffer[ProcessedFrame],
        processor: FrameProcessor,
        metrics: PipelineMetrics,
    ) -> None:
        self._input = input_buffer
        self._output = output_buffer
        self._processor = processor
        self._metrics = metrics
        self._stop_event = Event()
        self._thread = Thread(
            target=self._run, name="gazefix-processor", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._input.wake_all()

    def join(self, timeout: float | None = None) -> bool:
        """Wait up to ``timeout`` for the thread; a thread that never started needs no wait."""

        if self.started:
            self._thread.join(timeout)
        return not self._thread.is_alive()

    @property
    def started(self) -> bool:
        """Whether ``start`` launched the thread (``Thread.ident`` is set once it runs)."""

        return self._thread.ident is not None

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        logger.info("Processing worker started", extra={"event": "processor_started"})
        last_sequence = 0
        try:
            start = getattr(self._processor, "start", None)
            if callable(start):
                try:
                    start(self._metrics)
                except Exception:
                    logger.exception(
                        "Frame processor start failed; frames pass through its process()",
                        extra={"event": "processor_start_error"},
                    )
            while not self._stop_event.is_set():
                item = self._input.wait_for_latest(
                    last_sequence, timeout=0.25, cancelled=self._stop_event.is_set
                )
                if item is None:
                    continue
                last_sequence = item.sequence
                source = item.value
                context = FrameContext(
                    capture_sequence=item.sequence,
                    captured_at_ns=source.captured_at_ns,
                    camera_request_id=source.camera_request_id,
                )
                started_ns = time.perf_counter_ns()
                try:
                    output = self._processor.process(source.frame, context)
                    if isinstance(output, np.ndarray):
                        # A processor that returns a bare array is accepted as
                        # "this frame, no metadata".
                        output = ProcessorOutput(output)
                    if not isinstance(output, ProcessorOutput) or not isinstance(output.frame, np.ndarray):
                        raise TypeError(
                            f"processor returned {type(output).__name__}, expected ProcessorOutput"
                        )
                except Exception:
                    logger.exception(
                        "Frame processor failed; preserving original frame",
                        extra={"event": "processor_failure"},
                    )
                    output = ProcessorOutput(source.frame)
                processed_at_ns = time.perf_counter_ns()
                self._metrics.record_processing(
                    (processed_at_ns - started_ns) / 1_000_000
                )
                self._metrics.record_pipeline_latency(
                    (processed_at_ns - source.captured_at_ns) / 1_000_000
                )
                self._output.publish(
                    ProcessedFrame(
                        frame=output.frame,
                        captured_at_ns=source.captured_at_ns,
                        processed_at_ns=processed_at_ns,
                        camera_request_id=source.camera_request_id,
                        capture_sequence=item.sequence,
                        tracking=output.tracking,
                    )
                )
        finally:
            # The processor owns whatever it created (a tracker, its thread);
            # it is released here, on the thread that used it, bounded by the
            # processor's own join policy so the runtime's deadline still holds.
            try:
                self._processor.close()
            except Exception:
                logger.exception(
                    "Frame processor close failed", extra={"event": "processor_close_error"}
                )
            logger.info(
                "Processing worker stopped", extra={"event": "processor_stopped"}
            )
