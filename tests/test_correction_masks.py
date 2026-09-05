"""Frozen M3 SA section 15.2 mask and layered-compositing requirements."""

import numpy as np
import pytest

from correction_fakes import correction_scene, render_eye_roi
from gazefix.correction import masks
import cv2


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
    assert error.max() <= 2
    # A1 mandates the superseded formula as the non-vacuous control.
    old = np.rint(alpha[..., None] * (opacity[..., None] * iris
                  + (1 - opacity[..., None]) * background)
                  + (1 - alpha[..., None]) * frame).astype(np.uint8)
    assert np.abs(old.astype(np.int16) - iris.astype(np.int16))[band].max() > 2


@pytest.mark.parametrize("realistic", [False, True])
def test_iris_alpha_binary_occlusion_and_range(realistic):
    frame, opening, center, radius = render_eye_roi(correction_scene(realistic=realistic))
    mask, _ = masks.opening_fields(opening, frame.shape[:2])
    opacity = masks.iris_alpha(mask, center, radius, np.array([0., -12.]))
    assert np.isfinite(opacity).all() and opacity.min() == 0 and opacity.max() == 1
    assert np.all(opacity[mask == 0] == 0)


def test_convexity_and_field_equivalence():
    a, i = np.meshgrid(np.linspace(0,1,11,dtype=np.float32), np.linspace(0,1,11,dtype=np.float32))
    weights = np.stack([i, (1-i)*a, (1-i)*(1-a)])
    assert np.all(weights >= 0) and np.allclose(weights.sum(axis=0), 1, atol=1e-6)
    original = np.full((*a.shape,3), 90, np.uint8)
    bg = np.full_like(original, 200); iris = np.full_like(original, 20)
    canvas = original.copy()
    masks.blend_into(canvas, bg, a, iris, i)
    expected = np.rint(i[...,None]*iris+(1-i[...,None])*a[...,None]*bg
                       +(1-i[...,None])*(1-a[...,None])*original).astype(np.uint8)
    assert np.max(np.abs(canvas.astype(int)-expected.astype(int))) <= 1
    assert canvas.min() >= 20 and canvas.max() <= 200
    canvas = original.copy(); masks.blend_into(canvas, bg, a)
    assert np.array_equal(canvas, np.rint(a[...,None]*bg+(1-a[...,None])*original).astype(np.uint8))


def test_source_straddling_is_excluded_with_fractional_negative_control():
    frame, opening, center, radius = render_eye_roi(correction_scene(realistic=True, eye_pitch_deg=15))
    mask, distance = masks.opening_fields(opening, frame.shape[:2])
    # Colour tracer: only lid skin has a blue channel, eye content has zero.
    frame[...,0] = np.where(mask == 0, 255, 0)
    d = np.array([8.25, -.25], np.float32)
    tx, ty = masks.translated_maps(mask.shape, d)
    fractional = masks.sample(mask.astype(np.float32), tx, ty)
    opacity = masks.iris_alpha(mask, center, radius, d)
    y,x = np.indices(mask.shape)
    disc = np.clip((1.05*radius-np.hypot(x-center[0]-d[0],y-center[1]-d[1]))/1.5,0,1)
    straddling = (fractional > 0) & (fractional < 1) & (mask == 1) & (disc > 0)
    assert straddling.any() and np.all(opacity[straddling] == 0)
    bg = masks.sample(frame, *masks.warp_maps(distance,d,45)[:2])
    iris = masks.sample(frame, tx, ty)
    alpha = masks.blend_alpha(mask,distance)
    base = frame.copy(); masks.blend_into(base,bg,alpha)
    canvas = frame.copy(); masks.blend_into(canvas,bg,alpha,iris,opacity)
    assert np.array_equal(canvas[straddling],base[straddling])
    assert np.all(canvas[...,0][mask==1] == 0)
    negative = frame.copy(); masks.blend_into(negative,bg,alpha,iris,disc*mask*fractional)
    assert np.any(negative[...,0][straddling] > 0)


