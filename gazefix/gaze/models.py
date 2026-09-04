"""Gaze-estimation contract: an approximate, UNCALIBRATED direction estimate.

What this is and is not
-----------------------
``GazeResult`` says roughly where the eyes are looking, relative to the
camera. It is derived from eye and iris geometry (see
``gazefix.gaze.estimator``): ``eye_yaw_deg`` and ``eye_pitch_deg`` are the
eye's rotation INSIDE its socket, driven by where the iris sits between the
eye corners, and ``yaw_deg``/``pitch_deg`` compose that with the head's
orientation to give a camera-relative direction.

Head pose is not the source of the eye-in-head signal, but it is not absent
from it either, and the docs should not pretend otherwise. It enters twice,
both bounded: as a foreshortening scale on the VERTICAL component only (see
``estimator``), and as a residual leak once the eye corners and the iris are
not at the same depth — about 5 degrees of apparent eye yaw at 30 degrees of
head yaw for a 2 mm depth difference. ``docs/gaze.md`` section 5 measures
both. What makes gaze a distinct signal is that the iris moves it while the
head is still, by far more than either term.

It is not eye tracking. There is no calibration in M2, no per-user anatomy,
no camera intrinsics, and no correction for the angle between a person's
optical and visual axes. The degrees below are a geometric approximation
whose limitations are listed in ``docs/gaze.md``; treat them as an
indication of how far the eyes are looking away from the camera, not as a
measurement. Present them rounded to whole degrees.

Frame and sign conventions (the full table is in ``docs/gaze.md``)
------------------------------------------------------------------
``direction`` is a unit vector in the SAME right-handed camera frame that
``gazefix.tracking.models.HeadPose`` uses: ``x`` toward the image's right,
``y`` up, ``z`` toward the viewer. It points FROM the eyes TOWARD what is
being looked at, so looking straight into the camera is ``(0, 0, 1)``.

``yaw_deg = degrees(atan2(x, z))`` and ``pitch_deg = degrees(asin(y))``:

- ``yaw_deg > 0``: the eyes look toward the subject's OWN LEFT (toward the
  image's right in an unmirrored frame). Same sense as ``HeadPose.yaw_deg``.
- ``pitch_deg > 0``: the eyes look UP. **This is the opposite sense to
  ``HeadPose.pitch_deg``, where positive means the head is tilted DOWN.**
  Gaze pitch is defined directly as the elevation of a direction vector;
  the head-pose angle comes from an Euler decomposition. Never compare the
  two pitches without accounting for the sign.
- Both are ``0`` when the eyes look straight into the camera.

``yaw_deg`` and ``pitch_deg`` are ``None`` on an ``UNAVAILABLE`` result, so
"no estimate" can never be misread as "looking at the camera".
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Literal

import numpy as np
from numpy.typing import NDArray


Array = NDArray[np.float32]
Side = Literal["left", "right"]

#: Value of ``GazeConfidence.provenance``: this is a documented heuristic
#: built from measurable geometry, never a model probability. No gaze model
#: in this milestone reports a probability of its own.
CONFIDENCE_PROVENANCE = (
    "heuristic: product of tracking quality, eyelid openness, inter-eye "
    "agreement, head-pose plausibility, iris-offset headroom and eye "
    "resolution"
)


class GazeStatus(str, Enum):
    """Whether this frame carries a usable gaze estimate.

    ``ESTIMATED``  a gaze direction was computed and its confidence reached
                   the configured minimum.
    ``LOW_CONFIDENCE``
                   a direction was computed but the confidence is below the
                   minimum. The angles are carried so a developer can see
                   them; a consumer must treat them as untrusted.
    ``UNAVAILABLE`` no direction could be computed. ``yaw_deg`` and
                   ``pitch_deg`` are ``None`` and ``message`` says why.
    """

    ESTIMATED = "estimated"
    LOW_CONFIDENCE = "low_confidence"
    UNAVAILABLE = "unavailable"

    @property
    def has_direction(self) -> bool:
        return self in (GazeStatus.ESTIMATED, GazeStatus.LOW_CONFIDENCE)


@dataclass(frozen=True, slots=True)
class GazeConfidence:
    """A deterministic heuristic in ``[0, 1]``, with every factor exposed.

    ``score`` is the product of the six terms below, each itself in
    ``[0, 1]``. Every term is computed from a quantity the pipeline actually
    measures; none of them is a model probability, and none is invented when
    its input is missing (a missing input lowers the relevant term instead).

    - ``tracking_quality``: ``TrackingQuality.score`` from M1 (itself a
      documented geometric heuristic, not a probability).
    - ``openness_term``: from the less-open of the two eyes. An eyelid that
      covers the iris makes the iris centre unreliable; a blink drives this
      to 0.
    - ``agreement_term``: how closely the two eyes' independent estimates
      agree. Replaced by a fixed, lower constant when only one eye is usable,
      because a single eye cannot be cross-checked.
    - ``pose_term``: 1 while the head is near-frontal and falling as the head
      turns away, because the projected-geometry model degrades with head
      rotation. A fixed, lower constant when head pose is unavailable.
    - ``offset_term``: falls as the measured iris offset approaches the limit
      of the eyeball model, where the estimate saturates.
    - ``resolution_term``: falls as the eye becomes small in pixels. Every
      angle here is a ratio over the eye's half-width, so a distant face
      turns one pixel of iris noise into several degrees; without this term a
      tiny eye could report a confident-looking number.

    Only ``tracking_quality`` and the agreement deadband are derived from
    measurement; the other thresholds are CHOSEN engineering defaults, and
    ``docs/gaze.md`` section 4 says which is which. ``eyes_used`` is how many
    eyes contributed. ``head_pose_applied`` says
    whether a head rotation was composed in; when ``False`` the angles are
    eye-in-head angles reported as if the head faced the camera.
    """

    score: float
    tracking_quality: float
    openness_term: float
    agreement_term: float
    pose_term: float
    offset_term: float
    eyes_used: int
    head_pose_applied: bool
    resolution_term: float = 1.0
    provenance: str = CONFIDENCE_PROVENANCE


@dataclass(frozen=True, slots=True)
class EyeGaze:
    """One eye's own eye-in-head rotation and the raw offsets behind it.

    ``yaw_deg`` and ``pitch_deg`` are this eye's rotation inside its socket,
    in the head's frame: positive yaw toward the subject's left, positive
    pitch up, both zero when the iris is centred in the palpebral fissure and
    the head is square to the camera.

    ``offset_u`` and ``offset_v`` are the measured iris-centre displacement
    from the corner midpoint, as a fraction of the eye's half-width, along
    the eye's own axis (``u``, positive toward the subject's left) and
    perpendicular to it (``v``, positive up). ``offset_v`` is the value after
    the head-pose foreshortening correction, so it is directly comparable
    with ``offset_u``; see ``docs/gaze.md``.
    """

    side: Side
    yaw_deg: float
    pitch_deg: float
    offset_u: float
    offset_v: float
    #: Corner-to-corner half-width in pixels. It is the denominator of both
    #: ratios above, so it sets the angular resolution of this eye's estimate;
    #: ``GazeConfidence.resolution_term`` is derived from it.
    half_width_px: float = 0.0
    #: Eyelid aperture over the full eye width, measured along the eye's own
    #: up axis. Same definition and scale as ``EyeLandmarks.openness``, but
    #: roll-invariant, because M1 measures its version along image ``y`` and
    #: so reads a tilted head as a closing eye. ``openness_term`` uses this.
    openness: float = 0.0


@dataclass(frozen=True, slots=True, eq=False)
class GazeResult:
    """One frame's approximate gaze estimate.

    The result belongs to whichever ``TrackingResult`` carries it, and
    inherits that result's frame identity (capture sequence, capture
    timestamp and camera generation): a gaze estimate is never published on
    its own, so it cannot be paired with the wrong frame.

    ``yaw_deg``/``pitch_deg`` are the camera-relative gaze direction and are
    ``None`` when ``status`` is ``UNAVAILABLE``. ``eye_yaw_deg``/
    ``eye_pitch_deg`` are the combined eye-in-head rotation, also ``None``
    when unavailable; they are what distinguishes this estimate from head
    pose and they respond only to iris geometry.
    """

    status: GazeStatus
    confidence: GazeConfidence
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    eye_yaw_deg: float | None = None
    eye_pitch_deg: float | None = None
    direction: Array | None = None
    per_eye: tuple[EyeGaze, ...] = ()
    smoothed: bool = False
    estimation_ms: float | None = None
    message: str = ""

    @property
    def available(self) -> bool:
        """A direction was computed AND its confidence met the minimum."""

        return self.status is GazeStatus.ESTIMATED

    @property
    def head_pose_applied(self) -> bool:
        return self.confidence.head_pose_applied

    def mirrored(self) -> "GazeResult":
        """The same estimate seen in a horizontally mirrored preview.

        Mirroring flips the image's x axis, so the ``x`` component of the
        direction flips and yaw flips with it; pitch is unchanged. This is
        the rule ``HeadPose.mirrored`` uses, applied to the gaze frame, and
        it applies to the eye-in-head angles for the same reason. Sides stay
        anatomical: the subject's left eye is still ``"left"``.
        """

        return replace(
            self,
            yaw_deg=None if self.yaw_deg is None else -self.yaw_deg,
            eye_yaw_deg=None if self.eye_yaw_deg is None else -self.eye_yaw_deg,
            direction=None if self.direction is None else _mirror_direction(self.direction),
            per_eye=tuple(
                replace(eye, yaw_deg=-eye.yaw_deg, offset_u=-eye.offset_u) for eye in self.per_eye
            ),
        )


def _mirror_direction(direction: Array) -> Array:
    mirrored = np.array(direction, dtype=np.float32, copy=True)
    mirrored[0] = -mirrored[0]
    mirrored.setflags(write=False)
    return mirrored


def unavailable(message: str, estimation_ms: float | None = None) -> GazeResult:
    """A result that carries no direction, only the reason there is none."""

    return GazeResult(
        status=GazeStatus.UNAVAILABLE,
        confidence=GazeConfidence(
            score=0.0,
            tracking_quality=0.0,
            openness_term=0.0,
            agreement_term=0.0,
            pose_term=0.0,
            offset_term=0.0,
            eyes_used=0,
            head_pose_applied=False,
            resolution_term=0.0,
        ),
        message=message,
        estimation_ms=estimation_ms,
    )


def direction_from_angles(yaw_deg: float, pitch_deg: float) -> Array:
    """Unit vector for a yaw/pitch pair in the gaze frame (x right, y up, z to viewer)."""

    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    cos_pitch = math.cos(pitch)
    vector = np.array(
        [math.sin(yaw) * cos_pitch, math.sin(pitch), math.cos(yaw) * cos_pitch],
        dtype=np.float32,
    )
    vector.setflags(write=False)
    return vector


def angles_from_direction(direction: Array) -> tuple[float, float]:
    """``(yaw_deg, pitch_deg)`` of a direction in the gaze frame.

    The vector is normalised first, so a slightly non-unit input (a rotation
    matrix that is only approximately orthonormal) cannot push ``asin`` out
    of its domain. A direction with no horizontal component at all — looking
    exactly straight up or down — has no defined yaw; ``atan2(0.0, 0.0)``
    returns 0.0, which is the documented choice rather than an error.
    """

    vector = np.asarray(direction, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("gaze direction must be a finite, non-zero vector")
    x, y, z = (vector / norm).tolist()
    return math.degrees(math.atan2(x, z)), math.degrees(math.asin(max(-1.0, min(1.0, y))))
