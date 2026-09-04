"""The tracker boundary: what a face-landmark backend must provide.

A ``FaceTracker`` is created by a ``TrackerFactory`` on the tracker thread,
called from that thread only, and closed there. It returns raw, backend-level
data (``RawDetection``); turning that into the ``TrackingResult`` contract
(validity, quality, eyes, pose angles) is the job of
``gazefix.tracking.analysis``, which is backend-independent and testable with
fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np
from numpy.typing import NDArray


Frame = NDArray[np.uint8]


class TrackerError(RuntimeError):
    """Base class for tracker failures the pipeline treats as recoverable."""


class TrackerInitializationError(TrackerError):
    """The backend could not be created (dependency, model, or runtime problem).

    ``retryable`` is ``False`` for conditions a retry cannot fix without user
    action (a missing or wrong model file, an import failure); the worker
    still re-arms its attempt budget on the next camera change so a fixed
    installation is picked up without restarting the application.
    """

    def __init__(self, message: str, *, retryable: bool = True, kind: str = "runtime") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind


class TrackerClosedError(TrackerError):
    """The tracker was used after ``close``."""


@dataclass(frozen=True, slots=True, eq=False)
class RawFace:
    """One detected face as the backend reports it.

    ``landmarks`` is ``(N, 3)`` float32 normalised to the input image
    (``N`` = 478 with iris, 468 without). ``transform`` is the 4×4
    face-to-camera matrix when the backend provides one.
    """

    landmarks: NDArray[np.float32]
    transform: NDArray[np.float32] | None = None


@dataclass(frozen=True, slots=True, eq=False)
class RawDetection:
    faces: tuple[RawFace, ...]
    inference_ms: float
    iris_available: bool


class FaceTracker(Protocol):
    """Backend interface; every method is called on the tracker thread only."""

    @property
    def description(self) -> str:
        """Backend/model identity for logs and the overlay (e.g. name + version)."""

    @property
    def backend_thresholds(self) -> tuple[float, float, float]:
        """(detection, presence, tracking) minimum scores the backend applies."""

    def detect(self, frame_bgr: Frame, timestamp_ms: int) -> RawDetection:
        """Run inference on an immutable BGR frame captured at ``timestamp_ms``.

        ``timestamp_ms`` is strictly increasing within one tracker instance.
        Implementations must not write to ``frame_bgr``. They raise
        ``TrackerError`` (or any exception, treated the same) on failure.
        """

    def close(self) -> None:
        """Release native resources; idempotent."""


TrackerFactory = Callable[[], FaceTracker]
"""Builds a ready tracker or raises ``TrackerInitializationError``.

The factory is invoked on the tracker thread so a slow import or model load
never touches the Qt or processor threads.
"""
