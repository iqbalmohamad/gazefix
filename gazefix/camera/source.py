"""OpenCV camera source with Windows backend fallback."""

from __future__ import annotations

import logging
import os
from threading import Event, Lock
import time
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from gazefix.camera.backends import ordered_backends_for_device
from gazefix.camera.environment import MSMF_HW_TRANSFORMS_ENV
from gazefix.camera.models import CameraBackend, CameraDevice, CameraOpenResult
from gazefix.config import AppSettings


logger = logging.getLogger(__name__)
Frame = NDArray[np.uint8]


class CameraOpenInterrupted(RuntimeError):
    """Raised when ``interrupt`` cancelled an open before it produced a camera."""


class CameraSource(Protocol):
    def open(self, device: CameraDevice) -> CameraOpenResult:
        """Open ``device`` and return only once it has delivered a frame.

        Implementations raise on failure. They must check for an interrupt
        between backend attempts so a superseded or shutting-down open stops
        as soon as the driver hands control back.
        """

    def read(self) -> tuple[bool, Frame | None]:
        ...

    def close(self) -> None:
        ...

    def interrupt(self) -> None:
        """Ask a blocked open or read to give up as soon as it safely can."""


class PreparedCamera:
    """A validated, already-open camera whose ownership transfers exactly once.

    Discovery produces one of these for the candidate the UI will select so the
    capture worker can adopt the open source instead of paying for a second
    driver open. ``claim`` hands the source to exactly one caller; whoever still
    holds an unclaimed instance when it is no longer needed calls
    ``close_if_unclaimed`` on a thread that may block briefly on release.
    """

    def __init__(
        self,
        device: CameraDevice,
        source: CameraSource,
        open_result: CameraOpenResult,
    ) -> None:
        self.device = device
        self.open_result = open_result
        self._source: CameraSource | None = source
        self._lock = Lock()

    def claim(self) -> tuple[CameraSource, CameraOpenResult] | None:
        with self._lock:
            source = self._source
            self._source = None
        if source is None:
            return None
        return source, self.open_result

    def close_if_unclaimed(self) -> bool:
        claimed = self.claim()
        if claimed is None:
            return False
        source, _ = claimed
        try:
            source.close()
        except Exception:
            logger.exception(
                "Closing an unclaimed prepared camera failed",
                extra={"event": "prepared_camera_close_error", "camera_index": self.device.index},
            )
        return True

    @property
    def is_pending(self) -> bool:
        with self._lock:
            return self._source is not None


