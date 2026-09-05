"""A2 structural regressions and independent negative controls."""
import cv2
import numpy as np
import pytest

from correction_fakes import correction_scene, render_eye_roi, render_eyes, visible_centroid_ideal
from test_correction_warp import centroid
from gazefix.correction import masks, geometry
from gazefix.correction.geometric import GeometricCorrectionEngine as Engine, GeometricCorrectionSettings as Settings
from gazefix.gaze.models import direction_from_angles

SCLERA = np.array([225, 230, 235])


@pytest.mark.parametrize("yaw", [0, 10, -10])
def test_plate_tones_extent_and_fallbacks(yaw):
    frame, opening, center, radius = render_eye_roi(correction_scene(realistic=True, eye_yaw_deg=yaw))
    before = frame.copy()
    mask, distance = masks.opening_fields(opening, frame.shape[:2])
    y, x = np.indices(mask.shape)
    hole = (np.hypot(x-center[0], y-center[1]) <= radius+1) & (mask == 1)
    available = (mask == 1) & ~hole
    plate = masks.sclera_plate(frame, mask, center, radius)
    assert hole.any() and available.any()
    assert np.all(plate[hole] == SCLERA)  # includes pupil and catchlight
    assert np.array_equal(plate[~hole], frame[~hole])
    assert np.array_equal(frame, before) and not np.shares_memory(plate, frame)
    assert np.array_equal(plate, masks.sclera_plate(frame, mask, center, radius))
    one_sided = empty_row = False
    for row in np.flatnonzero(hole.any(axis=1)):
        hx, sx = np.flatnonzero(hole[row]), np.flatnonzero(available[row])
        if not sx.size:
            empty_row = True
            assert np.all(plate[row, hx] == np.median(frame[available], axis=0))
        elif sx.max() < hx.min() or sx.min() > hx.max():
            one_sided = True
            assert np.all(plate[row, hx] == frame[row, sx[0]])
    if yaw:
        assert one_sided and empty_row, "Exercise both fallbacks on deviated anatomy"
    mx, my, w = masks.warp_maps(distance, np.array([6.2,-3.1]), 45)
    assert (w > 0).any() and np.all(masks.source_coverage(mask,mx,my)[w>0] == 1)


def test_scanline_interpolation_uses_nearest_sclera():
    source=np.zeros((9,17,3),np.uint8)
    source[:,:]=np.arange(17)[None,:,None]*10
    mask=np.zeros((9,17),np.uint8);mask[1:8,1:16]=1
    y,x=np.indices(mask.shape);hole=(np.hypot(x-8,y-4)<=4)&(mask==1)
    source[hole]=255
    plate=masks.sclera_plate(source,mask,np.array([8,4]),3)
    assert np.array_equal(plate[hole], np.repeat((x*10)[...,None],3,axis=2)[hole])


def test_empty_scanline_uses_median_of_available_interior_only():
    source,opening,center,radius=render_eye_roi(correction_scene(realistic=True,eye_yaw_deg=10))
    mask,_=masks.opening_fields(opening,source.shape[:2])
    y,x=np.indices(mask.shape);hole=(np.hypot(x-center[0],y-center[1])<=radius+1)&(mask==1)
    available=(mask==1)&~hole
    source[available]=np.repeat((x%100)[...,None],3,axis=2)[available]
    empty=np.flatnonzero(hole.any(1)&~available.any(1))
    assert empty.size
    plate=masks.sclera_plate(source,mask,center,radius)
    for row in empty:
        assert np.all(plate[row,hole[row]]==np.rint(np.median(source[available],axis=0)))


