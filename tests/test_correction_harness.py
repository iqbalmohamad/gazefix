from dataclasses import replace
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from gaze_fakes import gaze_scene
from gazefix.correction.harness import main, safe_correct, analyse_frame
from gazefix.gaze.estimator import GeometricGazeEstimator, GazeSettings
from gazefix.tracking.stabilizer import LandmarkStabilizer
from gazefix.config import AppSettings
from gazefix.tracking.tracker import RawFace, RawDetection


class FakeTracker:
    description="synthetic fixture tracker"
    backend_thresholds=(.5,.5,.5)
    closed=False
    def __init__(self): self.frames=[]
    def detect(self,frame,ts):
        self.frames.append(frame.copy())
        scene=gaze_scene()
        return RawDetection((RawFace(scene.landmarks,scene.transform),),1.,True)
    def close(self): self.closed=True


@pytest.fixture
def source(tmp_path):
    image=np.full((720,1280,3),100,np.uint8); image[:,0]=200
    path=tmp_path/"input.png"; assert cv2.imwrite(str(path),image)
    return path


def args(source,tmp_path,name="run"):
    return ["--image",str(source),"--out",str(tmp_path),"--name",name,"--effective-strength",".75","--target-pitch","15"]


def test_cli_reports_artifacts_and_shared_constants(source,tmp_path):
    tracker=FakeTracker()
    assert main(args(source,tmp_path)+["--debug","--repeat","3","--eye-model-ratio","1.3"],tracker_factory=lambda _:tracker)==0
    root=tmp_path/"run"
    for name in ("original.png","corrected.png","side_by_side.png","debug.png","report.json","frames.jsonl"):
        assert (root/name).is_file()
    report=json.loads((root/"report.json").read_text())
    assert report["source"]["sha256"]==hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["settings"]["engine"]["eye_model_ratio"]==report["settings"]["gaze"]["eye_model_ratio"]==1.3
    assert not any(report["mapping_mismatch"].values())
    assert report["timings"]["correction_ms"]["samples"]==3
    entry=report["experiments"][0]
    assert entry["policy"]["effective_strength"]==.75 and entry["correction"]["status"]=="corrected"
    assert entry["eye_geometry"]["right"]["metadata_matches"]
    assert "landmarks" not in entry["tracking"] and tracker.closed


def test_sweeps_unmirror_and_override(source,tmp_path):
    tracker=FakeTracker()
    assert main(args(source,tmp_path)+["--sweep-strength","0,.5,1","--unmirror",
                "--set","engine.eye_model_ratio=1.4"],tracker_factory=lambda _:tracker)==0
    report=json.loads((tmp_path/"run"/"report.json").read_text())
    assert len(report["experiments"])==3 and (tmp_path/"run"/"sweep.png").is_file()
    assert report["mapping_mismatch"]["eye_model_ratio"]
    assert np.array_equal(tracker.frames[0],cv2.flip(cv2.imread(str(source)),1))
    assert report["experiments"][0]["correction"]["message"]=="strength 0"


@pytest.mark.parametrize("extra", [["--set","edge_px=2"],["--set","engine.nope=1"],
    ["--set","engine.edge_px=nan"],["--set","engine.pair_coupling=1"],
    ["--repeat","0"],["--target-pitch","nan"],["--canvas","0x720"],["--gaze-smoothing",".5"],
    ["--name","../escape"],["--set","engine.distance_transform=chamfer3"],["--sweep-strength","-1,0"]])
def test_invalid_arguments(source,tmp_path,extra):
    with pytest.raises(SystemExit) as exc: main(args(source,tmp_path)+extra,tracker_factory=lambda _:pytest.fail("must validate before tracker"))
    assert exc.value.code==2


def test_raise_containment_and_no_overwrite(source,tmp_path):
    tracker=FakeTracker()
    assert main(args(source,tmp_path),tracker_factory=lambda _:tracker)==0
    report=(tmp_path/"run"/"report.json").read_bytes()
    assert main(args(source,tmp_path),tracker_factory=lambda _:tracker)==1
    assert (tmp_path/"run"/"report.json").read_bytes()==report
    class Broken:
        def correct(self,*a): raise RuntimeError("fault")
    frame=np.zeros((5,5,3),np.uint8)
    out=safe_correct(Broken(),frame,None,np.array([0,0,1]),.7)
    assert out.frame is frame and out.result.status.value=="failed"


def test_video_bounded_png_fallback(tmp_path,monkeypatch):
    source=tmp_path/"clip.avi"
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*"MJPG"),30,(1280,720))
    assert writer.isOpened()
    for _ in range(5): writer.write(np.full((720,1280,3),100,np.uint8))
    writer.release()
    class NoCodec:
        def isOpened(self): return False
        def release(self): pass
    monkeypatch.setattr(cv2,"VideoWriter",lambda *a:NoCodec())
    tracker=FakeTracker()
    assert main(["--video",str(source),"--out",str(tmp_path),"--name","video","--max-frames","4","--every","2",
                 "--debug","--effective-strength",".7","--target-pitch","15"],tracker_factory=lambda _:tracker)==0
    report=json.loads((tmp_path/"video"/"report.json").read_text())
    assert report["frame_count"]==2 and len(tracker.frames)==2 and tracker.closed
    assert all(v["png_fallback"] for v in report["video_outputs"].values())
    assert len(list((tmp_path/"video"/"corrected").glob("*.png")))==2
    assert len((tmp_path/"video"/"frames.jsonl").read_text().splitlines())==2


def test_analysis_quality_rule():
    tracker=FakeTracker()
    frame=np.zeros((720,1280,3),np.uint8)
    estimator=GeometricGazeEstimator(GazeSettings(smoothing=0))
    tr=analyse_frame(tracker,estimator,LandmarkStabilizer(0),frame,1,1,replace(AppSettings(),tracking_min_eye_width_px=100))
    assert tr.status.value=="low_quality" and "right eye" in tr.message


@pytest.mark.parametrize("sweep,expected_records", [([],1),
    (["--sweep-strength",".25,.5,.75","--sweep-target-yaw","0,10"],6)])
def test_tracking_error_count_is_per_frame(source,tmp_path,sweep,expected_records):
    class BrokenTracker(FakeTracker):
        calls=0
        def detect(self,frame,ts):
            self.calls+=1
            raise RuntimeError("tracking failure for this frame")
    tracker=BrokenTracker()
    assert main(args(source,tmp_path)+sweep+["--repeat","3"],tracker_factory=lambda _:tracker)==1
    report=json.loads((tmp_path/"run"/"report.json").read_text())
    records=[json.loads(line) for line in (tmp_path/"run"/"frames.jsonl").read_text().splitlines()]
    assert tracker.calls==1 and tracker.closed and report["frame_count"]==1
    assert report["failures"]==1
    assert len(report["experiments"])==len(records)==expected_records
    assert all(e["tracking"]["status"]=="error" and e["correction"]["status"]=="skipped" for e in records)


def test_engine_error_count_stays_per_experiment(source,tmp_path,monkeypatch):
    from gazefix.correction.geometric import GeometricCorrectionEngine
    def fail(*args): raise RuntimeError("engine failure")
    monkeypatch.setattr(GeometricCorrectionEngine,"correct",fail)
    assert main(args(source,tmp_path)+["--sweep-strength",".25,.5,.75","--repeat","3"],
                tracker_factory=lambda _:FakeTracker())==1
    report=json.loads((tmp_path/"run"/"report.json").read_text())
    assert report["frame_count"]==1 and report["failures"]==3
    assert len(report["experiments"])==3
    assert all(e["correction"]["status"]=="failed" for e in report["experiments"])
