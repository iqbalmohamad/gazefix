"""Validated numerical camera probing performed away from the UI thread."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from threading import Event, Lock, Thread, current_thread
import time
from typing import Callable

from gazefix.camera.models import CameraDevice
from gazefix.camera.source import CameraSource, OpenCVCameraSource, PreparedCamera
from gazefix.config import AppSettings


logger = logging.getLogger(__name__)
Probe = Callable[[int], CameraDevice | None]


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Validated candidates plus, optionally, the first one still open.

    ``prepared`` lets the consumer that selects ``devices[0]`` adopt the camera
    discovery already opened and validated instead of opening it again. It is
    owned by whoever claims it first; the discovery service closes it if it is
    still unclaimed when discovery stops or restarts.
    """

    devices: list[CameraDevice] = field(default_factory=list)
    prepared: PreparedCamera | None = None


def probe_camera(
    index: int,
    settings: AppSettings,
    source_factory: Callable[[AppSettings], CameraSource] = OpenCVCameraSource,
    stop_event: Event | None = None,
    on_source: Callable[[CameraSource | None], None] | None = None,
    on_prepared: Callable[[PreparedCamera], None] | None = None,
) -> CameraDevice | None:
    """Return a candidate only after the source both opened and delivered a frame.

    ``CameraSource.open`` already refuses to succeed without a frame, so one
    open is the whole validation. When ``on_prepared`` is given the validated
    source is handed over still open instead of being released.
    """

    candidate = CameraDevice(index=index)
    source = source_factory(settings)
    if on_source is not None:
        on_source(source)
    started = time.perf_counter()
    keep_open = False
    try:
        if stop_event is not None and stop_event.is_set():
            return None
        result = source.open(candidate)
        device = CameraDevice(index=index, validated_backend=result.backend)
        if stop_event is not None and stop_event.is_set():
            return None
        if on_prepared is not None:
            keep_open = True
            on_prepared(PreparedCamera(device, source, result))
        logger.info(
            "Camera candidate validated",
            extra={
                "event": "camera_probe_validated",
                "camera_index": index,
                "backend_reported": result.reported_backend,
                "probe_ms": _elapsed_ms(started),
                "kept_open": keep_open,
            },
        )
        return device
    except Exception as exc:
        logger.info(
            "Camera candidate validation failed",
            extra={
                "event": "camera_probe_failed",
                "camera_index": index,
                "error": str(exc),
                "probe_ms": _elapsed_ms(started),
            },
        )
    finally:
        if not keep_open:
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
    started = time.perf_counter()
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
            "discovery_ms": _elapsed_ms(started),
        },
    )
    return devices


class CameraDiscoveryService:
    """Run numerical probing in one managed background thread.

    With ``keep_first_open`` one validated camera stays open and travels to
    ``on_finished`` inside ``DiscoveryResult.prepared`` so the selection that
    follows discovery does not pay for a second driver open. ``start`` accepts
    the index the caller intends to select (the camera in use before a refresh);
    that candidate is the one kept open when it validates, otherwise the first.
    """

    def __init__(
        self,
        settings: AppSettings,
        on_finished: Callable[[DiscoveryResult], None],
        on_error: Callable[[str], None],
        source_factory: Callable[[AppSettings], CameraSource] = OpenCVCameraSource,
        keep_first_open: bool = True,
    ) -> None:
        self._settings = settings
        self._on_finished = on_finished
        self._on_error = on_error
        self._source_factory = source_factory
        self._keep_first_open = keep_first_open
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._active_source: CameraSource | None = None
        self._prepared: PreparedCamera | None = None
        self._keep_open_index: int | None = None
        self._delivered = True

    def start(self, keep_open_index: int | None = None) -> bool:
        """Start a run; returns False only while a run has not yet delivered.

        A thread that has already called ``on_finished``/``on_error`` and is
        merely exiting is waited out, so a Refresh that lands right after the
        previous result is honoured instead of silently ignored.
        """

        with self._lock:
            previous = self._thread
            if previous is not None and previous.is_alive() and not self._delivered:
                return False
        if previous is not None and previous is not current_thread():
            previous.join(1.0)  # only its trailing log line remains
        with self._lock:
            if self._thread is not previous:
                return False  # another caller restarted meanwhile
            self._delivered = False
            self._keep_open_index = keep_open_index
            self._stop_event = Event()
            self._thread = Thread(
                target=self._run, name="gazefix-camera-discovery", daemon=True
            )
            self._thread.start()
            return True

    def request_stop(self) -> None:
        """Signal the worker without waiting; pair with ``join``."""

        self._stop_event.set()
        with self._lock:
            source = self._active_source
        if source is not None:
            source.interrupt()

    def join(self, timeout: float) -> bool:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self._close_unclaimed_prepared()
        return thread is None or not thread.is_alive()

    def stop(self, timeout: float) -> bool:
        self.request_stop()
        return self.join(timeout)

    @property
    def is_running(self) -> bool:
        """True from ``start`` until the result or error has been delivered."""

        with self._lock:
            return (
                self._thread is not None
                and self._thread.is_alive()
                and not self._delivered
            )

    def _run(self) -> None:
        logger.info(
            "Camera discovery worker started",
            extra={"event": "camera_discovery_started"},
        )
        # A prepared camera from a previous run that nobody adopted is closed
        # here, on a worker thread, before it could be leaked or double-opened.
        self._close_unclaimed_prepared()
        try:
            devices = discover_camera_devices(
                self._settings, self._stop_event, probe=self._probe
            )
            if self._stop_event.is_set():
                self._close_unclaimed_prepared()
                return
            with self._lock:
                prepared = self._prepared
                self._delivered = True
            self._on_finished(DiscoveryResult(devices, prepared))
        except Exception as exc:
            logger.exception(
                "Camera discovery failed",
                extra={"event": "camera_discovery_error"},
            )
            self._close_unclaimed_prepared()
            with self._lock:
                self._delivered = True
            if not self._stop_event.is_set():
                self._on_error(str(exc))
        finally:
            with self._lock:
                self._delivered = True
            logger.info(
                "Camera discovery worker stopped",
                extra={"event": "camera_discovery_stopped"},
            )

    def _probe(self, index: int) -> CameraDevice | None:
        with self._lock:
            wanted = self._keep_open_index
            keep_open = (
                self._keep_first_open
                and self._prepared is None
                and (wanted is None or wanted == index)
            )
        return probe_camera(
            index,
            self._settings,
            source_factory=self._source_factory,
            stop_event=self._stop_event,
            on_source=self._set_active_source,
            on_prepared=self._accept_prepared if keep_open else None,
        )

    def _accept_prepared(self, prepared: PreparedCamera) -> None:
        with self._lock:
            self._prepared = prepared

    def _close_unclaimed_prepared(self) -> None:
        with self._lock:
            prepared = self._prepared
            self._prepared = None
        if prepared is not None and prepared.close_if_unclaimed():
            logger.info(
                "Closed prepared camera that was never adopted",
                extra={
                    "event": "prepared_camera_discarded",
                    "camera_index": prepared.device.index,
                },
            )

    def _set_active_source(self, source: CameraSource | None) -> None:
        with self._lock:
            self._active_source = source


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)
