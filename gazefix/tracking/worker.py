"""The tracker thread: owns one ``FaceTracker`` and turns frames into results.

Ownership and threads (see docs/tracking.md):

- Exactly one daemon thread, ``gazefix-tracker``, creates, calls, rebuilds
  and closes the tracker. Nothing else touches it.
- The processor thread hands frames in through a latest-value slot
  (``submit``): an unprocessed frame is replaced, never queued, so a slow
  tracker sees at most one waiting frame. It then waits, bounded, for that
  frame's own result (``wait_for``). The wait only stops waiting; it cannot
  and does not cancel the native call.
- Results are published to a single latest-result slot keyed by the capture
  sequence; a result that arrives after the processor stopped waiting for it
  is simply never picked up.
- A frame from a new camera generation makes the thread reset every piece
  of temporal state (the backend's own face-tracking state through
  ``FaceTracker.reset``, primary-face memory, stabiliser), so nothing learned
  on one camera can attach to another; the backend instance is kept (a
  rebuild costs a model load and, with the current backend, a network
  attempt inside ``close``). The attempt budget for initialisation is
  re-armed at the same time. A gap of more than ``tracking_reset_gap_s``
  between consecutive frames (camera reopen, stall) resets the same state.
- Initialisation failures retry with exponential backoff up to a bounded
  number of attempts per generation; inference failures rebuild the tracker
  after a bounded number of consecutive errors, at most
  ``tracking_max_rebuilds`` times per generation; an unexpected exception
  anywhere else in the loop is logged once and handled the same way, so the
  thread never dies silently. Logging is per attempt and rate-limited,
  never per frame.
- ``stop`` asks the thread to exit and joins it for a bounded time. If the
  thread is inside an uncancellable native call it is abandoned as a daemon
  (logged); it still closes the tracker itself when the call returns.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from threading import Condition, Event, Thread
import time
from typing import Callable

import numpy as np

from gazefix.config import AppSettings
from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.processor import Frame, FrameContext
from gazefix.tracking.analysis import (
    AnalysisSettings,
    MalformedLandmarks,
    compute_quality,
    extract_eye,
    head_pose_from_matrix,
    validate_landmarks,
)
from gazefix.tracking.models import (
    FrameGeometry,
    TrackingResult,
    TrackingStatus,
    TrackingTiming,
    untracked,
)
from gazefix.tracking.selection import PrimaryFaceSelector, SelectionSettings
from gazefix.tracking.stabilizer import LandmarkStabilizer
from gazefix.tracking.tracker import (
    FaceTracker,
    RawDetection,
    TrackerFactory,
    TrackerInitializationError,
)


logger = logging.getLogger(__name__)

STATE_INITIALIZING = "initializing"
STATE_READY = "ready"
STATE_UNAVAILABLE = "unavailable"

_ERROR_LOG_INTERVAL_S = 5.0


@dataclass(frozen=True, slots=True)
class _Submission:
    frame: Frame
    context: FrameContext
    submitted_at: float


@dataclass(frozen=True, slots=True)
class WorkerStatus:
    """What the processor needs to label a frame it publishes untracked."""

    state: str
    message: str
    description: str
    generation: int


class TrackerWorker:
    def __init__(
        self,
        factory: TrackerFactory,
        settings: AppSettings,
        metrics: PipelineMetrics | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._factory = factory
        self._settings = settings
        self.metrics = metrics  # may be bound later by the processor's start()
        self._clock = clock
        self._analysis = AnalysisSettings(
            min_quality=settings.tracking_min_quality,
            min_in_frame_fraction=settings.tracking_min_in_frame_fraction,
            min_eye_width_px=settings.tracking_min_eye_width_px,
        )
        self._selector = PrimaryFaceSelector(SelectionSettings())
        self._stabilizer = LandmarkStabilizer(settings.tracking_smoothing)
        self._condition = Condition()
        self._pending: _Submission | None = None
        self._latest: TrackingResult | None = None
        # Inference in flight: (sequence, started_at) while the tracker runs.
        self._in_flight: tuple[int, float] | None = None
        self._state = STATE_INITIALIZING
        self._message = "tracker initializing"
        self._description = ""
        self._generation: int | None = None
        self._stop = Event()
        self._tracker: FaceTracker | None = None
        self._init_attempts = 0
        self._next_init_at = 0.0
        self._consecutive_errors = 0
        self._rebuilds = 0
        self._last_error_log_at: float | None = None
        self._last_captured_at_ns: int | None = None
        self._thread = Thread(target=self._run, name="gazefix-tracker", daemon=True)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread.start()

    @property
    def started(self) -> bool:
        return self._thread.ident is not None

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def stop(self, timeout: float) -> bool:
        """Signal the thread and wait at most ``timeout`` seconds for it to exit."""

        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self.started:
            self._thread.join(max(0.0, timeout))
        alive = self._thread.is_alive()
        if alive:
            with self._condition:
                in_flight = self._in_flight
            logger.error(
                "Tracker thread did not stop before timeout; it is inside a native "
                "call and will end with the process",
                extra={
                    "event": "tracker_shutdown_timeout",
                    "timeout_s": timeout,
                    "in_flight_sequence": in_flight[0] if in_flight else None,
                    "state": self._state,
                },
            )
        return not alive

    # ------------------------------------------------- processor-thread API
    def submit(self, frame: Frame, context: FrameContext) -> None:
        """Replace the waiting frame with this one and wake the tracker thread."""

        submission = _Submission(frame, context, self._clock())
        with self._condition:
            if self._pending is not None and self.metrics is not None:
                self.metrics.record_tracking_replaced()
            self._pending = submission
            self._condition.notify_all()

    def wait_for(self, sequence: int, timeout_s: float) -> tuple[TrackingResult | None, WorkerStatus]:
        """Wait, bounded, for the result of ``sequence``.

        Returns the result (or ``None``) together with the worker status
        captured under the same lock at the moment the decision was made, so
        the caller labels the frame from the state that caused it, not from
        a later snapshot. Returns at once, without waiting, when waiting
        cannot pay off: the tracker is not ready (initialising or
        unavailable), the worker is stopping, or an inference of an OLDER
        frame has already been running longer than ``timeout_s`` (a stalled
        tracker: every later frame would otherwise wait the full timeout and
        the preview would crawl). In those cases the frame is published
        untracked and the video keeps flowing at capture rate.
        """

        deadline = self._clock() + timeout_s
        with self._condition:
            while True:
                latest = self._latest
                if latest is not None and latest.capture_sequence == sequence:
                    return latest, self._status_locked()
                if self._stop.is_set() or self._state != STATE_READY:
                    return None, self._status_locked()
                in_flight = self._in_flight
                if (
                    in_flight is not None
                    and in_flight[0] < sequence
                    and self._clock() - in_flight[1] >= timeout_s
                ):
                    return None, self._status_locked()  # stalled on an older frame
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return None, self._status_locked()
                self._condition.wait(remaining)

    def status(self) -> WorkerStatus:
        with self._condition:
            return self._status_locked()

    def _status_locked(self) -> WorkerStatus:
        return WorkerStatus(self._state, self._message, self._description, self._generation or 0)

    def mark_unavailable(self, message: str) -> None:
        """Label every frame as unavailable (the thread could not be started)."""

        self._set_state(STATE_UNAVAILABLE, message)

    # ------------------------------------------------------- tracker thread
    def _run(self) -> None:
        logger.info("Tracker worker started", extra={"event": "tracker_worker_started"})
        try:
            while not self._stop.is_set():
                try:
                    submission = self._next_submission()
                    if self._stop.is_set():
                        break
                    if submission is None:
                        if self._tracker is None and self._init_due():
                            self._initialize()
                        continue
                    self._handle(submission)
                except Exception as exc:  # noqa: BLE001  (supervised loop)
                    # Anything outside the per-frame inference path (a reset,
                    # a close, analysis) is treated like an inference failure
                    # burst: the tracker is rebuilt through the bounded path
                    # and the frame, if any, is published as an error.
                    logger.exception(
                        "Tracker worker iteration failed; rebuilding through the bounded path",
                        extra={"event": "tracker_worker_error"},
                    )
                    self._recover_from_crash(exc, submission if "submission" in locals() else None)
        finally:
            self._close_tracker("worker exit")
            with self._condition:
                self._state = STATE_UNAVAILABLE
                self._message = "tracker stopped"
                self._condition.notify_all()
            logger.info("Tracker worker stopped", extra={"event": "tracker_worker_stopped"})

    def _next_submission(self) -> _Submission | None:
        with self._condition:
            while not self._stop.is_set():
                if self._pending is not None:
                    submission, self._pending = self._pending, None
                    return submission
                if self._tracker is None:
                    wait = self._next_init_at - self._clock()
                    if wait <= 0 and self._init_attempts_left():
                        return None  # initialise now
                    timeout = min(0.25, wait) if wait > 0 and self._init_attempts_left() else 0.25
                else:
                    timeout = 0.25
                self._condition.wait(timeout)
            return None

    def _init_attempts_left(self) -> bool:
        return self._init_attempts < self._settings.tracking_init_max_attempts

    def _init_due(self) -> bool:
        return self._init_attempts_left() and self._clock() >= self._next_init_at

    def _initialize(self) -> None:
        attempt = self._init_attempts + 1
        self._set_state(
            STATE_INITIALIZING,
            f"tracker initializing (attempt {attempt}/{self._settings.tracking_init_max_attempts})",
        )
        started = self._clock()
        try:
            tracker = self._factory()
        except TrackerInitializationError as exc:
            self._init_failed(exc, attempt, started, retryable=exc.retryable, kind=exc.kind)
            return
        except Exception as exc:  # noqa: BLE001  (any failure is an init failure)
            self._init_failed(exc, attempt, started, retryable=True, kind=type(exc).__name__)
            return
        self._tracker = tracker
        self._init_attempts = 0
        self._consecutive_errors = 0
        self._selector.reset()
        self._stabilizer.reset()
        with self._condition:
            self._description = tracker.description
        self._set_state(STATE_READY, "")
        logger.info(
            "Tracker ready",
            extra={
                "event": "tracker_ready",
                "attempt": attempt,
                "init_ms": round((self._clock() - started) * 1000.0, 1),
                "description": tracker.description,
            },
        )

    def _init_failed(
        self, exc: BaseException, attempt: int, started: float, *, retryable: bool, kind: str
    ) -> None:
        self._init_attempts = attempt
        exhausted = not retryable or not self._init_attempts_left()
        if exhausted:
            self._next_init_at = float("inf")
            message = (
                f"tracking unavailable: {exc} (no further attempts until the camera "
                "is changed or refreshed)"
            )
        else:
            delay = min(
                self._settings.tracking_init_retry_s * (2 ** (attempt - 1)),
                self._settings.tracking_init_retry_max_s,
            )
            self._next_init_at = self._clock() + delay
            message = (
                f"tracking unavailable: {exc} (retry {attempt + 1}/"
                f"{self._settings.tracking_init_max_attempts} in {delay:.0f} s)"
            )
        self._set_state(STATE_UNAVAILABLE, message)
        logger.error(
            "Tracker initialization failed",
            extra={
                "event": "tracker_init_failed",
                "attempt": attempt,
                "max_attempts": self._settings.tracking_init_max_attempts,
                "kind": kind,
                "retryable": retryable,
                "exhausted": exhausted,
                "init_ms": round((self._clock() - started) * 1000.0, 1),
                "error": str(exc),
            },
        )

    def _handle(self, submission: _Submission) -> None:
        context = submission.context
        if self._generation is None:
            # First frame ever: nothing was learned on any camera yet, so the
            # tracker built at start-up is simply adopted for this generation.
            self._generation = context.camera_request_id
        elif context.camera_request_id != self._generation:
            self._on_generation_change(context.camera_request_id)
        elif (
            self._last_captured_at_ns is not None
            and context.captured_at_ns - self._last_captured_at_ns
            > self._settings.tracking_reset_gap_s * 1_000_000_000
        ):
            self._reset_temporal_state("frame gap")
        self._last_captured_at_ns = context.captured_at_ns
        if self._tracker is None and self._init_due():
            self._initialize()
        if self._tracker is None:
            status = TrackingStatus.INITIALIZING if self._state == STATE_INITIALIZING else TrackingStatus.UNAVAILABLE
            self._publish(self._untracked(submission, status, self._message))
            return
        with self._condition:
            self._in_flight = (context.capture_sequence, self._clock())
        try:
            detection = self._tracker.detect(submission.frame, context.captured_at_ns // 1_000_000)
        except Exception as exc:  # noqa: BLE001  (a backend exception is a frame failure)
            self._inference_failed(exc, submission)
            return
        finally:
            with self._condition:
                self._in_flight = None
        try:
            result = self._analyse(detection, submission)
        except Exception as exc:  # noqa: BLE001  (analysis of one frame failed)
            # Counts like an inference failure: bounded, rate-limited, and
            # rebuilt only after repeated occurrences.
            self._inference_failed(exc, submission)
            return
        self._consecutive_errors = 0
        self._publish(result)

    def _on_generation_change(self, generation: int) -> None:
        previous = self._generation
        self._generation = generation
        with self._condition:
            self._latest = None
        # Re-arm the attempt and rebuild budgets: a fixed installation or a
        # different camera deserves fresh attempts, bounded again.
        self._init_attempts = 0
        self._rebuilds = 0
        self._next_init_at = 0.0
        self._reset_temporal_state("camera generation change")
        if self._tracker is None and self._state == STATE_UNAVAILABLE:
            self._set_state(STATE_INITIALIZING, "tracker initializing")
        logger.info(
            "Tracker reset for a new camera generation",
            extra={
                "event": "tracker_generation_reset",
                "previous_generation": previous,
                "generation": generation,
            },
        )

    def _reset_temporal_state(self, reason: str) -> None:
        """Forget everything learned from earlier frames; keep the backend."""

        self._selector.reset()
        self._stabilizer.reset()
        self._last_captured_at_ns = None
        tracker = self._tracker
        if tracker is None:
            return
        reset = getattr(tracker, "reset", None)
        if not callable(reset):
            return
        started = self._clock()
        with self._condition:
            self._in_flight = (-1, started)
        try:
            reset()
        finally:
            with self._condition:
                self._in_flight = None
        logger.info(
            "Tracker state reset",
            extra={
                "event": "tracker_state_reset",
                "reason": reason,
                "reset_ms": round((self._clock() - started) * 1000.0, 1),
            },
        )

    def _recover_from_crash(self, exc: BaseException, submission: _Submission | None) -> None:
        """A failure outside inference: rebuild through the bounded path."""

        self._selector.reset()
        self._stabilizer.reset()
        self._rebuild_or_give_up(f"tracker failure: {exc}")
        if submission is not None:
            self._publish(self._untracked(submission, TrackingStatus.ERROR, f"tracking error: {exc}"))

    def _rebuild_or_give_up(self, reason: str) -> None:
        """Close the tracker and schedule a rebuild, bounded per generation."""

        # State first: the processor must stop waiting on this worker before
        # the (possibly slow) close runs, not after it.
        self._set_state(STATE_INITIALIZING, f"tracker restarting ({reason})")
        self._close_tracker(reason)
        self._consecutive_errors = 0
        self._rebuilds += 1
        if self._rebuilds > self._settings.tracking_max_rebuilds:
            self._next_init_at = float("inf")
            self._set_state(
                STATE_UNAVAILABLE,
                f"tracking unavailable: {reason} (rebuilt {self._settings.tracking_max_rebuilds} "
                "times; change or refresh the camera to retry)",
            )
            logger.error(
                "Tracker rebuild budget exhausted",
                extra={"event": "tracker_rebuild_exhausted", "reason": reason,
                       "max_rebuilds": self._settings.tracking_max_rebuilds},
            )
            return
        self._next_init_at = self._clock() + self._settings.tracking_init_retry_s
        self._set_state(STATE_INITIALIZING, f"tracker restarting ({reason})")

    def _inference_failed(self, exc: BaseException, submission: _Submission) -> None:
        self._consecutive_errors += 1
        now = self._clock()
        first = self._last_error_log_at is None or now - self._last_error_log_at >= _ERROR_LOG_INTERVAL_S
        if first:
            self._last_error_log_at = now
            logger.exception(
                "Tracker inference failed",
                extra={
                    "event": "tracker_inference_error",
                    "consecutive_errors": self._consecutive_errors,
                    "sequence": submission.context.capture_sequence,
                },
            )
        message = f"tracking error: {exc}"
        if self._consecutive_errors >= self._settings.tracking_max_consecutive_errors:
            self._rebuild_or_give_up("repeated inference errors")
            message += "; restarting tracker"
        self._selector.reset()
        self._stabilizer.reset()
        self._publish(self._untracked(submission, TrackingStatus.ERROR, message))

    def _analyse(self, detection: RawDetection, submission: _Submission) -> TrackingResult:
        context = submission.context
        geometry = FrameGeometry(submission.frame.shape[1], submission.frame.shape[0])
        timing = TrackingTiming(
            inference_ms=detection.inference_ms,
            total_ms=(self._clock() - submission.submitted_at) * 1000.0,
        )
        analysis = self._analysis
        # Selection works on plausible arrays only; a backend that returns a
        # degenerate face must not take the selector down with it.
        candidates = tuple(face for face in detection.faces if _plausible(face.landmarks))
        if detection.faces and not candidates:
            # Raised, not returned: a malformed backend output counts toward the
            # bounded error budget and is rate-limit logged like any failure.
            raise MalformedLandmarks("malformed landmarks: no usable face array")
        selection = self._selector.select(candidates)
        if selection is None:
            self._stabilizer.reset()
            return untracked(
                TrackingStatus.NO_FACE, context.capture_sequence, context.captured_at_ns,
                context.camera_request_id, geometry, "no face detected", timing, 0,
            )
        face = candidates[selection.index]
        try:
            landmarks, iris_available = validate_landmarks(face.landmarks)
        except MalformedLandmarks as exc:
            raise MalformedLandmarks(f"malformed landmarks: {exc}") from exc
        if selection.identity_changed:
            self._stabilizer.reset()
        stabilized = self._stabilizer.enabled
        landmarks = self._stabilizer.apply(landmarks)
        tracker = self._tracker
        thresholds = tracker.backend_thresholds if tracker is not None else (0.0, 0.0, 0.0)
        quality = compute_quality(landmarks, geometry, self._analysis, thresholds)
        right_eye = extract_eye(landmarks, "right", geometry, self._analysis, iris_available)
        left_eye = extract_eye(landmarks, "left", geometry, self._analysis, iris_available)
        pose = head_pose_from_matrix(face.transform) if face.transform is not None else None
        reasons = []
        if quality.in_frame_fraction < analysis.min_in_frame_fraction:
            reasons.append(
                f"face partially outside the frame ({quality.in_frame_fraction:.2f} of landmarks inside)"
            )
        if quality.score < analysis.min_quality:
            reasons.append(f"quality {quality.score:.2f} below {analysis.min_quality:.2f}")
        if not right_eye.valid:
            reasons.append("right eye outside the frame or too small")
        if not left_eye.valid:
            reasons.append("left eye outside the frame or too small")
        status = TrackingStatus.TRACKED if not reasons else TrackingStatus.LOW_QUALITY
        return TrackingResult(
            status=status,
            capture_sequence=context.capture_sequence,
            captured_at_ns=context.captured_at_ns,
            camera_request_id=context.camera_request_id,
            geometry=geometry,
            timing=timing,
            message="; ".join(reasons),
            faces_detected=len(detection.faces),
            landmarks=landmarks,
            left_eye=left_eye,
            right_eye=right_eye,
            iris_available=iris_available,
            pose=pose,
            quality=quality,
            stabilized=stabilized,
        )

    def _untracked(self, submission: _Submission, status: TrackingStatus, message: str) -> TrackingResult:
        context = submission.context
        return untracked(
            status,
            context.capture_sequence,
            context.captured_at_ns,
            context.camera_request_id,
            FrameGeometry(submission.frame.shape[1], submission.frame.shape[0]),
            message,
            TrackingTiming(inference_ms=None, total_ms=(self._clock() - submission.submitted_at) * 1000.0),
        )

    def _publish(self, result: TrackingResult) -> None:
        with self._condition:
            self._latest = result
            self._condition.notify_all()

    def _set_state(self, state: str, message: str) -> None:
        with self._condition:
            self._state = state
            self._message = message
            if state != STATE_READY:
                self._description = self._description if state == STATE_INITIALIZING else ""
            self._condition.notify_all()

    def _close_tracker(self, reason: str) -> None:
        tracker, self._tracker = self._tracker, None
        if tracker is None:
            return
        started = self._clock()
        try:
            tracker.close()
        except Exception:
            logger.exception(
                "Tracker close failed", extra={"event": "tracker_close_error", "reason": reason}
            )
        else:
            logger.info(
                "Tracker released",
                extra={
                    "event": "tracker_released",
                    "reason": reason,
                    "close_ms": round((self._clock() - started) * 1000.0, 1),
                },
            )


def _plausible(landmarks: object) -> bool:
    """Cheap shape/finiteness check before an array reaches the selector."""

    shape = getattr(landmarks, "shape", None)
    if shape is None or len(shape) != 2 or shape[1] != 3 or shape[0] not in (478, 468):
        return False
    try:
        return bool(np.all(np.isfinite(landmarks)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
