"""Synchronous local-file experiment CLI. No webcam, GUI, or pipeline imports.

Exit 0: artifacts written without an engine fault (safe skips are evidence).
Exit 1: input/backend/rendering/I/O fault. Exit 2: invalid arguments.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, fields, is_dataclass, replace
from datetime import datetime
from enum import Enum
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import subprocess
import time

from gazefix.config import AppSettings


def build_parser():
    p = argparse.ArgumentParser(description="Offline GazeFix correction experiments; local files only")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path)
    source.add_argument("--video", type=Path)
    p.add_argument("--canvas", help="image canvas WIDTHxHEIGHT")
    p.add_argument("--face-scale", type=float, default=.8)
    p.add_argument("--unmirror", action="store_true")
    strength = p.add_mutually_exclusive_group()
    strength.add_argument("--strength", type=float, default=.7)
    strength.add_argument("--effective-strength", type=float)
    p.add_argument("--target-yaw", type=float, default=0.)
    p.add_argument("--target-pitch", type=float, default=0.)
    for flag in ("strength", "target-yaw", "target-pitch"):
        p.add_argument("--sweep-" + flag)
    p.add_argument("--variant", choices=("layered", "field"), default="layered")
    p.add_argument("--set", action="append", default=[], metavar="NAMESPACE.KEY=VALUE")
    p.add_argument("--eye-model-ratio", type=float, default=AppSettings().gaze_eye_model_ratio)
    p.add_argument("--stabilizer", type=float, default=0.)
    p.add_argument("--gaze-smoothing", type=float, default=0.)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--debug-layers", default="contour,iris,alpha,roi,warp,text")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--max-frames", type=int, default=300, help="maximum decoded source frames")
    p.add_argument("--every", type=int, default=1)
    p.add_argument("--out", type=Path, default=Path("experiments"))
    p.add_argument("--name")
    p.add_argument("--label", default="")
    p.add_argument("--model-dir", type=Path)
    return p


def _overrides(objects, overrides):
    """Strict namespaced, typed dataclass replacement; never eval input."""
    for item in overrides:
        try:
            key, raw = item.split("=", 1)
            namespace, name = key.split(".", 1)
            obj = objects[namespace]
            if name not in {f.name for f in fields(obj)}:
                raise ValueError("unknown field")
            old = getattr(obj, name)
            if isinstance(old, str): value = raw
            elif isinstance(old, bool):
                if raw.lower() not in ("true", "false"): raise ValueError("boolean needs true/false")
                value = raw.lower() == "true"
            elif isinstance(old, tuple): value = tuple(float(v) for v in raw.strip("()[]").split(","))
            elif isinstance(old, int): value = int(raw)
            else: value = float(raw)
            objects[namespace] = replace(obj, **{name: value}).validated()
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"invalid --set {item}: {exc}") from exc
    return objects


def _json(value):
    if is_dataclass(value): return {f.name: _json(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value, Enum): return value.value
    if isinstance(value, Path): return str(value)
    if isinstance(value, dict): return {str(k): _json(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)): return [_json(v) for v in value]
    if hasattr(value,"tolist"): return value.tolist()
    return value


def image_canvas(still, width, height, face_scale=.8):
    import cv2
    import numpy as np
    factor = min(height*.95*face_scale/still.shape[0], width*.95/still.shape[1])
    patch = cv2.resize(still,(max(1,int(still.shape[1]*factor)),max(1,int(still.shape[0]*factor))))
    frame = np.full((height,width,3),96,np.uint8)
    x,y = (width-patch.shape[1])//2,(height-patch.shape[0])//2
    frame[y:y+patch.shape[0],x:x+patch.shape[1]] = patch
    return frame


def analyse_frame(tracker, estimator, stabilizer, frame, index, timestamp_ms, app):
    """Frozen worker's analysis/status rule, assembled offline without a worker."""
    import numpy as np
    from gazefix.tracking.analysis import (AnalysisSettings, compute_quality, extract_eye,
                                           head_pose_from_matrix, validate_landmarks)
    from gazefix.tracking.models import FrameGeometry, TrackingResult, TrackingStatus, TrackingTiming
    started = time.perf_counter_ns()
    geometry = FrameGeometry(frame.shape[1],frame.shape[0])
    identity = dict(capture_sequence=index, captured_at_ns=timestamp_ms*1_000_000, camera_request_id=1, geometry=geometry)
    analysis = AnalysisSettings(min_quality=app.tracking_min_quality,
        min_in_frame_fraction=app.tracking_min_in_frame_fraction, min_eye_width_px=app.tracking_min_eye_width_px)
    try:
        detection = tracker.detect(frame,timestamp_ms)
        if not detection.faces:
            stabilizer.reset(); estimator.reset()
            result = TrackingResult(status=TrackingStatus.NO_FACE,message="no face detected",**identity)
        else:
            face = max(detection.faces,key=lambda f: float(np.ptp(f.landmarks[:,1])))
            landmarks, iris = validate_landmarks(face.landmarks)
            landmarks = stabilizer.apply(landmarks)
            quality = compute_quality(landmarks,geometry,analysis,tracker.backend_thresholds)
            right = extract_eye(landmarks,"right",geometry,analysis,iris)
            left = extract_eye(landmarks,"left",geometry,analysis,iris)
            reasons = []
            if quality.in_frame_fraction < analysis.min_in_frame_fraction:
                reasons.append(f"face partially outside the frame ({quality.in_frame_fraction:.2f} of landmarks inside)")
            if quality.score < analysis.min_quality:
                reasons.append(f"quality {quality.score:.2f} below {analysis.min_quality:.2f}")
            for eye in (right,left):
                if not eye.valid: reasons.append(f"{eye.side} eye outside the frame or too small")
            result = TrackingResult(status=TrackingStatus.LOW_QUALITY if reasons else TrackingStatus.TRACKED,
                message="; ".join(reasons),faces_detected=len(detection.faces),landmarks=landmarks,
                right_eye=right,left_eye=left,iris_available=iris,quality=quality,
                pose=head_pose_from_matrix(face.transform),stabilized=stabilizer.enabled,**identity)
        result = replace(result,gaze=estimator.estimate(result),timing=TrackingTiming(
            inference_ms=detection.inference_ms,total_ms=(time.perf_counter_ns()-started)/1e6))
    except Exception as exc:
        stabilizer.reset(); estimator.reset()
        result = TrackingResult(status=TrackingStatus.ERROR,message=f"tracking/analysis failed: {exc}",**identity)
        result = replace(result,gaze=estimator.estimate(result))
    return result


