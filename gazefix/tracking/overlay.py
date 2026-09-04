"""Development overlay: draw a ``TrackingResult`` onto a COPY of a frame.

Never mutates its input. The input frame is the shared, read-only capture
array; the overlay allocates its own BGR canvas, draws with OpenCV and
returns it. With the overlay disabled the processor never calls this module,
so the original array object reaches the preview untouched.

Colours and labels are anatomical: the subject's right eye (image left in
the unmirrored preview) is cyan and labelled ``R``; the left eye is yellow
and labelled ``L``. The head-pose axes are drawn at the nose tip and labelled
"head pose (not gaze)".
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np
from numpy.typing import NDArray

from gazefix.tracking import landmarks as topology
from gazefix.tracking.models import EyeLandmarks, TrackingResult, TrackingStatus


Frame = NDArray[np.uint8]

_MESH = (110, 110, 110)
_RIGHT_EYE = (255, 255, 0)  # cyan in BGR
_LEFT_EYE = (0, 255, 255)  # yellow in BGR
_OVAL = (160, 160, 160)
_TEXT = (240, 240, 240)
_DIM_TEXT = (180, 180, 180)
_WARN = (0, 140, 255)
_ERROR = (0, 0, 220)
_AXIS_X = (0, 0, 255)
_AXIS_Y = (0, 255, 0)
_AXIS_Z = (255, 0, 0)


@dataclass(frozen=True, slots=True)
class OverlayStyle:
    mesh_points: bool = True
    face_oval: bool = True
    pose_axes: bool = True
    text: bool = True
    axis_length_px: int = 60
    description: str = ""


def render_overlay(frame: Frame, result: TrackingResult, style: OverlayStyle | None = None) -> Frame:
    """Return a new frame with the tracking overlay; ``frame`` is left untouched."""

    style = style or OverlayStyle()
    if frame.ndim != 3 or frame.shape[2] != 3:
        return frame
    canvas = np.array(frame, dtype=np.uint8, copy=True, order="C")
    height, width = canvas.shape[:2]
    if result.status.has_landmarks and result.landmarks is not None:
        pixels = result.landmark_pixels()
        if pixels is not None and pixels.shape[0] >= topology.LANDMARK_COUNT_WITHOUT_IRIS:
            dim = result.status is TrackingStatus.LOW_QUALITY
            if style.mesh_points:
                _draw_points(canvas, pixels[: topology.LANDMARK_COUNT_WITHOUT_IRIS], _MESH, 1)
            if style.face_oval:
                _draw_polyline(canvas, pixels[list(topology.FACE_OVAL)], _OVAL, closed=True)
            for eye, colour, label in (
                (result.right_eye, _RIGHT_EYE, "R"),
                (result.left_eye, _LEFT_EYE, "L"),
            ):
                if eye is not None:
                    # Same mapping as the mesh: the result's own geometry.
                    _draw_eye(canvas, eye, colour if not dim else _DIM_TEXT, label,
                              result.geometry.width, result.geometry.height)
            if style.pose_axes and result.pose is not None:
                _draw_pose_axes(canvas, pixels[topology.NOSE_TIP], result, style.axis_length_px)
    if style.text:
        _draw_text_panel(canvas, result, style)
    return canvas


def _draw_points(canvas: Frame, points: np.ndarray, colour: tuple[int, int, int], radius: int) -> None:
    """Draw only points that lie inside the image.

    Landmarks outside the frame are the model's extrapolation, not
    observations; pinning them to the border would show a false contour.
    """

    height, width = canvas.shape[:2]
    for x, y in _clip(points, canvas):
        if 0 <= x < width and 0 <= y < height:
            cv2.circle(canvas, (x, y), radius, colour, -1, lineType=cv2.LINE_AA)


def _clip_segment(
    x0: float, y0: float, x1: float, y1: float, width: int, height: int
) -> tuple[float, float, float, float] | None:
    """Liang-Barsky: the part of the segment inside the image, or ``None``.

    Clamping a vertex to the border would move the line, drawing a contour
    along the image edge that no landmark supports. Clipping keeps the
    segment's true geometry and simply stops it where it leaves the frame;
    a segment entirely outside is dropped.
    """

    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        return None
    dx, dy = x1 - x0, y1 - y0
    x_max, y_max = float(width - 1), float(height - 1)
    enter, leave = 0.0, 1.0
    for delta, distance in (
        (-dx, x0 - 0.0),
        (dx, x_max - x0),
        (-dy, y0 - 0.0),
        (dy, y_max - y0),
    ):
        if delta == 0.0:
            if distance < 0.0:
                return None  # parallel to this edge and wholly outside it
            continue
        crossing = distance / delta
        if delta < 0.0:
            if crossing > leave:
                return None
            enter = max(enter, crossing)
        else:
            if crossing < enter:
                return None
            leave = min(leave, crossing)
    if enter > leave:
        return None
    return (x0 + enter * dx, y0 + enter * dy, x0 + leave * dx, y0 + leave * dy)


def _draw_polyline(canvas: Frame, points: np.ndarray, colour: tuple[int, int, int], closed: bool) -> None:
    """Draw each segment's visible part; off-screen parts are clipped away."""

    height, width = canvas.shape[:2]
    if len(points) < 2:
        return
    segments = list(zip(points, points[1:]))
    if closed:
        segments.append((points[-1], points[0]))
    for start, end in segments:
        visible = _clip_segment(
            float(start[0]), float(start[1]), float(end[0]), float(end[1]), width, height
        )
        if visible is None:
            continue
        cv2.line(
            canvas,
            (int(round(visible[0])), int(round(visible[1]))),
            (int(round(visible[2])), int(round(visible[3]))),
            colour,
            1,
            lineType=cv2.LINE_AA,
        )


