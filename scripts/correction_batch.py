"""Repeatable M3 batch driver for the existing offline harness, no capture.

Run from the checkout: python -m scripts.correction_batch fixture|po
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import html
import json
from pathlib import Path

from gazefix.correction.harness import main as run_experiment, repository_provenance


STILLS = tuple(f"{gaze}-{glasses}" for glasses in ("no-glasses","glasses")
               for gaze in ("lens","screen","notes","horizontal"))
CLIPS = ("speaking-smiling","minor-rotation","blink-wink-squint")
SCORES = ("eye_realism","iris_realism","blink_realism","eyelid_preservation",
          "identity_preservation","artifact_visibility","perceived_eye_contact",
          "less_distracting_yes_no","temporal_notes_clips_only","notes")


def plan(mode, inputs, fixture, unmirror=False):
    """Resolve every input before starting a batch; exact names avoid mix-ups."""
    if mode == "fixture":
        if not fixture.is_file():
            raise ValueError(f"fixture missing: {fixture}")
        return [(f"{variant}-{axis}-s{strength}",
                 ["--image",str(fixture),"--canvas","1280x720","--variant",variant,
                  "--effective-strength",str(strength),f"--sweep-target-{axis}","5,10,15,20,25,30","--debug"])
                for variant in ("field","layered") for axis in ("yaw","pitch")
                for strength in (.25,.5,.75,1.)]
    jobs=[];missing=[]
    for stem in (*STILLS,*CLIPS):
        video=stem in CLIPS
        allowed=(".mp4",".avi",".mov",".mkv") if video else (".png",".jpg",".jpeg")
        matches=[p for p in inputs.glob(stem+".*") if p.suffix.lower() in allowed]
        if len(matches)!=1:
            missing.append(stem+" (need exactly one image/video)");continue
        # Default C/settings and policy, strength .7, optical-axis target.
        args=["--video" if video else "--image",str(matches[0]),"--strength",".7","--debug"]
        if video: args += ["--max-frames","1200"]  # covers 10 s even at 120 Hz
        if unmirror: args.append("--unmirror")
        jobs.append((stem,args))
    if missing:
        raise ValueError("Missing/ambiguous captures in "+str(inputs)+": "+", ".join(missing))
    return jobs


def main(argv=None, runner=run_experiment):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("fixture","po"))
    parser.add_argument("--inputs",type=Path,default=Path("experiments/inputs"))
    parser.add_argument("--fixture",type=Path,default=Path("tests/assets/astronaut_face.png"))
    parser.add_argument("--out",type=Path,default=Path("experiments"))
    parser.add_argument("--name")
    parser.add_argument("--unmirror",action="store_true",help="PO session recorded mirrored")
    args=parser.parse_args(argv)
    name=args.name or "m3-v12-"+args.mode+"-"+datetime.now().strftime("%Y%m%d-%H%M%S")
    if Path(name).name!=name or name in (".","..") or any(c in name for c in '/\\:'):
        parser.error("name must be a single directory name")
    try:
        jobs=plan(args.mode,args.inputs,args.fixture,args.unmirror)
    except ValueError as exc:
        parser.error(str(exc))
    root=args.out/name
    if root.exists(): parser.error(f"batch already exists: {root}")
    root.mkdir(parents=True)
    results=[]
    for stem,options in jobs:
        code=runner(options+["--out",str(root),"--name",stem,"--label",stem])
        results.append({"experiment":stem,"exit_code":code,"arguments":options})
    provenance=repository_provenance()
    (root/"batch.json").write_text(json.dumps({"mode":args.mode,"repository":provenance,
        "visual_gate":"NOT EVALUATED","experiments":results},indent=2),encoding="utf-8")
    with (root/"scores.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.writer(stream);writer.writerow(("experiment","tested_sha",*SCORES))
        writer.writerows((item["experiment"],provenance["head"],*("" for _ in SCORES)) for item in results)
    sections=[]
    for item in results:
        stem=item["experiment"]
        sheet="sweep.png" if args.mode=="fixture" else "side_by_side.png"
        section=f'<section><h2>{html.escape(stem)}</h2><p>Harness exit: {item["exit_code"]}. '
        section+=f'<a href="{stem}/report.json">Settings, outcomes and timing</a></p>'
        section+=f'<a href="{stem}/{sheet}"><img loading="lazy" src="{stem}/{sheet}" alt="{stem}"></a>'
        report_path=root/stem/"report.json"
        if report_path.exists():
            report=json.loads(report_path.read_text(encoding="utf-8"))
            for key,value in report.get("video_outputs",{}).items():
                relative=html.escape(stem+"/"+value["path"].replace("\\","/"),quote=True)
                if value["png_fallback"]:
                    section+=f'<p><a href="{relative}">{key} PNG sequence (codec unavailable)</a></p>'
                elif key=="side_by_side":
                    section+=f'<video controls preload="metadata" src="{relative}"></video>'
        sections.append(section+"</section>")
    (root/"index.html").write_text('<!doctype html><meta charset="utf-8"><title>GazeFix M3 evaluation</title>'
        '<style>body{font:18px system-ui;max-width:1400px;margin:32px auto;background:#eee;color:#222}'
        'img,video{max-width:100%}section{background:white;padding:20px;margin:20px 0}</style>'
        '<h1>GazeFix M3 — visual gate NOT EVALUATED</h1>'
        '<p>Click each sheet for native 100% inspection and 3x eye crops. '
        'A CORRECTED frame or exit 0 is not a quality verdict. '
        '<a href="scores.csv">Blank scoring sheet</a></p>'+"".join(sections),encoding="utf-8")
    print(f"Batch index: {root/'index.html'}")
    return int(any(item["exit_code"] for item in results))


if __name__=="__main__":
    raise SystemExit(main())
