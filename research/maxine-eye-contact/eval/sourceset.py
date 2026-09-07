"""Held-out source set: discovery, planning and the mandatory freeze (S7).

The Phase 1A protocol requires the held-out set to be frozen *before* the first
Maxine inference. This module builds that frozen source manifest and then
enforces it: once frozen, a clip may be marked technically invalid, but it may
not be removed, and no clip may be added.

The clip vocabulary is the M3 capture vocabulary (see ``scenarios``), so a
Phase 1A clip stays traceable to the M3 capture it came from.
"""

from __future__ import annotations

from pathlib import Path

from . import scenarios as scen
from .hashing import manifest_digest, sha256_file
from .mediaprobe import (ProbeUnavailable, probe, stable_diagnostic,
                         tool_version, unmeasured)

MANIFEST_KIND = "phase1a-source-manifest"
MANIFEST_VERSION = 1

VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")

#: The two M3 captures the Product Owner actually scored at the M3 visual gate
#: (``docs/milestones/m3-evaluation.md``). The rest of the eleven-capture M3
#: matrix carries no score; that record is explicit that no inference was drawn
#: from their absence.
M3_SCORED_STEMS = ("horizontal-no-glasses", "lens-no-glasses")

ROLE_SCORED = "SCORED_IN_M3_PO_GATE"
ROLE_MATRIX = "IN_M3_CAPTURE_MATRIX_NOT_SCORED"
ROLE_OUTSIDE = "NOT_PART_OF_M3_EVALUATION"


def m3_role(stem):
    """Classify a capture stem's role in the recorded M3 evaluation."""
    if stem in M3_SCORED_STEMS:
        return ROLE_SCORED
    if stem in scen.M3_CLIP_STEMS or stem in scen.M3_STILL_STEMS:
        return ROLE_MATRIX
    return ROLE_OUTSIDE


def clip_id(index):
    """Stable, immutable clip identifier."""
    return f"P1A-{index:02d}"


def discover(inputs_root):
    """Find candidate video sources under ``inputs_root``.

    Returns ``(candidates, skipped)``. M3 clip stems are listed first and in
    their canonical M3 order so the plan is deterministic; any other video in
    the directory follows, sorted by name. Stills are reported as skipped with
    a reason: Maxine Eye Contact is a temporal video model, so a still is not a
    usable held-out input for it.
    """
    root = Path(inputs_root)
    if not root.is_dir():
        raise FileNotFoundError(f"inputs directory not found: {root}")

    videos = sorted(p for p in root.iterdir()
                    if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES)
    by_stem = {}
    for path in videos:
        by_stem.setdefault(path.stem, []).append(path)

    candidates, skipped = [], []
    ordered_stems = list(scen.M3_CLIP_STEMS)
    ordered_stems += [s for s in sorted(by_stem) if s not in ordered_stems]

    for stem in ordered_stems:
        matches = by_stem.get(stem) or []
        if not matches:
            continue
        if len(matches) > 1:
            skipped.append({"stem": stem, "reason": "AMBIGUOUS: more than one "
                            "video shares this stem",
                            "paths": [str(p) for p in matches]})
            continue
        candidates.append({"stem": stem, "path": matches[0],
                           "scenarios": list(scen.scenarios_for_stem(stem)),
                           "m3_role": m3_role(stem)})

    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg"):
            skipped.append({
                "stem": path.stem, "reason": "STILL IMAGE: Maxine Eye Contact "
                "is a temporal video model; a still is not a usable held-out "
                "input", "paths": [str(path)]})
    return candidates, skipped


def build_plan(candidates, inputs_root):
    """Turn discovery candidates into an editable clip plan."""
    root = Path(inputs_root)
    return {
        "manifest_kind": "phase1a-source-plan",
        "inputs_root": str(root).replace("\\", "/"),
        "clips": [
            {
                "clip_id": clip_id(i),
                "source_name": c["path"].name,
                "m3_capture_stem": c["stem"],
                "m3_evaluation_role": c["m3_role"],
                "scenarios": c["scenarios"],
                "trim": None,
                "notes": "",
            }
            for i, c in enumerate(candidates, start=1)
        ],
    }


def _validate_trim(trim, clip_ref):
    if trim is None:
        return None
    if not isinstance(trim, dict):
        raise ValueError(f"{clip_ref}: trim must be an object or null")
    start = trim.get("start_s", 0.0)
    duration = trim.get("duration_s")
    try:
        start = float(start)
    except (TypeError, ValueError):
        raise ValueError(f"{clip_ref}: trim.start_s must be a number") from None
    if duration is None:
        raise ValueError(f"{clip_ref}: trim.duration_s is required")
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        raise ValueError(f"{clip_ref}: trim.duration_s must be a number") from None
    if start < 0 or duration <= 0:
        raise ValueError(f"{clip_ref}: trim must have start_s >= 0 and "
                         "duration_s > 0")
    return {"start_s": round(start, 3), "duration_s": round(duration, 3)}


