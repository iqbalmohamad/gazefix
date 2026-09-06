"""QA-M3-003/004/005: behavioral anchors across the real engine seam."""
import cv2
import numpy as np
import pytest

from correction_fakes import correction_scene, render_eyes, render_eye_roi
from gazefix.correction import masks
from gazefix.correction.geometric import GeometricCorrectionEngine as Engine, GeometricCorrectionSettings as Settings
from gazefix.gaze.models import direction_from_angles


def frontal_displacement(tracking, side, yaw, pitch, strength):
    """Independent SA 6.3 reference; no correction geometry/report inputs."""
    assert np.allclose(tracking.pose.rotation, np.eye(3))
    eye = getattr(tracking, side + "_eye")
    corners = eye.contour[[0,8], :2] * (tracking.geometry.width, tracking.geometry.height)
    axis = corners[1] - corners[0]
    half_width = np.linalg.norm(axis) / 2
    ex = axis / (2 * half_width) * (-1 if side == "left" else 1)
    ey = np.array([ex[1], -ex[0]])
    source = tracking.gaze.direction
    ys = np.arctan2(source[0], source[2])
    ps = np.arcsin(source[1])
    yc = ys + strength * (np.deg2rad(yaw) - ys)
    pc = ps + strength * (np.deg2rad(pitch) - ps)
    desired = np.array([np.sin(yc)*np.cos(pc), np.sin(pc), np.cos(yc)*np.cos(pc)])
    delta = desired - source
    return half_width / 1.25 * (delta[0]*ex + delta[1]*ey), half_width


def eye_patch(tracking, side):
    source, opening, center, radius = render_eye_roi(tracking, side)
    eye = getattr(tracking, side + "_eye")
    origin = np.floor((eye.contour[:,:2] * (tracking.geometry.width, tracking.geometry.height)).min(0)-25).astype(int)
    x, y = origin
    roi = (slice(y,y+source.shape[0]), slice(x,x+source.shape[1]))
    mask = np.zeros(source.shape[:2],np.uint8)
    cv2.fillPoly(mask,[np.rint(opening*256).astype(np.int32)],1,shift=8)
    return roi, mask, center, radius


def test_engine_yaw_60_reports_clamped_half_width():
    tr = correction_scene(realistic=True); frame = render_eyes(tr)
    out = Engine().correct(frame,tr,direction_from_angles(60,0),1)
    assert out.result.status.value == "corrected"
    for result in out.result.eyes:
        raw, half_width = frontal_displacement(tr,result.side,60,0,1)
        assert np.linalg.norm(raw) > .5*half_width  # clamp is genuinely exercised
        expected = raw / np.linalg.norm(raw) * (.5*half_width)
        assert result.status.value == "corrected" and result.clamped is True
        assert np.linalg.norm(result.displacement_px) == pytest.approx(.5*half_width,abs=1e-5)
        np.testing.assert_allclose(result.displacement_px,expected,atol=1e-5,rtol=0)


def test_engine_relative_displacement_and_target_semantic_centroid():
    # Already looking image-right and down: correction toward the lens must
    # move the rendered iris image-left and up, regardless of reported d.
    tr = correction_scene(eye_yaw_deg=15,eye_pitch_deg=-10)
    frame = render_eyes(tr)
    out = Engine().correct(frame,tr,direction_from_angles(0,0),.75)
    assert out.result.status.value == "corrected"
    assert tr.gaze.yaw_deg > 0 and tr.gaze.pitch_deg < 0
    semantic_direction = np.array([-tr.gaze.yaw_deg, tr.gaze.pitch_deg])
    for result in out.result.eyes:
        expected, _ = frontal_displacement(tr,result.side,0,0,.75)
        assert result.clamped is False
        np.testing.assert_allclose(result.displacement_px,expected,atol=1e-5,rtol=0)
        roi, mask, _, _ = eye_patch(tr,result.side)
        centers = []
        for image in (frame,out.frame):
            y,x = np.nonzero((image[roi][...,2] < 130) & (mask == 1))
            assert x.size
            centers.append(np.array([x.mean(),y.mean()]))
        observed = centers[1]-centers[0]
        assert np.all(observed < 0) and np.dot(observed,semantic_direction) > 0


