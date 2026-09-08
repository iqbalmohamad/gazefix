"""Corroborate "usable" with a real decoder.

:mod:`streamexp.progressive` establishes that every byte of a coded frame has
arrived. That is a container fact, not a decoder fact. To avoid claiming more
than was measured, the harness writes the received prefix at the moment it
called the first frame usable, and asks ``ffprobe``/``ffmpeg`` to decode it.

A successful decode of that truncated prefix is direct evidence that corrected
pictures existed on the client at that instant. A failure is reported as a
failure — it is not explained away, because it would mean the container-level
criterion is optimistic and every age in the run would need re-reading.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DecodeCheck:
    """Result of decoding a truncated prefix of the corrected output."""

    status: str
    """``VERIFIED`` / ``FAILED`` / ``NOT MEASURED``."""
    frames_decoded: int | None
    detail: str
    prefix_bytes: int


def tool(name: str) -> str | None:
    return shutil.which(name)


def decode_prefix(prefix: bytes, workdir: Path, label: str) -> DecodeCheck:
    """Decode ``prefix`` as an MP4 and report how many frames came out."""
    ffmpeg = tool("ffmpeg")
    if ffmpeg is None:
        return DecodeCheck("NOT MEASURED", None, "ffmpeg not on PATH", len(prefix))
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / f"{label}.mp4"
    path.write_bytes(prefix)
    try:
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return DecodeCheck("FAILED", None, f"{type(exc).__name__}: {exc}", len(prefix))

    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:400] or f"exit {result.returncode}"
        return DecodeCheck("FAILED", None, detail, len(prefix))

    frames = count_frames(path)
    if frames is None:
        frames = _frames_from_ffmpeg_stats(ffmpeg, path)
    if frames == 0:
        return DecodeCheck("FAILED", 0, "decoder produced no frames", len(prefix))
    detail = "decoded without error"
    if frames is None:
        detail += "; frame count unavailable (no ffprobe and no parsable stats)"
    return DecodeCheck("VERIFIED", frames, detail, len(prefix))


def _frames_from_ffmpeg_stats(ffmpeg: str, path: Path) -> int | None:
    """Count frames from ffmpeg's own progress line, when ffprobe is absent."""
    try:
        result = subprocess.run(
            [ffmpeg, "-v", "quiet", "-stats", "-i", str(path), "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    match = None
    for token in re.finditer(r"frame=\s*(\d+)", result.stderr or ""):
        match = token
    return int(match.group(1)) if match else None


def count_frames(path: Path) -> int | None:
    """Number of decodable video frames in ``path``, or ``None`` if unknown."""
    ffprobe = tool("ffprobe")
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_frames", "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        streams = json.loads(result.stdout).get("streams", [])
        return int(streams[0]["nb_read_frames"]) if streams else None
    except (ValueError, KeyError, IndexError, TypeError):
        return None
