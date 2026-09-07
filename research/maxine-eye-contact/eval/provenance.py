"""Repository provenance for evaluation manifests.

Mirrors the intent of the frozen harness's ``repository_provenance`` without
importing product code: an evaluation manifest must record which checkout
produced it and whether that checkout was clean.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

#: The frozen M3 geometric baseline this spike compares against.
GEOMETRIC_BASELINE_COMMIT = "f3831b54728a4747c38c064351ec9f48419a2efb"
GEOMETRIC_BASELINE_REF = "m3-geometric-baseline"

#: The governance checkpoint that authorised Phase 1A.
GOVERNANCE_CHECKPOINT_COMMIT = "95678777642d29912d0806a81f02dc4b11ea884b"
GOVERNANCE_CHECKPOINT_REF = "codex/maxine-phase1a-governance"

TIMEOUT_S = 15


def repository_root():
    """Return the repository root containing this package."""
    return Path(__file__).resolve().parents[3]


def _git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                   stderr=subprocess.DEVNULL,
                                   timeout=TIMEOUT_S).strip()


def repository_provenance(root=None):
    """Record the local revision, cleanliness and the frozen references."""
    root = Path(root) if root is not None else repository_root()
    record = {
        "geometric_baseline_ref": GEOMETRIC_BASELINE_REF,
        "geometric_baseline_commit": GEOMETRIC_BASELINE_COMMIT,
        "governance_checkpoint_ref": GOVERNANCE_CHECKPOINT_REF,
        "governance_checkpoint_commit": GOVERNANCE_CHECKPOINT_COMMIT,
    }
    try:
        record["head"] = _git(root, "rev-parse", "HEAD")
        record["branch"] = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        record["tracked_changes"] = bool(
            _git(root, "status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        record["head"] = None
        record["branch"] = None
        record["tracked_changes"] = None
    return record


def verify_frozen_refs(root=None, expected=None):
    """Check the frozen references still resolve to their recorded SHAs.

    Returns a list of ``{ref, expected, actual, ok}`` rows. A ref that cannot be
    resolved reports ``actual`` ``None`` and ``ok`` ``False`` rather than
    raising, so a caller can report the inconsistency.
    """
    root = Path(root) if root is not None else repository_root()
    expected = expected if expected is not None else {
        GEOMETRIC_BASELINE_REF: GEOMETRIC_BASELINE_COMMIT,
        GOVERNANCE_CHECKPOINT_REF: GOVERNANCE_CHECKPOINT_COMMIT,
    }
    rows = []
    for ref, sha in sorted(expected.items()):
        actual = None
        for candidate in (f"origin/{ref}", ref):
            try:
                actual = _git(root, "rev-parse", "--verify", "--quiet", candidate)
                break
            except (OSError, subprocess.SubprocessError):
                continue
        rows.append({"ref": ref, "expected": sha, "actual": actual,
                     "ok": actual == sha})
    return rows
