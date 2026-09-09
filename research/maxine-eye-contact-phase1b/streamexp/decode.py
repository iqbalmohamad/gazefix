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
    """Ask an external decoder what is actually decodable in ``path``.

    Never the custom MP4 parser: this is the independent check the parser is
    measured against, so it must share none of its assumptions.

    The state model, in order. It exists to separate two things that look alike
    in a summary but mean opposite things — a decoder that examined the bytes
    and found no frame, and a decoder that never got to look.

    1. **No decoder available** — nothing was examined. ``AMBIGUOUS``.
    2. **Zero bytes** — determinately zero frames. ``EMPTY``.
    3. **The container probe could not execute** (crash, timeout). ``AMBIGUOUS``.
    4. **The container probe ran and rejected the input**, or found no video
       stream — malformed or unrecognised media. ``AMBIGUOUS``, because
       "I cannot read this" is not "there is nothing here".
    5. **Container recognised with a declared video stream.** Now a frame count
       is sought from three sources in order of cost: ``-count_frames``, an
       explicit ``-show_frames`` enumeration, then ffmpeg's own decode stats.
       The first that *completes* is authoritative — including when it
       completes with zero. A truncated MP4 carrying only ``ftyp`` and ``moov``
       lands here: ffprobe parses the container, declares the H.264 stream,
       warns that the file is partial, enumerates to EOF and yields no frames.
       That is ``EMPTY``, and it is a real observation rather than a failure.
    6. **No source completed a count.** ``AMBIGUOUS``.

    Note that step 5's enumeration is what makes step 4 safe to be strict:
    a recognised container gets a determinate answer from a run that finished,
    not from the absence of an error message.
    """
    size = path.stat().st_size if path.is_file() else 0
    ffprobe, ffmpeg = tool("ffprobe"), tool("ffmpeg")
    if ffprobe is None and ffmpeg is None:
        return MediaExamination(
            "AMBIGUOUS", False, None, size,
            "neither ffprobe nor ffmpeg is on PATH; no independent examination was made",
        )
    if size == 0:
        return MediaExamination("EMPTY", False, 0, 0, "the file holds no bytes")

    notes: list[str] = []
    stream = _probe_video_stream(ffprobe, path, notes) if ffprobe else None
    if stream is _PROBE_FAILED:
        return MediaExamination("AMBIGUOUS", False, None, size, "; ".join(notes))
    if stream is None:
        # The probe ran and did not find media it could describe.
        return MediaExamination("AMBIGUOUS", False, None, size, "; ".join(notes))

    for source in (_count_via_count_frames, _count_via_show_frames, _count_via_ffmpeg):
        frames = source(ffprobe, ffmpeg, path, notes)
        if frames is None:
            continue
        detail = "; ".join(notes)
        if frames >= 1:
            return MediaExamination("VERIFIED", True, frames, size, detail)
        return MediaExamination("EMPTY", True, 0, size, detail)

    return MediaExamination("AMBIGUOUS", True, None, size, "; ".join(notes))


_PROBE_FAILED = object()


def _run(command: list[str], timeout: int = 300):
    """Execute a decoder command. ``None`` means it could not be executed at all."""
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None


def _probe_video_stream(ffprobe: str, path: Path, notes: list[str]):
    """Describe the first video stream, or say why none could be described."""
    result = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height", "-of", "json", str(path),
    ])
    if result is None:
        notes.append("ffprobe could not be executed")
        return _PROBE_FAILED
    if result.returncode != 0:
        notes.append(
            "ffprobe did not recognise the input: "
            + ((result.stderr or "").strip().splitlines()[-1][:180] if result.stderr
               else f"exit {result.returncode}")
        )
        return None
    try:
        streams = json.loads(result.stdout).get("streams", [])
    except ValueError:
        notes.append("ffprobe returned unparsable JSON")
        return _PROBE_FAILED
    if not streams:
        notes.append("ffprobe recognised the input but declared no video stream")
        return None
    stream = streams[0]
    notes.append(
        f"container recognised: {stream.get('codec_name', '?')} "
        f"{stream.get('width', '?')}x{stream.get('height', '?')}"
    )
    return stream


def _count_via_count_frames(ffprobe: str | None, _ffmpeg, path: Path,
                            notes: list[str]) -> int | None:
    """ffprobe's own counter. Cheap, and absent on a truncated file."""
    if ffprobe is None:
        return None
    result = _run([
        ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames", "-of", "json", str(path),
    ])
    if result is None or result.returncode != 0:
        return None
    try:
        streams = json.loads(result.stdout).get("streams", [])
        raw = streams[0].get("nb_read_frames") if streams else None
    except (ValueError, IndexError, AttributeError):
        return None
    if raw in (None, "N/A", ""):
        notes.append("ffprobe -count_frames reported no count")
        return None
    try:
        frames = int(raw)
    except (TypeError, ValueError):
        return None
    notes.append(f"ffprobe -count_frames: {frames}")
    return frames


def _count_via_show_frames(ffprobe: str | None, _ffmpeg, path: Path,
                           notes: list[str]) -> int | None:
    """Enumerate frames explicitly.

    This is what makes a metadata-only prefix determinate. ffprobe walks the
    stream to EOF and prints one row per frame; a clean exit with no rows is a
    completed enumeration that found nothing, not a failure to look.
    """
    if ffprobe is None:
        return None
    result = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "frame=media_type", "-of", "csv=p=0", str(path),
    ])
    if result is None or result.returncode != 0:
        notes.append("ffprobe frame enumeration did not complete")
        return None
    frames = sum(1 for line in (result.stdout or "").splitlines() if line.strip())
    notes.append(f"ffprobe enumerated {frames} frames to EOF")
    return frames


def _count_via_ffmpeg(_ffprobe, ffmpeg: str | None, path: Path,
                      notes: list[str]) -> int | None:
    if ffmpeg is None:
        return None
    counted = _frames_from_ffmpeg_stats(ffmpeg, path)
    if counted is None:
        notes.append("ffmpeg produced no parsable frame count")
        return None
    notes.append(f"ffmpeg decoded {counted} frames")
    return counted


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
