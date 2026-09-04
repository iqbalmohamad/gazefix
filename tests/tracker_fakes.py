"""Scriptable ``FaceTracker`` doubles and synthetic faces for the tracking tests."""

from __future__ import annotations

from dataclasses import replace
from threading import Event, current_thread
import time

import numpy as np

from gazefix.config import AppSettings
from gazefix.tracking.tracker import RawDetection, RawFace, TrackerInitializationError
from tracking_fakes import synthetic_landmarks


def synthetic_face(
    center: tuple[float, float] = (0.5, 0.5),
    face_height: float = 0.4,
    eye_openness: float = 0.3,
    count: int = 478,
) -> np.ndarray:
    """A plausible (count, 3) landmark set with anatomically placed eyes.

    Thin wrapper over ``tracking_fakes.synthetic_landmarks`` (shared with the
    contract/analysis tests): the subject's RIGHT eye sits on the image-left
    side of the centre, the LEFT eye on the image-right side, the nose tip at
    ``center``.
    """

    return synthetic_landmarks(center=center, face_height=face_height, count=count, eye_openness=eye_openness)


def identity_transform(z_cm: float = -45.0) -> np.ndarray:
    matrix = np.eye(4, dtype=np.float32)
    matrix[2, 3] = z_cm
    return matrix


def face(center: tuple[float, float] = (0.5, 0.5), **kwargs: object) -> RawFace:
    return RawFace(landmarks=synthetic_face(center, **kwargs), transform=identity_transform())  # type: ignore[arg-type]


class ScriptedTracker:
    """A ``FaceTracker`` whose behaviour tests script per call."""

    description = "scripted fake tracker"
    backend_thresholds = (0.5, 0.5, 0.5)

    def __init__(
        self,
        faces: tuple[RawFace, ...] | None = None,
        *,
        gate: Event | None = None,
        failure: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self.faces: tuple[RawFace, ...] = (face(),) if faces is None else faces
        self.gate = gate
        self.failure = failure
        self.delay_s = delay_s
        self.calls = 0
        self.timestamps: list[int] = []
        self.threads: list[str] = []
        self.close_calls = 0
        self.close_thread: str | None = None
        self.detect_started = Event()

    def detect(self, frame_bgr, timestamp_ms: int) -> RawDetection:  # type: ignore[no-untyped-def]
        self.calls += 1
        self.timestamps.append(timestamp_ms)
        self.threads.append(current_thread().name)
        self.detect_started.set()
        if self.gate is not None:
            self.gate.wait(5.0)
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.failure is not None:
            raise self.failure
        return RawDetection(self.faces, inference_ms=1.0, iris_available=all(f.landmarks.shape[0] == 478 for f in self.faces))

    def close(self) -> None:
        self.close_calls += 1
        self.close_thread = current_thread().name


class ScriptedFactory:
    """Builds ``ScriptedTracker`` instances; can fail or block per attempt."""

    def __init__(
        self,
        *,
        failures: list[Exception] | None = None,
        gate: Event | None = None,
        tracker_kwargs: dict | None = None,
    ) -> None:
        self.failures = list(failures or [])
        self.gate = gate
        self.tracker_kwargs = tracker_kwargs or {}
        self.trackers: list[ScriptedTracker] = []
        self.attempts = 0
        self.threads: list[str] = []

    def __call__(self) -> ScriptedTracker:
        self.attempts += 1
        self.threads.append(current_thread().name)
        if self.gate is not None:
            self.gate.wait(5.0)
        if self.failures:
            raise self.failures.pop(0)
        tracker = ScriptedTracker(**self.tracker_kwargs)
        self.trackers.append(tracker)
        return tracker


def init_error(message: str = "model missing", retryable: bool = False, kind: str = "model_missing") -> TrackerInitializationError:
    return TrackerInitializationError(message, retryable=retryable, kind=kind)


def tracking_settings(**overrides: object) -> AppSettings:
    """Fast, deterministic tracking settings for tests."""

    base = replace(
        AppSettings(),
        tracking_wait_ms=80,
        tracking_init_retry_s=0.02,
        tracking_init_retry_max_s=0.05,
        tracking_init_max_attempts=3,
        tracking_max_consecutive_errors=3,
        tracking_join_timeout_s=0.3,
        tracking_smoothing=0.0,
        worker_join_timeout_s=1.0,
        reconnect_delay_s=0.01,
        read_retry_delay_s=0.001,
    )
    return replace(base, **overrides).validated()  # type: ignore[arg-type]


def blank_frame(width: int = 640, height: int = 360) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame.setflags(write=False)
    return frame


def wait_until(predicate, timeout: float = 2.0, interval: float = 0.005) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())
