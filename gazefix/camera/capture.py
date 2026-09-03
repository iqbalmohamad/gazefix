"""Long-lived camera worker with explicit switching and recovery lifecycle."""

from __future__ import annotations

from dataclasses import replace
import logging
from threading import Event, Lock, Thread
import time
from typing import Callable

from gazefix.camera.backends import next_backend_after
from gazefix.camera.models import (
    CameraDevice,
    CameraOpenResult,
    CaptureState,
    CaptureStatus,
)
from gazefix.camera.source import (
    CameraSource,
    OpenCVCameraSource,
    PreparedCamera,
)
from gazefix.config import AppSettings
from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.frame_buffer import LatestValueBuffer
from gazefix.pipeline.processor import CapturedFrame


logger = logging.getLogger(__name__)
StatusCallback = Callable[[CaptureStatus], None]
SourceFactory = Callable[[AppSettings], CameraSource]

_PHASE_IDLE = "idle"
_PHASE_OPENING = "opening"
_PHASE_READING = "reading"


class CameraCaptureWorker:
    """Capture on one background thread; camera requests are latest-value commands.

    Every request gets a generation id. Statuses and frames carry the generation
    they belong to, a request that arrives while an open is in flight interrupts
    that open, and any status or frame for a superseded generation is dropped
    before it can reach a consumer.
    """

    def __init__(
        self,
        settings: AppSettings,
        output_buffer: LatestValueBuffer[CapturedFrame],
        metrics: PipelineMetrics,
        on_status: StatusCallback | None = None,
        source_factory: SourceFactory = OpenCVCameraSource,
    ) -> None:
        self._settings = settings
        self._output = output_buffer
        self._metrics = metrics
        self._on_status = on_status or (lambda _status: None)
        self._source_factory = source_factory
        self._stop_event = Event()
        self._command_event = Event()
        self._request_lock = Lock()
        self._requested_device: CameraDevice | None = None
        self._requested_prepared: PreparedCamera | None = None
        self._orphaned_prepared: list[PreparedCamera] = []
        self._request_id = 0
        self._active_source_lock = Lock()
        self._active_source: CameraSource | None = None
        self._active_phase = _PHASE_IDLE
        self._status_lock = Lock()
        self._last_status: CaptureStatus | None = None
        self._thread = Thread(
            target=self._run, name="gazefix-camera-capture", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def request_camera(
        self, device: CameraDevice | None, prepared: PreparedCamera | None = None
    ) -> int:
        """Request a switch without waiting for release/open operations.

        ``prepared`` is an already-open, validated source for ``device`` that
        the worker adopts instead of opening the camera a second time. Its
        ownership passes to the worker here; a prepared camera belonging to a
        request that is superseded before it is applied is closed on the worker
        thread, never on the caller's.
        """

        with self._request_lock:
            self._request_id += 1
            request_id = self._request_id
            self._requested_device = device
            previous = self._requested_prepared
            self._requested_prepared = prepared
            if previous is not None:
                self._orphaned_prepared.append(previous)
        self._command_event.set()
        self._abort_open_in_progress()
        return request_id

    def stop(self) -> None:
        # Flags first, so a read that lands while STOPPING is being published
        # cannot re-emit RUNNING after it.
        self._stop_event.set()
        self._command_event.set()
        self._abort_open_in_progress()
        self._emit(CaptureState.STOPPING, "Stopping camera worker")

    def interrupt(self) -> None:
        """Flag the active source so its next checkpoint gives up.

        Shutdown calls this after a grace period. It never releases a camera
        from this thread: a blocked driver open cannot be cancelled, and a
        release under a running read would corrupt the backend, so the worker
        thread releases the source itself as soon as the driver call returns.
        """

        with self._active_source_lock:
            source = self._active_source
        if source is not None:
            source.interrupt()

    def join(self, timeout: float | None = None) -> bool:
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def close_pending_prepared(self) -> None:
        """Close prepared cameras the worker will never adopt (after it stopped)."""

        self._close_orphaned_prepared()
        with self._request_lock:
            pending = self._requested_prepared
            self._requested_prepared = None
        if pending is not None:
            pending.close_if_unclaimed()

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _current_request(
        self,
    ) -> tuple[int, CameraDevice | None, PreparedCamera | None]:
        with self._request_lock:
            return self._request_id, self._requested_device, self._requested_prepared

    def _superseded(self, request_id: int) -> bool:
        if self._stop_event.is_set():
            return True
        with self._request_lock:
            return self._request_id != request_id

    def _abort_open_in_progress(self) -> None:
        # Held across the call so the worker cannot move the source into the
        # reading phase underneath us; an interrupt during open is flag-only.
        with self._active_source_lock:
            if self._active_phase == _PHASE_OPENING and self._active_source is not None:
                self._active_source.interrupt()

    def _run(self) -> None:
        logger.info(
            "Camera capture worker started", extra={"event": "capture_worker_started"}
        )
        # Request ids start at 1; 0 is the never-requested state, already applied.
        applied_request_id = 0
        active_device: CameraDevice | None = None
        source: CameraSource | None = None
        open_result: CameraOpenResult | None = None
        consecutive_failures = 0
        open_failures = 0
        self._emit(CaptureState.IDLE, "No camera selected")

        try:
            while not self._stop_event.is_set():
                self._close_orphaned_prepared()
                request_id, requested_device, prepared = self._current_request()
                if request_id != applied_request_id:
                    # Consume the wake-up for this request before re-reading it,
                    # so a stale event cannot shorten a later retry wait while a
                    # request arriving after the re-read still sets it again.
                    self._command_event.clear()
                    request_id, requested_device, prepared = self._current_request()
                    source = self._release_source(source)
                    open_result = None
                    active_device = requested_device
                    applied_request_id = request_id
                    consecutive_failures = 0
                    open_failures = 0
                    self._output.clear()
                    if active_device is None:
                        self._emit(
                            CaptureState.IDLE,
                            "Camera released; no camera selected",
                            request_id=applied_request_id,
                        )

                if active_device is None:
                    self._wait_for_command(0.25)
                    continue

                if source is None:
                    source, open_result = self._open_source(
                        active_device, applied_request_id, prepared, open_failures
                    )
                    if source is None:
                        open_failures += 1
                        continue
                    # A fresh source gets the full transient-failure allowance;
                    # otherwise one bad read after a reopen would reopen again.
                    consecutive_failures = 0
                    open_failures = 0
                    # Remember the backend that actually delivered frames so a
                    # reopen starts from it rather than from the discovery result.
                    active_device = replace(
                        active_device, validated_backend=open_result.backend
                    )

                read_started = time.perf_counter()
                success, frame = self._read(source)
                read_s = time.perf_counter() - read_started
                if self._stop_event.is_set():
                    break
                current_request_id, _, _ = self._current_request()
                if current_request_id != applied_request_id:
                    continue

                if success and frame is not None:
                    consecutive_failures = 0
                    captured_at_ns = time.perf_counter_ns()
                    self._metrics.record_capture()
                    self._output.publish(
                        CapturedFrame(
                            frame=frame,
                            captured_at_ns=captured_at_ns,
                            camera_request_id=applied_request_id,
                        )
                    )
                    with self._status_lock:
                        last_status = self._last_status
                    if (
                        last_status is None
                        or last_status.state is not CaptureState.RUNNING
                    ) and not self._stop_event.is_set():
                        self._emit(
                            CaptureState.RUNNING,
                            "Camera capture recovered",
                            active_device,
                            open_result,
                            applied_request_id,
                        )
                    continue

                consecutive_failures += 1
                self._metrics.record_read_failure()
                stalled = read_s >= self._settings.stalled_read_s
                if stalled:
                    # The backend itself waited this long for a frame (Media
                    # Foundation waits 10 s); that is a stall, not a dropped frame.
                    logger.error(
                        "Camera read stalled; reopening",
                        extra={
                            "event": "capture_read_stalled",
                            "camera_index": active_device.index,
                            "read_ms": round(read_s * 1000.0, 1),
                        },
                    )
                if not stalled and consecutive_failures < self._settings.transient_read_failures:
                    self._emit(
                        CaptureState.DEGRADED,
                        (
                            "Temporary frame-read failure "
                            f"({consecutive_failures}/"
                            f"{self._settings.transient_read_failures})"
                        ),
                        active_device,
                        open_result,
                        applied_request_id,
                    )
                    self._wait_for_command(self._settings.read_retry_delay_s)
                    continue

                if not stalled:
                    logger.error(
                        "Repeated camera read failures; reopening",
                        extra={
                            "event": "capture_read_failure_limit",
                            "camera_index": active_device.index,
                            "consecutive_failures": consecutive_failures,
                        },
                    )
                source = self._release_source(source)
                open_result = None
                self._output.clear()
                # The backend that stopped streaming is demoted for the reopen so
                # fallback also works from the steady-state read loop.
                active_device = replace(
                    active_device,
                    validated_backend=next_backend_after(active_device.validated_backend),
                )
                self._emit(
                    CaptureState.RETRYING,
                    "Camera disconnected or stopped responding; retrying",
                    active_device,
                    request_id=applied_request_id,
                )
                self._wait_for_command(self._settings.reconnect_delay_s)
        except Exception:
            logger.exception(
                "Unexpected camera worker error",
                extra={"event": "capture_worker_error"},
            )
            self._emit(CaptureState.ERROR, "Unexpected camera worker error")
        finally:
            self._release_source(source)
            self.close_pending_prepared()
            self._emit(CaptureState.STOPPED, "Camera worker stopped")
            logger.info(
                "Camera capture worker stopped",
                extra={"event": "capture_worker_stopped"},
            )

    def _open_source(
        self,
        device: CameraDevice,
        request_id: int,
        prepared: PreparedCamera | None,
        open_failures: int = 0,
    ) -> tuple[CameraSource | None, CameraOpenResult | None]:
        """Adopt the prepared camera or open a fresh one for ``request_id``.

        Returns ``(None, None)`` when the request was superseded or stopped
        meanwhile (silently, so no stale status reaches the UI) or when the
        open failed (after emitting ERROR and waiting for the retry delay,
        which backs off with ``open_failures``).
        """

        if prepared is not None and prepared.device != device:
            prepared.close_if_unclaimed()
            prepared = None
        claimed = prepared.claim() if prepared is not None else None
        if claimed is not None:
            source, open_result = claimed
            if self._superseded(request_id):
                self._safe_close(source)
                return None, None
            self._set_active_source(source, _PHASE_READING)
            logger.info(
                "Adopted validated camera from discovery",
                extra={
                    "event": "camera_adopted",
                    "camera_index": device.index,
                    "backend_reported": open_result.reported_backend,
                },
            )
            self._emit(
                CaptureState.RUNNING,
                _running_message(open_result),
                device,
                open_result,
                request_id,
            )
            return source, open_result

        if open_failures == 0:
            # Later attempts keep the ERROR text on screen instead of flickering
            # between "Opening" and "Could not open" on every retry.
            self._emit(
                CaptureState.STARTING,
                f"Opening {device.display_name}",
                device,
                request_id=request_id,
            )
        try:
            source = self._source_factory(self._settings)
        except Exception as exc:
            return self._open_failed(device, request_id, exc, open_failures)
        self._set_active_source(source, _PHASE_OPENING)
        if self._superseded(request_id):
            self._set_active_source(None)
            self._safe_close(source)
            return None, None
        try:
            open_result = source.open(device)
        except Exception as exc:
            self._set_active_source(None)
            self._safe_close(source)
            if self._superseded(request_id):
                logger.info(
                    "Camera open abandoned; request superseded or stopping",
                    extra={
                        "event": "capture_open_abandoned",
                        "camera_index": device.index,
                        "request_id": request_id,
                    },
                )
                return None, None
            return self._open_failed(device, request_id, exc, open_failures)
        if self._superseded(request_id):
            self._set_active_source(None)
            self._safe_close(source)
            return None, None
        self._set_active_source(source, _PHASE_READING)
        self._emit(
            CaptureState.RUNNING,
            _running_message(open_result),
            device,
            open_result,
            request_id,
        )
        return source, open_result

    def _open_failed(
        self, device: CameraDevice, request_id: int, exc: Exception, open_failures: int
    ) -> tuple[None, None]:
        delay = self._reconnect_delay(open_failures)
        logger.warning(
            "Camera open failed; will retry",
            extra={
                "event": "capture_open_failed",
                "camera_index": device.index,
                "error": str(exc),
                "attempt": open_failures + 1,
                "retry_delay_s": delay,
            },
        )
        self._emit(
            CaptureState.ERROR,
            f"Could not open camera: {exc}",
            device,
            request_id=request_id,
        )
        self._wait_for_command(delay)
        return None, None

    def _reconnect_delay(self, open_failures: int) -> float:
        """Exponential backoff from reconnect_delay_s, capped at reconnect_delay_max_s."""

        base = self._settings.reconnect_delay_s
        return min(base * (2 ** open_failures), self._settings.reconnect_delay_max_s)

    def _read(self, source: CameraSource) -> tuple[bool, object]:
        try:
            return source.read()
        except Exception as exc:
            # A backend exception is a failed read, not a reason to end capture.
            logger.warning(
                "Camera read raised; treating as a failed read",
                extra={"event": "capture_read_error", "error": str(exc)},
            )
            return False, None

    def _release_source(self, source: CameraSource | None) -> None:
        self._set_active_source(None)
        if source is not None:
            self._safe_close(source)
        return None

    def _safe_close(self, source: CameraSource) -> None:
        try:
            source.close()
        except Exception as exc:
            logger.warning(
                "Camera close raised; continuing",
                extra={"event": "capture_close_error", "error": str(exc)},
            )

    def _close_orphaned_prepared(self) -> None:
        with self._request_lock:
            orphans = self._orphaned_prepared
            self._orphaned_prepared = []
        for orphan in orphans:
            if orphan.close_if_unclaimed():
                logger.info(
                    "Closed prepared camera of a superseded request",
                    extra={
                        "event": "prepared_camera_discarded",
                        "camera_index": orphan.device.index,
                    },
                )

    def _set_active_source(
        self, source: CameraSource | None, phase: str = _PHASE_IDLE
    ) -> None:
        with self._active_source_lock:
            self._active_source = source
            self._active_phase = phase if source is not None else _PHASE_IDLE

    def _wait_for_command(self, timeout: float) -> None:
        self._command_event.wait(timeout)
        self._command_event.clear()

    def _emit(
        self,
        state: CaptureState,
        message: str,
        camera: CameraDevice | None = None,
        open_result: CameraOpenResult | None = None,
        request_id: int = -1,
    ) -> None:
        status = CaptureStatus(state, message, camera, open_result, request_id)
        with self._status_lock:
            if status == self._last_status:
                return
            self._last_status = status
        logger.info(
            message,
            extra={
                "event": "capture_state",
                "capture_state": state.value,
                "camera_index": camera.index if camera else None,
                "request_id": request_id,
            },
        )
        try:
            self._on_status(status)
        except Exception:
            logger.exception(
                "Capture status callback failed",
                extra={"event": "capture_status_callback_error"},
            )


def _running_message(open_result: CameraOpenResult) -> str:
    return (
        f"Running on {open_result.reported_backend} at "
        f"{open_result.width}×{open_result.height}"
    )
