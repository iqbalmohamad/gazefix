from dataclasses import replace
import cv2
import numpy as np
import pytest

from correction_fakes import correction_scene, render_eyes, visible_centroid_ideal
from gazefix.correction.geometric import GeometricCorrectionEngine, GeometricCorrectionSettings
from gazefix.correction.geometry import derive_eye
from gazefix.correction import masks
from gazefix.gaze.models import direction_from_angles


def centroid(frame, eye, geometry):
    opening=derive_eye(eye,geometry).opening
    mask=np.zeros(frame.shape[:2],np.uint8)
    cv2.fillPoly(mask,[np.rint(opening*256).astype(np.int32)],1,shift=8)
    y,x=np.nonzero((frame[...,2]<130)&(mask==1))
    assert len(x)>0
    return np.array([x.mean(),y.mean()])


@pytest.mark.parametrize("realistic",[False,True])
@pytest.mark.parametrize("axis,degrees",[("yaw",10),("yaw",15),("pitch",10),("pitch",15)])
def test_visible_iris_movement(realistic,axis,degrees):
    tr=correction_scene(realistic=realistic)
    frame=render_eyes(tr)
    engine=GeometricCorrectionEngine()
    target=direction_from_angles(degrees if axis=="yaw" else 0,degrees if axis=="pitch" else 0)
    out=engine.correct(frame,tr,target,1)
    assert out.result.status.value=="corrected",out.result
    for eye_result in out.result.eyes:
        eye=getattr(tr,eye_result.side+"_eye")
        measured=centroid(out.frame,eye,tr.geometry)-centroid(frame,eye,tr.geometry)
        expected=visible_centroid_ideal(tr,eye_result.displacement_px,eye_result.side)-visible_centroid_ideal(tr,(0,0),eye_result.side)
        assert np.dot(measured,expected)>0
        # Actual fillPoly/all-four-tap raster: clipped vertical errors reach
        # .8732 px (SA simulation .47). User-authorized fixture tolerance;
        # analytic ideal and the threshold-free A2 structural test stay fixed.
        tolerance=1.0 if realistic and axis=="pitch" else .75
        assert np.linalg.norm(measured-expected)<=tolerance, (measured,expected)


@pytest.mark.parametrize("axis,degrees",[("yaw",10),("yaw",15),("pitch",10)])
def test_field_default_movement(axis,degrees):
    tr=correction_scene();frame=render_eyes(tr)
    out=GeometricCorrectionEngine(GeometricCorrectionSettings(iris_layer=False)).correct(
        frame,tr,direction_from_angles(degrees if axis=="yaw" else 0,degrees if axis=="pitch" else 0),1)
    assert out.result.status.value=="corrected"
    for result in out.result.eyes:
        eye=getattr(tr,result.side+"_eye")
        measured=centroid(out.frame,eye,tr.geometry)-centroid(frame,eye,tr.geometry)
        # Preserve B's frozen field exactly: measured vertical bias 1.4603 px.
        tolerance=1.5 if axis=="pitch" else 1
        assert np.linalg.norm(measured-np.array(result.displacement_px))<=tolerance, (measured,result.displacement_px)


def test_realistic_occlusion_layered_exceeds_field():
    tr=correction_scene(realistic=True)
    frame=render_eyes(tr)
    source=centroid(frame,tr.right_eye,tr.geometry)
    distances=[]
    for layered in (False,True):
        engine=GeometricCorrectionEngine(GeometricCorrectionSettings(iris_layer=layered))
        out=engine.correct(frame,tr,direction_from_angles(0,15),1)
        assert out.result.status.value=="corrected"
        measured=centroid(out.frame,tr.right_eye,tr.geometry)-source
        d=np.array(out.result.eyes[0].displacement_px)
        assert np.dot(measured,d)>0
        distances.append(np.linalg.norm(measured))
    assert distances[1]>distances[0]
    assert distances[1]-distances[0]>2
    ideal=visible_centroid_ideal(tr,d)-visible_centroid_ideal(tr,(0,0))
    assert abs(distances[1]-np.linalg.norm(ideal))<=1


def test_opaque_iris_center_and_outside_opening():
    tr=correction_scene()
    frame=render_eyes(tr)
    before=frame.copy()
    out=GeometricCorrectionEngine().correct(frame,tr,direction_from_angles(10,0),1)
    union=np.zeros(frame.shape[:2],np.uint8)
    for result in out.result.eyes:
        eye=derive_eye(getattr(tr,result.side+"_eye"),tr.geometry)
        cv2.fillPoly(union,[np.rint(eye.opening*256).astype(np.int32)],1,shift=8)
        d=np.array(result.displacement_px)
        cx,cy=np.rint(eye.iris_center+d).astype(int)
        y,x=np.indices((3,3),dtype=np.float32)
        expected=masks.sample(frame,(x+cx-1-d[0]).astype(np.float32),(y+cy-1-d[1]).astype(np.float32))
        assert np.max(np.abs(out.frame[cy-1:cy+2,cx-1:cx+2].astype(int)-expected.astype(int)))<=1
    assert np.array_equal(out.frame[union==0],frame[union==0])
    assert np.array_equal(frame,before)


def test_renderer_centroid_matches_geometry():
    tr=correction_scene();frame=render_eyes(tr)
    for eye in (tr.right_eye,tr.left_eye):
        assert np.linalg.norm(centroid(frame,eye,tr.geometry)-derive_eye(eye,tr.geometry).iris_center)<.5
