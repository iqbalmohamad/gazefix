"""Approximate gaze estimation from eye and iris geometry (Milestone 2).

The estimator turns one M1 ``TrackingResult`` into one ``GazeResult``. It is
backend-independent and UI-independent: it reads only the tracking contract
and plain NumPy, so it is exercised by deterministic tests with synthetic
geometry. ``docs/gaze.md`` carries the full derivation, the sign table and
the limitations; the summary below is what a reader needs to follow the code.

The model
---------
Each eye is treated as a sphere of radius ``R`` behind a palpebral fissure of
half-width ``W``. When the eye rotates inside its socket the iris centre moves
across the front of that sphere, so the iris-centre displacement from the
corner midpoint, measured as a fraction of the eye's half-width, gives the
horizontal and vertical components of the eye's own gaze direction:

    g_head_x = k * u        k = W / R  (``GazeSettings.eye_model_ratio``)
    g_head_y = k * v * cos(head_yaw) / cos(head_pitch)
    g_head_z = sqrt(1 - g_head_x^2 - g_head_y^2)

``u`` and ``v`` are measured along the eye's OWN axis (corner to corner) and
perpendicular to it, so head roll is absorbed exactly and needs no correction.
``u`` needs no head-pose correction either: the projected eye width and the
projected horizontal displacement both shrink by ``cos(head_yaw)``, and the
factor cancels in the ratio. Only ``v`` needs the two head-pose factors,
because it is normalised by the horizontal half-width: head pitch
foreshortens the vertical displacement, and head yaw shrinks the normaliser.
That is the whole, and only, role head pose plays in producing the eye-in-head
direction — and it is a bounded scale correction, never the signal itself.

``g_head`` is the eye's direction in the HEAD frame (x toward the subject's
left, y up, z where the face points). Composing it with the head rotation
gives the camera-relative direction that ``GazeResult.yaw_deg`` and
``pitch_deg`` report:

    g_camera = head_rotation @ g_head

A centred iris gives ``g_head = (0, 0, 1)`` and therefore
``g_camera = rotation[:, 2]``, the direction the face points — a person whose
eyes are centred in their sockets is looking where their face points, which
is the correct limiting case rather than a leak of head pose into gaze. What
makes gaze a distinct signal is that ``g_head`` moves with the iris while the
head is still, and does not move at all when only the head moves.

Accuracy
--------
This is a projected-geometry approximation with no calibration, no camera
intrinsics and no per-user anatomy. The known error terms are listed in
``docs/gaze.md``; the largest is a systematic underestimate that grows with
head rotation (about 2 degrees at 30 degrees of head turn with the eyes 20
degrees off-axis, about 8 degrees at 45 and 30). ``GazeConfidence.pose_term``
exists precisely to report that degradation rather than hide it, and
``resolution_term`` reports the separate noise floor set by how many pixels
wide the eye is.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Protocol

import numpy as np

from gazefix.gaze.models import (
    Array,
    EyeGaze,
    GazeConfidence,
    GazeResult,
    GazeStatus,
    Side,
    angles_from_direction,
    unavailable,
)
from gazefix.gaze.smoothing import GazeSmoother
from gazefix.tracking import landmarks as topology
from gazefix.tracking.models import EyeLandmarks, FrameGeometry, HeadPose, TrackingResult


@dataclass(frozen=True, slots=True)
class GazeSettings:
    """Model constants and confidence thresholds; defaults documented in docs/gaze.md.

    ``eye_model_ratio`` is the ratio of the palpebral half-width to the
    eyeball radius. The default 1.25 comes from an adult palpebral fissure of
    roughly 30 mm (half-width 15 mm) and an eyeball radius of roughly 12 mm.
    It is population-average anatomy, not this user's: it is the single
    constant a future calibration milestone would replace.
    """

    eye_model_ratio: float = 1.25
    min_confidence: float = 0.35
    smoothing: float = 0.5
    # Eyelid aperture below which the iris centre is not trustworthy. M1
    # reports roughly 0.25-0.4 for an open eye and near 0 during a blink.
    openness_floor: float = 0.10
    openness_full: float = 0.20
    # The two eyes do not agree even on a well-tracked frontal face: the
    # nasal canthus extends further medially than the globe, so the corner
    # midpoint sits nasal to the eyeball centre and BOTH irises read as
    # displaced temporally. That bias is mirror-symmetric, so averaging the
    # eyes cancels it, but it still shows up as raw disagreement. Measured on
    # real MediaPipe output (docs/gaze.md): 12.6 deg +/- 1.3 across 9
    # detections of the same face at different scales, offsets and rotations.
    # The deadband is set above that so ordinary anatomy costs no confidence;
    # beyond it the term falls to 0 over ``agreement_span_deg``, which still
    # catches a genuinely mistracked eye.
    agreement_deadband_deg: float = 20.0
    agreement_span_deg: float = 25.0
    single_eye_factor: float = 0.6
    # Head rotation over which the projected-geometry model degrades.
    pose_full_deg: float = 25.0
    pose_limit_deg: float = 60.0
    pose_floor_factor: float = 0.25
    no_pose_factor: float = 0.7
    # Bounds the head-pose foreshortening correction to the range
    # [min_cos, 1/min_cos] so a large or noisy head angle cannot amplify the
    # vertical signal without limit.
    min_cos: float = 0.5
    # Planar magnitude of the head-frame direction at which the eyeball model
    # is at its limit; beyond `offset_limit` the direction is clamped.
    offset_warn: float = 0.7
    offset_limit: float = 0.95
    offset_floor_factor: float = 0.2
    # An eye narrower than this in pixels cannot produce a meaningful ratio.
    min_half_width_px: float = 2.0
    # Every angle here is a ratio over the eye's half-width, so the angular
    # noise floor is inversely proportional to it: at a 6 px half-width, one
    # pixel of iris-centre noise is already about 12 degrees. The resolution
    # term reports that, so a distant face cannot produce a confident-looking
    # number. CHOSEN defaults, not measured.
    resolution_floor_px: float = 5.0
    resolution_full_px: float = 20.0
    resolution_floor_factor: float = 0.2

    def validated(self) -> "GazeSettings":
        if not self.eye_model_ratio > 0 or not math.isfinite(self.eye_model_ratio):
            raise ValueError("eye_model_ratio must be positive")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        if not 0.0 <= self.smoothing <= 1.0:
            raise ValueError("smoothing must be between 0 and 1")
        if self.openness_full <= self.openness_floor:
            raise ValueError("openness_full must exceed openness_floor")
        if self.agreement_span_deg <= 0:
            raise ValueError("agreement_span_deg must be positive")
        if self.agreement_deadband_deg < 0:
            raise ValueError("agreement_deadband_deg cannot be negative")
        if self.pose_limit_deg <= self.pose_full_deg:
            raise ValueError("pose_limit_deg must exceed pose_full_deg")
        if self.resolution_full_px <= self.resolution_floor_px:
            raise ValueError("resolution_full_px must exceed resolution_floor_px")
        for name in (
            "single_eye_factor",
            "pose_floor_factor",
            "no_pose_factor",
            "offset_floor_factor",
            "resolution_floor_factor",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not 0.0 < self.min_cos <= 1.0:
            raise ValueError("min_cos must be in (0, 1]")
        if not 0.0 < self.offset_warn < self.offset_limit < 1.0:
            raise ValueError("offset_warn must be below offset_limit, both inside (0, 1)")
        if self.min_half_width_px <= 0:
            raise ValueError("min_half_width_px must be positive")
        return self


class GazeEstimator(Protocol):
    """The boundary consumers depend on, so no consumer depends on one algorithm.

    An implementation turns one tracking result into one gaze result and never
    raises: an input it cannot use becomes an ``UNAVAILABLE`` result carrying
    the reason. ``reset`` drops every piece of temporal state; the caller
    invokes it whenever the face, the camera generation or the frame
    continuity changes.
    """

    @property
    def description(self) -> str:
        """One line naming the algorithm, for the developer overlay and logs."""

    def estimate(self, result: TrackingResult) -> GazeResult:
        ...

    def reset(self) -> None:
        ...


class GeometricGazeEstimator:
    """Iris-offset gaze estimation; see the module docstring for the model."""

    def __init__(
        self,
        settings: GazeSettings | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._settings = (settings or GazeSettings()).validated()
        self._clock = clock
        self._smoother = GazeSmoother(self._settings.smoothing)

    @property
    def description(self) -> str:
        return (
            "geometric iris-offset gaze estimator (uncalibrated, approximate; "
            f"eye model ratio {self._settings.eye_model_ratio:.2f})"
        )

    def reset(self) -> None:
        self._smoother.reset()

    def estimate(self, result: TrackingResult) -> GazeResult:
        started = self._clock()
        try:
            return self._estimate(result, started)
        except Exception as exc:  # noqa: BLE001  (never break the frame path)
            # A gaze failure must not interrupt video: report it as an
            # unavailable estimate and let the frame through untouched.
            self.reset()
            return unavailable(f"gaze estimation failed: {exc}", self._elapsed_ms(started))

    # ------------------------------------------------------------- internals
    def _estimate(self, result: TrackingResult, started: float) -> GazeResult:
        settings = self._settings
        if result.geometry.mirrored:
            # Mirroring is a DISPLAY transform, applied after estimation:
            # ``TrackingResult.mirrored()`` re-expresses angles in the mirrored
            # image's frame (yaw flips, exactly as ``HeadPose.mirrored`` does),
            # while this estimator's eye axis is defined anatomically and would
            # read the same mirrored geometry with the unflipped sign. The two
            # are therefore NOT interchangeable, so estimating from mirrored
            # coordinates is refused rather than answered differently. The
            # pipeline never does it: the worker estimates on the captured
            # frame and any mirroring happens downstream.
            return self._give_up(
                "no gaze: gaze is estimated from unmirrored capture coordinates; "
                "mirror the result after estimation, not before",
                started,
            )
        if not result.status.has_landmarks:
            return self._give_up(
                f"no gaze: no face landmarks for this frame ({result.status.value})", started
            )
        # Deliberately NOT gated on TRACKED. M1 downgrades a frame to
        # LOW_QUALITY if either eye fails its own validity check, so a gate on
        # TRACKED would mean that covering one eye abolishes gaze instead of
        # degrading it. The per-eye loop below decides which eyes are usable,
        # and nothing is waved through: an eye is used only if its own contour
        # and iris are inside the frame and wide enough, and M1's quality score
        # is a factor of the confidence, so a partly-visible face reports a low
        # confidence rather than a confident wrong answer.
        if not result.iris_available:
            return self._give_up(
                "no gaze: the tracker delivered no iris landmarks", started
            )

        pose = _usable_pose(result.pose)
        cos_yaw, cos_pitch = self._foreshortening(pose)
        measurements: list[tuple[EyeGaze, float, float]] = []
        for eye in (result.right_eye, result.left_eye):
            if eye is None or not eye.valid or eye.iris is None:
                continue
            measured = self._measure_eye(eye, result.geometry, cos_yaw, cos_pitch)
            if measured is not None:
                measurements.append(measured)
        if not measurements:
            return self._give_up("no gaze: no eye had usable iris geometry", started)

        x = float(np.mean([m[1] for m in measurements]))
        y = float(np.mean([m[2] for m in measurements]))
        if not (math.isfinite(x) and math.isfinite(y)):
            return self._give_up("no gaze: eye geometry produced a non-finite direction", started)

        x, y = self._smoother.apply(x, y)
        offset_term = self._offset_term(math.hypot(x, y))
        head_direction = self._head_direction(x, y)
        eye_yaw_deg, eye_pitch_deg = angles_from_direction(head_direction)

        if pose is not None:
            camera_direction = np.asarray(pose.rotation, dtype=np.float64) @ head_direction
        else:
            camera_direction = head_direction
        try:
            yaw_deg, pitch_deg = angles_from_direction(camera_direction)
        except ValueError:
            return self._give_up("no gaze: head rotation collapsed the gaze direction", started)

        per_eye = tuple(m[0] for m in measurements)
        confidence = self._confidence(result, per_eye, pose, offset_term, measurements)
        if confidence.score <= 0.0:
            # A zero-confidence estimate carries no information. Publishing
            # angles beside it would invite a consumer to read them anyway, so
            # the honest answer is that there is no estimate for this frame.
            # A closed eyelid during a blink is the usual cause.
            return self._give_up(
                f"no gaze: {_zero_confidence_reason(confidence)}", started
            )
        if not confidence.head_pose_applied:
            # Without a head rotation the reported angles are eye-in-head
            # angles wearing camera-relative names, and the error is the whole
            # unknown head rotation — tens of degrees, not the 0.7 factor
            # pose_term charges. Never call that an ESTIMATED gaze.
            status = GazeStatus.LOW_CONFIDENCE
            message = (
                "head pose unavailable: the angles are eye-in-head only, as if "
                "the head faced the camera"
            )
        elif confidence.score >= settings.min_confidence:
            status, message = GazeStatus.ESTIMATED, ""
        else:
            status = GazeStatus.LOW_CONFIDENCE
            message = f"gaze confidence {confidence.score:.2f} below {settings.min_confidence:.2f}"

        return GazeResult(
            status=status,
            confidence=confidence,
            yaw_deg=yaw_deg,
            pitch_deg=pitch_deg,
            eye_yaw_deg=eye_yaw_deg,
            eye_pitch_deg=eye_pitch_deg,
            direction=_readonly_direction(camera_direction),
            per_eye=per_eye,
            smoothed=self._smoother.enabled,
            estimation_ms=self._elapsed_ms(started),
            message=message,
        )

    def _give_up(self, message: str, started: float) -> GazeResult:
        """No estimate for this frame: drop temporal state and say why."""

        self._smoother.reset()
        return unavailable(message, self._elapsed_ms(started))

    def _elapsed_ms(self, started: float) -> float:
        return (self._clock() - started) * 1000.0

    def _foreshortening(self, pose: HeadPose | None) -> tuple[float, float]:
        """``(cos(head_yaw), cos(head_pitch))``, each bounded by ``min_cos``.

        Both are 1.0 when there is no usable head pose, which leaves ``v``
        uncorrected; the result then reports ``head_pose_applied = False`` and
        is capped at ``LOW_CONFIDENCE``.
        """

        if pose is None:
            return 1.0, 1.0
        floor = self._settings.min_cos
        return (
            min(1.0, max(floor, abs(math.cos(math.radians(pose.yaw_deg))))),
            min(1.0, max(floor, abs(math.cos(math.radians(pose.pitch_deg))))),
        )

    def _measure_eye(
        self,
        eye: EyeLandmarks,
        geometry: FrameGeometry,
        cos_yaw: float,
        cos_pitch: float,
    ) -> tuple[EyeGaze, float, float] | None:
        """One eye's head-frame direction components, or ``None`` if degenerate."""

        assert eye.iris is not None  # guarded by the caller
        # M1's validate_landmarks already rejects non-finite landmarks, so this
        # only bites on a hand-built result; check anyway, because letting a
        # non-finite value reach the arithmetic below produces a NumPy warning
        # on the frame path before the finiteness test further down catches it.
        if not (
            np.all(np.isfinite(eye.contour[:, :2])) and np.all(np.isfinite(eye.iris[:1, :2]))
        ):
            return None
        scale = np.array([geometry.width, geometry.height], dtype=np.float64)
        outer = np.asarray(eye.contour[topology.CONTOUR_OUTER_CORNER_POSITION, :2], dtype=np.float64) * scale
        inner = np.asarray(eye.contour[topology.CONTOUR_INNER_CORNER_POSITION, :2], dtype=np.float64) * scale
        iris = np.asarray(eye.iris[0, :2], dtype=np.float64) * scale

        # ``ex`` runs along the eye axis and is oriented toward the SUBJECT'S
        # LEFT for both eyes: for the subject's right eye (image left) that is
        # outer -> inner, for the left eye (image right) it is inner -> outer.
        axis = inner - outer if eye.side == "right" else outer - inner
        half_width = float(np.linalg.norm(axis)) / 2.0
        if not math.isfinite(half_width) or half_width < self._settings.min_half_width_px:
            return None
        ex = axis / (2.0 * half_width)
        # Perpendicular pointing UP in the image (rows grow downwards), for
        # either eye, because ``ex`` has already been sign-corrected.
        ey = np.array([ex[1], -ex[0]], dtype=np.float64)

        offset = iris - (outer + inner) / 2.0
        u = float(offset @ ex) / half_width
        v = float(offset @ ey) / half_width * cos_yaw / cos_pitch
        if not (math.isfinite(u) and math.isfinite(v)):
            return None

        ratio = self._settings.eye_model_ratio
        x, y = ratio * u, ratio * v
        yaw_deg, pitch_deg = angles_from_direction(self._head_direction(x, y))
        return (
            EyeGaze(
                side=eye.side,
                yaw_deg=yaw_deg,
                pitch_deg=pitch_deg,
                offset_u=u,
                offset_v=v,
                half_width_px=half_width,
            ),
            x,
            y,
        )

    def _head_direction(self, x: float, y: float) -> np.ndarray:
        """Unit eye-in-head direction from its two planar components.

        A pair whose magnitude exceeds ``offset_limit`` is past the eyeball
        model's range; it is scaled back onto that limit rather than given an
        invented depth, and ``offset_term`` reports the loss of trust.
        """

        limit = self._settings.offset_limit
        planar = math.hypot(x, y)
        if planar > limit:
            x, y = x * (limit / planar), y * (limit / planar)
            planar = limit
        return np.array([x, y, math.sqrt(max(0.0, 1.0 - planar * planar))], dtype=np.float64)

    def _offset_term(self, planar: float) -> float:
        settings = self._settings
        if planar <= settings.offset_warn:
            return 1.0
        if planar >= settings.offset_limit:
            return settings.offset_floor_factor
        span = settings.offset_limit - settings.offset_warn
        fraction = (planar - settings.offset_warn) / span
        return 1.0 - fraction * (1.0 - settings.offset_floor_factor)

    def _confidence(
        self,
        result: TrackingResult,
        per_eye: tuple[EyeGaze, ...],
        pose: HeadPose | None,
        offset_term: float,
        measurements: list[tuple[EyeGaze, float, float]],
    ) -> GazeConfidence:
        settings = self._settings
        quality = result.quality.score if result.quality is not None else 0.0

        used_sides = {eye.side for eye in per_eye}
        opennesses = [
            eye.openness
            for eye in (result.right_eye, result.left_eye)
            if eye is not None and eye.side in used_sides
        ]
        openness_term = _ramp(
            min(opennesses) if opennesses else 0.0, settings.openness_floor, settings.openness_full
        )

        if len(per_eye) >= 2:
            spread = math.hypot(
                per_eye[0].yaw_deg - per_eye[1].yaw_deg,
                per_eye[0].pitch_deg - per_eye[1].pitch_deg,
            )
            excess = max(0.0, spread - settings.agreement_deadband_deg)
            agreement_term = max(0.0, 1.0 - excess / settings.agreement_span_deg)
        else:
            agreement_term = settings.single_eye_factor

        if pose is None:
            pose_term = settings.no_pose_factor
        else:
            turn = max(abs(pose.yaw_deg), abs(pose.pitch_deg))
            if turn <= settings.pose_full_deg:
                pose_term = 1.0
            elif turn >= settings.pose_limit_deg:
                pose_term = settings.pose_floor_factor
            else:
                span = settings.pose_limit_deg - settings.pose_full_deg
                fraction = (turn - settings.pose_full_deg) / span
                pose_term = 1.0 - fraction * (1.0 - settings.pose_floor_factor)

        widths = [eye.half_width_px for eye in per_eye if eye.half_width_px > 0]
        resolution_term = _ramp_to_floor(
            min(widths) if widths else 0.0,
            settings.resolution_floor_px,
            settings.resolution_full_px,
            settings.resolution_floor_factor,
        )

        terms = (quality, openness_term, agreement_term, pose_term, offset_term, resolution_term)
        score = 1.0
        for term in terms:
            score *= min(1.0, max(0.0, term if math.isfinite(term) else 0.0))
        return GazeConfidence(
            score=score,
            tracking_quality=quality,
            openness_term=openness_term,
            agreement_term=agreement_term,
            pose_term=pose_term,
            offset_term=offset_term,
            eyes_used=len(measurements),
            head_pose_applied=pose is not None,
            resolution_term=resolution_term,
        )


