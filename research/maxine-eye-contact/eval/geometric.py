"""Regenerating the GEOMETRIC condition from the frozen M3 baseline (S11).

The comparison must use the frozen geometric implementation at
``m3-geometric-baseline @ f3831b5...`` with its frozen evaluation settings, and
must not improve, retune or fix it. This module only *invokes* the frozen
harness; it never imports it, patches it, or changes a parameter.

The frozen PO settings are the ones ``scripts/correction_batch.py`` uses for
its ``po`` mode, which is the batch the M3 evaluation ran: default variant C
(``layered``), ``--strength .7`` with policy, optical-axis target, and
``--max-frames 1200``. They are restated here as data, not re-derived, and the
runner refuses to accept an override for them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: The frozen M3 "po" clip settings, verbatim from scripts/correction_batch.py.
#: Changing any of these would be tuning the frozen baseline, which is forbidden.
FROZEN_CLIP_ARGS = ("--strength", ".7", "--debug", "--max-frames", "1200")

#: Harness defaults that the frozen po batch relies on, recorded so the manifest
#: states the full configuration rather than only the explicit flags.
FROZEN_DEFAULTS = {
    "variant": "layered",
    "target_yaw": 0.0,
    "target_pitch": 0.0,
    "stabilizer": 0.0,
    "gaze_smoothing": 0.0,
    "every": 1,
    "repeat": 1,
    "face_scale": 0.8,
    "debug_layers": "contour,iris,alpha,roi,warp,text",
    "effective_strength": None,
    "canvas": None,
}

#: The harness writes these per-clip outputs. ``corrected.mp4`` is the clean
#: corrected video; ``side_by_side.mp4`` carries burned-in "Original | Corrected"
#: text and ``debug.mp4`` carries drawn overlays, so neither may ever be used as
#: the GEOMETRIC condition in a blind package.
CLEAN_OUTPUT = "corrected.mp4"
UNBLINDABLE_OUTPUTS = ("side_by_side.mp4", "debug.mp4", "side_by_side", "debug")

HARNESS_MODULE = "gazefix.correction.harness"


class FrozenSettingsViolation(RuntimeError):
    """Raised when a caller tries to alter the frozen baseline configuration."""


def build_argv(source, out_root, name, unmirror=False, extra=()):
    """Build the harness argv for one clip under the frozen settings.

    ``extra`` exists only for ``--model-dir``. Anything that would change the
    correction itself is refused.
    """
    forbidden = ("--strength", "--effective-strength", "--variant", "--set",
                 "--target-yaw", "--target-pitch", "--eye-model-ratio",
                 "--stabilizer", "--gaze-smoothing", "--max-frames", "--every",
                 "--repeat", "--sweep-strength", "--sweep-target-yaw",
                 "--sweep-target-pitch", "--face-scale", "--canvas")
    for item in extra:
        head = str(item).split("=", 1)[0]
        if head in forbidden:
            raise FrozenSettingsViolation(
                f"{head} would retune the frozen geometric baseline; the M3 "
                "settings are frozen and may not be changed for this spike")
    argv = ["--video", str(source), *FROZEN_CLIP_ARGS,
            "--out", str(out_root), "--name", name, "--label", name]
    if unmirror:
        argv.append("--unmirror")
    return argv + [str(i) for i in extra]


def build_command(python_executable, source, out_root, name, unmirror=False, extra=()):
    """Build the full subprocess command invoking the frozen harness."""
    return [str(python_executable), "-m", HARNESS_MODULE,
            *build_argv(source, out_root, name, unmirror, extra)]


def run(source, out_root, name, python_executable=None, unmirror=False,
        extra=(), cwd=None, timeout=3600, runner=None):
    """Run the frozen harness for one clip and return a result record."""
    python_executable = python_executable or sys.executable
    command = build_command(python_executable, source, out_root, name, unmirror, extra)
    runner = runner or _default_runner
    completed = runner(command, cwd, timeout)
    directory = Path(out_root) / name
    return {
        "clip_name": name,
        "command": command,
        "returncode": completed["returncode"],
        "stdout_tail": (completed.get("stdout") or "")[-2000:],
        "stderr_tail": (completed.get("stderr") or "")[-2000:],
        "output_dir": str(directory).replace("\\", "/"),
        "corrected_path": str(directory / CLEAN_OUTPUT).replace("\\", "/"),
        "report_path": str(directory / "report.json").replace("\\", "/"),
        "frozen_settings": {"explicit_flags": list(FROZEN_CLIP_ARGS),
                            "harness_defaults": dict(FROZEN_DEFAULTS),
                            "unmirror": bool(unmirror)},
    }


def _default_runner(command, cwd, timeout):
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True,
                                   text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": None, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}
    return {"returncode": completed.returncode, "stdout": completed.stdout,
            "stderr": completed.stderr}


def baseline_matches_source(report, expected_sha256):
    """Confirm a harness report was produced from the expected source bytes.

    The frozen harness records the source SHA-256 in ``report.json``. Reusing an
    existing canonical geometric output is only valid when that hash matches
    the frozen manifest's source hash byte for byte.
    """
    recorded = ((report or {}).get("source") or {}).get("sha256")
    return bool(recorded) and recorded == expected_sha256