def freeze(plan, frozen_at_utc, provenance, strict_probe=False):
    """Build the frozen source manifest from a plan.

    Every clip is hashed and probed. ``strict_probe`` turns an ffprobe failure
    into an error; otherwise the probe fields record NOT MEASURED, which is the
    honest outcome when the measurement is unavailable.
    """
    root = Path(plan["inputs_root"])
    entries, seen_ids, seen_paths = [], set(), set()

    for raw in plan.get("clips") or []:
        cid = raw.get("clip_id")
        if not cid:
            raise ValueError("every clip needs a clip_id")
        if cid in seen_ids:
            raise ValueError(f"duplicate clip_id: {cid}")
        seen_ids.add(cid)

        name = raw.get("source_name")
        if not name:
            raise ValueError(f"{cid}: source_name is required")
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"{cid}: source not found: {path}")
        resolved = str(path.resolve())
        if resolved in seen_paths:
            raise ValueError(f"{cid}: source already used by another clip: {name}")
        seen_paths.add(resolved)

        bad = [s for s in (raw.get("scenarios") or []) if s not in scen.SCENARIO_IDS]
        if bad:
            raise ValueError(f"{cid}: unknown scenario tag(s): {', '.join(bad)}")

        try:
            media = probe(path)
            media["probe_status"] = "VERIFIED"
        except ProbeUnavailable:
            if strict_probe:
                raise
            media = unmeasured()
            media["probe_note"] = "ffprobe not available in this environment"
        except RuntimeError as exc:
            if strict_probe:
                raise
            media = unmeasured()
            media["probe_note"] = stable_diagnostic(str(exc))

        entries.append({
            "clip_id": cid,
            "source_name": name,
            "source_path": str(path).replace("\\", "/"),
            "source_sha256": sha256_file(path),
            "source_bytes": path.stat().st_size,
            "m3_capture_stem": raw.get("m3_capture_stem"),
            "m3_evaluation_role": raw.get("m3_evaluation_role")
                or m3_role(raw.get("m3_capture_stem") or ""),
            "scenarios": list(raw.get("scenarios") or []),
            "media": media,
            "trim": _validate_trim(raw.get("trim"), cid),
            "preprocessing": [],
            "derived": None,
            "exclusion": None,
            "notes": raw.get("notes") or "",
        })

    manifest = {
        "manifest_kind": MANIFEST_KIND,
        "manifest_version": MANIFEST_VERSION,
        "notice": "RESEARCH/EVALUATION ONLY - NOT AUTHORIZED FOR GAZEFIX PRODUCTION",
        "frozen_at_utc": frozen_at_utc,
        "inputs_root": str(root).replace("\\", "/"),
        "repository": provenance,
        "tools": {"ffprobe": tool_version("ffprobe"), "ffmpeg": tool_version("ffmpeg")},
        "clip_count": len(entries),
        "clips": entries,
        "coverage": scen.coverage(entries),
        "uncovered_scenarios": list(scen.uncovered(entries)),
    }
    manifest["manifest_sha256"] = manifest_digest(manifest)
    return manifest


def active_clips(manifest):
    """Clips that are still valid inputs (excluded clips are retained, not run)."""
    return [c for c in manifest["clips"] if not c.get("exclusion")]


def verify_unchanged(manifest, allow_missing=False):
    """Re-hash every source and report drift against the frozen manifest."""
    rows = []
    for clip in manifest["clips"]:
        path = Path(clip["source_path"])
        if not path.is_file():
            rows.append({"clip_id": clip["clip_id"], "status": "MISSING",
                         "expected": clip["source_sha256"], "actual": None})
            continue
        actual = sha256_file(path)
        rows.append({"clip_id": clip["clip_id"],
                     "status": "OK" if actual == clip["source_sha256"] else "CHANGED",
                     "expected": clip["source_sha256"], "actual": actual})
    if not allow_missing:
        return rows
    return [r for r in rows if r["status"] != "MISSING"]


def diff_membership(frozen, candidate):
    """Compare clip membership between a frozen manifest and a later one.

    Returns ``{added, removed, rehashed}``. Any non-empty field is an
    evaluation-integrity failure: the held-out set is frozen before the first
    inference and cheap-picking it afterwards is exactly what the protocol
    forbids.
    """
    before = {c["clip_id"]: c["source_sha256"] for c in frozen["clips"]}
    after = {c["clip_id"]: c["source_sha256"] for c in candidate["clips"]}
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "rehashed": sorted(k for k in set(before) & set(after)
                           if before[k] != after[k]),
    }


def exclude(manifest, clip_id_, reason):
    """Mark a clip technically invalid, retaining it in the manifest.

    The protocol forbids removing a clip after the freeze. A technically
    invalid clip stays in the manifest carrying its exclusion reason so the
    record shows what was dropped and why.
    """
    for clip in manifest["clips"]:
        if clip["clip_id"] == clip_id_:
            if not reason:
                raise ValueError("an exclusion needs a reason")
            clip["exclusion"] = {"reason": reason}
            manifest["coverage"] = scen.coverage(active_clips(manifest))
            manifest["uncovered_scenarios"] = list(scen.uncovered(active_clips(manifest)))
            manifest.pop("manifest_sha256", None)
            manifest["manifest_sha256"] = manifest_digest(manifest)
            return manifest
    raise KeyError(f"unknown clip_id: {clip_id_}")
