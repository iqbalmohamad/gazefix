"""Stateless geometric engine: analytic validation, one copy, atomic return."""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
import math
import time
from typing import Callable

import cv2
import numpy as np

from gazefix.correction import geometry as geo, masks
from gazefix.correction.engine import CorrectionEngineFactory
from gazefix.correction.models import (CorrectionDebug, CorrectionOutput, CorrectionResult,
                                       CorrectionStatus as Status, EyeCorrection)
from gazefix.gaze.models import GazeStatus


@dataclass(frozen=True, slots=True)
class GeometricCorrectionSettings:
    eye_model_ratio: float = 1.25
    min_cos: float = 0.5
    displacement_gain: float = 1.0
    max_displacement_fraction: float = 0.5
    min_displacement_px: float = 0.25
    iris_margin_fraction: float = 0.15
    min_half_width_px: float = 8.0
    min_aperture: float = 0.18
    iris_radius_bounds: tuple[float, float] = (0.2, 0.6)
    min_polygon_area_px: float = 30.0
    padding_fraction: float = 0.25
    edge_px: float = 1.5
    falloff_fraction: float = 0.15
    distance_transform: str = "precise"
    field_guard_px: float = 1.5
    iris_layer: bool = True
    iris_layer_radius_scale: float = 1.05
    pair_coupling: bool = True
    interpolation: str = "linear"
    debug: bool = False

    def validated(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{field.name} must be finite and nonnegative")
        for name in ("eye_model_ratio", "min_cos", "min_half_width_px", "min_polygon_area_px",
                     "falloff_fraction", "iris_layer_radius_scale"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 < self.min_cos <= 1 or not 0 <= self.min_aperture <= 1:
            raise ValueError("min_cos/min_aperture out of range")
        if not 1 <= self.edge_px <= 4:
            raise ValueError("edge_px must be 1..4 (4 is the experimental control)")
        if (len(self.iris_radius_bounds) != 2 or not all(math.isfinite(v) for v in self.iris_radius_bounds)
                or not 0 < self.iris_radius_bounds[0] < self.iris_radius_bounds[1] <= 1):
            raise ValueError("invalid iris_radius_bounds")
        if self.distance_transform not in ("precise", "chamfer3", "chamfer5"):
            raise ValueError("invalid distance_transform")
        minimum = 1.5 if self.distance_transform == "precise" else 2.5
        if self.field_guard_px < minimum:
            raise ValueError(f"field_guard_px must be at least {minimum}")
        if self.interpolation not in ("linear", "cubic"):
            raise ValueError("interpolation must be linear or cubic")
        for name in ("iris_layer", "pair_coupling", "debug"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        return self


class GeometricCorrectionEngine:
    def __init__(self, settings: GeometricCorrectionSettings | None = None,
                 *, clock_ns: Callable[[], int] = time.perf_counter_ns):
        self.settings = (settings or GeometricCorrectionSettings()).validated()
        self._clock = clock_ns
        self._closed = False

    @property
    def description(self):
        s = self.settings
        return f"geometric {'layered' if s.iris_layer else 'field'} eye-region remap (k={s.eye_model_ratio:.2f}, gain={s.displacement_gain:.2f})"

    def reset(self):
        """No temporal state in M3; does not reopen a closed engine."""

    def close(self):
        self._closed = True

    def correct(self, frame, tracking, target, strength):
        started = self._clock()
        eyes = ()
        strength_value = 0.
        compositing_ms = None
        debug = None

        def finish(status, message, output=frame):
            return CorrectionOutput(output, CorrectionResult(status, message, strength_value,
                (self._clock() - started) / 1e6, compositing_ms, eyes, debug))

        def fault(message):
            nonlocal eyes
            eyes = tuple(replace(e, status=Status.FAILED, reason=message, displacement_px=(0., 0.))
                         if e.status is Status.CORRECTED else e for e in eyes)
            return finish(Status.FAILED, message)

        try:
            # Echo valid strength even when an earlier frame gate fires.
            valid_strength = isinstance(strength, (int, float, np.number)) and math.isfinite(strength) and 0 <= strength <= 1
            if valid_strength:
                strength_value = float(strength)
            if self._closed:
                return finish(Status.SKIPPED, "engine closed")
            if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3
                    or frame.shape[2] != 3 or min(frame.shape[:2]) <= 0):
                return finish(Status.SKIPPED, "unsupported frame")
            if frame.shape[:2] != (tracking.geometry.height, tracking.geometry.width):
                return finish(Status.SKIPPED, "geometry mismatch")
            if tracking.geometry.mirrored:
                return finish(Status.SKIPPED, "mirrored coordinates")
            if not valid_strength:
                return finish(Status.SKIPPED, "invalid strength")
            if strength_value == 0:
                return finish(Status.SKIPPED, "strength 0")
            try:
                target = geo.normalize_target(target)
            except (TypeError, ValueError):
                target = None
            if target is None:
                return finish(Status.SKIPPED, "invalid target")
            gaze = tracking.gaze
            if gaze is None or gaze.status is not GazeStatus.ESTIMATED:
                return finish(Status.SKIPPED, f"no gaze: {gaze.status.value if gaze else 'missing'}")
            if not tracking.status.has_landmarks:
                return finish(Status.SKIPPED, "no landmarks")
            if not tracking.iris_available:
                return finish(Status.SKIPPED, "no iris")
            s = self.settings
            change = geo.head_change(tracking, target, strength_value, s.min_cos)
            evaluated = [self._eye(getattr(tracking, side + "_eye"), side, tracking.geometry, change)
                         for side in ("right", "left")]
            eyes = tuple(e[0] for e in evaluated)
            for eye in eyes:
                if eye.status is Status.FAILED:
                    return fault(f"{eye.side} displacement not finite")
            if all(e[1] is not None for e in evaluated) and geo.openings_overlap(evaluated[0][1], evaluated[1][1]):
                eyes = tuple(EyeCorrection(e.side, Status.SKIPPED, "eyes overlap") for e in eyes)
            if s.pair_coupling:
                unsafe = next((e for e in eyes if e.status is Status.SKIPPED
                               and e.reason not in ("eye closed", "negligible displacement")), None)
                if unsafe:
                    eyes = tuple(EyeCorrection(e.side, Status.SKIPPED,
                                 f"pair skipped: {unsafe.side} {unsafe.reason}")
                                 if e.status is Status.CORRECTED else e for e in eyes)
            if not any(e.status is Status.CORRECTED for e in eyes):
                return finish(Status.SKIPPED, "both eyes skipped: " + "; ".join(f"{e.side} {e.reason}" for e in eyes))

            copy_start = self._clock()
            canvas = np.array(frame, copy=True, order="C")  # sole full-frame allocation
            stages = [("copy", (self._clock() - copy_start) / 1e6)]
            layers = []
            for eye, (_, geometry, roi) in zip(eyes, evaluated):
                if eye.status is not Status.CORRECTED:
                    continue
                warp_start = self._clock()
                x0, y0, x1, y1 = roi
                source = frame[y0:y1, x0:x1]
                d = np.asarray(eye.displacement_px, np.float32)
                try:
                    mask, distance = masks.opening_fields(geometry.opening - (x0, y0), source.shape[:2])
                    if s.distance_transform != "precise":
                        distance = cv2.distanceTransform(mask, cv2.DIST_L2, 3 if s.distance_transform == "chamfer3" else 5)
                    if not mask.any() or not np.isfinite(distance).all():
                        raise ValueError("empty/non-finite mask")
                    background_source = masks.sclera_plate(source, mask,
                        geometry.iris_center - (x0, y0), geometry.iris_radius) if s.iris_layer else source
                except Exception as exc:
                    return fault(f"mask generation failed: {exc}")
                try:
                    mx, my, _ = masks.warp_maps(distance, d, geometry.half_width_px,
                                                s.falloff_fraction, s.field_guard_px)
                    interpolation = cv2.INTER_LINEAR if s.interpolation == "linear" else cv2.INTER_CUBIC
                    background = masks.sample_background(background_source, mask, mx, my, interpolation)
                    iris = masks.sample(source, *masks.translated_maps(mask.shape, d)) if s.iris_layer else None
                    layers.append((eye, geometry, roi, mask, distance, background, iris))
                except Exception as exc:
                    return fault(f"compositing failed: {exc}")
                stages.append((f"warp_{eye.side}", (self._clock() - warp_start) / 1e6))
            composite_start = self._clock()  # both eyes' warped layers exist
            try:
                for eye, geometry, roi, mask, distance, background, iris in layers:
                    x0, y0, x1, y1 = roi
                    alpha = masks.blend_alpha(mask, distance, s.edge_px)
                    opacity = masks.iris_alpha(mask, geometry.iris_center - (x0, y0), geometry.iris_radius,
                        np.asarray(eye.displacement_px), s.iris_layer_radius_scale) if iris is not None else None
                    masks.blend_into(canvas[y0:y1, x0:x1], background, alpha, iris, opacity)
            except Exception as exc:
                compositing_ms = (self._clock() - composite_start) / 1e6
                return fault(f"compositing failed: {exc}")
            compositing_ms = (self._clock() - composite_start) / 1e6
            if s.debug:
                stages.append(("composite", compositing_ms))
                bounds = []
                for eye, _, roi, mask, *_ in layers:
                    yy, xx = np.nonzero(mask)
                    bounds.append((eye.side, (int(xx.min()+roi[0]), int(yy.min()+roi[1]),
                                              int(xx.max()+roi[0]+1), int(yy.max()+roi[1]+1))))
                debug = CorrectionDebug(tuple((e.side, roi) for e, _, roi, *_ in layers), tuple(bounds), tuple(stages))
            return finish(Status.CORRECTED, "", canvas)
        except Exception as exc:
            return fault(f"engine exception: {type(exc).__name__}: {exc}")

    def _eye(self, eye, side, frame_geometry, change):
        s = self.settings
        geometry = roi = None
        def skip(reason):
            return EyeCorrection(side, Status.SKIPPED, reason), geometry, roi
        if (eye is None or eye.iris is None or eye.contour.shape != (16, 3)
                or eye.iris.shape != (5, 3) or not np.isfinite(eye.contour).all() or not np.isfinite(eye.iris).all()):
            return skip("no iris")
        geometry = geo.derive_eye(eye, frame_geometry)
        if geometry.aperture < s.min_aperture:
            return skip("eye closed")
        if geo.polygon_area(geometry.opening) < s.min_polygon_area_px or not geo.simple_polygon(geometry.opening):
            return skip("degenerate contour")
        if not eye.valid:
            return skip("eye invalid")
        if geometry.half_width_px < s.min_half_width_px:
            return skip("eye too small")
        if (not s.iris_radius_bounds[0] <= geometry.iris_radius / geometry.half_width_px <= s.iris_radius_bounds[1]
                or not geo.contains(geometry.iris_center, geometry.opening)):
            return skip("iris implausible")
        d = geo.displacement(geometry, change, s.eye_model_ratio, s.displacement_gain)
        if not np.isfinite(d).all():
            return EyeCorrection(side, Status.FAILED, "displacement not finite"), geometry, roi
        d, clamped = geo.clamp_displacement(d, geometry.half_width_px, s.max_displacement_fraction)
        if np.linalg.norm(d) < s.min_displacement_px:
            return skip("negligible displacement")
        destination = geometry.iris_center + d
        if (not geo.contains(destination, geometry.opening)
                or geo.edge_distance(destination, geometry.opening) < max(s.iris_margin_fraction * geometry.iris_radius, s.edge_px)):
            return skip("iris would leave the eye")
        roi = geo.roi_for(geometry, d, s.padding_fraction, s.edge_px)
        if roi[0] < 0 or roi[1] < 0 or roi[2] > frame_geometry.width or roi[3] > frame_geometry.height:
            return skip("eye at image border")
        return EyeCorrection(side, Status.CORRECTED, "", tuple(float(v) for v in d), clamped), geometry, roi


def geometric_engine_factory(settings: GeometricCorrectionSettings | None = None) -> CorrectionEngineFactory:
    return lambda: GeometricCorrectionEngine(settings)
