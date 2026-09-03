"""Deterministic primary-face selection policy."""

from __future__ import annotations

from collections.abc import Sequence

from gazefix.tracking.models import TrackedFace


def _normalized_rank_value(value: float) -> float:
    return round(value, 12)


def select_primary_face(faces: Sequence[TrackedFace]) -> int | None:
    """Select the largest, then most central face using stable geometric ties."""

    if not faces:
        return None

    def rank(index: int) -> tuple[float, ...]:
        face = faces[index]
        bounds = face.bounds
        center_x, center_y = bounds.center
        center_distance = (center_x - 0.5) ** 2 + (center_y - 0.5) ** 2
        first = face.landmarks[0]
        # Provider outputs are float32-like values. Rounding prevents negligible
        # representation noise from defeating the documented area/center ties.
        return (
            -_normalized_rank_value(bounds.area),
            _normalized_rank_value(center_distance),
            _normalized_rank_value(bounds.left),
            _normalized_rank_value(bounds.top),
            _normalized_rank_value(bounds.right),
            _normalized_rank_value(bounds.bottom),
            _normalized_rank_value(first.x),
            _normalized_rank_value(first.y),
            _normalized_rank_value(first.z),
            float(face.source_index),
        )

    return min(range(len(faces)), key=rank)
