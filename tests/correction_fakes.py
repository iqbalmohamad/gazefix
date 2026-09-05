"""Deterministic synthetic eye pixels, using the frozen M2 scene geometry."""

from dataclasses import replace

import cv2
import numpy as np

from gaze_fakes import gaze_scene
from gazefix.gaze.estimator import GazeSettings, GeometricGazeEstimator
from gazefix.tracking.models import readonly


def correction_scene(*, realistic: bool = False, **scene_kwargs):
    scene_kwargs.setdefault("eye_openness", 0.25 if realistic else 0.30)
    result = gaze_scene(**scene_kwargs).result()
    if realistic:
        eyes = {}
        for side in ("right", "left"):
            eye = getattr(result, side + "_eye")
            iris = eye.iris.copy()
            iris[1:] = iris[0] + (iris[1:] - iris[0]) * (0.39 / 0.24)
            eyes[side + "_eye"] = replace(eye, iris=readonly(iris))
        result = replace(result, **eyes)
    estimator = GeometricGazeEstimator(GazeSettings(smoothing=0))
    return replace(result, gaze=estimator.estimate(result))


def render_eye_roi(result, side="right"):
    """Local padded eye patch; lid skin occludes the source iris disc."""
    eye = getattr(result, side + "_eye")
    scale = np.array([result.geometry.width, result.geometry.height])
    opening = eye.contour[:, :2] * scale
    origin = np.floor(opening.min(axis=0) - 25)
    extent = np.ceil(opening.max(axis=0) + 25) - origin
    opening = opening - origin
    center = eye.iris[0, :2] * scale - origin
    radius = float(np.linalg.norm((eye.iris[1:, :2] - eye.iris[0, :2]) * scale, axis=1).mean())
    shape = (int(extent[1]), int(extent[0]))
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.rint(opening * 256).astype(np.int32)], 1, shift=8)
    frame = np.full((*shape, 3), (110, 155, 195), np.uint8)
    frame[mask != 0] = (225, 230, 235)
    y, x = np.indices(shape)
    radial = np.hypot(x - center[0], y - center[1])
    frame[(radial <= radius) & (mask != 0)] = (45, 65, 80)
    frame[(radial <= radius * 0.35) & (mask != 0)] = (10, 10, 10)
    highlight = (x - center[0] + radius * 0.25) ** 2 + (y - center[1] + radius * 0.25) ** 2 < 1.5 ** 2
    frame[highlight & (mask != 0)] = (245, 245, 245)
    return frame, opening, center, radius


def render_eyes(result):
    frame = np.full((result.geometry.height, result.geometry.width, 3), (110, 155, 195), np.uint8)
    for side in ("right", "left"):
        patch, _, _, _ = render_eye_roi(result, side)
        eye = getattr(result, side + "_eye")
        opening = eye.contour[:, :2] * (result.geometry.width, result.geometry.height)
        x, y = np.floor(opening.min(axis=0) - 25).astype(int)
        frame[y:y+patch.shape[0], x:x+patch.shape[1]] = patch
    return frame


def visible_centroid_ideal(result, d, side="right", supersample=24):
    """Independent area centroid of a translated disc clipped by the lids.

    Integrate pixel subcells against the analytic polygon and circle, without
    correction geometry, masks, raster rendering, or engine code.
    """
    eye = getattr(result, side + "_eye")
    scale = np.array([result.geometry.width, result.geometry.height])
    polygon = eye.contour[:, :2] * scale
    center = eye.iris[0, :2] * scale + np.asarray(d)
    radius = np.linalg.norm((eye.iris[1:, :2] - eye.iris[0, :2]) * scale, axis=1).mean()
    lo = np.maximum(polygon.min(axis=0), center - radius)
    hi = np.minimum(polygon.max(axis=0), center + radius)
    xx = np.arange(np.floor(lo[0]), np.ceil(hi[0]), 1 / supersample) + .5 / supersample
    yy = np.arange(np.floor(lo[1]), np.ceil(hi[1]), 1 / supersample) + .5 / supersample
    x, y = np.meshgrid(xx, yy)
    inside = np.zeros(x.shape, dtype=bool)
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        if b[1] != a[1]:
            inside ^= ((a[1] > y) != (b[1] > y)) & (x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])
    inside &= (x - center[0]) ** 2 + (y - center[1]) ** 2 <= radius ** 2
    if not inside.any():
        raise ValueError("empty visible ideal")
    return np.array([x[inside].mean(), y[inside].mean()])
