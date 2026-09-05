"""Pure requested-to-effective strength policy; no engine or temporal state."""
from dataclasses import dataclass, fields
import math

import numpy as np
from gazefix.gaze.models import GazeStatus


@dataclass(frozen=True, slots=True)
class PolicySettings:
    light_factor: float = 0.3
    normal_deg: float = 5.
    reduce_deg: float = 25.
    disable_deg: float = 35.
    conf_floor: float = 0.35
    conf_full: float = 0.60
    max_effective_strength: float = 1.

    def validated(self):
        if not all(math.isfinite(getattr(self, f.name)) for f in fields(self)):
            raise ValueError("policy settings must be finite")
        if not 0 < self.normal_deg < self.reduce_deg < self.disable_deg <= 180:
            raise ValueError("policy breakpoints must increase within (0,180]")
        if not 0 <= self.conf_floor < self.conf_full <= 1:
            raise ValueError("confidence ramp must increase within [0,1]")
        if not 0 <= self.light_factor <= 1 or not 0 <= self.max_effective_strength <= 1:
            raise ValueError("policy multipliers must be within [0,1]")
        return self


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    requested_strength: float
    effective_strength: float
    deviation_deg: float | None
    confidence: float
    reason: str


def resolve_effective_strength(requested, gaze, target, settings=None):
    s = (settings or PolicySettings()).validated()
    if not math.isfinite(requested) or not 0 <= requested <= 1:
        raise ValueError("requested strength must be in [0,1]")
    if gaze is None or gaze.status is not GazeStatus.ESTIMATED:
        return PolicyDecision(requested, 0., None, 0. if gaze is None else gaze.confidence.score, "gaze not estimated")
    target = np.asarray(target, dtype=np.float64)
    if target.shape != (3,) or not np.isfinite(target).all() or not np.any(target):
        raise ValueError("invalid target")
    target = target / np.max(np.abs(target))
    target /= np.linalg.norm(target)
    deviation = math.degrees(math.acos(float(np.clip(np.dot(gaze.direction, target), -1, 1))))
    confidence = gaze.confidence.score
    mc = float(np.clip((confidence - s.conf_floor) / (s.conf_full - s.conf_floor), 0, 1))
    md = float(np.interp(deviation, (0, s.normal_deg, s.reduce_deg, s.disable_deg), (s.light_factor, 1, 1, 0)))
    reason = ("requested strength 0" if requested == 0 else "low confidence" if mc == 0 else
              "deviation above disable threshold" if deviation >= s.disable_deg else "ok")
    return PolicyDecision(requested, min(s.max_effective_strength, requested * md * mc), deviation, confidence, reason)
