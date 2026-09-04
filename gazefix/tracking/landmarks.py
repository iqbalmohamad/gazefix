"""Canonical index sets of the 478-point face-mesh topology.

The indices are those of MediaPipe's face landmark model with the attention
(iris) refinement: 468 mesh points followed by 5 iris points per eye. They are
copied here as plain constants so the contract, overlay and tests never import
MediaPipe; ``tests/test_tracking_landmarks.py`` cross-checks them against the
package's own ``FaceLandmarksConnections`` when MediaPipe is importable.

Left and right are ANATOMICAL, the subject's own left and right. In an
unmirrored camera frame the subject's right eye therefore appears on the
image's left (smaller x). Every eyelid contour below is ordered the same way:
outer (temporal) corner, the lower lid from the outer to the inner corner,
inner (nasal) corner, then the upper lid from the inner corner back to the
outer one, so index positions mean the same thing for both eyes.
"""

from __future__ import annotations


LANDMARK_COUNT_WITH_IRIS = 478
LANDMARK_COUNT_WITHOUT_IRIS = 468
IRIS_POINTS_PER_EYE = 5
EYE_CONTOUR_POINTS = 16

# Subject's RIGHT eye (image left when unmirrored).
RIGHT_EYE_OUTER_CORNER = 33
RIGHT_EYE_INNER_CORNER = 133
RIGHT_EYE_LOWER_LID = (7, 163, 144, 145, 153, 154, 155)  # outer -> inner
RIGHT_EYE_UPPER_LID = (173, 157, 158, 159, 160, 161, 246)  # inner -> outer
RIGHT_EYE_CONTOUR = (
    (RIGHT_EYE_OUTER_CORNER,)
    + RIGHT_EYE_LOWER_LID
    + (RIGHT_EYE_INNER_CORNER,)
    + RIGHT_EYE_UPPER_LID
)
RIGHT_IRIS_CENTER = 468
RIGHT_IRIS_CONTOUR = (469, 470, 471, 472)

# Subject's LEFT eye (image right when unmirrored).
LEFT_EYE_OUTER_CORNER = 263
LEFT_EYE_INNER_CORNER = 362
LEFT_EYE_LOWER_LID = (249, 390, 373, 374, 380, 381, 382)  # outer -> inner
LEFT_EYE_UPPER_LID = (398, 384, 385, 386, 387, 388, 466)  # inner -> outer
LEFT_EYE_CONTOUR = (
    (LEFT_EYE_OUTER_CORNER,)
    + LEFT_EYE_LOWER_LID
    + (LEFT_EYE_INNER_CORNER,)
    + LEFT_EYE_UPPER_LID
)
LEFT_IRIS_CENTER = 473
LEFT_IRIS_CONTOUR = (474, 475, 476, 477)

# Positions inside an eye contour tuple (identical for both eyes).
CONTOUR_OUTER_CORNER_POSITION = 0
CONTOUR_LOWER_LID_POSITIONS = tuple(range(1, 8))
CONTOUR_INNER_CORNER_POSITION = 8
CONTOUR_UPPER_LID_POSITIONS = tuple(range(9, 16))

FACE_OVAL = (
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379,
    378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127,
    162, 21, 54, 103, 67, 109,
)

NOSE_TIP = 1
CHIN = 152
FOREHEAD = 10
RIGHT_FACE_EDGE = 234  # subject's right cheek edge (image left when unmirrored)
LEFT_FACE_EDGE = 454


def iris_indices(side: str) -> tuple[int, ...]:
    """Centre followed by the four contour points of ``side`` ("left"/"right")."""

    if side == "left":
        return (LEFT_IRIS_CENTER,) + LEFT_IRIS_CONTOUR
    if side == "right":
        return (RIGHT_IRIS_CENTER,) + RIGHT_IRIS_CONTOUR
    raise ValueError(f"Unknown eye side: {side!r}")


def eye_contour(side: str) -> tuple[int, ...]:
    if side == "left":
        return LEFT_EYE_CONTOUR
    if side == "right":
        return RIGHT_EYE_CONTOUR
    raise ValueError(f"Unknown eye side: {side!r}")
