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


@dataclass(frozen=True)
class MediaExamination:
    """What an external decoder made of a byte range.

    The distinction between ``EMPTY`` and ``AMBIGUOUS`` is the whole point of
    this type. ``EMPTY`` means a decoder ran, looked, and found no complete
    frame — a determinate finding. ``AMBIGUOUS`` means the examination itself
    did not happen or could not be trusted. Only the first may be read as
    evidence that no usable output existed; collapsing the two would turn a
    missing ffprobe into a Stage A ``NO``.
    """

    status: str
    """``VERIFIED`` (>=1 frame) / ``EMPTY`` (0 frames, determinate) / ``AMBIGUOUS``."""
    stream_detected: bool
    frames_decoded: int | None
    bytes_examined: int
    detail: str

    @property
    def determinate(self) -> bool:
        return self.status in ("VERIFIED", "EMPTY")


def examine(path: Path) -> MediaExamination:
    """Ask ffprobe and ffmpeg what is actually decodable in ``path``.

    Never the custom MP4 parser: this is the independent check the parser is
    measured against, so it must share none of its assumptions.
    """
    size = path.stat().st_size if path.is_file() else 0
    ffprobe, ffmpeg = tool("ffprobe"), tool("ffmpeg")
    if ffprobe is None and ffmpeg is None:
        return MediaExamination(
            "AMBIGUOUS", False, None, size,
            "neither ffprobe nor ffmpeg is on PATH; no independent examination was made",
        )
    if size == 0:
        return MediaExamination("EMPTY", False, 0, 0, "the file is empty")

    stream_detected = False
    frames: int | None = None
    notes: list[str] = []

    if ffprobe is not None:
        try:
            result = subprocess.run(
                [
                    ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
                    "-show_entries", "stream=codec_name,width,height,nb_read_frames",
                    "-of", "json", str(path),
                ],
                capture_output=True, text=True, timeout=300,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            notes.append(f"ffprobe could not run: {type(exc).__name__}: {exc}")
        else:
            if result.returncode == 0:
                try:
                    streams = json.loads(result.stdout).get("streams", [])
                except ValueError:
                    streams = []
                if streams:
                    stream_detected = True
                    raw = streams[0].get("nb_read_frames")
                    if raw not in (None, "N/A"):
                        try:
                            frames = int(raw)
                        except (TypeError, ValueError):
                            pass
                    notes.append(
                        f"ffprobe: {streams[0].get('codec_name', '?')} "
                        f"{streams[0].get('width', '?')}x{streams[0].get('height', '?')}, "
                        f"nb_read_frames={raw}"
                    )
                else:
                    notes.append("ffprobe: no video stream found")
            else:
                notes.append(
                    "ffprobe rejected the input: "
                    + ((result.stderr or "").strip()[:200] or f"exit {result.returncode}")
                )

    if frames is None and ffmpeg is not None:
        counted = _frames_from_ffmpeg_stats(ffmpeg, path)
        if counted is None:
            notes.append("ffmpeg produced no parsable frame count")
        else:
            frames = counted
            notes.append(f"ffmpeg decoded {counted} frames")

    detail = "; ".join(notes) or "no decoder output"
    if frames is None:
        # A decoder ran and rejected the bytes outright: that is a determinate
        # "nothing decodable here", not a tool failure.
        if not stream_detected and any(
            "rejected the input" in n or "no video stream" in n for n in notes
        ):
            return MediaExamination("EMPTY", False, 0, size, detail)
        return MediaExamination("AMBIGUOUS", stream_detected, None, size, detail)
    if frames >= 1:
        return MediaExamination("VERIFIED", True, frames, size, detail)
    return MediaExamination("EMPTY", stream_detected, 0, size, detail)


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
