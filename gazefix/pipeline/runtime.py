"""Lifecycle owner connecting capture, processing, and frame consumers."""

from __future__ import annotations

from enum import Enum
import logging
from threading import Lock
import time
from typing import Callable

from gazefix.camera.capture import CameraCaptureWorker, SourceFactory
from gazefix.camera.models import CameraDevice, CaptureStatus
from gazefix.camera.source import OpenCVCameraSource, PreparedCamera
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


class RuntimeState(str, Enum):
    """Lifecycle state of a ``PipelineRuntime``, derived when it is read.

    ``STOPPING`` versus ``STOPPED`` is decided by whether an owned worker
    thread is alive right now, never by a flag that ``stop()`` sets. A shutdown
    that timed out with a worker still inside a driver call therefore keeps
    reporting ``STOPPING`` until that thread has actually exited.
    """

    NEW = "new"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


class PipelineRuntime:
    """Own all M0 workers and expose non-blocking UI-facing operations.

    A runtime is single-use: ``start()`` launches both worker threads once and
    ``stop()`` winds them down. Python threads cannot be restarted, so there is
    deliberately no restart path; ``start()`` after ``stop()`` raises rather
    than pretending.
    """

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
        # Guards the three lifecycle flags below. It is held only for flag
        # reads and writes (and, in ``select_camera``, across the publish of a
        # request), never across a join, so no UI-facing call can block on a
        # shutdown that is waiting for a camera driver.
        self._lifecycle_lock = Lock()
        self._started = False
        self._stop_requested = False
        self._stop_finalized = False

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._stop_requested:
                raise RuntimeError(
                    "PipelineRuntime cannot be restarted after stop(); "
                    "create a new runtime"
                )
            if self._started:
                return
            self._processor.start()
            self._capture.start()
            self._started = True

    def select_camera(
        self, device: CameraDevice | None, prepared: PreparedCamera | None = None
    ) -> int:
        """Request a camera change and return its generation identifier.

        ``prepared`` is an already-open validated source for ``device`` (from
        discovery) that the capture worker adopts instead of reopening.

        Once ``stop()`` has been requested no worker will ever apply a request,
        so the request is refused: nothing is published, the current generation
        is returned unchanged, and a prepared camera is closed here because
        there is no worker left to own it.
        """

        with self._lifecycle_lock:
            accepted = not self._stop_requested
            if accepted:
                self._capture_buffer.clear()
                self._output_buffer.clear()
                # The generation is published under the same lock the frame
                # consumer reads it with, so no frame of the new generation can
                # be judged against the old id and no old frame against the new
                # one. Publishing under the lifecycle lock as well means a
                # request can never slip in between ``stop()`` deciding to
                # stop and the worker being told, where nobody would close it.
                with self._request_lock:
                    request_id = self._capture.request_camera(device, prepared)
                    self._current_request_id = request_id
        if not accepted:
            if prepared is not None:
                self._close_refused_prepared(prepared, device)
            logger.warning(
                "Camera request refused; runtime is stopping or stopped",
                extra={
                    "event": "camera_switch_refused",
                    "camera_index": device.index if device else None,
                    "runtime_state": self.state.value,
                },
            )
            return self.current_request_id
        logger.info(
            "Camera switch requested",
            extra={
                "event": "camera_switch_requested",
                "request_id": request_id,
                "camera_index": device.index if device else None,
                "adopting_prepared": prepared is not None,
            },
        )
        return request_id

    @property
    def current_request_id(self) -> int:
        with self._request_lock:
            return self._current_request_id

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
        """Ask both workers to stop and join them within ``worker_join_timeout_s``.

        Returns ``True`` only when every owned worker thread has terminated by
        the time this call returns. The result is derived from thread liveness,
        never from bookkeeping: a shutdown that runs out of time while a worker
        is inside an uncancellable driver call returns ``False`` and leaves the
        runtime ``STOPPING``. Calling ``stop()`` again then joins the surviving
        worker against a fresh bounded deadline and returns ``True`` only once
        it has actually exited, at which point the stopped state is finalized
        (pending prepared cameras closed, terminal log line written). Every
        call is bounded by one join timeout; none blocks indefinitely.
        """

        with self._lifecycle_lock:
            first_call = not self._stop_requested
            self._stop_requested = True
            started = self._started
        timeout = self._settings.worker_join_timeout_s
        deadline = time.perf_counter() + timeout
        if started:
            self._capture.stop()
            self._processor.stop()
            # A normal webcam read returns promptly; letting the owning thread
            # close the source avoids backend deadlocks caused by concurrent
            # release/read.
            capture_stopped = self._capture.join(min(0.5, timeout * 0.25))
            if not capture_stopped:
                # Flag the source so the worker gives up at its next checkpoint.
                # No release happens from this thread: a blocked driver open
                # cannot be cancelled, and a blocked read returns on the
                # backend's own timeout, after which the worker releases the
                # camera itself.
                self._capture.interrupt()
                capture_stopped = self._capture.join(
                    max(0.0, deadline - time.perf_counter())
                )
            processor_stopped = self._processor.join(
                max(0.0, deadline - time.perf_counter())
            )
        else:
            # Threads that were never started cannot be alive or be joined.
            capture_stopped = processor_stopped = True
        # Prepared cameras the worker will never adopt are closed by the
        # caller. After ``stop()`` the worker has either exited (its own
        # cleanup already ran) or is abandoned inside a driver call and may
        # never reach that cleanup. The token hands its source to exactly one
        # closer, so this cannot race the worker's own ``close_if_unclaimed``,
        # and nobody is reading an unclaimed source, so releasing it here is
        # the same ownership rule discovery applies to its unclaimed tokens.
        self._capture.close_pending_prepared()
        clean = capture_stopped and processor_stopped
        with self._lifecycle_lock:
            newly_finalized = clean and not self._stop_finalized
            self._stop_finalized = self._stop_finalized or clean
        if not clean:
            logger.error(
                "Pipeline shutdown timed out; a worker is still alive",
                extra={
                    "event": "pipeline_shutdown_timeout",
                    "capture_stopped": capture_stopped,
                    "processor_stopped": processor_stopped,
                    "timeout_s": timeout,
                    "repeated_stop": not first_call,
                },
            )
        elif newly_finalized:
            logger.info(
                "Pipeline stopped",
                extra={
                    "event": "pipeline_stopped",
                    "capture_stopped": True,
                    "processor_stopped": True,
                    "after_timeout": not first_call,
                },
            )
        else:
            logger.debug(
                "Pipeline already stopped", extra={"event": "pipeline_stop_repeated"}
            )
        return clean

    @property
    def state(self) -> RuntimeState:
        """Current lifecycle state, computed from the worker threads' liveness."""

        with self._lifecycle_lock:
            started, stop_requested = self._started, self._stop_requested
        if not stop_requested:
            return RuntimeState.RUNNING if started else RuntimeState.NEW
        return RuntimeState.STOPPING if self.workers_alive else RuntimeState.STOPPED

    @property
    def workers_alive(self) -> bool:
        return self._capture.is_alive or self._processor.is_alive

    def _close_refused_prepared(
        self, prepared: PreparedCamera, device: CameraDevice | None
    ) -> None:
        if prepared.close_if_unclaimed():
            logger.info(
                "Closed prepared camera of a request refused after stop()",
                extra={
                    "event": "prepared_camera_discarded",
                    "camera_index": device.index if device else None,
                },
            )
