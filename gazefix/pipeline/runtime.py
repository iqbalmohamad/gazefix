"""Lifecycle owner connecting capture, processing, and frame consumers."""

from __future__ import annotations

import logging
from threading import Lock
import time
from typing import Callable

from gazefix.camera.capture import CameraCaptureWorker, SourceFactory
from gazefix.camera.models import CameraDevice, CaptureStatus
from gazefix.camera.source import OpenCVCameraSource
from gazefix.config import AppSettings
from gazefix.diagnostics.metrics import MetricsSnapshot, PipelineMetrics
from gazefix.pipeline.frame_buffer import LatestValueBuffer, VersionedValue
from gazefix.pipeline.processor import (
    CapturedFrame,
    FrameProcessor,
    PassthroughProcessor,
    ProcessedFrame,
    ProcessingWorker,
)


logger = logging.getLogger(__name__)


class PipelineRuntime:
    """Own all M0 workers and expose non-blocking UI-facing operations."""

    def __init__(
        self,
        settings: AppSettings,
        on_status: Callable[[CaptureStatus], None] | None = None,
        processor: FrameProcessor | None = None,
        source_factory: SourceFactory | None = None,
    ) -> None:
        self._settings = settings
        self._capture_buffer: LatestValueBuffer[CapturedFrame] = LatestValueBuffer()
        self._output_buffer: LatestValueBuffer[ProcessedFrame] = LatestValueBuffer()
        self._metrics = PipelineMetrics()
        self._capture = CameraCaptureWorker(
            settings=settings,
            output_buffer=self._capture_buffer,
            metrics=self._metrics,
            on_status=on_status,
            source_factory=source_factory or OpenCVCameraSource,
        )
        self._processor = ProcessingWorker(
            self._capture_buffer,
            self._output_buffer,
            processor or PassthroughProcessor(),
            self._metrics,
        )
        self._request_lock = Lock()
        self._current_request_id = 0
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._processor.start()
        self._capture.start()
        self._started = True

    def select_camera(self, device: CameraDevice | None) -> int:
        """Request a camera change and return its generation identifier."""

        self._capture_buffer.clear()
        self._output_buffer.clear()
        request_id = self._capture.request_camera(device)
        with self._request_lock:
            self._current_request_id = request_id
        logger.info(
            "Camera switch requested",
            extra={
                "event": "camera_switch_requested",
                "request_id": request_id,
                "camera_index": device.index if device else None,
            },
        )
        return request_id

    def consume_latest_output(
        self, after_sequence: int = 0
    ) -> VersionedValue[ProcessedFrame] | None:
        item = self._output_buffer.consume_latest(after_sequence)
        if item is None:
            return None
        with self._request_lock:
            current_request_id = self._current_request_id
        if item.value.camera_request_id != current_request_id:
            return None
        return item

    def record_display(self) -> None:
        self._metrics.record_display()

    def metrics(self) -> MetricsSnapshot:
        return self._metrics.snapshot(
            capture_replacements=self._capture_buffer.replaced_count,
            output_replacements=self._output_buffer.replaced_count,
        )

    def stop(self) -> bool:
        if not self._started:
            return True
        self._capture.stop()
        self._processor.stop()
        timeout = self._settings.worker_join_timeout_s
        deadline = time.perf_counter() + timeout
        # A normal webcam read returns promptly; letting the owning thread close
        # the source avoids backend deadlocks caused by concurrent release/read.
        capture_stopped = self._capture.join(min(0.5, timeout * 0.25))
        if not capture_stopped:
            # Camera open can block much longer than one frame interval. It is
            # safe to release the registered, not-yet-open capture as a fallback.
            self._capture.interrupt()
            capture_stopped = self._capture.join(
                max(0.0, deadline - time.perf_counter())
            )
        processor_stopped = self._processor.join(
            max(0.0, deadline - time.perf_counter())
        )
        self._started = False
        clean = capture_stopped and processor_stopped
        log = logger.info if clean else logger.error
        log(
            "Pipeline stopped" if clean else "Pipeline shutdown timed out",
            extra={
                "event": "pipeline_stopped",
                "capture_stopped": capture_stopped,
                "processor_stopped": processor_stopped,
            },
        )
        return clean

    @property
    def workers_alive(self) -> bool:
        return self._capture.is_alive or self._processor.is_alive
