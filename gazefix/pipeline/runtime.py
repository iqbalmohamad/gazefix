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

    Every transition is decided from what the runtime owns: whether a worker
    thread has been started, whether one is alive, and whether a
    runtime-owned prepared-camera release is still outstanding. The runtime
    records two facts of its own: that ``stop()`` (or a failed ``start()``)
    has been requested, and, once nothing owned is left, that shutdown is
    final. ``STOPPED`` is a latch: it is entered exactly once, under the
    lifecycle lock, when no owned worker is alive and no runtime-owned
    release is outstanding, and it is never left. Work that reaches the
    runtime's cleanup thread after that point (a refused request's token) is
    a detached disposal owned by the cleanup thread, not runtime lifecycle
    work, so no later event can move the state back to ``STOPPING``.
    A shutdown that timed out with a worker still inside a driver call keeps
    reporting ``STOPPING`` until that thread has exited and every
    runtime-owned release has returned.
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
    handed to the runtime's own cleanup thread and tracked as outstanding
    shutdown work; the active camera is only ever released by the capture
    worker thread.

    The cleanup thread is created by and owned by this runtime; it is
    deliberately not injectable, so no other component (discovery, the
    window) can put work on it and mutate this runtime's lifecycle state.
    Cleanup other components own is theirs to track; the application
    aggregates all owners at its own shutdown.
    """

    def __init__(
        self,
        settings: AppSettings,
        on_status: Callable[[CaptureStatus], None] | None = None,
        processor: FrameProcessor | None = None,
        source_factory: SourceFactory | None = None,
    ) -> None:
        self._settings = settings
        # Owned, never shared: only this runtime submits to it, so its
        # ``outstanding`` count is runtime-owned work by construction.
        self._closer = PreparedCameraCloser("gazefix-runtime-prepared-close")
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
        # The STOPPED latch: set exactly once, under the lifecycle lock, when
        # nothing owned is alive or outstanding; never cleared. Refused-token
        # submission happens under the same lock, so a submission is either
        # observed by the latch decision or lands after it as a disposal.
        self._stop_finalized = False
        self._stop_logged = False

    @property
    def prepared_closer(self) -> PreparedCameraCloser:
        """The runtime-owned cleanup thread; exposed for application shutdown accounting.

        Only the runtime submits work to it. After the runtime has finalized,
        anything still (or newly) on it is a detached disposal, invisible to
        ``state`` but joinable here by the application within its deadline.
        """

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
        is returned unchanged, and a prepared camera the caller handed in is
        accepted for disposal by the runtime's cleanup thread (never released
        on the caller's thread, and never leaked). The hand-off happens under
        the lifecycle lock, the same lock under which shutdown finalizes, so
        exactly one of two things is true: the token was registered before the
        final check (it counts as runtime-owned cleanup, ``stop()`` cannot
        report success past it, and ``state`` stays ``STOPPING`` until it is
        released) or the runtime was already finalized (the token is a
        detached disposal of the cleanup thread and the latched ``STOPPED``
        is unaffected). ``stop() == True`` therefore can never race with new
        runtime-owned cleanup appearing afterwards.
        """

        with self._lifecycle_lock:
            accepted = not self._stop_requested
            if not accepted and prepared is not None:
                # Registered or disposed under the same lock that finalizes
                # shutdown; see the docstring. ``submit`` never blocks.
                self._closer.submit(prepared)
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
        no runtime-owned prepared-camera release is still outstanding. The
        check runs under the lifecycle lock and latches ``STOPPED`` (see
        ``RuntimeState``), so a ``True`` is final: the state stays
        ``STOPPED``, later calls return ``True`` at once, and no
        runtime-owned cleanup can appear afterwards, because refused-token
        registration is serialized under the same lock. Two things are kept
        apart: whether the configured deadline ran out during this call
        (logged as ``deadline_exhausted``) and whether owned work is still
        alive when the call returns (the return value and ``state``). A join
        that timed out but whose thread exited before the final check yields
        ``True`` and ``STOPPED``; a thread still inside an uncancellable
        driver call yields ``False`` and ``STOPPING``, and a later ``stop()``
        joins again against a fresh bounded deadline. Nothing here can turn a
        live thread into a reported success, and every call is bounded by one
        timeout.
        """

        with self._lifecycle_lock:
            first_call = not self._stop_requested
            self._stop_requested = True
            finalized = self._stop_finalized
        if finalized:
            # STOPPED is a latch: nothing owned can come back to life, so a
            # repeated stop() succeeds without re-running the wind-down.
            self._log_finalized(first_call=first_call, deadline_exhausted=False)
            return True
        waits = self._wind_down(self._settings.worker_join_timeout_s)
        return self._finish_shutdown(waits, first_call=first_call)

    @property
    def state(self) -> RuntimeState:
        """Current lifecycle state, computed from what the runtime owns right now.

        ``STOPPED`` latches on its first observation (see ``RuntimeState``),
        so this property is monotonic once shutdown has been requested:
        ``STOPPING`` can become ``STOPPED``, never the other way round.
        """

        with self._lifecycle_lock:
            if not self._stop_requested:
                started = self._capture.started or self._processor.started
                return RuntimeState.RUNNING if started else RuntimeState.NEW
            stopped, _, _, _ = self._latch_if_stopped_locked()
        return RuntimeState.STOPPED if stopped else RuntimeState.STOPPING

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
        # Hand unadopted prepared cameras to the cleanup thread now, so their
        # release overlaps the worker joins instead of starting only once the
        # joins have used up the deadline (a release that would have finished
        # in a millisecond was otherwise reported as still outstanding).
        self._submit_pending_prepared()
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
        # Second sweep for a token the worker orphaned while it was winding
        # down, then wait, still within the deadline, for the releases.
        self._submit_pending_prepared()
        cleanup_done = self._closer.join(max(0.0, deadline - time.perf_counter()))
        return capture_joined, processor_joined, cleanup_done

    def _submit_pending_prepared(self) -> None:
        """Hand the prepared cameras the worker will never adopt to the cleanup thread.

        After ``stop`` the worker has either exited (its own cleanup already
        ran and left nothing here) or is abandoned inside a driver call and
        may never reach that cleanup. Taking the tokens swaps them out under
        the worker's request lock, and the cleanup thread releases them, so
        the caller never blocks on a driver and no token is released twice.
        ``submit`` drops a token that was already claimed (it has an owner and
        no source left to release), so only real work counts as outstanding.
        """

        for prepared in self._capture.take_pending_prepared():
            self._closer.submit(prepared)

    def _latch_if_stopped_locked(self) -> tuple[bool, bool, bool, int]:
        """Read owned work and latch STOPPED if none is left; lifecycle lock held.

        Returns ``(stopped, capture_alive, processor_alive, cleanup_outstanding)``.
        The latch decision and the refused-token registration in
        ``select_camera`` share the lifecycle lock, so a registration is
        either counted here (no latch until it drains) or happens after the
        latch, where it can no longer change the lifecycle. Thread liveness
        only ever moves from alive to exited, so a latch taken here can never
        be contradicted later.
        """

        if self._stop_finalized:
            return True, False, False, 0
        capture_alive = self._capture.is_alive
        processor_alive = self._processor.is_alive
        cleanup_outstanding = self._closer.outstanding
        stopped = not (capture_alive or processor_alive or cleanup_outstanding)
        if stopped:
            self._stop_finalized = True
        return stopped, capture_alive, processor_alive, cleanup_outstanding

    def _log_finalized(self, *, first_call: bool, deadline_exhausted: bool) -> None:
        """Write the terminal ``pipeline_stopped`` line exactly once."""

        with self._lifecycle_lock:
            newly_logged = not self._stop_logged
            self._stop_logged = True
        if newly_logged:
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

    def _finish_shutdown(
        self, waits: tuple[bool, bool, bool], *, first_call: bool
    ) -> bool:
        """Reconcile the real state after all waits and log it once, truthfully."""

        deadline_exhausted = not all(waits)
        # The final check is what the return value reports: everything the
        # runtime owns, read after the last wait and immediately before
        # returning, under the lifecycle lock, so a worker that exited after
        # its join timed out is still counted as stopped and a refused-token
        # registration cannot slip between the check and the latch.
        with self._lifecycle_lock:
            stopped, capture_alive, processor_alive, cleanup_outstanding = (
                self._latch_if_stopped_locked()
            )
        if not stopped:
            logger.error(
                "Pipeline shutdown incomplete; a worker or a prepared-camera "
                "release is still outstanding",
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
            return False
        self._log_finalized(first_call=first_call, deadline_exhausted=deadline_exhausted)
        return True