def safe_correct(engine, frame, tracking, target, strength):
    from gazefix.correction.models import CorrectionOutput, CorrectionResult, CorrectionStatus
    started = time.perf_counter_ns()
    try:
        return engine.correct(frame,tracking,target,strength)
    except Exception as exc:
        return CorrectionOutput(frame,CorrectionResult(CorrectionStatus.FAILED,
            f"engine exception: {type(exc).__name__}: {exc}",strength,(time.perf_counter_ns()-started)/1e6))


def tracking_metadata(tr):
    return {"status":tr.status,"message":tr.message,"quality":tr.quality,
        "geometry":tr.geometry,"capture_sequence":tr.capture_sequence,"captured_at_ns":tr.captured_at_ns,
        "camera_request_id":tr.camera_request_id,"timing":tr.timing,"iris_available":tr.iris_available,
        "eyes": {s: None if getattr(tr,s+"_eye") is None else {"valid":getattr(tr,s+"_eye").valid,
            "openness":getattr(tr,s+"_eye").openness} for s in ("right","left")}}


def _write_image(path, frame):
    import cv2
    if not cv2.imwrite(str(path),frame): raise OSError(f"could not write {path}")


def comparison(original, corrected, tracking, label=""):
    import cv2
    import numpy as np
    pair = np.hstack((original,corrected))
    strip = np.full((max(160,original.shape[0]//2),pair.shape[1],3),32,np.uint8)
    eyes = [e for e in (tracking.right_eye,tracking.left_eye) if e is not None]
    if eyes:
        points = np.concatenate([e.contour[:,:2] for e in eyes]) * (original.shape[1],original.shape[0])
        lo = np.maximum(0,np.floor(points.min(axis=0)-8).astype(int))
        hi = np.minimum((original.shape[1],original.shape[0]),np.ceil(points.max(axis=0)+8).astype(int))
        if np.all(hi>lo):
            crops = [cv2.resize(f[lo[1]:hi[1],lo[0]:hi[0]],None,fx=3,fy=3,interpolation=cv2.INTER_NEAREST)
                     for f in (original,corrected)]
            for i,crop in enumerate(crops):
                h,w = min(crop.shape[0],strip.shape[0]-35),min(crop.shape[1],original.shape[1])
                strip[35:35+h,i*original.shape[1]:i*original.shape[1]+w] = crop[:h,:w]
    cv2.putText(strip,"Original | Corrected   3x eye crops   "+label,(8,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(240,240,240),1,cv2.LINE_AA)
    return np.vstack((pair,strip))


class _VideoSink:
    """File writer with a per-stream PNG fallback; retains no frame queue."""
    def __init__(self, path, fps, shape):
        import cv2
        self.path = path
        self.writer = cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),fps,(shape[1],shape[0]))
        self.fallback = not self.writer.isOpened()
        if self.fallback:
            self.writer.release()
            self.path = path.with_suffix("")
            self.path.mkdir()
    def write(self,frame,index):
        if self.fallback: _write_image(self.path/f"{index:06d}.png",frame)
        else: self.writer.write(frame)
    def close(self):
        self.writer.release()


def _percentiles(rows):
    import numpy as np
    values = {}
    for row in rows:
        for key in ("correction_ms","compositing_ms"):
            if row[key] is not None: values.setdefault(key,[]).append(row[key])
        for key,value in row.get("stage_ms",[]): values.setdefault(key,[]).append(value)
    return {k:{"median":float(np.median(v)),"p90":float(np.percentile(v,90)),"samples":len(v)} for k,v in values.items()}


def repository_provenance():
    """Read local revision only; runs correctly even outside the checkout cwd."""
    root=Path(__file__).resolve().parents[2]
    try:
        def git(*args):
            return subprocess.check_output(["git","-C",str(root),*args],text=True,
                stderr=subprocess.DEVNULL,timeout=5).strip()
        return {"head":git("rev-parse","HEAD"),"tracked_changes":bool(git("status","--porcelain","--untracked-files=no")),
                "m3_sa":"m3-architecture-v1.2 @ 6a64ab7ae55a4c2c3e71f7084b9ed48b51c91b93"}
    except (OSError,subprocess.SubprocessError):
        return {"head":None,"tracked_changes":None}


def main(argv=None, tracker_factory=None):
    parser = build_parser(); args = parser.parse_args(argv)
    # Dependencies remain lazy so --help never loads a backend or OpenCV.
    from gazefix.correction.geometric import GeometricCorrectionEngine, GeometricCorrectionSettings
    from gazefix.correction.policy import PolicySettings, PolicyDecision, resolve_effective_strength
    from gazefix.gaze.estimator import GazeSettings, GeometricGazeEstimator
    from gazefix.gaze.models import direction_from_angles
    from gazefix.tracking.stabilizer import LandmarkStabilizer
    from gazefix.correction.models import CorrectionStatus
    import cv2
    import numpy as np
    try:
        if min(args.repeat,args.max_frames,args.every) < 1: raise ValueError("repeat/max-frames/every must be positive")
        for name in ("strength","effective_strength","stabilizer","gaze_smoothing"):
            v = getattr(args,name)
            if v is not None and (not math.isfinite(v) or not 0<=v<=1): raise ValueError(f"{name} must be in [0,1]")
        if not math.isfinite(args.face_scale) or not .05<=args.face_scale<=1: raise ValueError("face-scale must be .05..1")
        for name,limit in (("target_yaw",180),("target_pitch",90)):
            if not math.isfinite(getattr(args,name)) or abs(getattr(args,name))>limit: raise ValueError(f"invalid {name}")
        size = tuple(int(v) for v in args.canvas.lower().split("x")) if args.canvas else None
        if size and (len(size)!=2 or min(size)<2): raise ValueError("canvas must be positive WIDTHxHEIGHT")
        if args.video and size: raise ValueError("canvas is image-only")
        if args.image and (args.stabilizer or args.gaze_smoothing): raise ValueError("smoothing is video-only")
        sweeps=[]
        for name,default,limit in (("strength",args.effective_strength if args.effective_strength is not None else args.strength,1),
                                   ("target_yaw",args.target_yaw,180),("target_pitch",args.target_pitch,90)):
            raw=getattr(args,"sweep_"+name)
            values=[float(v) for v in raw.split(",")] if raw else [default]
            if not values or any(not math.isfinite(v) or abs(v)>limit or (name=="strength" and v<0) for v in values):
                raise ValueError(f"invalid sweep {name}")
            sweeps.append(values)
        sweeping = any(getattr(args,"sweep_"+n) for n in ("strength","target_yaw","target_pitch"))
        if args.video and sweeping: raise ValueError("contact-sheet sweeps are image-only; run clips separately")
        debug_layers = set(args.debug_layers.split(","))
        if not debug_layers <= {"contour","iris","alpha","roi","warp","text"}: raise ValueError("unknown debug layer")
        app = AppSettings()
        if args.model_dir: app=replace(app,model_directory=args.model_dir)
        app=app.validated()
        settings=_overrides({"engine":GeometricCorrectionSettings(eye_model_ratio=args.eye_model_ratio,
            iris_layer=args.variant=="layered",debug=args.debug),"gaze":GazeSettings(eye_model_ratio=args.eye_model_ratio,
            min_confidence=app.gaze_min_confidence,smoothing=args.gaze_smoothing),
            "policy":PolicySettings(conf_floor=app.gaze_min_confidence)},args.set)
        for obj in settings.values(): obj.validated()
        if args.image and settings["gaze"].smoothing: raise ValueError("gaze smoothing is video-only, including --set")
        source=args.image or args.video
        if not source.is_file(): raise ValueError("source must be an existing local file")
        name=args.name or source.stem+"_"+datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        if Path(name).name!=name or name in (".","..") or any(c in name for c in '/\\:'):
            raise ValueError("name must be a single directory name")
    except (ValueError,TypeError) as exc: parser.error(str(exc))

    root=args.out/name
    report={"arguments":vars(args),"source":{"name":source.name,"sha256":None,"unmirror":args.unmirror},
            "settings":settings,"label":args.label,"gazefix_version":__import__("gazefix").__version__,
            "repository":repository_provenance(),
            "mapping_mismatch":{k:getattr(settings["engine"],k)!=getattr(settings["gaze"],k) for k in ("eye_model_ratio","min_cos")}}
    tracker = capture = None
    sinks={}; experiments=[]; timing_rows=[]; failures=0; frame_count=0
    try:
        root.mkdir(parents=True,exist_ok=False)
        with source.open("rb") as stream: report["source"]["sha256"]=hashlib.file_digest(stream,"sha256").hexdigest()
        if tracker_factory is None:
            from gazefix.tracking.mediapipe_tracker import create_mediapipe_tracker
            tracker_factory=create_mediapipe_tracker
        started=time.perf_counter_ns(); tracker=tracker_factory(app)
        report.update(tracker=tracker.description,init_ms=(time.perf_counter_ns()-started)/1e6)
        estimator=GeometricGazeEstimator(settings["gaze"]); stabilizer=LandmarkStabilizer(args.stabilizer)
        estimator.reset(); stabilizer.reset()
        engine=GeometricCorrectionEngine(settings["engine"])
        if args.image:
            still=cv2.imread(str(source))
            if still is None: raise ValueError("could not decode image")
            frames=iter([(0,still)])
            fps=30.
        else:
            capture=cv2.VideoCapture(str(source))
            if not capture.isOpened(): raise ValueError("could not open video file")
            fps=capture.get(cv2.CAP_PROP_FPS)
            if not math.isfinite(fps) or fps<=0:
                fps=30.; report["video_timing_warning"]="source FPS unavailable; 30 FPS used"
            def decoded():
                for index in range(args.max_frames):
                    ok,frame=capture.read()
                    if not ok: break
                    if index%args.every==0: yield index,frame
            frames=decoded()
        report["source_fps"]=fps if args.video else None
        with (root/"frames.jsonl").open("w",encoding="utf-8") as jsonl:
            for index,frame in frames:
                frame_count+=1
                report["source"].setdefault("dimensions",[frame.shape[1],frame.shape[0]])
                if args.unmirror: frame=cv2.flip(frame,1)
                if size: frame=image_canvas(frame,*size,args.face_scale)
                frame.setflags(write=False)
                tr=analyse_frame(tracker,estimator,stabilizer,frame,index+1,max(index+1,int(index*1000/fps)+1),app)
                for n,(strength,yaw,pitch) in enumerate(itertools.product(*sweeps)):
                    target=direction_from_angles(yaw,pitch)
                    decision=resolve_effective_strength(strength,tr.gaze,target,settings["policy"])
                    if args.effective_strength is not None:
                        decision=PolicyDecision(strength,strength,decision.deviation_deg,decision.confidence,"effective-strength bypass")
                    repeats=[]
                    for _ in range(args.repeat):
                        output=safe_correct(engine,frame,tr,target,decision.effective_strength)
                        row={"correction_ms":output.result.correction_ms,"compositing_ms":output.result.compositing_ms,
                             "stage_ms":output.result.debug.stage_ms if output.result.debug else ()}
                        repeats.append(row); timing_rows.append(row)
                        if output.result.status is CorrectionStatus.FAILED:
                            break  # a later repetition must never hide a fault
                    entry={"tracking":tracking_metadata(tr),"gaze":tr.gaze,"policy":decision,"correction":output.result,
                           "target":{"yaw":yaw,"pitch":pitch},"timings":_percentiles(repeats)}
                    if output.result.status is CorrectionStatus.FAILED:
                        failures+=1; print(f"frame {index}: {output.result.message}",file=sys.stderr)
                    if tr.status.value=="error": failures+=1
                    label=f"s={strength:g} effective={decision.effective_strength:.3f} yaw={yaw:g} pitch={pitch:g} {output.result.status.value}"
                    sheet=comparison(frame,output.frame,tr,label)
                    images={"corrected":output.frame,"side_by_side":sheet}
                    if args.debug:
                        from gazefix.correction.debug import render_debug
                        images["debug"],entry["eye_geometry"] = render_debug(output.frame,tr,output.result,settings["engine"],decision,debug_layers)
                    if args.image:
                        dest=root/f"sweep_{n:03d}" if sweeping else root
                        dest.mkdir(exist_ok=True)
                        _write_image(dest/"original.png",frame)
                        for key,value in images.items(): _write_image(dest/(key+".png"),value)
                        entry["directory"]=str(dest.relative_to(root)); experiments.append(entry)
                        if n==0 and sweeping:
                            _write_image(root/"original.png",frame)
                            for key,value in images.items(): _write_image(root/(key+".png"),value)
                    else:
                        for key,value in images.items():
                            if key not in sinks: sinks[key]=_VideoSink(root/(key+".mp4"),fps/args.every,value.shape)
                            sinks[key].write(value,index)
                        if frame_count==1:
                            _write_image(root/"original.png",frame)
                            for key,value in images.items(): _write_image(root/(key+".png"),value)
                    jsonl.write(json.dumps(_json(entry),allow_nan=False)+"\n")
        engine.close()
        if frame_count==0: raise ValueError("no frames decoded")
        if sweeping:
            thumbnails=[]
            for entry in experiments:
                im=cv2.imread(str(root/entry["directory"]/"side_by_side.png"))
                thumbnails.append(cv2.resize(im,(960,int(im.shape[0]*960/im.shape[1]))))
            _write_image(root/"sweep.png",np.vstack(thumbnails))
        report.update(frame_count=frame_count,failures=failures,experiments=experiments,timings=_percentiles(timing_rows),
                      last_frame=entry if args.video else None,
                      video_outputs={k:{"path":str(v.path.relative_to(root)),"png_fallback":v.fallback} for k,v in sinks.items()})
    except Exception as exc:
        failures+=1; report["error"]=f"{type(exc).__name__}: {exc}"
        print(report["error"],file=sys.stderr)
    finally:
        for sink in sinks.values(): sink.close()
        if capture is not None: capture.release()
        if tracker is not None:
            try: tracker.close()
            except Exception as exc: failures+=1; report["close_error"]=str(exc)
    # Never overwrite a prior experiment when mkdir failed.
    if report["source"]["sha256"] is not None:
        report["failures"]=failures
        try: (root/"report.json").write_text(json.dumps(_json(report),indent=2,allow_nan=False),encoding="utf-8")
        except (OSError,ValueError) as exc: print(str(exc),file=sys.stderr); return 1
    print(f"{root}: {frame_count} frames, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
