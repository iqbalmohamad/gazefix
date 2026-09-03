"""Stable tracking contract independent of any inference provider."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from gazefix.tracking.metrics import TrackingMetricsSnapshot
from gazefix.tracking.models import TrackingResult


Frame = NDArray[np.uint8]


@runtime_checkable
class FaceTracker(Protocol):
    """Lifecycle and frame-tracking API consumed by future pipeline wiring."""

    def initialize(self) -> None:
        """Allocate provider resources and make the tracker ready."""

    def track(
        self,
        frame: Frame,
        *,
        frame_sequence: int | None = None,
        timestamp_ns: int | None = None,
    ) -> TrackingResult:
        """Return metadata for one BGR uint8 frame without modifying it."""

    def metrics_snapshot(self) -> TrackingMetricsSnapshot:
        """Return a thread-safe snapshot of tracker-specific diagnostics."""

    def shutdown(self) -> None:
        """Release provider resources; repeated calls must be safe."""
