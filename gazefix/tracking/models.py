"""Tracking-result contract: immutable values tied to one captured frame.

Every ``TrackingResult`` names the frame it describes (``sequence``,
``captured_at_ns``) and the camera generation it belongs to
(``camera_request_id``); consumers compare those to the frame they display and
never pair a result with a different frame.

Coordinates and conventions (see docs/tracking.md):

- Landmarks are ``float32`` arrays of shape ``(N, 3)`` in NORMALISED frame
  coordinates of the unmirrored captured frame: ``x`` in ``[0, 1]`` from the
  image's left edge to its right edge, ``y`` in ``[0, 1]`` from top to bottom,
  ``z`` a model-relative depth on roughly the same scale as ``x`` (smaller and
  negative means closer to the camera; not metric). ``landmark_pixels`` maps
  them to pixels of the frame described by ``geometry``. Points may fall
  slightly outside ``[0, 1]`` when the face touches the frame edge.
- Left and right are ANATOMICAL: the subject's own left and right. In an
  unmirrored frame the subject's right eye appears on the image's left.
- ``HeadPose`` is head orientation only. It says nothing about where the eyes
  look; eye-direction estimation is not part of this milestone.
- ``TrackingQuality.score`` is a documented geometric availability signal, not
  a model probability: the tracking backend applies its own detection,
  presence and tracking thresholds internally and does not expose the scores.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from gazefix.tracking import landmarks as topology


Array = NDArray[np.float32]
Side = Literal["left", "right"]


class TrackingStatus(str, Enum):
    """What the tracking stage produced for a frame.

    Only ``TRACKED`` means a valid primary face with usable eye landmarks.
    ``LOW_QUALITY`` still carries the raw landmarks but ``face_valid`` is
    ``False``; every other status carries no landmarks at all.
    """

    TRACKED = "tracked"
    LOW_QUALITY = "low_quality"
    NO_FACE = "no_face"
    INITIALIZING = "initializing"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    TIMEOUT = "timeout"
    DISABLED = "disabled"

    @property
    def has_landmarks(self) -> bool:
        return self in (TrackingStatus.TRACKED, TrackingStatus.LOW_QUALITY)


@dataclass(frozen=True, slots=True)
class FrameGeometry:
    """Size of the frame the normalised coordinates refer to.

    ``mirrored`` is ``False`` for every result the tracker produces (the
    captured frame is not mirrored); it becomes ``True`` only on a result
    returned by ``TrackingResult.mirrored`` so a mirrored preview can keep the
    convention explicit.
    """

    width: int
    height: int
    mirrored: bool = False


def readonly(values: object, shape: tuple[int, ...] | None = None) -> Array:
    """Return a read-only ``float32`` copy, optionally checking ``shape``."""

    array = np.array(values, dtype=np.float32, copy=True)
    if shape is not None and array.shape != shape:
        raise ValueError(f"Expected an array of shape {shape}, got {array.shape}")
    array.setflags(write=False)
    return array


@dataclass(frozen=True, slots=True, eq=False)
class HeadPose:
    """Head ORIENTATION relative to the camera (never eye gaze).

    Right-handed camera frame: ``x`` to the image's right, ``y`` up, ``z``
    toward the viewer. ``rotation`` (3×3) maps the canonical face frame into
    it and ``translation_cm`` is the face origin in that frame (the backend's
    canonical-face metric units; approximate, negative ``z`` = in front of
    the camera). The Euler angles decompose ``rotation = Rz(roll) · Ry(yaw)
    · Rx(pitch)`` in degrees:

    - ``yaw_deg > 0``: the head is turned toward the subject's LEFT (the nose
      moves toward the image's right in the unmirrored frame).
    - ``pitch_deg > 0``: the head is tilted DOWN (forehead toward the camera,
      chin away). The sign follows the right-handed frame; it was checked
      against the landmark depth ordering, not against a physical nod.
    - ``roll_deg > 0``: the head rotates counter-clockwise as seen in the
      unmirrored image (toward the subject's right shoulder).
    """

    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    rotation: Array
    translation_cm: Array

    def mirrored(self) -> "HeadPose":
        """The same pose seen in a horizontally mirrored image (yaw and roll flip)."""

        flip = np.diag([-1.0, 1.0, 1.0]).astype(np.float32)
        return HeadPose(
            yaw_deg=-self.yaw_deg,
            pitch_deg=self.pitch_deg,
            roll_deg=-self.roll_deg,
            rotation=readonly(flip @ self.rotation @ flip, (3, 3)),
            translation_cm=readonly(self.translation_cm * np.array([-1.0, 1.0, 1.0]), (3,)),
        )


@dataclass(frozen=True, slots=True, eq=False)
class EyeLandmarks:
    """One eye: its eyelid contour and, when delivered, its iris.

    ``contour`` has 16 points in the order documented in
    ``gazefix.tracking.landmarks``: outer corner, lower lid (outer to inner),
    inner corner, upper lid (inner to outer). ``iris`` is ``(5, 3)`` (centre
    then four contour points) or ``None`` when the tracker delivered no iris
    landmarks. ``openness`` is the mean vertical lid separation divided by the
    corner-to-corner width, both in pixels: a geometric eyelid-aperture ratio
    (roughly 0.25–0.4 open, near 0 during a blink), not an eye direction.
    ``valid`` requires every contour (and iris) point inside the frame and a
    corner width of at least the configured minimum in pixels.
    """

    side: Side
    contour: Array
    iris: Array | None
    openness: float
    width_px: float
    valid: bool

    @property
    def outer_corner(self) -> Array:
        return self.contour[topology.CONTOUR_OUTER_CORNER_POSITION]

    @property
    def inner_corner(self) -> Array:
        return self.contour[topology.CONTOUR_INNER_CORNER_POSITION]

    @property
    def lower_lid(self) -> Array:
        return self.contour[list(topology.CONTOUR_LOWER_LID_POSITIONS)]

    @property
    def upper_lid(self) -> Array:
        return self.contour[list(topology.CONTOUR_UPPER_LID_POSITIONS)]

    @property
    def iris_center(self) -> Array | None:
        return None if self.iris is None else self.iris[0]

    def mirrored(self) -> "EyeLandmarks":
        return replace(
            self,
            contour=_mirror_x(self.contour),
            iris=None if self.iris is None else _mirror_x(self.iris),
        )


@dataclass(frozen=True, slots=True)
class TrackingQuality:
    """Availability/geometric quality of the primary face, in ``[0, 1]``.

    ``score = min(in_frame_fraction, size_term)`` where ``in_frame_fraction``
    is the share of landmarks inside the frame and ``size_term`` rises
    linearly from 0 at a face height of ``size_floor`` of the frame height to
    1 at ``size_full`` (defaults 10 % and 20 %). ``provenance`` states that
    the value is this heuristic; ``backend_thresholds`` records the
    (detection, presence, tracking) minimum scores the backend applied
    internally before it reported the face at all. There is no model
    probability in this contract because the backend does not expose one.
    """

    score: float
    in_frame_fraction: float
    face_height_fraction: float
    backend_thresholds: tuple[float, float, float]
    provenance: str = "heuristic: min(in-frame fraction, face-size term)"


@dataclass(frozen=True, slots=True)
class TrackingTiming:
    """Milliseconds, measured on the tracker and processor threads.

    - ``inference_ms``: colour conversion plus the backend call, on the
      tracker thread.
    - ``total_ms``: from the processor handing the frame to the tracker until
      the result was available (includes queueing behind an in-flight
      inference).
    - ``waited_ms``: how long the processor thread actually waited for this
      frame's result before publishing (bounded by ``tracking_wait_ms``).
    """

    inference_ms: float = 0.0
    total_ms: float = 0.0
    waited_ms: float = 0.0


@dataclass(frozen=True, slots=True, eq=False)
class TrackingResult:
    """Everything the tracking stage knows about one captured frame."""

    status: TrackingStatus
    sequence: int
    captured_at_ns: int
    camera_request_id: int
    geometry: FrameGeometry
    timing: TrackingTiming = TrackingTiming()
    message: str = ""
    faces_detected: int = 0
    landmarks: Array | None = None
    left_eye: EyeLandmarks | None = None
    right_eye: EyeLandmarks | None = None
    iris_available: bool = False
    pose: HeadPose | None = None
    quality: TrackingQuality | None = None
    stabilized: bool = False

    @property
    def face_valid(self) -> bool:
        return self.status is TrackingStatus.TRACKED

    @property
    def eyes_valid(self) -> bool:
        return (
            self.left_eye is not None
            and self.right_eye is not None
            and self.left_eye.valid
            and self.right_eye.valid
        )

    @property
    def pose_available(self) -> bool:
        return self.pose is not None

    def belongs_to(self, sequence: int, camera_request_id: int) -> bool:
        return self.sequence == sequence and self.camera_request_id == camera_request_id

    def landmark_pixels(self) -> Array | None:
        """``(N, 2)`` pixel coordinates of ``landmarks`` in ``geometry``."""

        if self.landmarks is None:
            return None
        scale = np.array([self.geometry.width, self.geometry.height], dtype=np.float32)
        return readonly(self.landmarks[:, :2] * scale)

    def mirrored(self) -> "TrackingResult":
        """Coordinates for a horizontally mirrored preview; sides stay anatomical."""

        if self.geometry.mirrored:
            raise ValueError("Result is already expressed in mirrored coordinates")
        return replace(
            self,
            geometry=replace(self.geometry, mirrored=True),
            landmarks=None if self.landmarks is None else _mirror_x(self.landmarks),
            left_eye=None if self.left_eye is None else self.left_eye.mirrored(),
            right_eye=None if self.right_eye is None else self.right_eye.mirrored(),
            pose=None if self.pose is None else self.pose.mirrored(),
        )


def _mirror_x(points: Array) -> Array:
    mirrored = np.array(points, dtype=np.float32, copy=True)
    mirrored[:, 0] = 1.0 - mirrored[:, 0]
    mirrored.setflags(write=False)
    return mirrored


def untracked(
    status: TrackingStatus,
    sequence: int,
    captured_at_ns: int,
    camera_request_id: int,
    geometry: FrameGeometry,
    message: str = "",
    timing: TrackingTiming | None = None,
    faces_detected: int = 0,
) -> TrackingResult:
    """A result without landmarks for any status that carries none."""

    if status.has_landmarks:
        raise ValueError(f"{status.value} results carry landmarks; use the analysis path")
    return TrackingResult(
        status=status,
        sequence=sequence,
        captured_at_ns=captured_at_ns,
        camera_request_id=camera_request_id,
        geometry=geometry,
        timing=timing or TrackingTiming(),
        message=message,
        faces_detected=faces_detected,
    )


def is_finite(points: Array) -> bool:
    return bool(np.all(np.isfinite(points)))


def in_frame(points: Array) -> NDArray[np.bool_]:
    """Per-point flag: ``0 <= x <= 1`` and ``0 <= y <= 1``."""

    return (
        (points[:, 0] >= 0.0)
        & (points[:, 0] <= 1.0)
        & (points[:, 1] >= 0.0)
        & (points[:, 1] <= 1.0)
    )


def pixel_distance(a: Array, b: Array, geometry: FrameGeometry) -> float:
    dx = float(a[0] - b[0]) * geometry.width
    dy = float(a[1] - b[1]) * geometry.height
    return math.hypot(dx, dy)
