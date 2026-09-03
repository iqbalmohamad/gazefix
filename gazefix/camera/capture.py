"""Long-lived camera worker with explicit switching and recovery lifecycle."""

from __future__ import annotations

import logging
from threading import Event, Lock, Thread
import time
from typing import Callable

from gazefix.camera.models import (
    CameraDevice,
    CameraOpenResult,
    CaptureState,
    CaptureStatus,
)
from gazefix.camera.source import CameraSource, OpenCVCameraSource
from gazefix.config import AppSettings
from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.frame_buffer import LatestValueBuffer
from gazefix.pipeline.processor import CapturedFrame


logger = logging.getLogger(__name__)
StatusCallback = Callable[[CaptureStatus], None]
SourceFactory = Callable[[AppSettings], CameraSource]


class CameraCaptureWorker:
    """Capture on one background thread; camera requests are latest-value commands."""

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
        self._request_id = 0
        self._active_source_lock = Lock()
        self._active_source: CameraSource | None = None
        self._last_status: CaptureStatus | None = None
        self._thread = Thread(
            target=self._run, name="gazefix-camera-capture", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def request_camera(self, device: CameraDevice | None) -> int:
        """Request a switch without waiting for release/open operations."""

        with self._request_lock:
            self._request_id += 1
            self._requested_device = device
            request_id = self._request_id
        self._command_event.set()
        return request_id

    def stop(self) -> None:
        self._emit(CaptureState.STOPPING, "Stopping camera worker")
        self._stop_event.set()
        self._command_event.set()

    def interrupt(self) -> None:
        """Best-effort fallback for an open/read that ignores the stop request."""

        with self._active_source_lock:
            source = self._active_source
        if source is not None:
            source.interrupt()

    def join(self, timeout: float | None = None) -> bool:
        self._thread.join(timeout)
        return not self._thread.is_alive()

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _current_request(self) -> tuple[int, CameraDevice | None]:
        with self._request_lock:
            return self._request_id, self._requested_device

    def _run(self) -> None:
        logger.info(
            "Camera capture worker started", extra={"event": "capture_worker_started"}
        )
        applied_request_id = -1
        active_device: CameraDevice | None = None
        source: CameraSource | None = None
        open_result = None
        consecutive_failures = 0
        self._emit(CaptureState.IDLE, "No camera selected")

        try:
            while not self._stop_event.is_set():
                request_id, requested_device = self._current_request()
                if request_id != applied_request_id:
                    if source is not None:
                        source.close()
                        self._set_active_source(None)
                    source = None
                    open_result = None
                    active_device = requested_device
                    applied_request_id = request_id
                    consecutive_failures = 0
                    self._output.clear()
                    if active_device is None:
                        self._emit(
                            CaptureState.IDLE,
                            "Camera released; no camera selected",
                        )

                if active_device is None:
                    self._wait_for_command(0.25)
                    continue

                if source is None:
                    self._emit(
                        CaptureState.STARTING,
                        f"Opening {active_device.display_name}",
                        active_device,
                    )
                    source = self._source_factory(self._settings)
                    self._set_active_source(source)
                    try:
                        open_result = source.open(active_device)
                    except Exception as exc:
                        logger.warning(
                            "Camera open failed; will retry",
                            extra={
                                "event": "capture_open_failed",
                                "camera_index": active_device.index,
                                "error": str(exc),
                            },
                        )
                        source.close()
                        self._set_active_source(None)
                        source = None
                        self._emit(
                            CaptureState.ERROR,
                            f"Could not open camera: {exc}",
                            active_device,
                        )
                        self._wait_for_command(self._settings.reconnect_delay_s)
                        continue
                    self._emit(
                        CaptureState.RUNNING,
                        (
                            f"Running on {open_result.reported_backend} at "
                            f"{open_result.width}×{open_result.height}"
                        ),
                        active_device,
                        open_result,
                    )

                success, frame = source.read()
                if self._stop_event.is_set():
                    break
                current_request_id, _ = self._current_request()
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
                    if self._last_status is None or (
                        self._last_status.state is not CaptureState.RUNNING
                    ):
                        self._emit(
                            CaptureState.RUNNING,
                            "Camera capture recovered",
                            active_device,
                            open_result,
                        )
                    continue

                consecutive_failures += 1
                self._metrics.record_read_failure()
                if consecutive_failures < self._settings.transient_read_failures:
                    self._emit(
                        CaptureState.DEGRADED,
                        (
                            "Temporary frame-read failure "
                            f"({consecutive_failures}/"
                            f"{self._settings.transient_read_failures})"
                        ),
                        active_device,
                        open_result,
                    )
                    self._wait_for_command(self._settings.read_retry_delay_s)
                    continue

                logger.error(
                    "Repeated camera read failures; reopening",
                    extra={
                        "event": "capture_read_failure_limit",
                        "camera_index": active_device.index,
                        "consecutive_failures": consecutive_failures,
                    },
                )
                source.close()
                self._set_active_source(None)
                source = None
                self._output.clear()
                self._emit(
                    CaptureState.RETRYING,
                    "Camera disconnected or stopped responding; retrying",
                    active_device,
                )
                self._wait_for_command(self._settings.reconnect_delay_s)
        except Exception:
            logger.exception(
                "Unexpected camera worker error",
                extra={"event": "capture_worker_error"},
            )
            self._emit(CaptureState.ERROR, "Unexpected camera worker error")
        finally:
            if source is not None:
                source.close()
            self._set_active_source(None)
            self._emit(CaptureState.STOPPED, "Camera worker stopped")
            logger.info(
                "Camera capture worker stopped",
                extra={"event": "capture_worker_stopped"},
            )

    def _set_active_source(self, source: CameraSource | None) -> None:
        with self._active_source_lock:
            self._active_source = source

    def _wait_for_command(self, timeout: float) -> None:
        self._command_event.wait(timeout)
        self._command_event.clear()

    def _emit(
        self,
        state: CaptureState,
        message: str,
        camera: CameraDevice | None = None,
        open_result: CameraOpenResult | None = None,
    ) -> None:
        status = CaptureStatus(state, message, camera, open_result)
        if status == self._last_status:
            return
        self._last_status = status
        logger.info(
            message,
            extra={
                "event": "capture_state",
                "capture_state": state.value,
                "camera_index": camera.index if camera else None,
            },
        )
        try:
            self._on_status(status)
        except Exception:
            logger.exception(
                "Capture status callback failed",
                extra={"event": "capture_status_callback_error"},
            )
