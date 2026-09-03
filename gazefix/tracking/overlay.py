"""Development-only rendering of application-owned tracking metadata."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from gazefix.tracking.models import NormalizedLandmark, TrackingResult


Frame = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class DebugOverlayStyle:
    face_color: tuple[int, int, int] = (100, 180, 100)
    eye_color: tuple[int, int, int] = (0, 255, 255)
    iris_color: tuple[int, int, int] = (255, 0, 255)
    text_color: tuple[int, int, int] = (255, 255, 255)
    face_radius: int = 1
    feature_thickness: int = 1


class DebugOverlayRenderer:
    """Render a detached BGR debug frame; never mutate the source image."""

    def __init__(self, style: DebugOverlayStyle | None = None) -> None:
        self._style = style or DebugOverlayStyle()

    def render(self, frame: Frame, result: TrackingResult) -> Frame:
        if (
            not isinstance(frame, np.ndarray)
            or frame.dtype != np.uint8
            or frame.ndim != 3
            or frame.shape[2] != 3
            or frame.shape[0] <= 0
            or frame.shape[1] <= 0
        ):
            raise ValueError("Overlay input must be a non-empty BGR uint8 frame")

        output = frame.copy()
        height, width = output.shape[:2]
        if result.frame_width is not None and (
            result.frame_width != width or result.frame_height != height
        ):
            raise ValueError("Tracking result dimensions do not match overlay frame")
        face = result.primary_face
        if face is not None:
            for landmark in face.landmarks:
                cv2.circle(
                    output,
                    landmark.to_pixel(width, height),
                    self._style.face_radius,
                    self._style.face_color,
                    -1,
                    lineType=cv2.LINE_AA,
                )
            self._draw_loop(output, face.left_eye_landmarks, self._style.eye_color)
            self._draw_loop(output, face.right_eye_landmarks, self._style.eye_color)
            self._draw_iris(output, face.left_iris_landmarks)
            self._draw_iris(output, face.right_iris_landmarks)

        confidence = result.reliability.confidence
        confidence_text = "n/a" if confidence is None else f"{confidence:.2f}"
        label = f"tracking: {result.state.value} confidence: {confidence_text}"
        cv2.putText(
            output,
            label,
            (8, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            self._style.text_color,
            1,
            lineType=cv2.LINE_AA,
        )
        return output

    def _draw_loop(
        self,
        output: Frame,
        landmarks: tuple[NormalizedLandmark, ...],
        color: tuple[int, int, int],
    ) -> None:
        if len(landmarks) < 2:
            return
        height, width = output.shape[:2]
        points = np.asarray(
            [point.to_pixel(width, height) for point in landmarks], dtype=np.int32
        ).reshape((-1, 1, 2))
        cv2.polylines(
            output,
            [points],
            isClosed=True,
            color=color,
            thickness=self._style.feature_thickness,
            lineType=cv2.LINE_AA,
        )

    def _draw_iris(
        self, output: Frame, landmarks: tuple[NormalizedLandmark, ...]
    ) -> None:
        if not landmarks:
            return
        height, width = output.shape[:2]
        center, contour = landmarks[0], landmarks[1:]
        cv2.circle(
            output,
            center.to_pixel(width, height),
            2,
            self._style.iris_color,
            -1,
            lineType=cv2.LINE_AA,
        )
        self._draw_loop(output, contour, self._style.iris_color)
