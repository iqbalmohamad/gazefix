"""Stage B/C source: MP4 bytes that do not exist until the RPC is already open.

Stage A proves (or disproves) something about the *service*. Stage B proves
something about the *source*: that the media handed to ``RedirectGaze`` can be
manufactured frame by frame while the call is in flight, rather than read from a
file that was finished beforehand.

How, without inventing an interface. The RPC carries MP4 container bytes and
nothing else, so a live source has to produce a container progressively. A
plain "faststart" MP4 cannot be produced progressively — its ``moov`` describes
every sample, so it can only be written once the last sample is known.
A **fragmented** MP4 can: ``ftyp`` and an empty ``moov`` (carrying ``mvex``) go
out before any frame is encoded, then each frame becomes a ``moof``/``mdat``
pair. The result still satisfies the exact condition NVIDIA's client checks for
streaming mode — ``moov`` immediately after ``ftyp`` — so nothing about the
service contract is changed or assumed.

Two ways of producing that container are offered, because they trade different
things and the experiment needs both:

``ffmpeg`` (default)
    ``ffmpeg`` encodes *and* muxes, reading raw frames from a pipe at capture
    cadence. The container is produced by the same widely-deployed muxer that
    writes most of the world's fragmented MP4, which is what makes it the right
    choice for the Stage B question "will the NIM accept this at all?".
    Its cost is latency: measured on this hardware the muxer holds each frame
    for about two frame intervals (~73 ms at 30 FPS) waiting for the next
    packet, because it will not close a fragment until it knows the current
    sample's duration.

``inprocess``
    The encoder is driven directly through PyAV, so packet boundaries are exact
    rather than inferred from a byte pipe, and :mod:`streamexp.fmp4` writes the
    fragment immediately. Measured on the same hardware this costs about 4 ms
    per frame instead of 73 — the difference between a Stage C latency budget
    that can be attributed to the network and the NIM, and one already spent
    before a byte leaves the client.

Either way, no completed input MP4 exists at any point, and the number of frames
muxed is checked against the number captured rather than assumed.

Whether the NIM's demuxer accepts a progressively-fragmented MP4 is exactly the
unknown Stage B exists to close. This module makes the question askable; it does
not presume the answer.
"""

from __future__ import annotations

import fractions
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

from . import h264
from .clock import RealtimeSchedule
from .fmp4 import FragmentedMp4Writer
from .progressive import ProgressiveMp4Reader
from .session import SendUnit
from .timing import monotonic

READ_CHUNK = 64 * 1024


class LiveSourceError(RuntimeError):
    """Raised when the live encoder cannot be started or dies mid-run."""


@dataclass(frozen=True)
class LiveEncoderConfig:
    """Encoder settings for the live path.

    The defaults are the low-latency ones a real capture path would use:
    ``ultrafast``/``zerolatency`` so encoding never becomes the bottleneck being
    measured, and one fragment per frame so a corrected frame is never withheld
    waiting for a group of pictures to close.
    """

    width: int = 1280
    height: int = 720
    fps: int = 30
    pixel_format: str = "bgr24"
    gop: int = 30
    preset: str = "ultrafast"
    tune: str = "zerolatency"
    bitrate: str | None = None
    fragment_per_frame: bool = True
    muxer: str = "ffmpeg"
    """``ffmpeg`` for container compatibility, ``inprocess`` for latency."""

    def command(self, ffmpeg: str) -> list[str]:
        movflags = "+empty_moov+default_base_moof"
        movflags += "+frag_every_frame" if self.fragment_per_frame else "+frag_keyframe"
        args = [
            # No "-fflags +nobuffer" here. It buys nothing on a rawvideo pipe,
            # which has no demuxer buffering to skip, and measurably costs the
            # LAST frame: with it ffmpeg emits N-1 fragments for N frames, which
            # showed up as a permanent output/input frame-count mismatch and
            # would have cast doubt on an otherwise good Stage B result.
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "rawvideo",
            "-pix_fmt", self.pixel_format,
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps),
            "-i", "pipe:0",
            "-an",
            "-c:v", "libx264",
            "-preset", self.preset,
            "-tune", self.tune,
            "-g", str(self.gop),
            "-pix_fmt", "yuv420p",
        ]
        if self.bitrate:
            args += ["-b:v", self.bitrate]
        args += [
            "-f", "mp4",
            "-movflags", movflags,
            "-flush_packets", "1",
            "pipe:1",
        ]
        return args

    @property
    def frame_bytes(self) -> int:
        channels = 3 if self.pixel_format in ("bgr24", "rgb24") else 4
        return self.width * self.height * channels


