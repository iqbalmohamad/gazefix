"""Preflight gate for a Phase 1A run.

Every precondition the protocol depends on is checked in one place and reported
at its true verification level. The run is allowed to proceed to remote
execution only when every blocking check passes; a failing check is reported,
never worked around.
"""

from __future__ import annotations

from pathlib import Path

from . import maxine, provenance
from .mediaprobe import tool_version

BLOCKING = "BLOCKING"
ADVISORY = "ADVISORY"


def _check(name, ok, detail, severity=BLOCKING, status=None):
    return {"check": name,
            "status": status or ("PASS" if ok else "FAIL"),
            "severity": severity, "detail": detail}


def run(inputs_root, workspace, env=None, repo_root=None, spec=None):
    """Evaluate every precondition and return a preflight report."""
    checks = []

    rows = provenance.verify_frozen_refs(repo_root)
    bad = [r for r in rows if not r["ok"]]
    checks.append(_check(
        "frozen-references-unchanged", not bad,
        "all frozen references resolve to their recorded SHAs" if not bad
        else f"drifted: {bad}"))

    inputs = Path(inputs_root)
    videos = sorted(p.name for p in inputs.iterdir()
                    if p.is_file() and p.suffix.lower() in
                    (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")
                    ) if inputs.is_dir() else []
    checks.append(_check(
        "product-owner-footage-present", bool(videos),
        f"{len(videos)} video source(s) under {inputs}" if videos
        else f"no video source found under {inputs}. Phase 1A must use "
             "existing Product Owner footage; benchmark video from the "
             "internet and synthetic subjects are both forbidden."))

    for tool in ("ffprobe", "ffmpeg"):
        version = tool_version(tool)
        checks.append(_check(
            f"tool-{tool}", bool(version),
            version or f"{tool} not found on PATH"))

    present = maxine.api_key_present(env)
    checks.append(_check(
        "nvidia-credential", present,
        f"{maxine.API_KEY_ENV} is set" if present
        else f"{maxine.API_KEY_ENV} is not set in this environment"))

    client = Path(workspace.client) / "scripts" / "eye-contact.py"
    checks.append(_check(
        "nvidia-client-available", client.is_file(),
        f"NVIDIA client present at {client}" if client.is_file()
        else f"NVIDIA client not found at {client}; see README step 'Fetch "
             "NVIDIA's client'"))

    interfaces = Path(workspace.client) / "interfaces" / "eyecontact_pb2.py"
    checks.append(_check(
        "nvidia-protos-compiled", interfaces.is_file(),
        "generated gRPC interfaces present" if interfaces.is_file()
        else "protos not compiled; run NVIDIA's compile_protos script"))

    spec = spec if spec is not None else _load_spec()
    availability = ((spec or {}).get("hosted_availability") or {})
    checks.append(_check(
        "hosted-api-availability-confirmed", False,
        availability.get("required_gate")
        or "hosted endpoint availability must be confirmed first-hand",
        severity=BLOCKING,
        status=availability.get("status", "NOT VERIFIED")))

    blocking = [c for c in checks
                if c["severity"] == BLOCKING and c["status"] != "PASS"]
    return {
        "manifest_kind": "phase1a-preflight",
        "checks": checks,
        "blocking_failures": [c["check"] for c in blocking],
        "may_execute_remotely": not blocking,
        "frozen_references": rows,
    }


def _load_spec():
    try:
        return maxine.load_spec()
    except (OSError, ValueError):
        return {}