def test_overlapping_roi_eye_order():
    original = np.full((40,80,3), 100, np.uint8)
    # ROI spans overlap by 20 columns, their opening supports are disjoint.
    a = np.zeros((40,50), np.float32); a[10:30,5:25] = .7
    b = np.zeros((40,50), np.float32); b[10:30,25:45] = .6
    patches = [(slice(0,50),a,180), (slice(30,80),b,30)]
    results = []
    for sequence in (patches,patches[::-1]):
        canvas = original.copy()
        for columns,alpha,color in sequence:
            bg = np.full((40,50,3),color,np.uint8)
            masks.blend_into(canvas[:,columns],bg,alpha,255-bg,(alpha>0).astype(np.float32)*.8)
        results.append(canvas)
    assert np.array_equal(*results)
    assert np.any(results[0][:,5:25] != original[:,5:25])
    assert np.any(results[0][:,55:75] != original[:,55:75])


def test_sclera_dilution_control():
    frame, mask, distance, *_ = layers()
    # A weak sclera gradient makes a subpixel background displacement visible.
    y,x = np.indices(mask.shape)
    frame[mask==1] = np.repeat((x*2 % 200)[...,None],3,axis=2)[mask==1]
    d = np.array([8.,0.],np.float32)
    bg = masks.sample(frame,*masks.warp_maps(distance,d,45)[:2])
    a = masks.blend_alpha(mask,distance,1.5); wide = masks.blend_alpha(mask,distance,4)
    _,_,center,radius = render_eye_roi(correction_scene(realistic=True))
    outside_disc = np.hypot(x-center[0]-d[0],y-center[1]) > 1.05*radius
    band = (wide>0) & (wide<1) & outside_disc
    normal = frame.copy(); masks.blend_into(normal,bg,a)
    diluted = frame.copy(); masks.blend_into(diluted,bg,wide)
    delta = np.abs(normal.astype(int)-frame.astype(int)).sum(axis=2)
    delta_wide = np.abs(diluted.astype(int)-frame.astype(int)).sum(axis=2)
    assert np.any((delta_wide < delta) & band)


def test_lid_edge_aliasing_bound(record_property):
    # Isolate the lid edge with a flat iris and high-contrast skin. A pupil
    # or catchlight would make an image-wide max-gradient test measure that
    # unrelated texture edge instead of Q12's iris/lid rasterization step.
    frame, opening, center, radius = render_eye_roi(correction_scene(realistic=True))
    mask, distance = masks.opening_fields(opening,frame.shape[:2])
    y,x = np.indices(mask.shape)
    frame[mask==0] = 255
    frame[(mask==1)&(np.hypot(x-center[0],y-center[1])<=radius)] = (45,65,80)
    d = np.array([0.,-36*np.sin(np.deg2rad(15))],np.float32)
    bg = masks.sample(frame,*masks.warp_maps(distance,d,45)[:2])
    iris = masks.sample(frame,*masks.translated_maps(mask.shape,d))
    opacity = masks.iris_alpha(mask,center,radius,d)
    canvas = frame.copy()
    masks.blend_into(canvas,bg,masks.blend_alpha(mask,distance),iris,opacity)
    differences = np.zeros(mask.shape, dtype=int)
    for axis in (0,1):
        jump = np.abs(np.diff(canvas.astype(int),axis=axis)).max(axis=2)
        if axis == 0:
            differences[:-1] = np.maximum(differences[:-1],jump)
            differences[1:] = np.maximum(differences[1:],jump)
        else:
            differences[:,:-1] = np.maximum(differences[:,:-1],jump)
            differences[:,1:] = np.maximum(differences[:,1:],jump)
    # Explicit 4-neighbour boundary ring, not an image-wide beauty score.
    ring = (mask==1) & ((np.roll(mask,1,0)==0)|(np.roll(mask,-1,0)==0)|
                        (np.roll(mask,1,1)==0)|(np.roll(mask,-1,1)==0))
    maximum = int(differences[mask==1].max())
    record_property("q12_max_channel_jump", maximum)
    assert maximum > 0 and np.any((opacity >= 1-1e-6)&ring)
    assert not np.any((differences == maximum) & (mask==1) & ~ring)
    assert np.array_equal(canvas[mask==0],frame[mask==0])


def test_chamfer_guard_sampling_bound():
    frame, mask, _, *_ = layers()
    distance = cv2.distanceTransform(mask,cv2.DIST_L2,3)
    mx,my,weight = masks.warp_maps(distance,np.array([4.2,-9.3]),45,field_guard_px=2.5)
    moved = weight>0
    assert moved.any()
    assert np.all(masks.source_coverage(mask,mx,my)[moved] == 1)
