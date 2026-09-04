"""ProcessingWorker seam contract: outputs, hooks, and failure containment."""

from __future__ import annotations

from threading import current_thread

import numpy as np

from camera_fakes import wait_until
from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.frame_buffer import LatestValueBuffer
from gazefix.pipeline.processor import CapturedFrame, ProcessingWorker, ProcessorOutput


class RecordingProcessor:
    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour
        self.started_with: object = "unset"
        self.start_thread: str | None = None
        self.close_thread: str | None = None
        self.contexts: list[object] = []

    def start(self, metrics=None):  # type: ignore[no-untyped-def]
        self.started_with = metrics
        self.start_thread = current_thread().name

    def process(self, frame, context):  # type: ignore[no-untyped-def]
        self.contexts.append(context)
        if self.behaviour == "output":
            return ProcessorOutput(frame)
        if self.behaviour == "bare":
            return frame
        if self.behaviour == "none":
            return None
        if self.behaviour == "garbage":
            return ProcessorOutput("not an array")  # type: ignore[arg-type]
        raise RuntimeError("processor exploded")

    def close(self) -> None:
        self.close_thread = current_thread().name


def _run_one(behaviour: str):  # type: ignore[no-untyped-def]
    inputs: LatestValueBuffer[CapturedFrame] = LatestValueBuffer()
    outputs = LatestValueBuffer()
    metrics = PipelineMetrics()
    processor = RecordingProcessor(behaviour)
    worker = ProcessingWorker(inputs, outputs, processor, metrics)
    worker.start()
    frame = np.full((2, 2, 3), 7, dtype=np.uint8)
    frame.setflags(write=False)
    inputs.publish(CapturedFrame(frame, captured_at_ns=123, camera_request_id=4))
    assert wait_until(lambda: outputs.sequence >= 1)
    item = outputs.consume_latest(0)
    worker.stop()
    assert worker.join(2.0)
    assert item is not None
    return processor, item.value, frame, metrics


def test_processor_output_is_published_with_frame_identity_and_hooks_on_the_worker_thread() -> None:
    processor, processed, frame, metrics = _run_one("output")
    assert processed.frame is frame
    assert processed.tracking is None
    assert processed.capture_sequence == 1 and processed.camera_request_id == 4
    assert processed.captured_at_ns == 123
    assert processor.started_with is metrics
    assert processor.start_thread == "gazefix-processor" and processor.close_thread == "gazefix-processor"
    context = processor.contexts[0]
    assert (context.capture_sequence, context.captured_at_ns, context.camera_request_id) == (1, 123, 4)
    assert metrics.snapshot().pipeline_latency_ms > 0


def test_bare_array_is_accepted_as_frame_without_metadata() -> None:
    _, processed, frame, _ = _run_one("bare")
    assert processed.frame is frame and processed.tracking is None


def test_invalid_outputs_and_exceptions_preserve_the_original_frame() -> None:
    for behaviour in ("none", "garbage", "raise"):
        _, processed, frame, _ = _run_one(behaviour)
        assert processed.frame is frame and processed.tracking is None
