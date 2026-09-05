"""Frozen M3 SA section 15.2 mask and layered-compositing requirements."""

import numpy as np
import pytest

from correction_fakes import correction_scene, render_eye_roi
from gazefix.correction import masks


def layers():
    result = correction_scene(realistic=True)
    frame, opening, center, radius = render_eye_roi(result)
    # Frontal source gaze zero -> target pitch +15 degrees at strength 1:
    # frozen SA 6.3, half-width 45 px, k=1.25, image y down.
    d = np.array([0, -45 / 1.25 * np.sin(np.deg2rad(15))], np.float32)
    mask, distance = masks.opening_fields(opening, frame.shape[:2])
    mx, my, weight = masks.warp_maps(distance, d, 45)
    background = masks.sample(frame, mx, my)
    tx, ty = masks.translated_maps(mask.shape, d)
    iris = masks.sample(frame, tx, ty)
    opacity = masks.iris_alpha(mask, center, radius, d)
    return frame, mask, distance, mx, my, weight, background, iris, opacity


def test_alpha_and_bilinear_sampling_bound():
    frame, mask, distance, mx, my, weight, background, iris, opacity = layers()
    alpha = masks.blend_alpha(mask, distance)
    assert np.isfinite(alpha).all() and alpha.min() == 0 and alpha.max() == 1
    assert np.all(alpha[mask == 0] == 0)
    assert np.all(alpha[distance >= 1.5] == 1)
    moved = weight > 0
    assert moved.any()
    x, y = np.floor(mx[moved]).astype(int), np.floor(my[moved]).astype(int)
    for dx, dy in ((0, 0), (0, 1), (1, 0), (1, 1)):
        assert np.all(mask[y + dy, x + dx] == 1)
    before = frame.copy()
    canvas = frame.copy()
    masks.blend_into(canvas, background, alpha, iris, opacity)
    assert np.array_equal(canvas[mask == 0], frame[mask == 0])
    assert np.array_equal(frame, before)


def test_zero_area_rejected():
    with pytest.raises(ValueError, match="empty opening"):
        masks.opening_fields(np.zeros((16, 2)), (50, 100))


@pytest.mark.parametrize("edge_px", [1.5, 4.0])
def test_no_ghosting_near_lid(edge_px):
    frame, mask, distance, _, _, _, background, iris, opacity = layers()
    alpha = masks.blend_alpha(mask, distance, edge_px)
    band = (opacity == 1) & (alpha > 0.5) & (alpha < 1)
    assert band.any(), "Must exercise opaque iris in the partial-alpha lid band"
    canvas = frame.copy()
    masks.blend_into(canvas, background, alpha, iris, opacity)
    error = np.abs(canvas.astype(np.int16) - iris.astype(np.int16))[band]
    if edge_px == 4:
        assert error.max() > 2, "SA wide-feather negative control must ghost"
    else:
        assert error.max() <= 2, (
            f"SA 15.2 requires translated iris without original mixing: "
            f"{int(band.sum())} pixels exercised; max channel error {int(error.max())}/255"
        )
