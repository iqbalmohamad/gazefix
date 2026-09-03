"""Validated numerical camera probing performed away from the UI thread."""

from __future__ import annotations

import logging
from threading import Event, Lock, Thread
import time
from typing import Callable

from gazefix.camera.models import CameraDevice
from gazefix.camera.source import CameraSource, OpenCVCameraSource
from gazefix.config import AppSettings


logger = logging.getLogger(__name__)
Probe = Callable[[int], CameraDevice | None]


def probe_camera(
    index: int,
    settings: AppSettings,
    source_factory: Callable[[AppSettings], CameraSource] = OpenCVCameraSource,
    stop_event: Event | None = None,
    on_source: Callable[[CameraSource | None], None] | None = None,
) -> CameraDevice | None:
    """Return a candidate only after both opening and reading a real frame."""

    candidate = CameraDevice(index=index)
    source = source_factory(settings)
    if on_source is not None:
        on_source(source)
    try:
        if stop_event is not None and stop_event.is_set():
            return None
        result = source.open(candidate)
        for _ in range(settings.discovery_validation_reads):
            if stop_event is not None and stop_event.is_set():
                return None
            success, frame = source.read()
            if success and frame is not None:
                return CameraDevice(index=index, validated_backend=result.backend)
            time.sleep(settings.read_retry_delay_s)
    except Exception as exc:
        logger.info(
            "Camera candidate validation failed",
            extra={
                "event": "camera_probe_failed",
                "camera_index": index,
                "error": str(exc),
            },
        )
    finally:
        source.close()
        if on_source is not None:
            on_source(None)
    return None


def discover_camera_devices(
    settings: AppSettings,
    stop_event: Event | None = None,
    probe: Probe | None = None,
) -> list[CameraDevice]:
    """Probe a bounded set of numerical indexes; this is not OS enumeration."""

    should_stop = stop_event or Event()
    probe_one = probe or (lambda index: probe_camera(index, settings))
    devices: list[CameraDevice] = []
    for index in range(settings.camera_probe_limit):
        if should_stop.is_set():
            break
        device = probe_one(index)
        if device is not None:
            devices.append(device)
    logger.info(
        "Camera probing finished",
        extra={
            "event": "camera_discovery_finished",
            "validated_candidates": len(devices),
            "probe_limit": settings.camera_probe_limit,
        },
    )
    return devices


class CameraDiscoveryService:
    """Run numerical probing in one managed background thread."""

    def __init__(
        self,
        settings: AppSettings,
        on_finished: Callable[[list[CameraDevice]], None],
        on_error: Callable[[str], None],
        source_factory: Callable[[AppSettings], CameraSource] = OpenCVCameraSource,
    ) -> None:
        self._settings = settings
        self._on_finished = on_finished
        self._on_error = on_error
        self._source_factory = source_factory
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._active_source: CameraSource | None = None

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event = Event()
            self._thread = Thread(
                target=self._run, name="gazefix-camera-discovery", daemon=True
            )
            self._thread.start()
            return True

    def stop(self, timeout: float) -> bool:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
            source = self._active_source
        if source is not None:
            source.interrupt()
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        logger.info(
            "Camera discovery worker started",
            extra={"event": "camera_discovery_started"},
        )
        try:
            devices = discover_camera_devices(
                self._settings,
                self._stop_event,
                probe=lambda index: probe_camera(
                    index,
                    self._settings,
                    source_factory=self._source_factory,
                    stop_event=self._stop_event,
                    on_source=self._set_active_source,
                ),
            )
            if not self._stop_event.is_set():
                self._on_finished(devices)
        except Exception as exc:
            logger.exception(
                "Camera discovery failed",
                extra={"event": "camera_discovery_error"},
            )
            if not self._stop_event.is_set():
                self._on_error(str(exc))
        finally:
            logger.info(
                "Camera discovery worker stopped",
                extra={"event": "camera_discovery_stopped"},
            )

    def _set_active_source(self, source: CameraSource | None) -> None:
        with self._lock:
            self._active_source = source
