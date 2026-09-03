"""Lifecycle owner connecting capture, processing, and frame consumers."""

from __future__ import annotations

from enum import Enum
import logging
from threading import Lock
import time
from typing import Callable

from gazefix.camera.capture import CameraCaptureWorker, SourceFactory
from gazefix.camera.models import CameraDevice, CaptureStatus
from gazefix.camera.source import (
    OpenCVCameraSource,
    PreparedCamera,
    PreparedCameraCloser,
)
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

    Every transition is decided from what the runtime actually owns at the
    moment of the read: whether a worker thread has been started, whether one
    is alive, and whether a prepared-camera release handed to the cleanup
    thread is still outstanding. The only fact the runtime records itself is
    that ``stop()`` (or a failed ``start()``) has been requested. A shutdown
    that timed out with a worker still inside a driver call therefore keeps
    reporting ``STOPPING`` until that thread has actually exited and every
    handed-off release has returned.
    """

    NEW = "new"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


class PipelineRuntime:
    """Own all M0 workers and expose non-blocking UI-facing operations.

    A runtime is single-use: ``start()`` launches both worker threads once and
    ``stop()`` winds them down. Python threads cannot be restarted, so there is
    deliberately no restart path; ``start()`` after ``stop()``, or after a
    ``start()`` that failed part-way, raises rather than pretending.

    Nothing UI-facing here blocks on a camera driver. Releasing a camera is a
    driver call with no upper bound, so every release the runtime itself must
    perform (prepared cameras the capture worker can no longer adopt) is
    handed to ``prepared_closer`` and tracked as outstanding shutdown work;
    the active camera is only ever released by the capture worker thread.
    """

    def __init__(
        self,
        settings: AppSettings,
        on_status: Callable[[CaptureStatus], None] | None = None,
        processor: FrameProcessor | None = None,
        source_factory: SourceFactory | None = None,
        prepared_closer: PreparedCameraCloser | None = None,
    ) -> None:
        self._settings = settings
        self._closer = prepared_closer or PreparedCameraCloser()
        self._capture_buffer: LatestValueBuffer[CapturedFrame] = LatestValueBuffer()
        self._output_buffer: LatestValueBuffer[ProcessedFrame] = LatestValueBuffer()
        self._metrics = PipelineMetrics()
        self._capture = CameraCaptureWorker(
            settings=settings,
            output_buffer=self._capture_buffer,
            metrics=self._metrics,
            on_status=on_status,
            source_factory=source_factory or OpenCVCameraSource,
            prepared_closer=self._closer,
        )
        self._processor = ProcessingWorker(
            self._capture_buffer,
            self._output_buffer,
            processor or PassthroughProcessor(),
            self._metrics,
        )
        self._request_lock = Lock()
        self._current_request_id = 0
        # Guards the two lifecycle flags below. It is held only for flag reads
        # and writes, across the (non-blocking) thread launches in ``start``,
        # and in ``select_camera`` across the publish of a request; never
        # across a join or a driver call, so no UI-facing call can block on a
        # shutdown that is waiting for a camera.
        self._lifecycle_lock = Lock()
        self._stop_requested = False
        self._stop_finalized = False

    @property
    def prepared_closer(self) -> PreparedCameraCloser:
        """The cleanup thread that releases prepared cameras on the runtime's behalf."""

        return self._closer

    def start(self) -> None:
        """Start both workers exactly once, or leave nothing running.

        Starting is transactional: if launching a worker raises after another
        was already launched, the runtime marks itself spent, signals every
        worker that did start, joins them against one bounded deadline, and
        re-raises the original error. A caller therefore never inherits a
        live thread from a failed ``start()``; if a started worker outlives
        the deadline, ``state`` reports it and ``stop()`` keeps tracking it.
        """

        with self._lifecycle_lock:
            if self._stop_requested:
                raise RuntimeError(
                    "PipelineRuntime cannot be restarted after stop(); "
                    "create a new runtime"
                )
            if self._capture.started or self._processor.started:
                return
            failure: BaseException | None = None
            try:
                self._processor.start()
                self._capture.start()
            except BaseException as exc:  # noqa: BLE001  (re-raised below)
                # Whatever raised, a thread that did start must not be leaked;
                # the runtime is spent from here on.
                failure = exc
                self._stop_requested = True
        if failure is None:
            return
        waits = self._wind_down(self._settings.worker_join_timeout_s)
        stopped = self._finish_shutdown(waits, first_call=True)
        logger.error(
            "Pipeline startup failed; started workers were wound down",
            extra={
                "event": "pipeline_start_failed",
                "error": str(failure),
                "capture_started": self._capture.started,
                "processor_started": self._processor.started,
                "stopped": stopped,
            },
        )
        raise failure

    def select_camera(
        self, device: CameraDevice | None, prepared: PreparedCamera | None = None
    ) -> int:
        """Request a camera change and return its generation identifier.

        ``prepared`` is an already-open validated source for ``device`` (from
        discovery) that the capture worker adopts instead of reopening.

        Once ``stop()`` has been requested no worker will ever apply a request,
        so the request is refused: nothing is published, the current generation
        is returned unchanged, and a prepared camera is handed to the cleanup
        thread (never released on the caller's thread).
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
                self._closer.submit(prepared)
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
        """Wind down everything the runtime owns within ``worker_join_timeout_s``.

        Returns ``True`` only when, at the final check made after every wait
        and immediately before returning, no owned worker thread is alive and
        no prepared-camera release handed to the cleanup thread is still
        outstanding. Two things are kept apart: whether the configured
        deadline ran out during this call (logged as ``deadline_exhausted``)
        and whether owned work is still alive when the call returns (the
        return value and ``state``). A join that timed out but whose thread
        exited before the final check therefore yields ``True`` and
        ``STOPPED``; a thread still inside an uncancellable driver call
        yields ``False`` and ``STOPPING``, and a later ``stop()`` joins again
        against a fresh bounded deadline. Nothing here can turn a live thread
        into a reported success, and every call is bounded by one timeout.
        """

        with self._lifecycle_lock:
            first_call = not self._stop_requested
            self._stop_requested = True
        waits = self._wind_down(self._settings.worker_join_timeout_s)
        return self._finish_shutdown(waits, first_call=first_call)

    @property
    def state(self) -> RuntimeState:
        """Current lifecycle state, computed from what the runtime owns right now."""

        with self._lifecycle_lock:
            stop_requested = self._stop_requested
        if not stop_requested:
            started = self._capture.started or self._processor.started
            return RuntimeState.RUNNING if started else RuntimeState.NEW
        if self.workers_alive or self._closer.outstanding:
            return RuntimeState.STOPPING
        return RuntimeState.STOPPED

    @property
    def workers_alive(self) -> bool:
        return self._capture.is_alive or self._processor.is_alive

    def _wind_down(self, timeout: float) -> tuple[bool, bool, bool]:
        """Signal, bounded-join, and hand off cleanup; report which waits completed.

        Safe for workers that never started: signalling them is a no-op and
        their ``join`` returns at once. Called without the lifecycle lock.
        """

        deadline = time.perf_counter() + timeout
        self._capture.stop()
        self._processor.stop()
        # A normal webcam read returns promptly; letting the owning thread
        # close the source avoids backend deadlocks caused by concurrent
        # release/read.
        capture_joined = self._capture.join(min(0.5, timeout * 0.25))
        if not capture_joined:
            # Flag the source so the worker gives up at its next checkpoint.
            # No release happens from this thread: a blocked driver open
            # cannot be cancelled, and a blocked read returns on the backend's
            # own timeout, after which the worker releases the camera itself.
            self._capture.interrupt()
            capture_joined = self._capture.join(
                max(0.0, deadline - time.perf_counter())
            )
        processor_joined = self._processor.join(
            max(0.0, deadline - time.perf_counter())
        )
        # Prepared cameras the worker will never adopt: after ``stop`` the
        # worker has either exited (its own cleanup already ran and left
        # nothing here) or is abandoned inside a driver call and may never
        # reach that cleanup. Taking the tokens swaps them out under the
        # worker's request lock, and the cleanup thread releases them, so the
        # caller never blocks on a driver and no token is released twice.
        for prepared in self._capture.take_pending_prepared():
            self._closer.submit(prepared)
        cleanup_done = self._closer.join(max(0.0, deadline - time.perf_counter()))
        return capture_joined, processor_joined, cleanup_done

    def _finish_shutdown(
        self, waits: tuple[bool, bool, bool], *, first_call: bool
    ) -> bool:
        """Reconcile the real state after all waits and log it once, truthfully."""

        deadline_exhausted = not all(waits)
        # The final check is what the return value reports: everything the
        # runtime owns, read after the last wait and immediately before
        # returning, so a worker that exited after its join timed out is
        # still counted as stopped.
        capture_alive = self._capture.is_alive
        processor_alive = self._processor.is_alive
        cleanup_outstanding = self._closer.outstanding
        stopped = not (capture_alive or processor_alive or cleanup_outstanding)
        with self._lifecycle_lock:
            newly_finalized = stopped and not self._stop_finalized
            self._stop_finalized = self._stop_finalized or stopped
        if not stopped:
            logger.error(
                "Pipeline shutdown incomplete; owned work is still alive",
                extra={
                    "event": "pipeline_shutdown_timeout",
                    "capture_alive": capture_alive,
                    "processor_alive": processor_alive,
                    "cleanup_outstanding": cleanup_outstanding,
                    "deadline_exhausted": deadline_exhausted,
                    "timeout_s": self._settings.worker_join_timeout_s,
                    "repeated_stop": not first_call,
                },
            )
        elif newly_finalized:
            logger.info(
                "Pipeline stopped"
                + (
                    "; a wait ran out of time but every worker exited before return"
                    if deadline_exhausted
                    else ""
                ),
                extra={
                    "event": "pipeline_stopped",
                    "deadline_exhausted": deadline_exhausted,
                    "after_timeout": not first_call,
                },
            )
        else:
            logger.debug(
                "Pipeline already stopped", extra={"event": "pipeline_stop_repeated"}
            )
        return stopped