@dataclass
class LiveRunStats:
    """What the live producer actually did, for the report's decomposition."""

    frames_written: int = 0
    bytes_produced: int = 0
    captured_at: dict[int, float] = field(default_factory=dict)
    muxed_at: dict[int, float] = field(default_factory=dict)
    encoder_stderr: str = ""
    frames_muxed: int = 0

    def encode_prepare_ms(self) -> list[float]:
        """Per-frame milliseconds from capture to the frame's bytes being sendable."""
        return [
            (self.muxed_at[i] - self.captured_at[i]) * 1000
            for i in sorted(self.muxed_at)
            if i in self.captured_at
        ]


class LiveFragmentedMp4Source:
    """Encode frames at capture cadence and emit the container as it is built."""

    def __init__(
        self,
        config: LiveEncoderConfig,
        frames: Iterable[bytes],
        *,
        ffmpeg: str | None = None,
    ) -> None:
        self.config = config
        self._frames = frames
        self._ffmpeg = ffmpeg or shutil.which("ffmpeg")
        if self._ffmpeg is None:
            raise LiveSourceError("ffmpeg is not on PATH; the live path cannot be built")
        self.stats = LiveRunStats()
        self._process: subprocess.Popen[bytes] | None = None

    def units(self, schedule: RealtimeSchedule, fed_at: dict[int, float],
              rpc_origin: Callable[[], float]) -> Iterator[SendUnit]:
        """Yield container bytes as the encoder produces them.

        ``fed_at`` is filled with each frame's **capture** instant, not the
        instant its bytes were sent, so a later frame age is measured from when
        the picture existed — the only definition that means anything for a
        live call.
        """
        self._process = subprocess.Popen(
            self.config.command(self._ffmpeg),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process = self._process
        assert process.stdin is not None and process.stdout is not None

        stderr_chunks: list[bytes] = []
        stderr_thread = threading.Thread(
            target=lambda: stderr_chunks.append(process.stderr.read() or b""),
            daemon=True,
        )
        stderr_thread.start()

        writer = threading.Thread(
            target=self._write_frames,
            args=(process, schedule, fed_at, rpc_origin),
            daemon=True,
        )
        writer.start()

        outbound = ProgressiveMp4Reader()
        try:
            while True:
                # read1, not read: a full-buffer read would hold finished frames
                # back until 64 KiB had accumulated, adding a delay the harness
                # would then measure as if the service had caused it.
                chunk = process.stdout.read1(READ_CHUNK)
                if not chunk:
                    break
                now = monotonic()
                self.stats.bytes_produced += len(chunk)
                completed = outbound.feed(chunk, now)
                indices: list[int] = []
                for event in completed:
                    self.stats.muxed_at[event.index] = now - rpc_origin()
                    self.stats.frames_muxed += 1
                    indices.append(event.index)
                yield SendUnit(payload=chunk, media_time=None, frame_indices=tuple(indices))
        finally:
            writer.join(timeout=10)
            try:
                process.stdout.close()
            except OSError:
                pass
            process.wait(timeout=30)
            stderr_thread.join(timeout=5)
            self.stats.encoder_stderr = b"".join(stderr_chunks).decode("utf-8", "replace")[:4000]
            if process.returncode not in (0, None) and not self.stats.bytes_produced:
                raise LiveSourceError(
                    f"ffmpeg exited {process.returncode} without producing media: "
                    f"{self.stats.encoder_stderr}"
                )

    def _write_frames(
        self,
        process: subprocess.Popen[bytes],
        schedule: RealtimeSchedule,
        fed_at: dict[int, float],
        rpc_origin: Callable[[], float],
    ) -> None:
        """Hand raw frames to the encoder on the capture clock, then close stdin."""
        assert process.stdin is not None
        expected = self.config.frame_bytes
        index = 0
        try:
            for frame in self._frames:
                if len(frame) != expected:
                    raise LiveSourceError(
                        f"frame {index} is {len(frame)} bytes, expected {expected}"
                    )
                schedule.wait_until(index / self.config.fps)
                fed_at.setdefault(index, monotonic() - rpc_origin())
                self.stats.captured_at[index] = fed_at[index]
                process.stdin.write(frame)
                process.stdin.flush()
                self.stats.frames_written = index + 1
                index += 1
        except (BrokenPipeError, LiveSourceError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass


class InProcessLiveSource:
    """Encode through PyAV and mux each packet immediately, in this process.

    The frame's whole journey — capture, colour conversion, encode, fragment —
    happens on the thread gRPC is draining for requests, which is exactly what a
    real client would do and makes the cost of that journey directly measurable.
    Nothing is buffered on the way: one captured frame becomes one ``moof``/
    ``mdat`` pair and is handed straight to the RPC.

    Requires PyAV (``pip install av``). The harness does not fall back to the
    ffmpeg muxer if it is missing, because silently swapping in a path with
    twenty times the latency would corrupt a Stage C result.
    """

    def __init__(self, config: LiveEncoderConfig, frames: Iterable[bytes]) -> None:
        self.config = config
        self._frames = frames
        self.stats = LiveRunStats()

    def units(self, schedule: RealtimeSchedule, fed_at: dict[int, float],
              rpc_origin: Callable[[], float]) -> Iterator[SendUnit]:
        try:
            import av  # noqa: PLC0415 - optional dependency of the low-latency path
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise LiveSourceError(
                "the in-process muxer needs PyAV: pip install av "
                "(or run with --muxer ffmpeg)"
            ) from exc

        config = self.config
        codec = av.CodecContext.create("libx264", "w")
        codec.width, codec.height = config.width, config.height
        codec.pix_fmt = "yuv420p"
        codec.time_base = fractions.Fraction(1, config.fps)
        codec.gop_size = config.gop
        options = {"preset": config.preset, "tune": config.tune}
        if config.bitrate:
            options["b"] = config.bitrate
        codec.options = options

        writer: FragmentedMp4Writer | None = None
        expected = config.frame_bytes
        index = 0
        emitted = 0

        for raw in self._frames:
            if len(raw) != expected:
                raise LiveSourceError(f"frame {index} is {len(raw)} bytes, expected {expected}")
            schedule.wait_until(index / config.fps)
            captured = monotonic() - rpc_origin()
            fed_at.setdefault(index, captured)
            self.stats.captured_at[index] = captured
            self.stats.frames_written = index + 1
            index += 1

            source = av.VideoFrame(config.width, config.height, config.pixel_format)
            source.planes[0].update(raw)
            frame = source.reformat(format="yuv420p")
            frame.pts = index - 1
            frame.time_base = codec.time_base

            for packet in codec.encode(frame):
                unit = self._package(bytes(packet), packet.is_keyframe, writer, config)
                if unit is None:
                    continue
                writer, payload = unit
                now = monotonic() - rpc_origin()
                self.stats.muxed_at[emitted] = now
                self.stats.bytes_produced += len(payload)
                self.stats.frames_muxed += 1
                yield SendUnit(payload=payload, media_time=None, frame_indices=(emitted,))
                emitted += 1

        for packet in codec.encode(None):
            unit = self._package(bytes(packet), packet.is_keyframe, writer, config)
            if unit is None:
                continue
            writer, payload = unit
            self.stats.muxed_at[emitted] = monotonic() - rpc_origin()
            self.stats.bytes_produced += len(payload)
            self.stats.frames_muxed += 1
            yield SendUnit(payload=payload, media_time=None, frame_indices=(emitted,))
            emitted += 1

    def _package(self, data: bytes, is_keyframe: bool,
                 writer: FragmentedMp4Writer | None,
                 config: LiveEncoderConfig) -> tuple[FragmentedMp4Writer, bytes] | None:
        """Turn one encoded packet into container bytes, opening the file if needed."""
        nals = list(h264.iter_nal_units(data))
        if not nals:
            return None
        payload = b""
        if writer is None:
            sps, pps = h264.parameter_sets(nals)
            if not (sps and pps):
                # x264 puts the parameter sets in the first packet; until they
                # arrive there is nothing to describe the track with.
                return None
            writer = FragmentedMp4Writer(config.width, config.height, config.fps, sps, pps)
            payload = writer.initialization_segment()
        unit = h264.AccessUnit([nal for _type, nal in nals], is_keyframe)
        return writer, payload + writer.fragment(unit, 1)


def build_live_source(config: LiveEncoderConfig, frames: Iterable[bytes],
                      ffmpeg: str | None = None):
    """Pick the live source for the configured muxer."""
    if config.muxer == "inprocess":
        return InProcessLiveSource(config, frames)
    if config.muxer == "ffmpeg":
        return LiveFragmentedMp4Source(config, frames, ffmpeg=ffmpeg)
    raise LiveSourceError(f"unknown muxer {config.muxer!r}")


def frames_from_video(path: Path, config: LiveEncoderConfig,
                      ffmpeg: str | None = None) -> Iterator[bytes]:
    """Decode a prerecorded file into raw frames, one at a time.

    Stage B allows prerecorded frames supplied at realtime cadence: the property
    under test is that the *container* is built live, not that a camera is
    physically present. Frames are pulled lazily so the whole clip is never
    resident, and so the decode cannot run arbitrarily far ahead of the
    schedule that consumes it.
    """
    binary = ffmpeg or shutil.which("ffmpeg")
    if binary is None:
        raise LiveSourceError("ffmpeg is not on PATH")
    command = [
        binary, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(path),
        "-f", "rawvideo",
        "-pix_fmt", config.pixel_format,
        "-s", f"{config.width}x{config.height}",
        "-r", str(config.fps),
        "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    size = config.frame_bytes
    produced = 0
    try:
        while True:
            buffer = process.stdout.read(size)
            if not buffer or len(buffer) < size:
                break
            produced += 1
            yield buffer
    finally:
        try:
            process.stdout.close()
        except OSError:
            pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()
        if produced == 0:
            # Silence here used to look exactly like a service that accepted the
            # stream and returned nothing. It is the decoder refusing the file,
            # and its reason is the only thing that says so.
            detail = (process.stderr.read() or b"").decode("utf-8", "replace")[:2000]
            raise LiveSourceError(
                f"no frames could be decoded from {path}. This is a source problem, "
                f"not a service result. ffmpeg said: {detail.strip() or '(nothing)'}"
            )


def camera_frames(device: str, config: LiveEncoderConfig, input_format: str,
                  ffmpeg: str | None = None) -> Iterator[bytes]:
    """Raw frames from a physical camera, for Stage C.

    ``input_format`` is the ffmpeg capture backend: ``dshow`` on Windows,
    ``v4l2`` on Linux, ``avfoundation`` on macOS. Not exercised by the harness
    self-verification, which has no camera; a run that uses it must say so.
    """
    binary = ffmpeg or shutil.which("ffmpeg")
    if binary is None:
        raise LiveSourceError("ffmpeg is not on PATH")
    command = [
        binary, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", input_format,
        "-framerate", str(config.fps),
        "-video_size", f"{config.width}x{config.height}",
        "-i", device,
        "-f", "rawvideo",
        "-pix_fmt", config.pixel_format,
        "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert process.stdout is not None
    size = config.frame_bytes
    try:
        while True:
            buffer = process.stdout.read(size)
            if not buffer or len(buffer) < size:
                return
            yield buffer
    finally:
        try:
            process.stdout.close()
        except OSError:
            pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()
