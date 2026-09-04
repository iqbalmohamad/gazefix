"""Velocity-adaptive exponential smoothing of a landmark set.

The filter blends each new landmark with its previous smoothed position using
a per-point weight that grows with the point's displacement, so slow jitter
is damped while fast motion passes through almost unfiltered. It never holds
a frame back: the output for a frame is computed from that frame and the
previous output only, so no queueing latency is added. It resets whenever
tracking is lost, the primary identity changes, the camera generation changes
or the landmark count changes, so an old face can never bleed into a new one.
"""

from __future__ import annotations

import numpy as np

from gazefix.tracking.models import Array, readonly


class LandmarkStabilizer:
    def __init__(self, smoothing: float, motion_scale: float = 0.02) -> None:
        """``smoothing`` in ``[0, 1]``: 0 disables the filter; 1 is the strongest.

        The minimum blend weight is ``1 - 0.7 * smoothing`` (never below 0.3),
        and a displacement of ``motion_scale`` normalised units or more (2 %
        of the frame by default) lets the new position through unfiltered.
        """

        if not 0.0 <= smoothing <= 1.0:
            raise ValueError("smoothing must be between 0 and 1")
        if motion_scale <= 0:
            raise ValueError("motion_scale must be positive")
        self._alpha_min = 1.0 - 0.7 * smoothing
        self._motion_scale = motion_scale
        self._previous: np.ndarray | None = None

    @property
    def enabled(self) -> bool:
        return self._alpha_min < 1.0

    def reset(self) -> None:
        self._previous = None

    def apply(self, landmarks: Array) -> Array:
        if not self.enabled:
            return landmarks
        current = np.asarray(landmarks, dtype=np.float32)
        previous = self._previous
        if previous is None or previous.shape != current.shape:
            self._previous = np.array(current, copy=True)
            return landmarks
        delta = current - previous
        displacement = np.hypot(delta[:, 0], delta[:, 1])
        alpha = np.clip(self._alpha_min + displacement / self._motion_scale, self._alpha_min, 1.0)
        smoothed = previous + alpha[:, None] * delta
        self._previous = smoothed
        return readonly(smoothed)
