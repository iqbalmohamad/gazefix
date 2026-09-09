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


def summarise_ages(
    records: Sequence[FrameRecord], source_frames: int | None = None
) -> dict[str, Any]:
    """Summarise corrected-frame age, and say plainly how much it covers.

    Two things are reported alongside the percentiles because leaving them out
    would let the headline number be read as more than it is:

    ``age_coverage``
        The fraction of corrected frames an age could be computed for. A p50
        drawn from a sixth of the stream is not the stream's p50, and a reader
        who sees only a percentile has no way to know that.

    ``frames_usable_before_their_source_was_fed``
        Frames whose age came out **negative** — the corrected frame appeared
        before the client had finished sending the frame it supposedly
        corrects. That is physically impossible for a real service, so it is
        evidence that output frame *n* is not the correction of input frame
        *n*: the 1:1, in-order correspondence this harness assumes has broken.
        Such frames are excluded from the percentiles and counted here instead
        of being quietly dropped.
    """
    total = len(records)
    measurable = [r.age_s for r in records if r.age_s is not None]
    negative = [age for age in measurable if age < 0]
    ages = [age for age in measurable if age >= 0]

    short_output = source_frames is not None and total != source_frames
    integrity = {
        "output_frames": total,
        "source_frames": source_frames if source_frames is not None else "NOT MEASURED",
        "frames_with_age": len(ages),
        "age_coverage": (
            "NOT MEASURED" if total == 0 else f"{len(ages)}/{total}"
        ),
        "frames_usable_before_their_source_was_fed": len(negative),
        # The sender records a frame's feed instant before handing its bytes to
        # gRPC, so the harness cannot manufacture a negative age by racing its
        # own threads. Magnitude is still reported, because how early a frame
        # arrived says how badly correspondence has slipped.
        "most_negative_age_ms": (
            round(min(negative) * 1000, 3) if negative else None
        ),
        # Complete coverage of the frames that came back is not the same as
        # complete coverage of the stream. A response that is short by ten
        # frames can still age every frame it contains, and reporting that as
        # intact would let a real discrepancy pass as a clean run.
        "correspondence_intact": (
            len(negative) == 0 and len(ages) == total and not short_output
        ),
    }
    if short_output:
        integrity["count_warning"] = (
            f"{total} corrected frames came back for {source_frames} source frames. "
            "Per-frame ages assume corrected frame n corrects source frame n; with a "
            "differing count that assumption is unproven and the percentiles below "
            "should not be quoted as the stream's latency."
        )
    if total and len(ages) < total:
        integrity["coverage_warning"] = (
            f"Only {len(ages)} of {total} corrected frames could be aged. The "
            "percentiles below describe those frames and not the whole stream."
        )
    if negative:
        integrity["correspondence_warning"] = (
            f"{len(negative)} corrected frames became usable before the client had "
            f"even begun sending the source frame of the same index (worst "
            f"{min(negative) * 1000:.3f} ms). No service can correct a frame it has "
            "not received, so output frame n is not the correction of input frame n: "
            "per-frame ages below cannot be trusted, and the run should be repeated "
            "before any latency claim is made."
        )

    if not ages:
        return {
            **integrity,
            "p50_frame_age_ms": "NOT MEASURED",
            "p95_frame_age_ms": "NOT MEASURED",
            "p99_frame_age_ms": "NOT MEASURED",
            "max_frame_age_ms": "NOT MEASURED",
            "age_growth_ms_per_frame": "NOT MEASURED",
        }
    return {
        **integrity,
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
