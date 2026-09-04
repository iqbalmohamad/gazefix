"""Velocity-adaptive smoothing of the eye-in-head gaze direction.

Iris landmarks jitter by a pixel or two between frames, which at a typical
eye width is worth a couple of degrees of apparent eye rotation — enough to
make a raw gaze readout unusable. The filter below damps that jitter while
letting a real saccade through almost unfiltered, using the same
velocity-adaptive blend as ``gazefix.tracking.stabilizer``.

It smooths the EYE-IN-HEAD direction ``(x, y)``, not the camera-relative
gaze. Head motion therefore passes through the estimator instantly (it is
applied after smoothing, by composing the head rotation) and only the
eye-in-socket signal is damped. It never holds a frame back: a frame's
output depends on that frame and the previous output only, so no latency is
added. It is reset whenever the estimate is unavailable, the face is lost or
re-identified, the camera generation changes, or frames stop arriving, so an
old eye position can never bleed into a new one.
"""

from __future__ import annotations

import math


class GazeSmoother:
    def __init__(self, smoothing: float, motion_scale: float = 0.05) -> None:
        """``smoothing`` in ``[0, 1]``: 0 disables the filter, 1 is strongest.

        The minimum blend weight is ``1 - 0.7 * smoothing`` (never below 0.3).
        A frame-to-frame movement of ``motion_scale`` or more in the direction
        components — 0.05 is roughly 3 degrees of eye rotation — passes
        through unfiltered.
        """

        if not 0.0 <= smoothing <= 1.0:
            raise ValueError("smoothing must be between 0 and 1")
        if motion_scale <= 0:
            raise ValueError("motion_scale must be positive")
        self._alpha_min = 1.0 - 0.7 * smoothing
        self._motion_scale = motion_scale
        self._previous: tuple[float, float] | None = None

    @property
    def enabled(self) -> bool:
        return self._alpha_min < 1.0

    def reset(self) -> None:
        self._previous = None

    def apply(self, x: float, y: float) -> tuple[float, float]:
        """Return the smoothed ``(x, y)``; the first sample passes through."""

        if not self.enabled or not (math.isfinite(x) and math.isfinite(y)):
            return x, y
        previous = self._previous
        if previous is None:
            self._previous = (x, y)
            return x, y
        dx, dy = x - previous[0], y - previous[1]
        alpha = min(1.0, self._alpha_min + math.hypot(dx, dy) / self._motion_scale)
        smoothed = (previous[0] + alpha * dx, previous[1] + alpha * dy)
        self._previous = smoothed
        return smoothed
