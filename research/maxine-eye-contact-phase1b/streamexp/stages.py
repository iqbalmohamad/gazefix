"""Stage A and Stage B runners, and the artifacts they leave behind.

Both stages drive the same instrument (:class:`~streamexp.session.RedirectGazeSession`)
and differ only in where the container bytes come from:

Stage A
    A completed, known-good streamable MP4, delivered on its own timestamps.
    Isolates the question "does the service return usable output before it has
    the whole input?" from every question about producing media live.

Stage B
    A fragmented MP4 that does not exist when the RPC opens and is manufactured
    frame by frame while it is in flight. Isolates the question "can the service
    consume genuinely live-generated media?".

Neither runner decides anything. Each writes what it measured, states each
determination as ``YES`` / ``NO`` / ``NOT MEASURED``, and stops.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import decode, livesource, proto, source
from .channel import ChannelSpec, build, call_metadata, wait_until_ready
from .clock import RealtimeSchedule
from .progressive import Layout
from .session import RedirectGazeSession, SessionResult
from .timing import Timeline, frame_rows, summarise_ages, write_csv, write_json


@dataclass
class RunOptions:
    """Everything a stage run needs, and nothing about what it should conclude."""

    channel: ChannelSpec
    clone_dir: Path
    workspace: Path
    label: str
    source_path: Path | None = None
    chunk_size: int = proto.DATA_CHUNK_SIZE
    send_config: bool = True
    config_params: dict[str, Any] = field(default_factory=dict)
    encoder: livesource.LiveEncoderConfig = field(default_factory=livesource.LiveEncoderConfig)
    frame_source: str = "file"
    """``file``, ``camera`` or ``synthetic`` — recorded in the results."""
    camera_device: str = ""
    camera_backend: str = ""
    max_frames: int | None = None
    decode_check: bool = True
    rpc_timeout_s: float | None = 600.0


def environment_record(options: RunOptions) -> dict[str, Any]:
    """Facts about where a measurement was taken. Never inferred, never omitted."""
    import grpc  # noqa: PLC0415

    return {
        "client_os": f"{platform.system()} {platform.release()}",
        "client_platform": platform.platform(),
        "client_machine": platform.machine(),
        "client_processor": platform.processor() or "UNKNOWN",
        "client_python": sys.version.split()[0],
        "grpcio_version": grpc.__version__,
        "ffmpeg": decode.tool("ffmpeg") or "NOT PRESENT",
        "ffprobe": decode.tool("ffprobe") or "NOT PRESENT",
        "nvidia_client_revision": proto.git_revision(options.clone_dir),
        "connection": options.channel.describe(),
        "server_gpu": "NOT MEASURED — supply the serving host's GPU model",
        "nim_image_and_version": "NOT MEASURED — supply the container image tag",
        "network_context": "NOT MEASURED — supply the client-to-server network path",
    }


def _determinations(
    result: SessionResult, stage: str, source_frames: int | None = None
) -> dict[str, str]:
    layout = result.reader.layout
    determinations = {
        "usable_output_before_input_eos": result.output_before_eos(),
        "output_container_layout": layout.value,
        "rpc_completed": "NO" if result.error else "YES",
        "output_input_frame_correspondence": _correspondence(result, source_frames),
    }
    if layout is Layout.MOOV_LAST:
        determinations["output_indexable_before_eos"] = "NO"
        determinations["kill_condition_3_whole_file_interface"] = (
            "OBSERVED — the response placed its moov after the media, so no corrected "
            "frame could be located until the whole output had arrived"
        )
    if stage == "B":
        determinations["maxine_consumed_live_generated_input"] = _consumed_live_input(result)
        determinations["output_indexable_by_this_harness"] = (
            "YES" if result.frames else "NO"
        )
    return determinations


#: gRPC statuses that mean the server looked at what we sent and refused it.
#: Everything else is a transient or unexplained end and answers nothing about
#: whether a progressively-built container is acceptable.
_REJECTION_STATUSES = frozenset(
    {"INVALID_ARGUMENT", "FAILED_PRECONDITION", "UNIMPLEMENTED", "OUT_OF_RANGE"}
)


def _consumed_live_input(result: SessionResult) -> str:
    """Did the NIM accept media that did not exist when the call opened?

    The question is about the **input** side. Whether the corrected output
    happened to be indexable by this harness is a different matter and is
    reported separately: a service that swallowed a progressively-built
    fragmented MP4 and returned valid corrected bytes has answered YES even if
    its response came back in a layout we could only read as a whole.
    """
    if result.interrupted or result.sender_incomplete:
        return "NOT MEASURED"
    if result.grpc_status:
        if result.grpc_status in _REJECTION_STATUSES:
            return f"NO — the server refused it with {result.grpc_status}"
        return f"NOT MEASURED — the call ended with {result.grpc_status}, which is not a refusal"
    if result.error:
        return "NOT MEASURED"
    if result.bytes_received > 0:
        return "YES"
    return "NO — the call completed but the server returned no media at all"


def _write_artifacts(
    workspace: Path, label: str, payload: dict[str, Any], result: SessionResult
) -> dict[str, str]:
    results_dir = workspace / label
    write_json(results_dir / "summary.json", payload)
    write_csv(results_dir / "timeline.csv", result.timeline.to_rows())
    write_csv(results_dir / "frames.csv", frame_rows(result.frames))
    write_csv(
        results_dir / "backlog.csv",
        [{k: v for k, v in sample.items()} for sample in result.backlog_samples],
    )
    return {
        "summary": str(results_dir / "summary.json"),
        "timeline_csv": str(results_dir / "timeline.csv"),
        "frames_csv": str(results_dir / "frames.csv"),
        "backlog_csv": str(results_dir / "backlog.csv"),
        "corrected_output": str(results_dir / "corrected.mp4"),
    }


def _timing_block(result: SessionResult) -> dict[str, Any]:
    def ms(name: str) -> Any:
        value = result.timeline.elapsed(name)
        return "NOT MEASURED" if value is None else round(value * 1000, 3)

    return {
        "rpc_start_wall_clock": result.timeline.started_wall,
        "first_input_bytes_ms": ms("first_input_bytes"),
        "config_echo_ms": ms("config_echo"),
        "first_response_ms": ms("first_response"),
        "first_output_bytes_ms": ms("first_output_bytes"),
        "first_usable_frame_ms": ms("first_usable_frame"),
        "input_eos_ms": ms("input_eos"),
        "rpc_end_ms": ms("rpc_end"),
    }


def _throughput_block(result: SessionResult, duration_s: float | None) -> dict[str, Any]:
    total = result.timeline.elapsed("rpc_end") or 0.0
    return {
        "bytes_sent": result.bytes_sent,
        "bytes_received": result.bytes_received,
        "responses": result.responses,
        "keepalives": result.keepalives,
        "usable_output_frames": len(result.frames),
        "output_fps_over_rpc": round(len(result.frames) / total, 3) if total else "NOT MEASURED",
        "source_duration_s": duration_s if duration_s is not None else "NOT MEASURED",
        "max_harness_retained_bytes": result.max_reader_buffer_bytes,
        "note": (
            "Throughput is reported for completeness only. It is not latency and "
            "must not be read as one."
        ),
    }


# -- Stage A -------------------------------------------------------------


def run_stage_a(options: RunOptions) -> dict[str, Any]:
    """Feed a completed streamable MP4 at its own cadence through one RPC."""
    if options.source_path is None:
        raise ValueError("Stage A requires --source")

    interfaces = proto.load(options.clone_dir)
    profile, index = source.probe(options.source_path)
    warnings = _check_stage_a_source(profile, options.rpc_timeout_s)
    workspace = options.workspace
    output_path = workspace / options.label / "corrected.mp4"

    schedule = RealtimeSchedule()
    metadata = call_metadata(options.channel)
    channel = build(options.channel)
    try:
        wait_until_ready(channel)
        session = RedirectGazeSession(
            interfaces,
            interfaces.stub(channel),
            send_config=options.send_config,
            config_params=options.config_params,
            metadata=metadata,
            output_path=output_path,
            timeout_s=options.rpc_timeout_s,
        )
        units = source.paced_units(options.source_path, index, options.chunk_size)
        schedule.origin = Timeline().started_monotonic
        result = session.run(units, schedule)
    finally:
        channel.close()

    payload: dict[str, Any] = {
        "stage": "A",
        "question": (
            "Does one continuously-open RedirectGaze RPC return usable corrected "
            "output before the client has finished sending a realtime-paced input?"
        ),
        "harness_version": _version(),
        "environment": environment_record(options),
        "proto": {
            "path": str(interfaces.proto_path),
            "sha256": interfaces.proto_sha256,
            "service": "nvidia.maxine.eyecontact.v1.MaxineEyeContactService/RedirectGaze",
        },
        "source": {**profile.describe(), "warnings": warnings},
        "delivery": {
            "mode": "realtime-throttled by source presentation timestamps",
            "rpc_timeout_s": options.rpc_timeout_s if options.rpc_timeout_s else "none",
            "chunk_size_bytes": options.chunk_size,
            "config_message_sent": options.send_config,
            "config_parameters_sent": (
                options.config_params
                if options.config_params
                else (
                    "an EMPTY RedirectGazeConfig message was sent (no field set, so the "
                    "server applies its own defaults). Use --no-config to send no config "
                    "message at all."
                    if options.send_config
                    else "no config message sent at all"
                )
            ),
            "config_echoed_by_server": result.config_echo or "none",
            "schedule": schedule.statistics(),
            "units_sent": result.units_sent,
        },
        "timing_ms_since_rpc_start": _timing_block(result),
        "determinations": _determinations(result, "A", profile.frame_count),
        "frame_age": summarise_ages(result.frames, profile.frame_count),
        "throughput": _throughput_block(result, profile.duration_seconds),
        "error": result.error or "",
        "failure_attribution": _attribution(result),
    }
    payload["decode_corroboration"] = _corroborate(
        options, result, workspace, profile.frame_count
    )
    payload["artifacts"] = _write_artifacts(workspace, options.label, payload, result)
    write_json(workspace / options.label / "summary.json", payload)
    return payload


# -- Stage B -------------------------------------------------------------


def run_stage_b(options: RunOptions) -> dict[str, Any]:
    """Manufacture the container while the RPC is open, and feed it live."""
    interfaces = proto.load(options.clone_dir)
    workspace = options.workspace
    output_path = workspace / options.label / "corrected.mp4"
    encoder = options.encoder

    source_profile = None
    if options.frame_source == "file":
        if options.source_path is None:
            raise ValueError("file frame source requires --source")
        # Stage B replays this clip's frames, so the same refusals that protect
        # Stage A apply: an LFS pointer, a non-MP4 or an HEVC clip would
        # otherwise decode to nothing and look like a service that accepted the
        # stream and returned no frames.
        source_profile, _index = source.probe(options.source_path)
        _check_stage_b_source(source_profile)

    if options.frame_source == "camera":
        if not (options.camera_device and options.camera_backend):
            raise ValueError("camera frame source requires --camera-device and --camera-backend")
        frames = livesource.camera_frames(
            options.camera_device, encoder, options.camera_backend
        )
    elif options.frame_source == "file":
        frames = livesource.frames_from_video(options.source_path, encoder)
    else:
        raise ValueError(f"unknown frame source {options.frame_source!r}")

    if options.max_frames is not None:
        frames = _take(frames, options.max_frames)

    live = livesource.build_live_source(encoder, frames)
    schedule = RealtimeSchedule()
    metadata = call_metadata(options.channel)
    channel = build(options.channel)
    fed_at: dict[int, float] = {}
    try:
        wait_until_ready(channel)
        session = RedirectGazeSession(
            interfaces,
            interfaces.stub(channel),
            send_config=options.send_config,
            config_params=options.config_params,
            metadata=metadata,
            output_path=output_path,
            timeout_s=options.rpc_timeout_s,
        )
        timeline_origin = Timeline().started_monotonic
        schedule.origin = timeline_origin
        units = live.units(schedule, fed_at, lambda: timeline_origin)
        try:
            result = session.run(units, schedule, fed_at=fed_at)
        finally:
            # Close the producer explicitly. If gRPC abandons the request
            # iterator, only the outer generator is finalised and livesource's
            # cleanup never runs — leaving ffmpeg unreaped and its stderr empty
            # exactly when it is the only thing that separates "the NIM rejected
            # our container" from "our encoder produced a broken one".
            units.close()
    finally:
        channel.close()

    encode_ms = live.stats.encode_prepare_ms()
    payload: dict[str, Any] = {
        "stage": "B",
        "question": (
            "Can the NIM consume a media stream generated incrementally while the "
            "RPC is open, rather than read from an already-completed MP4?"
        ),
        "harness_version": _version(),
        "environment": environment_record(options),
        "proto": {
            "path": str(interfaces.proto_path),
            "sha256": interfaces.proto_sha256,
            "service": "nvidia.maxine.eyecontact.v1.MaxineEyeContactService/RedirectGaze",
        },
        "what_was_sent_over_the_rpc": {
            "container": "fragmented MP4 (ftyp + empty moov with mvex, then moof/mdat per frame)",
            "muxer": _muxer_description(encoder),
            "video_codec": "H.264 (libx264)",
            "audio": "none",
            "moov_precedes_media": True,
            "completed_input_mp4_existed_before_rpc": False,
            "frame_source": options.frame_source,
            "replayed_source": source_profile.describe() if source_profile else "n/a",
            "encoder": {
                "width": encoder.width,
                "height": encoder.height,
                "fps": encoder.fps,
                "gop": encoder.gop,
                "preset": encoder.preset,
                "tune": encoder.tune,
                "fragment_per_frame": encoder.fragment_per_frame,
                "muxer": encoder.muxer,
            },
        },
        "live_production": {
            "frames_captured": live.stats.frames_written,
            "frames_muxed": live.stats.frames_muxed,
            "frames_muxed_matches_captured":
                live.stats.frames_muxed == live.stats.frames_written,
            "container_bytes_produced": live.stats.bytes_produced,
            "encode_and_mux_ms_p50": _p(encode_ms, 0.50),
            "encode_and_mux_ms_p95": _p(encode_ms, 0.95),
            "encoder_stderr": live.stats.encoder_stderr,
            "schedule": schedule.statistics(),
        },
        "timing_ms_since_rpc_start": _timing_block(result),
        "determinations": _determinations(result, "B", live.stats.frames_written),
        "frame_age": summarise_ages(result.frames, live.stats.frames_written),
        "throughput": _throughput_block(
            result,
            live.stats.frames_written / encoder.fps if live.stats.frames_written else None,
        ),
        "error": result.error or "",
        "failure_attribution": _attribution(result),
    }
    payload["decode_corroboration"] = _corroborate(
        options, result, workspace, live.stats.frames_written
    )
    payload["artifacts"] = _write_artifacts(workspace, options.label, payload, result)
    write_json(workspace / options.label / "summary.json", payload)
    return payload


# -- shared helpers ------------------------------------------------------


def _corroborate(
    options: RunOptions, result: SessionResult, workspace: Path,
    source_frames: int | None = None,
) -> dict[str, Any]:
    """Decode what the client held, and say what the decode proves.

    Two cases, and the second one matters as much as the first.

    A frame became usable before EOS
        Decode the exact prefix the client held at that instant. That is direct
        evidence that corrected pictures existed on the client while capture was
        still running.

    No frame became usable
        Decode the **complete** received output instead. This is the case that
        produces a Stage A ``NO``, and a bare ``NO`` is not enough: it cannot
        distinguish "the service works but will not emit incrementally" from
        "the service returned something unusable". Those call for entirely
        different decisions, so the whole response is decoded and its frames
        counted before either is reported.
    """
    if not options.decode_check:
        return {"status": "NOT MEASURED", "detail": "decode check disabled"}
    if result.output_path is None or not result.output_path.is_file():
        return {"status": "NOT MEASURED", "detail": "no output was written"}

    directory = workspace / options.label / "corroboration"

    if result.first_usable_byte_end is None:
        if result.bytes_received == 0:
            return {
                "status": "NOT MEASURED",
                "scope": "no output",
                "detail": "the service returned no media bytes at all",
            }
        check = decode.decode_prefix(
            result.output_path.read_bytes(), directory, "complete-output"
        )
        # Why nothing was usable matters. Only one of these reasons is a
        # statement about the service.
        if result.reader_error:
            why = (
                "this harness could not parse the response container "
                f"({result.reader_error}), so no frame could be located. That is a "
                "harness limitation, not a service result."
            )
        elif result.reader.layout is Layout.MOOV_LAST:
            why = (
                "the response placed its moov after the media, so no corrected frame "
                "could be located until the whole output had arrived."
            )
        else:
            why = (
                f"the response layout was read as {result.reader.layout.value} but no "
                "sample ever completed."
            )
        counted = check.frames_decoded
        against = (
            f"{counted}/{source_frames}"
            if counted is not None and source_frames else "UNKNOWN"
        )
        short = (
            counted is not None and source_frames is not None and counted < source_frames
        )
        return {
            "status": check.status,
            "scope": "complete output — no frame was usable before input EOS",
            "why_nothing_was_usable": why,
            "frames_decoded": counted if counted is not None else "UNKNOWN",
            "frames_decoded_vs_source": against,
            "prefix_bytes": check.prefix_bytes,
            "detail": check.detail,
            "means": (
                (
                    "The service produced valid corrected video for every source "
                    "frame, but only as a whole file. That is a streaming result, "
                    "not a quality one — the correction itself worked."
                    if not short else
                    f"The complete response decodes, but to {against} frames. Fewer "
                    "corrected frames than source frames is its own finding and must "
                    "not be reported as a clean streaming-only failure."
                )
                if check.status == "VERIFIED" else
                "No corrected frame was usable before EOS AND the complete response "
                "did not decode. Treat this as a failed run rather than as evidence "
                "about the service's streaming behaviour, and check the source file "
                "and the server log before drawing any conclusion."
            ),
        }

    data = result.output_path.read_bytes()[: result.first_usable_byte_end]
    check = decode.decode_prefix(data, directory, "prefix-at-first-usable-frame")
    return {
        "status": check.status,
        "scope": "prefix held at the first usable frame",
        "frames_decoded": check.frames_decoded if check.frames_decoded is not None else "UNKNOWN",
        "prefix_bytes": check.prefix_bytes,
        "detail": check.detail,
        "means": (
            "The bytes the client held at the first-usable instant decode to real "
            "pictures." if check.status == "VERIFIED" else
            "The container-level usability criterion was not corroborated by a decoder; "
            "read every frame age in this run with that in mind."
        ),
    }


def _check_stage_a_source(
    profile: source.SourceProfile, rpc_timeout_s: float | None = None
) -> list[str]:
    """Refuse a source that cannot answer Stage A; warn about one that might not.

    Stage A asks whether corrected output appears before input EOS *under the
    supported streaming mode*. Feeding it a file the NIM's streaming mode does
    not accept produces a ``NO`` that says nothing about the service. Those
    cases are refused here, before the RPC is opened, rather than measured.

    Non-uniform sample durations are only warned about. The NIM does not
    support variable frame rate, but a trailing sample of a different length is
    ordinary in otherwise constant-rate material, and refusing on that alone
    would block valid runs. The warning is recorded in the summary so that if
    the run does fail, the cause is visible rather than guessed at.
    """
    if profile.frame_count == 0:
        raise source.SourceUnsuitable(
            f"{profile.path} contains no video samples"
        )
    # H.264 only. NVIDIA documents this, and it is invisible to every other
    # check: an HEVC clip remuxed with +faststart passes the layout gate.
    if profile.codec and profile.codec.lower() not in ("avc1", "avc3"):
        raise source.SourceUnsuitable(
            f"{profile.path} has video codec '{profile.codec}', not H.264. The NIM "
            "accepts H.264 in MP4 only. Convert it with:\n"
            "  ffmpeg -i <in> -c:v libx264 -pix_fmt yuv420p -movflags +faststart <out>.mp4"
        )
    if not profile.streamable:
        raise source.SourceUnsuitable(
            f"{profile.path} is not streamable: its top-level layout is "
            f"{profile.layout}, so 'moov' does not precede the media. NVIDIA's "
            "streaming mode requires moov first. Convert it with:\n"
            "  ffmpeg -i <in> -c copy -movflags +faststart <out>.mp4\n"
            "Refusing rather than measuring, because a NO from this file would "
            "be a statement about the file and not about the service."
        )

    warnings: list[str] = []
    duration = profile.duration_seconds
    if rpc_timeout_s and duration and duration > 0.8 * rpc_timeout_s:
        raise source.SourceUnsuitable(
            f"{profile.path} runs {duration:.0f}s and Stage A feeds it in realtime, "
            f"which leaves no room inside the {rpc_timeout_s:.0f}s RPC deadline for "
            "the server's tail. The client would cut the call off and the result "
            f"would look like a failure. Re-run with --rpc-timeout {duration * 3:.0f} "
            "or use a shorter clip."
        )
    if profile.nominal_fps is None:
        warnings.append(
            "Sample durations are not uniform. The NIM does not support variable "
            "frame rate; if this run fails, re-encode at a constant rate "
            "(ffmpeg -r 30 ...) and repeat before attributing anything to the service."
        )
    if profile.width and (profile.width, profile.height) != (1280, 720):
        warnings.append(
            f"Source is {profile.width}x{profile.height}, not the 1280x720 the "
            "experiment targets. Stage A's transport question does not depend on "
            "resolution, but the result should be read as measured at this size."
        )
    return warnings


def _check_stage_b_source(profile: source.SourceProfile) -> None:
    """Stage B decodes this clip to raw frames, so it must be decodable at all.

    The codec gate is intentionally softer than Stage A's: Stage B re-encodes
    to H.264 itself, so a non-H.264 input is only a problem if ffmpeg cannot
    decode it. What is refused here is material that is not video.
    """
    if profile.frame_count == 0:
        raise source.SourceUnsuitable(f"{profile.path} contains no video samples")


def _attribution(result: SessionResult) -> dict[str, Any]:
    """Say where a failure came from, so a verdict lands on the right thing.

    "The NIM is busy", "the NIM rejected the container", "our own deadline
    fired" and "the operator pressed Ctrl-C" all end a run. Collapsing them into
    one string would leave the reader to guess, and the likeliest guess — that
    the service failed — is the one that wrongly retires a technology.
    """
    if result.interrupted:
        blame = "OPERATOR — the run was interrupted; this is not a result"
    elif result.sender_incomplete:
        blame = "HARNESS — the sender never finished; the record is incomplete"
    elif result.grpc_status == "DEADLINE_EXCEEDED":
        blame = (
            "HARNESS — the client's own RPC deadline fired, not a server failure. "
            "Re-run with a larger --rpc-timeout before concluding anything."
        )
    elif result.grpc_status:
        blame = f"SERVER — the call ended with gRPC status {result.grpc_status}"
    elif result.error:
        blame = "CLIENT — the call failed before a status was returned"
    elif result.reader_error:
        blame = (
            "HARNESS PARSER — the transport succeeded and the output was saved, but "
            "this harness could not index the container. Analyse the saved output "
            "offline; do not read this as a service failure."
        )
    else:
        blame = "NONE — the call completed"
    return {
        "blame": blame,
        "grpc_status": result.grpc_status or "",
        "grpc_details": result.grpc_details or "",
        "reader_error": result.reader_error or "",
        "interrupted": result.interrupted,
    }


def _correspondence(result: SessionResult, source_frames: int | None) -> str:
    """State whether output frames can be matched to input frames 1:1.

    Every frame age in this harness assumes corrected frame *n* is the
    correction of source frame *n*. That assumption is cheap to state and
    expensive to get wrong, so it is checked and reported rather than left
    implicit in the numbers.
    """
    output_frames = len(result.frames)
    if source_frames is None or not output_frames:
        return "NOT MEASURED"
    early = sum(
        1 for r in result.frames if r.age_s is not None and r.age_s < 0
    )
    if early:
        return (
            f"BROKEN — {early} corrected frames arrived before their same-index source "
            f"frame had been sent ({output_frames} out, {source_frames} in)"
        )
    if output_frames != source_frames:
        return (
            f"MISMATCH — {output_frames} corrected frames for {source_frames} source "
            "frames; per-frame ages assume 1:1 and are unreliable"
        )
    return f"1:1 — {output_frames} corrected frames for {source_frames} source frames"


def _muxer_description(encoder: livesource.LiveEncoderConfig) -> str:
    if encoder.muxer == "inprocess":
        return (
            "PyAV libx264 packets muxed in-process by streamexp.fmp4 "
            "(ftyp + moov/mvex, then one moof/mdat per frame)"
        )
    flags = ("+empty_moov+default_base_moof+frag_every_frame"
             if encoder.fragment_per_frame
             else "+empty_moov+default_base_moof+frag_keyframe")
    return f"ffmpeg -f mp4 -movflags {flags}"


def _take(iterable, count: int):
    for i, item in enumerate(iterable):
        if i >= count:
            return
        yield item


def _p(values: list[float], fraction: float) -> Any:
    from .timing import percentile  # noqa: PLC0415 - avoids a cycle at import time

    result = percentile(values, fraction)
    return "NOT MEASURED" if result is None else round(result, 3)


def _version() -> str:
    from . import VERSION  # noqa: PLC0415

    return VERSION
