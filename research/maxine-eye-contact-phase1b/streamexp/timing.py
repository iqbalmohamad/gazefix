"""Event timeline, latency statistics and result serialisation.

Every timestamp the harness records goes through here, for three reasons:

* one monotonic clock is used for every interval, so no measurement can be
  corrupted by a wall-clock step;
* each event also carries a wall-clock reading, so a run can be correlated with
  a server-side log;
* nothing is summarised into a single number without the raw series being
  written out beside it, because the assignment forbids substituting
  throughput for latency.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence


def monotonic() -> float:
    return time.perf_counter()


def wall() -> float:
    return time.time()


@dataclass(frozen=True)
class Event:
    """One named instant in a run."""

    name: str
    at: float
    """Monotonic clock reading."""
    wall_clock: float
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Timeline:
    """Ordered record of everything that happened during one RPC."""

    started_monotonic: float = field(default_factory=monotonic)
    started_wall: float = field(default_factory=wall)
    events: list[Event] = field(default_factory=list)

    def mark(self, name: str, at: float | None = None, **detail: Any) -> Event:
        event = Event(name, monotonic() if at is None else at, wall(), detail)
        self.events.append(event)
        return event

    def first(self, name: str) -> Event | None:
        for event in self.events:
            if event.name == name:
                return event
        return None

    def elapsed(self, name: str) -> float | None:
        """Seconds from RPC start to the first occurrence of ``name``."""
        event = self.first(name)
        return None if event is None else event.at - self.started_monotonic

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "event": e.name,
                "t_since_start_s": round(e.at - self.started_monotonic, 6),
                "monotonic_s": round(e.at, 6),
                "wall_clock_iso": _iso(e.wall_clock),
                "detail": json.dumps(e.detail, sort_keys=True) if e.detail else "",
            }
            for e in self.events
        ]


@dataclass(frozen=True)
class FrameRecord:
    """One corrected frame, from its source instant to its usable instant."""

    output_index: int
    output_pts_s: float
    fed_at_s: float | None
    """Seconds since RPC start at which the matching source frame was fed."""
    usable_at_s: float
    """Seconds since RPC start at which every byte of this frame had arrived."""
    byte_end: int

    @property
    def age_s(self) -> float | None:
        """Age of the corrected frame when it became usable on the client."""
        if self.fed_at_s is None:
            return None
        return self.usable_at_s - self.fed_at_s


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile. ``None`` for an empty series, never a guess."""
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = max(1, min(len(ordered), int(round(fraction * len(ordered) + 0.5))))
    return ordered[rank - 1]


def summarise_ages(records: Sequence[FrameRecord]) -> dict[str, Any]:
    ages = [r.age_s for r in records if r.age_s is not None]
    if not ages:
        return {
            "frames_with_age": 0,
            "p50_frame_age_ms": "NOT MEASURED",
            "p95_frame_age_ms": "NOT MEASURED",
            "p99_frame_age_ms": "NOT MEASURED",
            "max_frame_age_ms": "NOT MEASURED",
            "age_growth_ms_per_frame": "NOT MEASURED",
        }
    return {
        "frames_with_age": len(ages),
        "p50_frame_age_ms": round(percentile(ages, 0.50) * 1000, 3),
        "p95_frame_age_ms": round(percentile(ages, 0.95) * 1000, 3),
        "p99_frame_age_ms": round(percentile(ages, 0.99) * 1000, 3),
        "max_frame_age_ms": round(max(ages) * 1000, 3),
        "age_growth_ms_per_frame": _slope_ms_per_frame(ages),
    }


def _slope_ms_per_frame(ages: Sequence[float]) -> float | None:
    """Least-squares slope of frame age against frame number.

    A positive slope that persists is the signature of kill condition 4,
    "latency grows continuously with stream duration". Reported as a number so
    the reader can judge it, not as a verdict.
    """
    n = len(ages)
    if n < 3:
        return None
    mean_x = (n - 1) / 2
    mean_y = sum(ages) / n
    numerator = sum((i - mean_x) * (a - mean_y) for i, a in enumerate(ages))
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    if denominator == 0:
        return None
    return round(numerator / denominator * 1000, 6)


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def frame_rows(records: Sequence[FrameRecord]) -> list[dict[str, Any]]:
    return [
        {
            "output_index": r.output_index,
            "output_pts_s": round(r.output_pts_s, 6),
            "fed_at_s": "" if r.fed_at_s is None else round(r.fed_at_s, 6),
            "usable_at_s": round(r.usable_at_s, 6),
            "frame_age_ms": "" if r.age_s is None else round(r.age_s * 1000, 3),
            "byte_end": r.byte_end,
        }
        for r in records
    ]


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch)) + f".{int(epoch % 1 * 1e6):06d}Z"


def as_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)
