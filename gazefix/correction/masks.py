"""ROI-only mask, remap and blend primitives from frozen M3 SA section 8.

Coordinates passed here are ROI-local image pixels (y down). Sampling reads
only the original ROI; blending writes only the caller's exclusive canvas.
"""

from __future__ import annotations

import cv2
import numpy as np


def opening_fields(opening: np.ndarray, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Rasterize the opening and compute precise distance to zero pixels."""
    if opening.shape != (16, 2) or not np.isfinite(opening).all():
        raise ValueError("invalid opening polygon")
    area = abs(float(np.dot(opening[:, 0], np.roll(opening[:, 1], 1))
                     - np.dot(opening[:, 1], np.roll(opening[:, 0], 1)))) / 2
    if area == 0:
        raise ValueError("empty opening polygon")
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, [np.rint(opening * 256).astype(np.int32)], 1, shift=8)
    if not mask.any():
        raise ValueError("empty opening mask")
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    if not np.isfinite(distance).all():
        raise ValueError("non-finite distance field")
    return mask, distance


def blend_alpha(mask: np.ndarray, distance: np.ndarray, edge_px: float = 1.5) -> np.ndarray:
    """Section 8.1: inward-only feather; exactly one beyond edge_px."""
    if not np.isfinite(edge_px) or edge_px <= 0:
        raise ValueError("edge_px must be positive and finite")
    return (np.clip(distance / edge_px, 0, 1) * mask).astype(np.float32)


def warp_maps(distance: np.ndarray, displacement: np.ndarray, half_width_px: float,
              falloff_fraction: float = 0.15, field_guard_px: float = 1.5
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Section 8.2: guarded background sampling, float32 subpixel maps."""
    falloff = max(float(np.linalg.norm(displacement)), falloff_fraction * half_width_px)
    if falloff <= 0:
        raise ValueError("falloff must be positive")
    weight = np.clip((distance - field_guard_px) / falloff, 0, 1)
    y, x = np.indices(distance.shape, dtype=np.float32)
    return ((x - displacement[0] * weight).astype(np.float32),
            (y - displacement[1] * weight).astype(np.float32), weight)


def translated_maps(shape: tuple[int, int], displacement: np.ndarray
                    ) -> tuple[np.ndarray, np.ndarray]:
    y, x = np.indices(shape, dtype=np.float32)
    return (x - displacement[0]).astype(np.float32), (y - displacement[1]).astype(np.float32)


def sample(source: np.ndarray, map_x: np.ndarray, map_y: np.ndarray,
           interpolation: int = cv2.INTER_LINEAR) -> np.ndarray:
    return cv2.remap(source, map_x, map_y, interpolation,
                     borderMode=cv2.BORDER_REPLICATE)


def iris_alpha(mask: np.ndarray, center: np.ndarray, radius: float,
               displacement: np.ndarray, radius_scale: float = 1.05,
               edge_px: float = 1.5) -> np.ndarray:
    """Soft destination disc, occluded at both destination and source."""
    y, x = np.indices(mask.shape, dtype=np.float32)
    destination = center + displacement
    radial_distance = np.hypot(x - destination[0], y - destination[1])
    disc = np.clip((radius_scale * radius - radial_distance) / edge_px, 0, 1)
    mx, my = translated_maps(mask.shape, displacement)
    source_opening = sample(mask.astype(np.float32), mx, my)
    return (disc * mask * source_opening).astype(np.float32)


def blend_into(canvas_roi: np.ndarray, background: np.ndarray, alpha: np.ndarray,
               iris_layer: np.ndarray | None = None,
               iris_opacity: np.ndarray | None = None) -> None:
    """Section 8.4 verbatim: layer composition followed by opening blend.

    Round once, after both blends. The canvas (not the original source) is
    the base so disjoint eyes survive overlapping padded ROIs.
    """
    composed = background.astype(np.float32)
    if iris_layer is not None:
        if iris_opacity is None:
            raise ValueError("iris layer needs opacity")
        opacity = iris_opacity[..., None]
        composed = opacity * iris_layer + (1 - opacity) * composed
    a = alpha[..., None]
    canvas_roi[:] = np.clip(np.rint(a * composed + (1 - a) * canvas_roi), 0, 255).astype(np.uint8)