def _draw_eye(
    canvas: Frame, eye: EyeLandmarks, colour: tuple[int, int, int], label: str, width: int, height: int
) -> None:
    scale = np.array([width, height], dtype=np.float32)
    contour = eye.contour[:, :2] * scale
    _draw_polyline(canvas, contour, colour, closed=True)
    if eye.iris is not None:
        iris = eye.iris[:, :2] * scale
        centre = iris[0]
        radius = float(np.mean(np.hypot(*(iris[1:] - centre).T)))
        if np.isfinite(radius) and _inside(centre, canvas):
            cx, cy = _clip(centre[None, :], canvas)[0]
            cv2.circle(canvas, (cx, cy), max(1, min(int(round(radius)), max(width, height))), colour, 1, lineType=cv2.LINE_AA)
            cv2.circle(canvas, (cx, cy), 2, colour, -1, lineType=cv2.LINE_AA)
    # The label is anchored to a landmark: drawing it from a clamped position
    # would put it somewhere no landmark is, so an off-screen corner has none.
    corner = contour[topology.CONTOUR_OUTER_CORNER_POSITION]
    if _inside(corner, canvas):
        ox, oy = _clip(corner[None, :], canvas)[0]
        text = f"{label} {eye.openness:.2f}" + ("" if eye.valid else " !")
        cv2.putText(canvas, text, (ox - 8, oy - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv2.LINE_AA)


def _draw_pose_axes(canvas: Frame, origin: np.ndarray, result: TrackingResult, length: int) -> None:
    pose = result.pose
    if pose is None:
        return
    if not _inside(origin, canvas):
        return  # the axes are anchored at the nose tip; off-screen means no anchor
    height, width = canvas.shape[:2]
    ox, oy = _clip(origin[None, :], canvas)[0]
    rotation = pose.rotation
    for column, colour in ((0, _AXIS_X), (1, _AXIS_Y), (2, _AXIS_Z)):
        axis = rotation[:, column]
        # Camera frame y points up; image rows grow downwards.
        visible = _clip_segment(
            float(ox), float(oy), ox + float(axis[0]) * length, oy - float(axis[1]) * length, width, height
        )
        if visible is None:
            continue
        cv2.line(
            canvas,
            (int(round(visible[0])), int(round(visible[1]))),
            (int(round(visible[2])), int(round(visible[3]))),
            colour,
            2,
            lineType=cv2.LINE_AA,
        )
    cv2.putText(
        canvas,
        f"head pose (not gaze) yaw {pose.yaw_deg:+.0f} pitch {pose.pitch_deg:+.0f} roll {pose.roll_deg:+.0f}",
        (ox + 12, oy + 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        _TEXT,
        1,
        cv2.LINE_AA,
    )


def _draw_text_panel(canvas: Frame, result: TrackingResult, style: OverlayStyle) -> None:
    status = result.status
    if status is TrackingStatus.TRACKED:
        colour = _TEXT
    elif status in (TrackingStatus.LOW_QUALITY, TrackingStatus.NO_FACE, TrackingStatus.INITIALIZING, TrackingStatus.TIMEOUT):
        colour = _WARN
    else:
        colour = _ERROR
    lines = [f"tracking: {status.value}" + (f"  faces {result.faces_detected}" if result.faces_detected else "")]
    if result.quality is not None:
        q = result.quality
        lines.append(
            f"quality {q.score:.2f} (in-frame {q.in_frame_fraction:.2f}, face {q.face_height_fraction:.2f} of height)"
            f"  iris {'yes' if result.iris_available else 'no'}"
            f"  stabilized {'yes' if result.stabilized else 'no'}"
        )
    timing = result.timing
    lines.append(
        f"inference {_ms(timing.inference_ms)}  total {_ms(timing.total_ms)}  waited {timing.waited_ms:.1f} ms"
    )
    if result.message:
        lines.append(result.message[:110])
    if style.description:
        lines.append(style.description[:110])
    x, y = 8, 18
    for line in lines:
        (tw, th), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(canvas, (x - 4, y - th - 4), (x + tw + 4, y + 5), (20, 20, 20), -1)
        cv2.putText(canvas, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv2.LINE_AA)
        y += th + 10


def _inside(point: np.ndarray, canvas: Frame) -> bool:
    """Whether a pixel-space point is finite and within the image."""

    height, width = canvas.shape[:2]
    x, y = float(point[0]), float(point[1])
    return math.isfinite(x) and math.isfinite(y) and 0.0 <= x < width and 0.0 <= y < height


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} ms"


def _clip(points: np.ndarray, canvas: Frame) -> list[tuple[int, int]]:
    height, width = canvas.shape[:2]
    finite = np.nan_to_num(np.asarray(points, dtype=np.float64), nan=-1.0, posinf=width, neginf=-1.0)
    xs = np.clip(np.round(finite[:, 0]), -1, width).astype(int)
    ys = np.clip(np.round(finite[:, 1]), -1, height).astype(int)
    return [(int(x), int(y)) for x, y in zip(xs, ys)]
