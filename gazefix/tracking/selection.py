"""Deterministic primary-face selection.

GazeFix tracks one face. When the backend reports several, the primary is
chosen by a fixed rule so the choice never jumps arbitrarily between people:

1. If a primary face was selected recently (within ``memory_frames``
   detections of the same camera generation), the candidate whose bounding-box
   centre is nearest to it is kept as long as that distance does not exceed
   ``identity_max_jump`` (normalised units, i.e. a fraction of the frame
   width horizontally / height vertically).
2. Otherwise the candidate with the largest bounding-box area wins; ties go to
   the candidate nearest the frame centre, then to the lowest backend index.

Multi-person tracking is not a feature: only the primary face is reported.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from gazefix.tracking.analysis import face_center_and_area
from gazefix.tracking.tracker import RawFace


@dataclass(frozen=True, slots=True)
class SelectionSettings:
    identity_max_jump: float = 0.25
    memory_frames: int = 15


@dataclass(frozen=True, slots=True)
class Selection:
    index: int
    center: tuple[float, float]
    area: float
    identity_changed: bool


class PrimaryFaceSelector:
    """Stateful selector; ``reset`` on face loss timeouts and camera changes."""

    def __init__(self, settings: SelectionSettings | None = None) -> None:
        self._settings = settings or SelectionSettings()
        self._previous: tuple[float, float] | None = None
        self._missing = 0

    def reset(self) -> None:
        self._previous = None
        self._missing = 0

    @property
    def has_identity(self) -> bool:
        return self._previous is not None

    def select(self, faces: Sequence[RawFace]) -> Selection | None:
        if not faces:
            self._missing += 1
            if self._missing >= self._settings.memory_frames:
                self._previous = None
            return None
        self._missing = 0
        candidates = [face_center_and_area(face.landmarks) for face in faces]
        chosen: int | None = None
        identity_changed = False
        if self._previous is not None:
            previous = self._previous
            distances = [
                math.hypot(center[0] - previous[0], center[1] - previous[1])
                for center, _ in candidates
            ]
            nearest = min(range(len(candidates)), key=lambda i: (distances[i], i))
            if distances[nearest] <= self._settings.identity_max_jump:
                chosen = nearest
            else:
                identity_changed = True
        if chosen is None:
            chosen = min(
                range(len(candidates)),
                key=lambda i: (
                    -candidates[i][1],
                    math.hypot(candidates[i][0][0] - 0.5, candidates[i][0][1] - 0.5),
                    i,
                ),
            )
        center, area = candidates[chosen]
        self._previous = center
        return Selection(chosen, center, area, identity_changed)