@pytest.mark.parametrize("axis,degrees", [("yaw",10),("yaw",15),("pitch",10),("pitch",15)])
def test_exactly_one_iris_and_raw_background_negative_control(monkeypatch, axis, degrees):
    tr=correction_scene(realistic=True); frame=render_eyes(tr)
    target=direction_from_angles(degrees if axis=="yaw" else 0, degrees if axis=="pitch" else 0)
    out=Engine().correct(frame,tr,target,1)
    assert out.result.status.value=="corrected"
    monkeypatch.setattr(masks,"sclera_plate",lambda source,*a:source)
    old=Engine().correct(frame,tr,target,1)
    assert old.result.status.value=="corrected"
    for result in out.result.eyes:
        g=geometry.derive_eye(getattr(tr,result.side+"_eye"),tr.geometry)
        mask,distance=masks.opening_fields(g.opening,frame.shape[:2])
        alpha=masks.blend_alpha(mask,distance)
        y,x=np.indices(mask.shape);center=g.iris_center+result.displacement_px
        outside=(np.hypot(x-center[0],y-center[1]) > g.iris_radius+1) & (mask==1)
        assert outside.any()
        # The only admissible non-sclera contribution is the original's
        # (1-alpha) lid ramp, plus half a uint8 rounding unit per channel.
        bound=(1-alpha[...,None])*np.abs(frame.astype(float)-SCLERA)+.501
        delta=np.abs(out.frame.astype(float)-SCLERA)
        assert np.all(delta[outside] <= bound[outside])
        assert np.any(np.abs(old.frame.astype(float)-SCLERA)[outside] > bound[outside])
        ramp=outside & (alpha>0) & (alpha<1) & np.any(frame != SCLERA,axis=2)
        assert ramp.any(), "Bound must include real source iris remnants"
        assert np.max(1-alpha[ramp])<=1/3+1e-6
        measured=centroid(old.frame,getattr(tr,result.side+"_eye"),tr.geometry)-centroid(frame,getattr(tr,result.side+"_eye"),tr.geometry)
        ideal=visible_centroid_ideal(tr,result.displacement_px,result.side)-visible_centroid_ideal(tr,(0,0),result.side)
        assert np.linalg.norm(measured-ideal) > 1.0  # rejects old C on every row


def test_b_never_builds_plate_and_matches_inline_formula(monkeypatch):
    def forbidden(*a):
        pytest.fail("variant B invoked plate")
    monkeypatch.setattr(masks,"sclera_plate",forbidden)
    tr=correction_scene(realistic=True);frame=render_eyes(tr)
    out=Engine(Settings(iris_layer=False)).correct(frame,tr,direction_from_angles(0,15),1)
    assert out.result.status.value=="corrected"
    expected=frame.copy()
    for result in out.result.eyes:
        g=geometry.derive_eye(getattr(tr,result.side+"_eye"),tr.geometry)
        d=np.asarray(result.displacement_px,np.float32)
        x0,y0,x1,y1=geometry.roi_for(g,d,.25,1.5)
        source=frame[y0:y1,x0:x1]
        mask,distance=masks.opening_fields(g.opening-(x0,y0),source.shape[:2])
        mx,my,_=masks.warp_maps(distance,d,g.half_width_px)
        bg=cv2.remap(source,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        a=np.clip(distance/1.5,0,1)[...,None]*mask[...,None]
        expected[y0:y1,x0:x1]=np.rint(a*bg+(1-a)*expected[y0:y1,x0:x1]).astype(np.uint8)
    assert np.array_equal(out.frame,expected)


def test_no_sclera_raises_and_engine_falls_back_atomically(monkeypatch):
    source=np.full((9,9,3),80,np.uint8);mask=np.ones((9,9),np.uint8)
    with pytest.raises(ValueError,match="no sclera to sample"):
        masks.sclera_plate(source,mask,np.array([4,4]),10)
    build=masks.sclera_plate
    calls=0
    def second_eye_without_sclera(source,mask,center,radius):
        nonlocal calls
        calls+=1
        return build(source,mask,center,1e4 if calls==2 else radius)
    monkeypatch.setattr(masks,"sclera_plate",second_eye_without_sclera)
    tr=correction_scene(realistic=True);frame=render_eyes(tr);before=frame.copy()
    out=Engine().correct(frame,tr,direction_from_angles(0,15),1)
    assert calls==2 and out.frame is frame and np.array_equal(frame,before)
    assert out.result.status.value=="failed"
    assert out.result.message=="mask generation failed: no sclera to sample"
    assert len(out.result.eyes)==2 and all(e.displacement_px==(0.,0.) for e in out.result.eyes)


def test_ideal_is_independent_converged_and_clipped():
    tr=correction_scene(realistic=True)
    source=visible_centroid_ideal(tr,(0,0))
    eye=tr.right_eye;center=eye.iris[0,:2]*(tr.geometry.width,tr.geometry.height)
    assert np.linalg.norm(source-center)<.01
    moved=visible_centroid_ideal(tr,(0,-9.3))
    assert 0 < source[1]-moved[1] < 9.3
    assert np.linalg.norm(moved-visible_centroid_ideal(tr,(0,-9.3),supersample=48))<.01
