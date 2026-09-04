"""OpenCV camera source with Windows backend fallback.

``open_validated_backend`` is the single open/configure/validate path for one
backend. ``OpenCVCameraSource`` runs it per backend and decides on fallback;
the camera diagnostic (``gazefix.camera.diagnostics``) runs it per index and
backend to time the production behaviour. Nothing in this module depends on
the diagnostic.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import os
from threading import Condition, Event, Lock, Thread
import time
from typing import Callable, Protocol

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


class PreparedCameraCloser:
    """Release unclaimed prepared cameras on one owned daemon thread.

    Releasing a camera is a driver call with no upper bound, so no thread that
    must stay responsive (the Qt thread inside ``closeEvent``, a runtime
    caller inside ``stop()``) may perform it. ``submit`` transfers the duty to
    close a token here; from then on this thread is the only party that will
    call ``close_if_unclaimed`` on it. Because a token hands its source to
    exactly one claimant, a party that still holds a reference (a capture
    worker that adopts it, its own shutdown cleanup) cannot release the same
    source a second time or at the same time: whichever side claims first
    releases, the other finds nothing to do. Nobody reads an unclaimed source,
    so a release here never overlaps a read.

    The work is tracked until the release call returns: ``outstanding`` counts
    the queued tokens plus the one whose release is in flight, so it stays
    truthful while a driver blocks, and ``join`` waits at most ``timeout`` for
    the count to reach zero. A release that never returns keeps this daemon
    thread alive until process exit, exactly like a capture worker abandoned
    inside a driver call; the tokens queued behind it stay counted as
    outstanding rather than being forgotten.
    """

    def __init__(self, name: str = "gazefix-prepared-close") -> None:
        self._name = name
        self._condition = Condition()
        self._queue: deque[PreparedCamera] = deque()
        self._in_flight: PreparedCamera | None = None
        self._thread: Thread | None = None

    def submit(self, prepared: PreparedCamera) -> None:
        """Take over closing ``prepared``; returns at once, never touching the driver.

        Queue insertion is the single, unambiguous ownership-acceptance
        point. When this method returns normally the closer owns the token
        (or found nothing to own); when it raises, the insertion did not
        happen and the caller still owns the token. Nothing after the
        insertion can raise for a recoverable failure: a cleanup-thread
        launch failure is logged and retried later (by the next ``submit``
        or ``join``) while the accepted token stays queued and counted.
        Re-submitting a token the closer already holds is a structural no-op
        (the queue never gains a duplicate), so a caller that could not
        observe its earlier call completing may safely try again; the
        claim-once handover underneath remains a final safety net, not the
        mechanism that prevents duplicates.

        A token that was already claimed is dropped on the spot: its source
        belongs to the claimant, there is nothing left to release, and
        queueing it would count a no-op as outstanding work. (A claim that
        lands after this check merely makes the queued release a no-op.)
        """

        if not prepared.is_pending:
            return
        with self._condition:
            if self._in_flight is prepared or any(
                queued is prepared for queued in self._queue
            ):
                return  # already accepted; never duplicate the entry
            self._queue.append(prepared)  # ownership commits here
            self._ensure_thread()  # logged best effort; never raises Exception

    def _ensure_thread(self) -> None:
        """Launch the thread if work is queued and none is running (condition held).

        Construction or start can fail (out of threads). That is recoverable:
        the failure is logged, never raised, the queued tokens stay owned and
        counted, and both the next ``submit`` and the next ``join`` try the
        launch again — so a launch failure can neither strand a token nor
        masquerade as a rejected submission.
        """

        if self._thread is not None or not self._queue:
            return
        try:
            thread = Thread(target=self._run, name=self._name, daemon=True)
            thread.start()
        except Exception:
            logger.exception(
                "Prepared camera cleanup thread could not start",
                extra={"event": "prepared_camera_closer_start_error"},
            )
            return
        self._thread = thread

    @property
    def outstanding(self) -> int:
        """Tokens not yet released: queued plus the one whose release is in flight."""

        with self._condition:
            return len(self._queue) + (1 if self._in_flight is not None else 0)

    def join(self, timeout: float) -> bool:
        """Bounded best-effort wait for every accepted token to be released.

        Retries the cleanup-thread launch first (a recoverable launch failure
        is logged, never raised, and never touches the queue), then waits at
        most ``timeout`` seconds. Returns ``True`` only when the queue and
        the in-flight slot are actually empty, so a launch failure yields a
        truthful ``False`` with every token still owned and counted.
        """

        with self._condition:
            self._ensure_thread()
            return self._condition.wait_for(self._idle, timeout=max(0.0, timeout))

    def _idle(self) -> bool:
        return not self._queue and self._in_flight is None

    def _run(self) -> None:
        while True:
            with self._condition:
                if not self._queue:
                    # Exit when idle; ``submit`` starts a fresh thread when it
                    # finds none, and it checks that under the same condition,
                    # so a token can never be queued behind a thread that is
                    # about to leave.
                    self._thread = None
                    self._condition.notify_all()
                    return
                prepared = self._queue.popleft()
                self._in_flight = prepared
            try:
                started = time.perf_counter()
                if prepared.close_if_unclaimed():
                    logger.info(
                        "Released a prepared camera nobody adopted",
                        extra={
                            "event": "prepared_camera_discarded",
                            "camera_index": prepared.device.index,
                            "release_ms": _elapsed_ms(started),
                        },
                    )
            except Exception:
                # ``close_if_unclaimed`` already absorbs source errors; this
                # only guards the loop itself so one bad token cannot strand
                # the ones queued behind it.
                logger.exception(
                    "Prepared camera cleanup failed",
                    extra={
                        "event": "prepared_camera_close_error",
                        "camera_index": prepared.device.index,
                    },
                )
            finally:
                with self._condition:
                    self._in_flight = None
                    self._condition.notify_all()


@dataclass(frozen=True, slots=True)
class BackendOpenOutcome:
    """What one production open of one backend did and how long each step took.

    Produced by ``open_validated_backend`` for the capture source and for the
    camera diagnostic alike, so both report the same measurement boundaries
    (all wall clock on the calling thread):

    - ``open_ms``: the ``VideoCapture.open`` call alone. DirectShow receives
      width and height as open parameters and builds its capture graph inside
      this call; Media Foundation negotiates its source reader here.
    - ``configure_ms``: the width/height/FPS property reads that decide
      whether each value must be set, the ``set`` calls that follow for the
      values that differ, and the buffer-size hint. ``format_sets_applied``
      is how many ``set`` calls of width, height, or FPS actually ran (each
      one renegotiates the stream on Media Foundation and rebuilds the graph
      on DirectShow). The reads that fill ``result`` afterwards are outside it.
    - ``first_frame_ms``: the bounded first-frame validation reads, including
      the retry delays between them; ``validation_reads`` counts the attempts.

    ``result`` holds the negotiated backend name, size, and FPS as read after
    configuration. It is present whenever the backend opened and configuration
    ran (also when validation then failed) and ``None`` otherwise.
    ``interrupted`` reports that the caller's interrupt was seen at a
    checkpoint; the remaining steps were skipped and the caller must discard
    the capture regardless of the other fields.
    """

    backend: CameraBackend
    opened: bool
    validated: bool
    interrupted: bool
    result: CameraOpenResult | None
    open_ms: float
    configure_ms: float | None
    first_frame_ms: float | None
    format_sets_applied: int
    validation_reads: int


def open_validated_backend(
    capture: cv2.VideoCapture,
    index: int,
    backend: CameraBackend,
    settings: AppSettings,
    interrupted: Callable[[], bool] | None = None,
) -> BackendOpenOutcome:
    """Open, configure, and first-frame validate ``capture`` on one backend.

    This is the production open path. ``interrupted`` is polled at the same
    checkpoints the capture source honours (right after the open call returns
    and between validation reads); once it reports True the remaining steps
    are skipped and the outcome is flagged. The capture is never released here:
    the caller owns it and decides between keeping it, discarding it, or
    falling back to another backend.
    """

    is_interrupted = interrupted or (lambda: False)
    started = time.perf_counter()
    opened = _open_capture(capture, index, backend, settings)
    open_ms = _elapsed_ms(started)
    # Read the flag once: ``reinstate`` can clear it from another thread, and
    # the decision to skip the remaining steps and the flag reported to the
    # caller must agree.
    interrupted_after_open = is_interrupted()
    if not opened or interrupted_after_open:
        return BackendOpenOutcome(
            backend=backend,
            opened=opened,
            validated=False,
            interrupted=interrupted_after_open,
            result=None,
            open_ms=open_ms,
            configure_ms=None,
            first_frame_ms=None,
            format_sets_applied=0,
            validation_reads=0,
        )

    started = time.perf_counter()
    applied = _apply_format(capture, settings)
    configure_ms = _elapsed_ms(started)
    result = CameraOpenResult(
        backend=backend,
        reported_backend=_reported_backend(capture),
        width=round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        height=round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        fps=float(capture.get(cv2.CAP_PROP_FPS)),
    )

    started = time.perf_counter()
    validated, reads = _validate_first_frame(capture, settings, is_interrupted)
    first_frame_ms = _elapsed_ms(started)
    return BackendOpenOutcome(
        backend=backend,
        opened=True,
        validated=validated,
        interrupted=is_interrupted(),
        result=result,
        open_ms=open_ms,
        configure_ms=configure_ms,
        first_frame_ms=first_frame_ms,
        format_sets_applied=applied,
        validation_reads=reads,
    )


def _open_capture(
    capture: cv2.VideoCapture, index: int, backend: CameraBackend, settings: AppSettings
) -> bool:
    """Open the backend, handing DirectShow its frame size up front.

    DirectShow builds its capture graph inside ``open`` and rebuilds it for
    every later ``set`` of width/height/FPS. Its constructor honours only
    width, height, and FOURCC as open parameters (``cap_dshow.cpp``), so
    those are passed there and the graph is built at the right size; FPS
    can only be applied by ``set`` afterwards and costs one rebuild when the
    camera's reported rate differs. Media Foundation applies open parameters
    through the same per-property renegotiation as ``set``, so it gains
    nothing from them and is configured afterwards, skipping properties the
    camera already reports at the requested value.
    """

    if backend.api_preference == cv2.CAP_DSHOW:
        params = [
            cv2.CAP_PROP_FRAME_WIDTH, settings.capture_width,
            cv2.CAP_PROP_FRAME_HEIGHT, settings.capture_height,
        ]
        try:
            return capture.open(index, backend.api_preference, params)
        except TypeError:
            # OpenCV builds without the parameters overload
            pass
    return capture.open(index, backend.api_preference)


def _apply_format(capture: cv2.VideoCapture, settings: AppSettings) -> int:
    """Set width, height, and FPS only where the camera differs from the request.

    On Media Foundation every ``set`` of these properties renegotiates the
    stream even when the value is unchanged (``cap_msmf.cpp`` ``setProperty``
    -> ``configureVideoOutput``), so an unconditional triple costs three
    format negotiations per open. Returns the number of ``set`` calls made.
    """

    wanted = (
        (cv2.CAP_PROP_FRAME_WIDTH, float(settings.capture_width)),
        (cv2.CAP_PROP_FRAME_HEIGHT, float(settings.capture_height)),
        (cv2.CAP_PROP_FPS, float(settings.target_fps)),
    )
    applied = 0
    for prop, value in wanted:
        current = capture.get(prop)
        if abs(current - value) < 0.5:
            continue
        if prop == cv2.CAP_PROP_FPS and current <= 0:
            # The backend does not report a rate (common on DirectShow);
            # setting one would only force a graph rebuild for a guess.
            continue
        capture.set(prop, value)
        applied += 1
    # Not honoured by MSMF or DirectShow; kept as a hint for other backends.
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return applied


def _validate_first_frame(
    capture: cv2.VideoCapture,
    settings: AppSettings,
    is_interrupted: Callable[[], bool],
) -> tuple[bool, int]:
    """Read until a frame arrives; returns (validated, read attempts).

    Bounded by count and by wall clock: one failed Media Foundation read
    already waits up to 10 s internally, so a stalled backend must not be
    given that patience three times over before the next backend is tried.
    """

    started = time.perf_counter()
    reads = 0
    for attempt in range(settings.discovery_validation_reads):
        if is_interrupted():
            return False, reads
        if attempt and (
            time.perf_counter() - started >= settings.open_validation_timeout_s
        ):
            return False, reads
        reads += 1
        success, frame = capture.read()
        if success and frame is not None and frame.size > 0:
            return True, reads
        if attempt + 1 < settings.discovery_validation_reads:
            time.sleep(settings.read_retry_delay_s)
    return False, reads


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
        # The open inside is the call that a driver can hold for many seconds.
        # OpenCV only attaches the backend object after it returns, so nothing
        # another thread does to this VideoCapture can shorten it; ``interrupt``
        # only sets a flag and this thread discards the capture as soon as the
        # shared open path reports the flag at one of its checkpoints.
        outcome = open_validated_backend(
            capture, device.index, backend, self._settings, self._interrupted.is_set
        )
        if outcome.interrupted:
            self._discard(capture)
            raise CameraOpenInterrupted("Camera open interrupted")
        if not outcome.opened:
            self._discard(capture)
            failures.append(backend.name)
            logger.warning(
                "Camera backend did not open",
                extra={
                    "event": "camera_open_failed",
                    "camera_index": device.index,
                    "backend_requested": backend.name,
                    "open_ms": outcome.open_ms,
                },
            )
            return None

        result = outcome.result
        if result is None or not outcome.validated:
            self._discard(capture)
            failures.append(f"{backend.name} (opened but produced no frame)")
            logger.warning(
                "Camera backend opened but produced no frame",
                extra={
                    "event": "camera_open_no_frame",
                    "camera_index": device.index,
                    "backend_requested": backend.name,
                    "backend_reported": result.reported_backend if result else None,
                    "open_ms": outcome.open_ms,
                    "configure_ms": outcome.configure_ms,
                    "validation_ms": outcome.first_frame_ms,
                    "validation_reads": outcome.validation_reads,
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
                "open_ms": outcome.open_ms,
                "configure_ms": outcome.configure_ms,
                "format_sets_applied": outcome.format_sets_applied,
                "first_frame_ms": outcome.first_frame_ms,
                "validation_reads": outcome.validation_reads,
                "msmf_hw_transforms": os.environ.get(MSMF_HW_TRANSFORMS_ENV),
            },
        )
        return result

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

    def reinstate(self) -> None:
        """Withdraw an interrupt because the owner wants this camera after all.

        Used when a newer request returns to the camera whose open is still in
        flight: if the open has not yet reached its checkpoint it completes
        normally and the worker keeps the camera; if it already gave up, the
        worker simply opens the camera again. Either outcome is correct.
        """

        self._interrupted.clear()

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
