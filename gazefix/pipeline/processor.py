"""Processing-stage seam and its dedicated worker."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Event, Thread
import time
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.frame_buffer import LatestValueBuffer


logger = logging.getLogger(__name__)
Frame = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    frame: Frame
    captured_at_ns: int
    camera_request_id: int


@dataclass(frozen=True, slots=True)
class ProcessedFrame:
    frame: Frame
    captured_at_ns: int
    processed_at_ns: int
    camera_request_id: int


class FrameProcessor(Protocol):
    def process(self, frame: Frame) -> Frame:
        """Process one immutable input frame and return an output frame."""


class PassthroughProcessor:
    """Milestone 0 processor that deliberately performs no computer vision."""

    def process(self, frame: Frame) -> Frame:
        return frame


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
            while not self._stop_event.is_set():
                item = self._input.wait_for_latest(
                    last_sequence, timeout=0.25, cancelled=self._stop_event.is_set
                )
                if item is None:
                    continue
                last_sequence = item.sequence
                source = item.value
                started_ns = time.perf_counter_ns()
                try:
                    output = self._processor.process(source.frame)
                except Exception:
                    logger.exception(
                        "Frame processor failed; preserving original frame",
                        extra={"event": "processor_failure"},
                    )
                    output = source.frame
                processed_at_ns = time.perf_counter_ns()
                self._metrics.record_processing(
                    (processed_at_ns - started_ns) / 1_000_000
                )
                self._output.publish(
                    ProcessedFrame(
                        frame=output,
                        captured_at_ns=source.captured_at_ns,
                        processed_at_ns=processed_at_ns,
                        camera_request_id=source.camera_request_id,
                    )
                )
        finally:
            logger.info(
                "Processing worker stopped", extra={"event": "processor_stopped"}
            )
