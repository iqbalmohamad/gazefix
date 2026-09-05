"""Opt-in real tracker -> analysis -> gaze -> correction, on licensed fixture."""
from dataclasses import replace
import os
from pathlib import Path

import numpy as np
import pytest

from gazefix.config import AppSettings, default_model_directory
from gazefix.correction.harness import image_canvas, analyse_frame
from gazefix.correction.geometric import GeometricCorrectionEngine
from gazefix.gaze.estimator import GeometricGazeEstimator, GazeSettings
from gazefix.gaze.models import direction_from_angles
from gazefix.tracking.stabilizer import LandmarkStabilizer

pytestmark=pytest.mark.real_model


def test_real_model_correction(record_property):
    if os.environ.get("GAZEFIX_REAL_MODEL_TESTS")!="1": pytest.skip("real-model tests are opt-in")
    import cv2
    from gazefix.tracking.mediapipe_tracker import create_mediapipe_tracker
    app=replace(AppSettings(),model_directory=Path(os.environ.get("GAZEFIX_MODEL_DIR") or default_model_directory()))
    tracker=create_mediapipe_tracker(app)
    try:
        still=cv2.imread(str(Path(__file__).parent/"assets"/"astronaut_face.png"))
        frame=image_canvas(still,1280,720)
        tr=analyse_frame(tracker,GeometricGazeEstimator(GazeSettings(smoothing=0)),LandmarkStabilizer(0),frame,1,1,app)
        out=GeometricCorrectionEngine().correct(frame,tr,direction_from_angles(10,0),.75)
        assert out.result.status.value=="corrected",out.result
        assert all(e.status.value=="corrected" for e in out.result.eyes)
        # Dark iris pixel centroid, restricted to the opening to exclude lashes.
        for e in out.result.eyes:
            eye=getattr(tr,e.side+"_eye")
            mask=np.zeros(frame.shape[:2],np.uint8)
            cv2.fillPoly(mask,[np.rint(eye.contour[:,:2]*(1280,720)).astype(np.int32)],1)
            points=[]
            # A source-derived threshold is held fixed across before/after.
            threshold=float(np.percentile(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)[mask==1],35))
            for image in (frame,out.frame):
                y,x=np.nonzero((cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)<=threshold)&(mask==1))
                assert len(x)>0
                points.append(np.array([x.mean(),y.mean()]))
            assert np.dot(points[1]-points[0],e.displacement_px)>0
        record_property("correction_ms",out.result.correction_ms)
        record_property("compositing_ms",out.result.compositing_ms)
    finally: tracker.close()
