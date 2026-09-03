"""OpenCV camera source with Windows backend fallback."""

from __future__ import annotations

import logging
from threading import Event, Lock
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from gazefix.camera.backends import ordered_backends_for_device
from gazefix.camera.models import CameraDevice, CameraOpenResult
from gazefix.config import AppSettings


logger = logging.getLogger(__name__)
Frame = NDArray[np.uint8]


class CameraSource(Protocol):
    def open(self, device: CameraDevice) -> CameraOpenResult:
        ...

    def read(self) -> tuple[bool, Frame | None]:
        ...

    def close(self) -> None:
        ...

    def interrupt(self) -> None:
        ...


class OpenCVCameraSource:
    """Own a single VideoCapture and try recoverable backend fallbacks."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._capture: cv2.VideoCapture | None = None
        self._capture_lock = Lock()
        self._interrupted = Event()

    def open(self, device: CameraDevice) -> CameraOpenResult:
        self.close()
        self._interrupted.clear()
        failures: list[str] = []
        for backend in ordered_backends_for_device(device.validated_backend):
            logger.info(
                "Opening camera",
                extra={
                    "event": "camera_open_attempt",
                    "camera_index": device.index,
                    "backend_requested": backend.name,
                },
            )
            # Register an empty capture before the potentially blocking open call.
            # Another thread can then release it to cancel shutdown promptly.
            capture = cv2.VideoCapture()
            with self._capture_lock:
                if self._interrupted.is_set():
                    raise RuntimeError("Camera open interrupted")
                self._capture = capture
            opened = capture.open(device.index, backend.api_preference)
            if self._interrupted.is_set():
                capture.release()
                raise RuntimeError("Camera open interrupted")
            if not opened:
                with self._capture_lock:
                    if self._capture is capture:
                        self._capture = None
                capture.release()
                failures.append(backend.name)
                logger.warning(
                    "Camera backend did not open",
                    extra={
                        "event": "camera_open_failed",
                        "camera_index": device.index,
                        "backend_requested": backend.name,
                    },
                )
                continue

            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings.capture_width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings.capture_height)
            capture.set(cv2.CAP_PROP_FPS, self._settings.target_fps)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            result = CameraOpenResult(
                backend=backend,
                reported_backend=_reported_backend(capture),
                width=round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                height=round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                fps=float(capture.get(cv2.CAP_PROP_FPS)),
            )
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
                },
            )
            return result

        attempted = ", ".join(failures) or "no available backend"
        raise RuntimeError(
            f"Camera index {device.index} could not be opened via {attempted}"
        )

    def read(self) -> tuple[bool, Frame | None]:
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
        """Best-effort release used to unblock a driver read during shutdown."""

        self._interrupted.set()
        with self._capture_lock:
            capture = self._capture
            self._capture = None
        if capture is not None:
            capture.release()

    def close(self) -> None:
        with self._capture_lock:
            capture = self._capture
            self._capture = None
        if capture is not None:
            capture.release()
            logger.info("Camera released", extra={"event": "camera_released"})


def _reported_backend(capture: cv2.VideoCapture) -> str:
    try:
        return capture.getBackendName()
    except cv2.error:
        return "unknown"
