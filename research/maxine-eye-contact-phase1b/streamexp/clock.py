"""Realtime pacing.

Stage A's whole point is that the input must *not* arrive as fast as the disk
allows. A ten-second source has to take about ten seconds to feed, or the
measurement answers a batch-throughput question instead of a live-capture one.

:class:`RealtimeSchedule` converts a media presentation time into a wall-clock
deadline relative to the moment feeding began, and blocks until it arrives. It
also records the error it could not absorb, so a run that failed to keep
cadence is visible in the results rather than assumed away.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class RealtimeSchedule:
    """Map media timestamps onto wall-clock deadlines."""

    origin: float = field(default_factory=time.perf_counter)
    lead_seconds: float = 0.0
    """Feed each unit this far ahead of its presentation time.

    Zero means strict realtime: the bytes of the frame shown at t=1.0 s are
    handed to the RPC one second after the feed began. A camera cannot produce
    a frame before it happens, so a positive lead would be a measurement that
    live capture cannot reproduce.
    """

    late_seconds: list[float] = field(default_factory=list)

    def deadline(self, media_time: float) -> float:
        return self.origin + max(0.0, media_time - self.lead_seconds)

    def wait_until(self, media_time: float) -> float:
        """Sleep until ``media_time`` is due; return the monotonic time on release."""
        target = self.deadline(media_time)
        while True:
            now = time.perf_counter()
            remaining = target - now
            if remaining <= 0:
                if remaining < -0.001:
                    self.late_seconds.append(-remaining)
                return now
            time.sleep(min(remaining, 0.005))

    def statistics(self) -> dict[str, float | int | str]:
        if not self.late_seconds:
            return {"late_units": 0, "max_lateness_ms": 0.0, "mean_lateness_ms": 0.0}
        return {
            "late_units": len(self.late_seconds),
            "max_lateness_ms": round(max(self.late_seconds) * 1000, 3),
            "mean_lateness_ms": round(
                sum(self.late_seconds) / len(self.late_seconds) * 1000, 3
            ),
        }
