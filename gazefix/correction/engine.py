"""Provider-neutral, synchronous, single-owner correction seam (ADR-0002)."""
from typing import Callable, Protocol

import numpy as np
from gazefix.tracking.models import TrackingResult
from gazefix.correction.models import CorrectionOutput


class CorrectionEngine(Protocol):
    @property
    def description(self) -> str: ...

    def correct(self, frame: np.ndarray, tracking: TrackingResult,
                target: np.ndarray, strength: float) -> CorrectionOutput:
        """Never raise; on skip/failure return the input object unmodified.

        Strength is effective (policy is caller-owned). Return exactly one
        exclusive writable full-frame copy on correction; retain no alias.
        Callers still contain a substitute engine that violates never-raise.
        """
        ...

    def reset(self) -> None: ...
    def close(self) -> None: ...


CorrectionEngineFactory = Callable[[], CorrectionEngine]