class OpenCVCameraSource:
    """Own a single VideoCapture and try recoverable backend fallbacks.

    ``open`` counts as successful only after the backend also delivered a frame,
    so a backend that opens but never streams (a known Media Foundation failure
    mode) falls through to the next backend instead of being reported as open.

    Only the owning thread ever releases the capture. ``interrupt`` from another
    thread merely raises a flag that the owner honours at its next checkpoint.
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._capture: cv2.VideoCapture | None = None
        self._capture_lock = Lock()
        self._interrupted = Event()

    def open(self, device: CameraDevice) -> CameraOpenResult:
        # The interrupt flag is deliberately never cleared: a source is opened
        # once by its owner, and an interrupt that lands just before ``open``
        # starts must still cancel it.
        self.close()
        failures: list[str] = []
        for backend in ordered_backends_for_device(device.validated_backend):
            if self._interrupted.is_set():
                raise CameraOpenInterrupted("Camera open interrupted")
            result = self._open_backend(device, backend, failures)
            if result is not None:
                return result
        if self._interrupted.is_set():
            raise CameraOpenInterrupted("Camera open interrupted")
        attempted = ", ".join(failures) or "no available backend"
        raise RuntimeError(
            f"Camera index {device.index} could not be opened via {attempted}"
        )

    def _open_backend(
        self,
        device: CameraDevice,
        backend: CameraBackend,
        failures: list[str],
    ) -> CameraOpenResult | None:
        logger.info(
            "Opening camera",
            extra={
                "event": "camera_open_attempt",
                "camera_index": device.index,
                "backend_requested": backend.name,
            },
        )
        capture = cv2.VideoCapture()
        with self._capture_lock:
            if self._interrupted.is_set():
                raise CameraOpenInterrupted("Camera open interrupted")
            self._capture = capture
        # This is the call that a driver can hold for many seconds. OpenCV only
        # attaches the backend object after it returns, so nothing another thread
        # does to this VideoCapture can shorten it; ``interrupt`` only sets a
        # flag and this thread discards the capture as soon as it returns.
        started = time.perf_counter()
        opened = self._open_capture(capture, device.index, backend)
        open_ms = _elapsed_ms(started)
        if not opened or self._interrupted.is_set():
            self._discard(capture)
            if self._interrupted.is_set():
                raise CameraOpenInterrupted("Camera open interrupted")
            failures.append(backend.name)
            logger.warning(
                "Camera backend did not open",
                extra={
                    "event": "camera_open_failed",
                    "camera_index": device.index,
                    "backend_requested": backend.name,
                    "open_ms": open_ms,
                },
            )
            return None

        started = time.perf_counter()
        applied = self._apply_format(capture, backend)
        configure_ms = _elapsed_ms(started)
        result = CameraOpenResult(
            backend=backend,
            reported_backend=_reported_backend(capture),
            width=round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=float(capture.get(cv2.CAP_PROP_FPS)),
        )

        started = time.perf_counter()
        validated = self._validate_first_frame(capture)
        first_frame_ms = _elapsed_ms(started)
        if self._interrupted.is_set():
            self._discard(capture)
            raise CameraOpenInterrupted("Camera open interrupted")
        if not validated:
            self._discard(capture)
            failures.append(f"{backend.name} (opened but produced no frame)")
            logger.warning(
                "Camera backend opened but produced no frame",
                extra={
                    "event": "camera_open_no_frame",
                    "camera_index": device.index,
                    "backend_requested": backend.name,
                    "backend_reported": result.reported_backend,
                    "open_ms": open_ms,
                    "configure_ms": configure_ms,
                    "validation_ms": first_frame_ms,
                },
            )
            return None

        logger.info(
            "Camera opened",
            extra={
                "event": "camera_opened",
                "camera_index": device.index,
                "backend_requested": backend.name,
                "backend_reported": result.reported_backend,
                "width": result.width,
                "height": result.height,
                "fps": result.fps,
                "open_ms": open_ms,
                "configure_ms": configure_ms,
                "format_sets_applied": applied,
                "first_frame_ms": first_frame_ms,
                "msmf_hw_transforms": os.environ.get(MSMF_HW_TRANSFORMS_ENV),
            },
        )
        return result

    def _open_capture(
        self, capture: cv2.VideoCapture, index: int, backend: CameraBackend
    ) -> bool:
        """Open the backend, handing DirectShow its format up front.

        DirectShow builds its capture graph inside ``open`` and rebuilds it for
        every later ``set`` of width/height/FPS, so the requested format is passed
        as open parameters there and the graph is built once. Media Foundation
        applies open parameters through the same per-property renegotiation as
        ``set``, so it gains nothing from them and is configured afterwards,
        skipping properties the camera already reports at the requested value.
        """

        if backend.api_preference == cv2.CAP_DSHOW:
            params = [
                cv2.CAP_PROP_FRAME_WIDTH, self._settings.capture_width,
                cv2.CAP_PROP_FRAME_HEIGHT, self._settings.capture_height,
                cv2.CAP_PROP_FPS, int(round(self._settings.target_fps)),
            ]
            try:
                return capture.open(index, backend.api_preference, params)
            except TypeError:
                # OpenCV builds without the parameters overload
                pass
        return capture.open(index, backend.api_preference)

    def _apply_format(self, capture: cv2.VideoCapture, backend: CameraBackend) -> int:
        """Set width, height, and FPS only where the camera differs from the request.

        On Media Foundation every ``set`` of these properties renegotiates the
        stream even when the value is unchanged (``cap_msmf.cpp`` ``setProperty``
        -> ``configureVideoOutput``), so an unconditional triple costs three
        format negotiations per open. Returns the number of ``set`` calls made.
        """

        wanted = (
            (cv2.CAP_PROP_FRAME_WIDTH, float(self._settings.capture_width)),
            (cv2.CAP_PROP_FRAME_HEIGHT, float(self._settings.capture_height)),
            (cv2.CAP_PROP_FPS, float(self._settings.target_fps)),
        )
        applied = 0
        for prop, value in wanted:
            current = capture.get(prop)
            if abs(current - value) < 0.5:
                continue
            capture.set(prop, value)
            applied += 1
        # Not honoured by MSMF or DirectShow; kept as a hint for other backends.
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return applied

    def _validate_first_frame(self, capture: cv2.VideoCapture) -> bool:
        # Bounded by count and by wall clock: one failed Media Foundation read
        # already waits up to 10 s internally, so a stalled backend must not be
        # given that patience three times over before the next backend is tried.
        started = time.perf_counter()
        for attempt in range(self._settings.discovery_validation_reads):
            if self._interrupted.is_set():
                return False
            if attempt and (
                time.perf_counter() - started >= self._settings.open_validation_timeout_s
            ):
                return False
            success, frame = capture.read()
            if success and frame is not None and frame.size > 0:
                return True
            if attempt + 1 < self._settings.discovery_validation_reads:
                time.sleep(self._settings.read_retry_delay_s)
        return False

    def _discard(self, capture: cv2.VideoCapture) -> None:
        with self._capture_lock:
            if self._capture is capture:
                self._capture = None
        capture.release()

    def read(self) -> tuple[bool, Frame | None]:
        if self._interrupted.is_set():
            return False, None
        with self._capture_lock:
            capture = self._capture
        if capture is None or not capture.isOpened():
            return False, None
        success, frame = capture.read()
        if not success or frame is None or frame.size == 0:
            return False, None
        # Each successful OpenCV read returns a distinct ndarray. Marking it
        # read-only documents ownership until a future processor explicitly copies.
        frame.setflags(write=False)
        return True, frame

    def interrupt(self) -> None:
        """Flag the source so its owning thread gives up at the next checkpoint.

        Nothing is released here, on purpose. A blocked ``VideoCapture.open``
        cannot be cancelled from another thread (OpenCV attaches the backend
        object only after the driver returns), and releasing a capture while its
        owner is inside ``read`` or ``set`` destroys the Media Foundation source
        reader and callback under a running call (``cap_msmf.cpp``: ``close()``
        releases both while ``grabFrame`` may still be waiting on the callback).
        The owning thread checks the flag between backend attempts, between
        validation reads, and before every read, and releases the capture itself
        as soon as the current driver call returns.
        """

        self._interrupted.set()

    def close(self) -> None:
        with self._capture_lock:
            capture = self._capture
            self._capture = None
        if capture is not None:
            started = time.perf_counter()
            capture.release()
            logger.info(
                "Camera released",
                extra={"event": "camera_released", "release_ms": _elapsed_ms(started)},
            )


def _reported_backend(capture: cv2.VideoCapture) -> str:
    try:
        return capture.getBackendName()
    except cv2.error:
        return "unknown"


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)
