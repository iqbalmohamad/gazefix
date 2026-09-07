"""Media inspection through ``ffprobe``.

The manifest records duration, resolution, FPS and codec for every source and
every derived input. Those facts come from ``ffprobe`` rather than from a
Python decoder so that the recorded values describe the container the API will
actually receive.

``ffprobe`` absence is a reported, non-fatal condition: the freeze step then
records ``NOT MEASURED`` for the probe fields instead of guessing them, which
is what ``docs/qa-policy.md`` requires of an unavailable measurement.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from fractions import Fraction

NOT_MEASURED = "NOT MEASURED"

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"
TIMEOUT_S = 120


class ProbeUnavailable(RuntimeError):
    """Raised when ``ffprobe`` is not installed."""


def tool_path(name):
    """Return the resolved path of an external tool, or ``None``."""
    return shutil.which(name)


def tool_version(name):
    """Return the first line of ``<tool> -version``, or ``None``."""
    path = tool_path(name)
    if path is None:
        return None
    try:
        out = subprocess.run([path, "-version"], capture_output=True, text=True,
                             timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout or out.stderr or "").splitlines()[0].strip() or None


#: ffmpeg embeds a context pointer in its diagnostics, e.g.
#: "[mov,mp4 @ 0x55ddee6536c0] moov atom not found". The address changes on
#: every run (ASLR), which would make a manifest that records the message
#: non-reproducible and destroy the value of its SHA-256 as a freeze token.
_POINTER = re.compile(r"@ 0x[0-9a-fA-F]+")


def stable_diagnostic(text, limit=400):
    """Normalise a tool diagnostic so it is byte-identical across runs."""
    text = _POINTER.sub("@ 0x<addr>", (text or "").strip())
    return " ".join(text.split())[:limit]


def _rate(value):
    """Parse an ffprobe rational such as ``30000/1001`` into a float."""
    if not value or value in ("0/0", "N/A"):
        return None
    try:
        rate = float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def probe(path):
    """Return normalised media facts for ``path``.

    Raises ``ProbeUnavailable`` when ffprobe is missing and ``RuntimeError``
    when ffprobe fails or the file carries no video stream.
    """
    exe = tool_path(FFPROBE)
    if exe is None:
        raise ProbeUnavailable("ffprobe not found on PATH")
    argv = [exe, "-hide_banner", "-loglevel", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path)]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True,
                                   timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"ffprobe failed on {path}: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe exit {completed.returncode} on {path}: "
                           f"{stable_diagnostic(completed.stderr)}")
    try:
        payload = json.loads(completed.stdout)
    except ValueError as exc:
        raise RuntimeError(f"ffprobe returned non-JSON for {path}") from exc
    return summarise(payload)


def summarise(payload):
    """Normalise a raw ``ffprobe -show_format -show_streams`` document."""
    streams = payload.get("streams") or []
    fmt = payload.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError("no video stream present")
    audio = [s for s in streams if s.get("codec_type") == "audio"]

    duration = video.get("duration") or fmt.get("duration")
    try:
        duration_s = round(float(duration), 3) if duration not in (None, "N/A") else None
    except (TypeError, ValueError):
        duration_s = None

    frames = video.get("nb_frames")
    try:
        frame_count = int(frames) if frames not in (None, "N/A") else None
    except (TypeError, ValueError):
        frame_count = None

    return {
        "container": (fmt.get("format_name") or NOT_MEASURED),
        "codec": video.get("codec_name") or NOT_MEASURED,
        "profile": video.get("profile"),
        "pix_fmt": video.get("pix_fmt"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps_avg": _rate(video.get("avg_frame_rate")),
        "fps_r": _rate(video.get("r_frame_rate")),
        "duration_s": duration_s,
        "frame_count": frame_count,
        "audio_streams": len(audio),
        "audio_codecs": [s.get("codec_name") for s in audio],
    }


def unmeasured():
    """Probe fields for a source that could not be measured."""
    return {
        "container": NOT_MEASURED, "codec": NOT_MEASURED, "profile": None,
        "pix_fmt": None, "width": None, "height": None, "fps_avg": None,
        "fps_r": None, "duration_s": None, "frame_count": None,
        "audio_streams": None, "audio_codecs": None,
        "probe_status": NOT_MEASURED,
    }
