"""Blind comparison package for the Product Owner visual gate (S12, S13).

The package presents each clip's conditions under neutral labels A/B/C, with
the answer key written to a separate directory that is not part of what the
Product Owner opens. Presentation files are copied verbatim: no re-encode, no
overlay, no watermark, and in particular nothing drawn near the eye region.

The scorer-facing viewer names nothing but clip ids and labels. Every string it
contains is checked for method leakage before the package is considered valid.
"""

from __future__ import annotations

import html
import shutil
from pathlib import Path

from . import blinding, rubric
from .hashing import manifest_digest, sha256_file, write_json

class WeakBlindError(RuntimeError):
    """Raised when a seed would present a condition under a constant label."""


PRESENTATION_DIRNAME = "presentation"
KEY_DIRNAME = "answer-key"
NOTICE = "RESEARCH/EVALUATION ONLY - NOT AUTHORIZED FOR GAZEFIX PRODUCTION"


def plan(seed, clips):
    """Decide the label assignment for every clip.

    ``clips`` is an iterable of ``{clip_id, conditions: {CONDITION: path}}``.
    A condition whose path is missing is dropped for that clip, and the drop is
    reported so the package never silently presents fewer conditions.
    """
    rows, dropped = [], []
    for clip in clips:
        available, missing = {}, []
        for condition in blinding.CONDITIONS:
            path = (clip.get("conditions") or {}).get(condition)
            if path and Path(path).is_file():
                available[condition] = Path(path)
            else:
                missing.append(condition)
        if missing:
            dropped.append({"clip_id": clip["clip_id"], "missing": missing})
        if not available:
            continue
        mapping = blinding.assign(seed, clip["clip_id"], tuple(available))
        rows.append({"clip_id": clip["clip_id"], "labels": mapping,
                     "paths": available})
    return rows, dropped


def build(root, seed, clips, copier=None):
    """Write the blind package and the separate answer key.

    Returns ``(package_manifest, answer_key)``. The manifest is scorer-facing
    and contains no method names; the answer key contains the mapping and is
    written outside the presentation directory.
    """
    root = Path(root)
    presentation = root / PRESENTATION_DIRNAME
    key_dir = root / KEY_DIRNAME
    presentation.mkdir(parents=True, exist_ok=True)
    key_dir.mkdir(parents=True, exist_ok=True)
    copier = copier or shutil.copyfile

    rows, dropped = plan(seed, clips)
    pinned = blinding.pinned_conditions([r["labels"] for r in rows])
    if pinned:
        raise WeakBlindError(
            f"seed {seed!r} places {', '.join(pinned)} under the same label in "
            "every clip, which is a weak blind. Choose a different seed and "
            "record it. Doing so before any output is scored biases nothing.")

    presented, key_rows = [], []

    for row in rows:
        clip_dir = presentation / row["clip_id"]
        clip_dir.mkdir(parents=True, exist_ok=True)
        entries = []
        for label, condition in sorted(row["labels"].items()):
            source = row["paths"][condition]
            # The filename carries the neutral label only; the condition never
            # appears in any scorer-visible path component.
            destination = clip_dir / f"{row['clip_id']}_{label}{source.suffix}"
            copier(str(source), str(destination))
            digest = sha256_file(destination)
            entries.append({"label": label,
                            "file": str(destination.relative_to(presentation)
                                        ).replace("\\", "/"),
                            "sha256": digest})
            key_rows.append({"clip_id": row["clip_id"], "label": label,
                             "condition": condition,
                             "source_path": str(source).replace("\\", "/"),
                             "presented_file": str(
                                 destination.relative_to(presentation)
                             ).replace("\\", "/"),
                             "sha256": digest})
        presented.append({"clip_id": row["clip_id"], "entries": entries})

    manifest = {
        "manifest_kind": "phase1a-blind-package",
        "notice": NOTICE,
        "label_vocabulary": list(blinding.LABELS),
        "clip_count": len(presented),
        "clips": presented,
        "instructions": "Score every labelled output on its own terms. The "
                        "labels carry no meaning and their order differs "
                        "between clips.",
    }
    key = {
        "manifest_kind": "phase1a-answer-key",
        "notice": NOTICE,
        "warning": "DO NOT OPEN BEFORE SCORING IS COMPLETE.",
        "seed": seed,
        "assignments": key_rows,
        "clips_missing_conditions": dropped,
    }
    # The digest covers the document without its own digest field, then the
    # field is added and the complete document written, so the file on disk and
    # the returned object agree.
    manifest["manifest_sha256"] = manifest_digest(manifest)
    key["manifest_sha256"] = manifest_digest(key)
    write_json(presentation / "package.json", manifest)
    write_json(key_dir / "answer-key.json", key)
    (presentation / "scores.csv").write_text(scoring_csv(presented),
                                             encoding="utf-8", newline="\n")
    (presentation / "index.html").write_text(viewer_html(presented),
                                             encoding="utf-8", newline="\n")
    return manifest, key


def scoring_csv(presented):
    """Blank scoring sheet, one row per clip per label."""
    lines = [",".join(rubric.COLUMNS)]
    for clip in presented:
        for entry in clip["entries"]:
            row = rubric.blank_row(clip["clip_id"], entry["label"])
            lines.append(",".join(str(row[c]) for c in rubric.COLUMNS))
    return "\n".join(lines) + "\n"


def viewer_html(presented):
    """A minimal offline viewer. Names no method and labels nothing over video."""
    parts = [
        "<!doctype html><meta charset=\"utf-8\">",
        "<title>GazeFix visual gate</title>",
        "<style>body{font:17px system-ui;max-width:1200px;margin:32px auto;"
        "background:#eee;color:#222}section{background:#fff;padding:20px;"
        "margin:20px 0}video{max-width:100%;background:#000}"
        ".row{display:flex;gap:16px;flex-wrap:wrap}.cell{flex:1 1 320px}"
        "h3{margin:8px 0 4px}</style>",
        "<h1>GazeFix visual gate</h1>",
        f"<p>{html.escape(NOTICE)}</p>",
        "<p>Each clip below is shown under neutral labels. The labels carry no "
        "meaning and their order differs between clips. Score each labelled "
        "output on its own terms in <a href=\"scores.csv\">scores.csv</a>.</p>",
    ]
    for clip in presented:
        parts.append(f"<section><h2>{html.escape(clip['clip_id'])}</h2><div class=\"row\">")
        for entry in clip["entries"]:
            src = html.escape(entry["file"], quote=True)
            parts.append(
                f"<div class=\"cell\"><h3>{html.escape(entry['label'])}</h3>"
                f"<video controls preload=\"metadata\" src=\"{src}\"></video></div>")
        parts.append("</div></section>")
    return "".join(parts) + "\n"


def audit_presentation(presentation_root):
    """Fail the package if any scorer-visible text names a method.

    Checks file and directory names as well as the text of every readable
    scorer-facing file.
    """
    root = Path(presentation_root)
    findings = []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        leaked = blinding.leaks(relative)
        if leaked:
            findings.append({"where": relative, "kind": "path", "tokens": leaked})
        if path.is_file() and path.suffix.lower() in (".json", ".csv", ".html", ".txt", ".md"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            leaked = blinding.leaks(text)
            if leaked:
                findings.append({"where": relative, "kind": "content",
                                 "tokens": leaked})
    return findings