def test_engine_a1_opaque_iris_at_partial_lid_alpha(monkeypatch):
    tr = correction_scene(realistic=True); frame = render_eyes(tr)
    out = Engine().correct(frame,tr,direction_from_angles(0,15),1)
    assert out.result.status.value == "corrected"
    witnesses = []
    for side in ("right","left"):
        roi,mask,center,radius = eye_patch(tr,side)
        source = frame[roi]
        d,_ = frontal_displacement(tr,side,0,15,1)
        y,x = np.indices(mask.shape,dtype=np.float32)
        mx,my = (x-d[0]).astype(np.float32),(y-d[1]).astype(np.float32)
        distance = cv2.distanceTransform(mask,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
        alpha = np.clip(distance/1.5,0,1)*mask
        sx,sy = np.floor(mx).astype(int),np.floor(my).astype(int)
        coverage = np.ones(mask.shape,dtype=bool)
        for dx,dy in ((0,0),(1,0),(0,1),(1,1)):
            coverage &= mask[np.clip(sy+dy,0,mask.shape[0]-1),np.clip(sx+dx,0,mask.shape[1]-1)]==1
        disc_opaque = np.hypot(x-center[0]-d[0],y-center[1]-d[1]) <= 1.05*radius-1.5
        band = disc_opaque & coverage & (alpha>.5) & (alpha<1)
        assert band.any(), "Must exercise the A1 opaque-iris/partial-alpha intersection"
        translated = cv2.remap(source,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        assert np.max(np.abs(out.frame[roi].astype(int)-translated.astype(int))[band]) <= 2
        witnesses.append((roi,band,translated))

    def pre_a1(canvas,background,alpha,iris_layer=None,iris_opacity=None):
        a = alpha[...,None]
        warped = background if iris_layer is None else (
            iris_opacity[...,None]*iris_layer+(1-iris_opacity[...,None])*background)
        canvas[:] = np.clip(np.rint(a*warped+(1-a)*canvas),0,255).astype(np.uint8)
    monkeypatch.setattr(masks,"blend_into",pre_a1)
    superseded = Engine().correct(frame,tr,direction_from_angles(0,15),1)
    assert superseded.result.status.value == "corrected"
    for roi,band,translated in witnesses:
        assert np.max(np.abs(superseded.frame[roi].astype(int)-translated.astype(int))[band]) > 2


def test_engine_chamfer3_guard_and_field_output():
    tr = correction_scene(realistic=True); frame = render_eyes(tr)
    union = np.zeros(frame.shape[:2],bool)
    for side in ("right","left"):
        roi,mask,_,_ = eye_patch(tr,side)
        union[roi] |= mask == 1
    frame[...,0] = np.where(union,0,255)  # skin-only tracer
    before = frame.copy()
    out = Engine(Settings(iris_layer=False,distance_transform="chamfer3",field_guard_px=2.5)).correct(
        frame,tr,direction_from_angles(10,10),1)
    assert out.result.status.value == "corrected"
    expected = frame.copy(); precise_control = frame.copy()
    for side in ("right","left"):
        roi,mask,_,_ = eye_patch(tr,side)
        d,half_width = frontal_displacement(tr,side,10,10,1)
        d = d.astype(np.float32)
        y,x = np.indices(mask.shape,dtype=np.float32)
        for destination,method in ((expected,3),(precise_control,cv2.DIST_MASK_PRECISE)):
            distance = cv2.distanceTransform(mask,cv2.DIST_L2,method)
            w = np.clip((distance-2.5)/max(np.linalg.norm(d),.15*half_width),0,1)
            mx,my = (x-d[0]*w).astype(np.float32),(y-d[1]*w).astype(np.float32)
            if method == 3:
                moved = w > 0
                assert moved.any()
                sx,sy = np.floor(mx[moved]).astype(int),np.floor(my[moved]).astype(int)
                for dx,dy in ((0,0),(1,0),(0,1),(1,1)):
                    assert np.all(mask[sy+dy,sx+dx] == 1)
            bg = cv2.remap(frame[roi],mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
            alpha = (np.clip(distance/1.5,0,1)*mask)[...,None]
            destination[roi] = np.rint(alpha*bg+(1-alpha)*destination[roi]).astype(np.uint8)
    assert np.array_equal(out.frame,expected)
    assert not np.array_equal(expected,precise_control), "Must reject ignored chamfer setting"
    assert np.array_equal(out.frame[~union],frame[~union]) and not out.frame[...,0][union].any()
    assert np.array_equal(frame,before) and not np.shares_memory(out.frame,frame)