def _usable_pose(pose: HeadPose | None) -> HeadPose | None:
    """The pose, or ``None`` if any part of it is missing or non-finite.

    One definition, used for the foreshortening correction, the composition
    and the confidence alike, so a partly-broken pose can never be applied in
    one place and reported as absent in another. It matters because
    ``max(floor, nan)`` returns the floor: a NaN head pitch would otherwise
    become a permanent 2x amplification of the vertical signal.
    """

    if pose is None:
        return None
    if not (math.isfinite(pose.yaw_deg) and math.isfinite(pose.pitch_deg)):
        return None
    if not bool(np.all(np.isfinite(pose.rotation))):
        return None
    return pose


def _zero_confidence_reason(confidence: GazeConfidence) -> str:
    """Name the factor that drove the confidence to zero, for the message."""

    named = (
        ("eyelids too closed to locate the iris", confidence.openness_term),
        ("face tracking quality is zero", confidence.tracking_quality),
        ("the two eyes disagree completely", confidence.agreement_term),
        ("head turned too far for the gaze model", confidence.pose_term),
        ("iris offset is outside the eyeball model", confidence.offset_term),
        ("the eye is too few pixels wide to measure", confidence.resolution_term),
    )
    zeroed = [reason for reason, term in named if term <= 0.0]
    return "; ".join(zeroed) if zeroed else "gaze confidence is zero"


def _ramp_to_floor(value: float, floor: float, full: float, floor_factor: float) -> float:
    """``floor_factor`` at or below ``floor``, 1 at or above ``full``, linear between."""

    if not math.isfinite(value):
        return floor_factor
    if full <= floor:
        return 1.0 if value >= full else floor_factor
    fraction = min(1.0, max(0.0, (value - floor) / (full - floor)))
    return floor_factor + fraction * (1.0 - floor_factor)


def _ramp(value: float, floor: float, full: float) -> float:
    """0 at or below ``floor``, 1 at or above ``full``, linear between."""

    if not math.isfinite(value):
        return 0.0
    if full <= floor:
        return 1.0 if value >= full else 0.0
    return min(1.0, max(0.0, (value - floor) / (full - floor)))


def _readonly_direction(vector: np.ndarray) -> Array:
    """A read-only unit copy; the norm is checked here, not assumed."""

    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("gaze direction must be a finite, non-zero vector")
    unit = np.asarray(vector, dtype=np.float32) / np.float32(norm)
    unit.setflags(write=False)
    return unit
