"""Metadata-only correction contract; pixels travel beside the result."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from gazefix.tracking.models import Side


class CorrectionStatus(str, Enum):
    CORRECTED = "corrected"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EyeCorrection:
    side: Side
    status: CorrectionStatus
    reason: str = ""
    displacement_px: tuple[float, float] = (0.0, 0.0)
    clamped: bool = False


@dataclass(frozen=True, slots=True)
class CorrectionDebug:
    # Tuples rather than mutable mappings: no scratch arrays cross this seam.
    rois: tuple[tuple[str, tuple[int, int, int, int]], ...] = ()
    mask_bounds: tuple[tuple[str, tuple[int, int, int, int]], ...] = ()
    stage_ms: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    status: CorrectionStatus
    message: str
    strength: float
    correction_ms: float
    compositing_ms: float | None = None
    eyes: tuple[EyeCorrection, ...] = ()
    debug: CorrectionDebug | None = None


@dataclass(frozen=True, slots=True, eq=False)
class CorrectionOutput:
    # Writable exclusive canvas if corrected; exact input object otherwise.
    frame: np.ndarray
    result: CorrectionResult
