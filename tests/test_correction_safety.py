"""Remaining M3 gate, geometry, ownership and sampling matrix cases."""
from dataclasses import replace
import cv2
import numpy as np
import pytest

from correction_fakes import correction_scene, render_eyes
from gazefix.correction import masks, geometry
from gazefix.correction.geometric import GeometricCorrectionEngine as Engine, GeometricCorrectionSettings as Settings
from gazefix.gaze.models import direction_from_angles


def moved_eye(eye, delta):
    contour=eye.contour.copy();iris=eye.iris.copy()
    contour[:,:2]+=delta;iris[:,:2]+=delta
    return replace(eye,contour=contour,iris=iris)


@pytest.mark.parametrize("case,reason",[("overlap","eyes overlap"),("border","eye at image border"),
                                      ("small","eye too small"),("radius","iris implausible")])
def test_geometry_skip_reasons(case,reason):
    tr=correction_scene();eye=tr.right_eye
    if case=="overlap":
        tr=replace(tr,left_eye=moved_eye(tr.left_eye,eye.iris[0,:2]-tr.left_eye.iris[0,:2]))
    elif case=="border":
        tr=replace(tr,right_eye=moved_eye(eye,np.array([.036-eye.iris[0,0],0])))
    elif case=="small":
        tr=correction_scene(pixels_per_mm=.5)
        tr=replace(tr,gaze=correction_scene().gaze,right_eye=replace(tr.right_eye,valid=True),left_eye=replace(tr.left_eye,valid=True))
    else:
        iris=eye.iris.copy();iris[1:]=iris[0]+3*(iris[1:]-iris[0])
        tr=replace(tr,right_eye=replace(eye,iris=iris))
    frame=np.full((720,1280,3),100,np.uint8)
    out=Engine().correct(frame,tr,direction_from_angles(10,0),1)
    assert out.frame is frame and out.result.status.value=="skipped"
    assert out.result.eyes[0].reason==reason


def test_overlapping_padded_rois_preserve_both_eyes_and_outside():
    tr=correction_scene();eye=tr.left_eye
    # Opening widths 90, centre separation 110: supports disjoint, ROIs overlap.
    tr=replace(tr,left_eye=moved_eye(eye,np.array([(110-186)/1280,0])))
    frame=np.full((720,1280,3),180,np.uint8)
    union=np.zeros(frame.shape[:2],np.uint8)
    for side in ("right","left"):
        g=geometry.derive_eye(getattr(tr,side+"_eye"),tr.geometry)
        cv2.fillPoly(union,[np.rint(g.opening*256).astype(np.int32)],1,shift=8)
        cv2.circle(frame,tuple(np.rint(g.iris_center).astype(int)),round(g.iris_radius),(20,20,20),-1)
    out=Engine(Settings(debug=True)).correct(frame,tr,direction_from_angles(10,0),1)
    assert out.result.status.value=="corrected"
    rois=dict(out.result.debug.rois)
    assert max(rois['right'][0],rois['left'][0]) < min(rois['right'][2],rois['left'][2])
    assert np.array_equal(out.frame[union==0],frame[union==0])
    for side in ("right","left"):
        g=geometry.derive_eye(getattr(tr,side+"_eye"),tr.geometry)
        x,y=np.rint(g.iris_center).astype(int)
        assert np.any(out.frame[y-10:y+10,x-20:x+20] != frame[y-10:y+10,x-20:x+20])


def test_readonly_strided_input_and_no_pose():
    tr=correction_scene()
    tr=replace(tr,pose=None,gaze=replace(tr.gaze,confidence=replace(tr.gaze.confidence,head_pose_applied=False)))
    backing=np.repeat(render_eyes(tr),2,axis=1);frame=backing[:,::2]
    frame.setflags(write=False);before=backing.copy()
    out=Engine().correct(frame,tr,direction_from_angles(10,0),1)
    assert out.result.status.value=="corrected"
    assert out.frame.flags.c_contiguous and out.frame.flags.writeable
    assert not np.shares_memory(out.frame,backing) and np.array_equal(backing,before)


def test_roll_invariant_aperture_and_upward_clamp():
    for roll in (0,30,-30):
        tr=correction_scene(head_roll_deg=roll,left_eye_openness=.05)
        g=geometry.derive_eye(tr.left_eye,tr.geometry)
        assert g.aperture<.18
        out=Engine().correct(render_eyes(tr),tr,direction_from_angles(10,0),1)
        assert out.result.status.value=="corrected" and out.result.eyes[1].reason=="eye closed"
    tr=correction_scene(realistic=True);f=render_eyes(tr)
    assert Engine().correct(f,tr,direction_from_angles(60,0),1).result.status.value=="corrected"
    assert "iris would leave the eye" in Engine().correct(f,tr,direction_from_angles(0,60),1).result.message


@pytest.mark.parametrize("empty",[False,True])
def test_nonfinite_or_empty_mask_falls_back(monkeypatch,empty):
    def invalid(opening,shape):
        return np.zeros(shape,np.uint8) if empty else np.ones(shape,np.uint8),np.full(shape,np.nan,np.float32)
    monkeypatch.setattr(masks,"opening_fields",invalid)
    tr=correction_scene();frame=render_eyes(tr)
    out=Engine().correct(frame,tr,direction_from_angles(10,0),1)
    assert out.frame is frame and out.result.status.value=="failed"
    assert out.result.message.startswith("mask generation failed:")


@pytest.mark.parametrize("layered",[False,True])
@pytest.mark.parametrize("interpolation",["linear","cubic"])
def test_interpolation_keeps_lid_skin_out(layered,interpolation):
    tr=correction_scene(realistic=True);frame=render_eyes(tr)
    union=np.zeros(frame.shape[:2],np.uint8)
    for side in ("right","left"):
        g=geometry.derive_eye(getattr(tr,side+"_eye"),tr.geometry)
        cv2.fillPoly(union,[np.rint(g.opening*256).astype(np.int32)],1,shift=8)
    # Blue tracer appears exclusively in skin, irrespective of sclera texture.
    frame[...,0]=np.where(union,0,255)
    out=Engine(Settings(iris_layer=layered,interpolation=interpolation)).correct(frame,tr,direction_from_angles(10,10),1)
    assert out.result.status.value=="corrected"
    assert not out.frame[...,0][union==1].any()
    assert np.array_equal(out.frame[union==0],frame[union==0])
