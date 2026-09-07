"""Deterministic source preparation (S8).

Preprocessing is kept minimal and, crucially, **symmetric**: each clip is
prepared exactly once and the single derived file is the input for *both* the
Maxine condition and the frozen geometric condition. That removes any
possibility of preparing the source more favourably for one method than the
other.

Only three transformations are permitted, all deterministic and all driven by
NVIDIA's stated input requirements rather than by how the output looks:

* trim to a recorded window,
* remux/transcode to MP4 + H.264 with a constant frame rate,
* drop audio.

Nothing here sharpens, denoises, retouches, recolours, crops per subject or
alters gaze. There is no quality knob that could be turned per clip.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .hashing import sha256_file
from .mediaprobe import FFMPEG, TIMEOUT_S, tool_path, tool_version

#: Constant, identical for every clip. H.264 in MP4 is what NVIDIA's client
#: requires; CFR is required because NVIDIA states variable frame rate is not
#: supported; audio is dropped because it plays no part in a visual gate.
#: ``-movflags +faststart`` is applied to every clip so that all clips share one
#: streamability state and therefore one frozen client invocation mode.
ENCODE_ARGS = (
    "-map", "0:v:0",
    "-an",
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-vsync", "cfr",
    "-movflags", "+faststart",
)

PROFILE_ID = "p1a-mp4-h264-cfr-faststart-crf18"


class FfmpegUnavailable(RuntimeError):
    """Raised when ffmpeg is not installed."""


def build_command(source, destination, trim=None, fps=None, ffmpeg=None):
    """Build the deterministic ffmpeg command for one clip.

    ``-ss``/``-t`` are placed after ``-i`` so the trim is frame-accurate and
    reproducible rather than seek-approximate.
    """
    exe = ffmpeg or tool_path(FFMPEG)
    if exe is None:
        raise FfmpegUnavailable("ffmpeg not found on PATH")
    command = [str(exe), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-i", str(source)]
    if trim:
        command += ["-ss", f"{float(trim['start_s']):.3f}",
                    "-t", f"{float(trim['duration_s']):.3f}"]
    command += list(ENCODE_ARGS)
    if fps:
        command += ["-r", str(fps)]
    command.append(str(destination))
    return command


def derive(source, destination, trim=None, fps=None, runner=None, ffmpeg=None):
    """Produce the derived input for one clip and record its provenance."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = build_command(source, destination, trim, fps, ffmpeg)
    completed = (runner or _default_runner)(command)
    if completed["returncode"] != 0 or not destination.is_file():
        raise RuntimeError(
            f"ffmpeg failed for {source.name}: exit {completed['returncode']}: "
            f"{(completed.get('stderr') or '').strip()[:400]}")
    return {
        "profile_id": PROFILE_ID,
        "source_path": str(source).replace("\\", "/"),
        "source_sha256": sha256_file(source),
        "derived_path": str(destination).replace("\\", "/"),
        "derived_sha256": sha256_file(destination),
        "derived_bytes": destination.stat().st_size,
        "trim": trim,
        "fps_forced": fps,
        "command": [str(c) for c in command],
        "ffmpeg_version": tool_version(FFMPEG),
        "transformations": ["trim" if trim else "no trim",
                            "remux/transcode to MP4 H.264 yuv420p CFR",
                            "audio removed",
                            "faststart (moov relocated to the front)"],
        "shared_by": ["MAXINE", "GEOMETRIC"],
    }


def _default_runner(command):
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=TIMEOUT_S * 10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": None, "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}"}
    return {"returncode": completed.returncode, "stdout": completed.stdout,
            "stderr": completed.stderr}
