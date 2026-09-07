"""Phase 1A command line driver.

Run from the repository root:

    python -m research.maxine-eye-contact.eval.cli --help          (not importable: hyphen)

The package directory contains a hyphen, so use the provided entry script:

    python research/maxine-eye-contact/run.py <command> [options]

Commands run in protocol order. Each refuses to run out of order rather than
improvising, because the protocol's value is that the held-out set and the
model configuration are frozen before any output is seen.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from . import (blinding, geometric, maxine, package, preflight, preprocess,
               provenance, redaction, scenarios, sourceset)
from .hashing import read_json, sha256_file, write_json
from .paths import DEFAULT_INPUTS, DEFAULT_WORKSPACE, Workspace


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path, what):
    if not Path(path).is_file():
        raise SystemExit(f"{what} not found at {path}; run the previous step first")
    return read_json(path)


def cmd_preflight(args):
    workspace = Workspace(args.workspace).ensure()
    report = preflight.run(args.inputs, workspace)
    report["generated_utc"] = _now()
    write_json(workspace.preflight, report)
    for check in report["checks"]:
        print(f"{check['status']:<13} {check['check']}: {check['detail']}")
    print(f"\nmay execute remotely: {report['may_execute_remotely']}")
    print(f"written: {workspace.preflight}")
    return 0 if report["may_execute_remotely"] else 3


def cmd_plan(args):
    workspace = Workspace(args.workspace).ensure()
    candidates, skipped = sourceset.discover(args.inputs)
    document = sourceset.build_plan(candidates, args.inputs)
    document["skipped"] = skipped
    document["generated_utc"] = _now()
    if workspace.plan_file.exists() and not args.force:
        raise SystemExit(f"{workspace.plan_file} exists; pass --force to replace it")
    write_json(workspace.plan_file, document)
    for clip in document["clips"]:
        print(f"{clip['clip_id']}  {clip['source_name']:<32} "
              f"{','.join(clip['scenarios']) or '(untagged)'}")
    for item in skipped:
        print(f"skipped: {item['stem']}: {item['reason']}")
    uncovered = scenarios.uncovered(document["clips"])
    for name in uncovered:
        print(f"{name}: {scenarios.NOT_AVAILABLE}")
    print(f"\nwritten: {workspace.plan_file}")
    print("Review and edit the plan (trim windows, scenario tags), then run 'freeze'.")
    return 0


def cmd_freeze(args):
    workspace = Workspace(args.workspace).ensure()
    document = _load(workspace.plan_file, "source plan")
    if workspace.manifest_file.exists() and not args.force:
        raise SystemExit(
            f"{workspace.manifest_file} already exists. The held-out set is "
            "frozen before the first inference and must not be re-rolled. Pass "
            "--force only if no Maxine output has been produced yet.")
    manifest = sourceset.freeze(document, _now(), provenance.repository_provenance(),
                               strict_probe=args.strict_probe)
    write_json(workspace.manifest_file, manifest)
    for clip in manifest["clips"]:
        media = clip["media"]
        if media.get("width") and media.get("height"):
            shape = (f"{media['width']}x{media['height']} "
                     f"{media.get('duration_s')}s {media.get('codec')}")
        else:
            shape = "NOT MEASURED (ffprobe unavailable)"
        print(f"{clip['clip_id']}  {clip['source_name']:<30} "
              f"{clip['source_sha256'][:12]}  {shape}")
    for row in manifest["coverage"]:
        if row["status"] != "COVERED":
            print(f"{row['scenario']}: {row['status']}")
    print(f"\nfrozen: {workspace.manifest_file}")
    print(f"manifest sha256: {manifest['manifest_sha256']}")
    return 0


def cmd_prepare(args):
    workspace = Workspace(args.workspace).ensure()
    manifest = _load(workspace.manifest_file, "frozen source manifest")
    workspace.derived.mkdir(parents=True, exist_ok=True)
    records = []
    for clip in sourceset.active_clips(manifest):
        destination = workspace.derived / f"{clip['clip_id']}.mp4"
        record = preprocess.derive(clip["source_path"], destination,
                                   trim=clip.get("trim"), fps=args.fps)
        record["clip_id"] = clip["clip_id"]
        records.append(record)
        print(f"{clip['clip_id']}  {record['derived_sha256'][:12]}  "
              f"{record['derived_bytes']} bytes")
    document = {"manifest_kind": "phase1a-derived-manifest",
                "generated_utc": _now(),
                "profile_id": preprocess.PROFILE_ID,
                "source_manifest_sha256": manifest.get("manifest_sha256"),
                "note": "One derived input per clip, used by BOTH conditions.",
                "clips": records}
    write_json(workspace.derived_manifest, document)
    print(f"\nwritten: {workspace.derived_manifest}")
    return 0


def cmd_geometric(args):
    workspace = Workspace(args.workspace).ensure()
    manifest = _load(workspace.manifest_file, "frozen source manifest")
    derived = {c["clip_id"]: c for c in
               _load(workspace.derived_manifest, "derived manifest")["clips"]}
    workspace.geometric.mkdir(parents=True, exist_ok=True)
    records = []
    for clip in sourceset.active_clips(manifest):
        entry = derived.get(clip["clip_id"])
        if entry is None:
            print(f"{clip['clip_id']}: no derived input; skipped")
            continue
        extra = ["--model-dir", str(args.model_dir)] if args.model_dir else []
        record = geometric.run(entry["derived_path"], workspace.geometric,
                               clip["clip_id"],
                               python_executable=args.python, extra=extra,
                               cwd=str(provenance.repository_root()))
        record["clip_id"] = clip["clip_id"]
        record["derived_sha256"] = entry["derived_sha256"]
        corrected = Path(record["corrected_path"])
        record["corrected_sha256"] = sha256_file(corrected) if corrected.is_file() else None
        records.append(record)
        print(f"{clip['clip_id']}  exit={record['returncode']}  "
              f"{'ok' if record['corrected_sha256'] else 'NO OUTPUT'}")
    write_json(workspace.geometric_manifest, {
        "manifest_kind": "phase1a-geometric-manifest",
        "generated_utc": _now(),
        "baseline_ref": provenance.GEOMETRIC_BASELINE_REF,
        "baseline_commit": provenance.GEOMETRIC_BASELINE_COMMIT,
        "repository": provenance.repository_provenance(),
        "frozen_settings": {"explicit_flags": list(geometric.FROZEN_CLIP_ARGS),
                            "harness_defaults": geometric.FROZEN_DEFAULTS},
        "clips": records})
    print(f"\nwritten: {workspace.geometric_manifest}")
    return 0


def cmd_maxine(args):
    workspace = Workspace(args.workspace).ensure()
    report = preflight.run(args.inputs, workspace)
    if not report["may_execute_remotely"] and not args.i_have_confirmed_availability:
        for name in report["blocking_failures"]:
            print(f"BLOCKED: {name}")
        raise SystemExit(
            "Preflight is not clear. Remote execution is refused. Resolve every "
            "blocking check, then re-run. Confirming the hosted endpoint is "
            "live is a first-hand step: pass "
            "--i-have-confirmed-availability only after you have done it and "
            "recorded the evidence in manifests/nvidia-api-spec.json.")

    manifest = _load(workspace.manifest_file, "frozen source manifest")
    derived = {c["clip_id"]: c for c in
               _load(workspace.derived_manifest, "derived manifest")["clips"]}
    workspace.maxine.mkdir(parents=True, exist_ok=True)

    client = Path(workspace.client) / "scripts" / "eye-contact.py"
    workspace.launcher.write_text(maxine.launcher_source(client),
                                  encoding="utf-8", newline="\n")

    records = []
    for clip in sourceset.active_clips(manifest):
        entry = derived.get(clip["clip_id"])
        if entry is None:
            print(f"{clip['clip_id']}: no derived input; skipped")
            continue
        output = workspace.maxine / f"{clip['clip_id']}.mp4"
        if output.exists() and not args.force:
            print(f"{clip['clip_id']}: output exists; not re-running "
                  "(re-running a clip to seek a better result is forbidden)")
            continue
        record = maxine.run_clip(client, entry["derived_path"], output,
                                 workspace.launcher, cwd=str(client.parent),
                                 python_executable=args.python)
        record["clip_id"] = clip["clip_id"]
        record["derived_sha256"] = entry["derived_sha256"]
        record["output_sha256"] = sha256_file(output) if output.is_file() else None
        records.append(record)
        print(f"{clip['clip_id']}  {'OK' if record['success'] else 'FAILED'}  "
              f"{record['hosted_turnaround_s']}s  "
              f"{record['output_sha256'][:12] if record['output_sha256'] else '-'}")
        if not record["success"]:
            for failure in record["failures"]:
                print(f"    {failure}")

    write_json(workspace.maxine_manifest, {
        "manifest_kind": "phase1a-maxine-manifest",
        "generated_utc": _now(),
        "notice": package.NOTICE,
        "timing_label": "HOSTED BATCH/API TURNAROUND - NOT REALTIME LATENCY",
        "timing_caveat": "These numbers say nothing about realtime "
                         "glass-to-glass latency, GPU inference time, "
                         "concurrency, capacity or cost.",
        "api_spec": maxine.load_spec(),
        "profile": {k: (list(v) if isinstance(v, tuple) else v)
                    for k, v in maxine.FROZEN_PROFILE.items()},
        "clips": records})
    print(f"\nwritten: {workspace.maxine_manifest}")
    return 0


def cmd_package(args):
    workspace = Workspace(args.workspace).ensure()
    manifest = _load(workspace.manifest_file, "frozen source manifest")
    derived = {c["clip_id"]: c for c in
               _load(workspace.derived_manifest, "derived manifest")["clips"]}
    geo = {}
    if workspace.geometric_manifest.is_file():
        geo = {c["clip_id"]: c for c in read_json(workspace.geometric_manifest)["clips"]}
    mx = {}
    if workspace.maxine_manifest.is_file():
        mx = {c["clip_id"]: c for c in read_json(workspace.maxine_manifest)["clips"]}

    clips = []
    for clip in sourceset.active_clips(manifest):
        cid = clip["clip_id"]
        conditions = {}
        if cid in derived:
            conditions[blinding.ORIGINAL] = derived[cid]["derived_path"]
        if cid in geo and geo[cid].get("corrected_path"):
            conditions[blinding.GEOMETRIC] = geo[cid]["corrected_path"]
        if cid in mx and mx[cid].get("output"):
            conditions[blinding.MAXINE] = mx[cid]["output"]
        clips.append({"clip_id": cid, "conditions": conditions})

    try:
        built, key = package.build(workspace.package, args.seed, clips)
    except package.WeakBlindError as exc:
        ids = [c["clip_id"] for c in clips]
        better = blinding.suggest_seed(
            args.seed,
            lambda s: [blinding.assign(s, i, tuple(
                c["conditions"] for c in clips if c["clip_id"] == i)[0])
                for i in ids])
        raise SystemExit(f"{exc}\n"
                         + (f"A seed with no pinned condition: {better}"
                            if better else ""))
    findings = package.audit_presentation(workspace.presentation)
    if findings:
        raise SystemExit(f"blind package leaks method identity: {findings}")
    print(f"clips presented: {built['clip_count']}")
    for row in key["clips_missing_conditions"]:
        print(f"{row['clip_id']}: missing {', '.join(row['missing'])}")
    print(f"seed: {args.seed}")
    print(f"presentation: {workspace.presentation}")
    print(f"answer key (do not open before scoring): {workspace.answer_key}")
    return 0


def cmd_verify(args):
    workspace = Workspace(args.workspace).ensure()
    report = {"manifest_kind": "phase1a-integrity", "generated_utc": _now(),
              "checks": []}

    if workspace.manifest_file.is_file():
        manifest = read_json(workspace.manifest_file)
        rows = sourceset.verify_unchanged(manifest)
        drift = [r for r in rows if r["status"] != "OK"]
        report["checks"].append({"check": "frozen-sources-unchanged",
                                 "status": "PASS" if not drift else "FAIL",
                                 "detail": drift or "every source still hashes "
                                                    "to its frozen value"})
    rows = provenance.verify_frozen_refs()
    bad = [r for r in rows if not r["ok"]]
    report["checks"].append({"check": "frozen-references-unchanged",
                             "status": "PASS" if not bad else "FAIL",
                             "detail": bad or rows})

    if workspace.presentation.is_dir():
        findings = package.audit_presentation(workspace.presentation)
        report["checks"].append({"check": "blind-package-does-not-leak-method",
                                 "status": "PASS" if not findings else "FAIL",
                                 "detail": findings or "no method token in any "
                                                       "scorer-visible name or text"})
    secrets = redaction.scan_tree(workspace.root) if workspace.root.is_dir() else []
    repo_secrets = redaction.scan_tree(Path(__file__).resolve().parents[1])
    report["checks"].append({
        "check": "no-credential-in-artifacts",
        "status": "PASS" if not secrets and not repo_secrets else "FAIL",
        "detail": [{"path": str(p), "matches": m}
                   for p, m in (secrets + repo_secrets)]
                  or "no credential-shaped content in the workspace or the "
                     "committed package"})

    write_json(workspace.integrity, report)
    for check in report["checks"]:
        print(f"{check['status']:<6} {check['check']}")
    print(f"\nwritten: {workspace.integrity}")
    return 0 if all(c["status"] == "PASS" for c in report["checks"]) else 4


def build_parser():
    # Shared options are attached to every subcommand as well as the top level
    # so they may be given on either side of the command name.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE,
                        help="ignored local run directory")
    common.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS,
                        help="directory holding existing Product Owner footage")

    parser = argparse.ArgumentParser(
        prog="maxine-phase1a", parents=[common],
        description="GazeFix Phase 1A evaluation driver. "
                    "RESEARCH/EVALUATION ONLY - NOT AUTHORIZED FOR GAZEFIX PRODUCTION.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", parents=[common],
                   help="check every precondition").set_defaults(func=cmd_preflight)

    p = sub.add_parser("plan", parents=[common],
                       help="discover sources and write an editable plan")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("freeze", parents=[common], help="freeze the held-out set (before any inference)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--strict-probe", action="store_true",
                   help="fail instead of recording NOT MEASURED when ffprobe is absent")
    p.set_defaults(func=cmd_freeze)

    p = sub.add_parser("prepare", parents=[common], help="derive the shared input for both conditions")
    p.add_argument("--fps", type=float, default=None)
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("geometric", parents=[common], help="regenerate the frozen geometric baseline")
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--model-dir", type=Path, default=None,
                   help="MediaPipe face landmarker directory, if not the default")
    p.set_defaults(func=cmd_geometric)

    p = sub.add_parser("maxine", parents=[common], help="run the hosted NVIDIA endpoint")
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--force", action="store_true",
                   help="overwrite an existing output; only for a technical failure")
    p.add_argument("--i-have-confirmed-availability", action="store_true",
                   help="assert that the hosted endpoint was confirmed live "
                        "first-hand and the evidence recorded in the API spec")
    p.set_defaults(func=cmd_maxine)

    p = sub.add_parser("package", parents=[common], help="build the blind comparison package")
    p.add_argument("--seed", required=True, help="recorded randomisation seed")
    p.set_defaults(func=cmd_package)

    sub.add_parser("verify", parents=[common], help="integrity and secret scan").set_defaults(
        func=cmd_verify)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
