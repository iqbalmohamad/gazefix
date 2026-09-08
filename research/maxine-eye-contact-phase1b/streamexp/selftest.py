"""Verify the instrument, against a mock, before trusting it against a service.

Every number this package can produce depends on four harness behaviours being
real rather than intended:

1. the input is genuinely paced — a ten-second source takes about ten seconds;
2. one RPC stays open while responses are read concurrently;
3. arriving container bytes are turned into per-frame usability instants;
4. the case where nothing is usable before EOS is *detected*, not waited out.

:func:`run_selftest` exercises all four against
:mod:`streamexp.mockserver`, which speaks NVIDIA's compiled proto and nothing
of Maxine's behaviour. A PASS here means the instrument works. It is not a
Phase 1B result, it is not evidence about Maxine, and it must never be
reported as one.

The media used is a synthetic ``testsrc2`` pattern — engineering scaffolding,
never evaluation material, and it establishes nothing about visual quality.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import livesource, mockserver, proto, source
from .channel import ChannelSpec
from .stages import RunOptions, run_stage_a, run_stage_b

SYNTHETIC_NOTE = (
    "synthetic testsrc2 pattern — engineering scaffolding, not evaluation material"
)


def build_synthetic_source(path: Path, width: int, height: int, fps: int,
                           seconds: int) -> Path:
    """Encode a faststart H.264 MP4 in the layout the NIM's streaming mode wants."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to build the self-test source")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}",
            "-t", str(seconds),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-g", str(fps),
            "-movflags", "+faststart",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return path


def _assertion(name: str, passed: bool, observed: Any, expected: str) -> dict[str, Any]:
    return {
        "assertion": name,
        "result": "PASS" if passed else "FAIL",
        "expected": expected,
        "observed": observed,
    }


def run_selftest(*, clone_dir: Path, workspace: Path, width: int = 1280,
                 height: int = 720, fps: int = 30, seconds: int = 3) -> dict[str, Any]:
    """Run the harness against the mock in both behaviours and check it."""
    interfaces = proto.load(clone_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    clip = build_synthetic_source(workspace / "synthetic-source.mp4", width, height, fps, seconds)
    profile, _ = source.probe(clip)

    assertions: list[dict[str, Any]] = []
    runs: dict[str, Any] = {}

    assertions.append(
        _assertion(
            "self-test source is moov-first (the NIM's streaming precondition)",
            profile.streamable,
            {"top_level_atoms": profile.layout},
            "ftyp then moov",
        )
    )

    # 1. A service that emits progressively.
    server, port = mockserver.serve(interfaces, mockserver.MockConfig(mode="streaming"))
    try:
        streaming = run_stage_a(
            _options(clone_dir, workspace, "mock-streaming", clip, port, width, height, fps)
        )
    finally:
        server.stop(0).wait()
    runs["stage_a_mock_streaming"] = streaming

    determinations = streaming["determinations"]
    timing = streaming["timing_ms_since_rpc_start"]
    assertions.append(
        _assertion(
            "usable output detected before input EOS when the service emits progressively",
            determinations["usable_output_before_input_eos"] == "YES",
            determinations["usable_output_before_input_eos"],
            "YES",
        )
    )
    eos_ms = timing["input_eos_ms"]
    expected_ms = seconds * 1000
    paced = isinstance(eos_ms, (int, float)) and 0.75 * expected_ms <= eos_ms <= 1.6 * expected_ms
    assertions.append(
        _assertion(
            "input is realtime-paced, not sent as fast as the disk allows",
            paced,
            {"input_eos_ms": eos_ms, "source_seconds": seconds},
            f"input EOS near {expected_ms} ms, not near zero",
        )
    )
    assertions.append(
        _assertion(
            "per-frame usability instants were produced",
            streaming["frame_age"]["frames_with_age"] > 0,
            streaming["frame_age"],
            "at least one frame with a measured age",
        )
    )
    retained = streaming["throughput"]["max_harness_retained_bytes"]
    assertions.append(
        _assertion(
            "the harness itself builds no unbounded queue",
            isinstance(retained, int) and retained <= 8 * 1024 * 1024,
            {"max_harness_retained_bytes": retained},
            "bounded retention regardless of stream length",
        )
    )

    # 2. A service that requires the whole input first — the Stage A kill signal.
    server, port = mockserver.serve(interfaces, mockserver.MockConfig(mode="transactional"))
    try:
        transactional = run_stage_a(
            _options(clone_dir, workspace, "mock-transactional", clip, port, width, height, fps)
        )
    finally:
        server.stop(0).wait()
    runs["stage_a_mock_transactional"] = transactional

    assertions.append(
        _assertion(
            "no usable output before EOS is DETECTED when the service buffers to EOS",
            transactional["determinations"]["usable_output_before_input_eos"] == "NO",
            transactional["determinations"]["usable_output_before_input_eos"],
            "NO",
        )
    )

    # 3. The live-produced container.
    server, port = mockserver.serve(interfaces, mockserver.MockConfig(mode="streaming"))
    try:
        live = run_stage_b(
            _options(clone_dir, workspace, "mock-live", clip, port, width, height, fps,
                     max_frames=fps * seconds)
        )
    finally:
        server.stop(0).wait()
    runs["stage_b_mock_streaming"] = live

    sent = live["what_was_sent_over_the_rpc"]
    assertions.append(
        _assertion(
            "Stage B sends a fragmented MP4 whose moov precedes any media",
            bool(sent["moov_precedes_media"]) and not sent["completed_input_mp4_existed_before_rpc"],
            sent,
            "moov first, no completed input MP4 beforehand",
        )
    )
    assertions.append(
        _assertion(
            "live-generated fragments are indexed into per-frame usability instants",
            live["frame_age"]["frames_with_age"] > 0,
            live["frame_age"],
            "at least one frame with a measured age",
        )
    )
    assertions.append(
        _assertion(
            "Stage B's output layout is recognised as fragmented",
            live["determinations"]["output_container_layout"] == "MOOV_FIRST_FRAGMENTED",
            live["determinations"]["output_container_layout"],
            "MOOV_FIRST_FRAGMENTED",
        )
    )

    # 4. The low-latency muxing path, which Stage C needs if a <100 ms budget is
    #    to be attributable to anything but the harness.
    inprocess: dict[str, Any] | None = None
    try:
        server, port = mockserver.serve(interfaces, mockserver.MockConfig(mode="streaming"))
        try:
            inprocess = run_stage_b(
                _options(clone_dir, workspace, "mock-live-inprocess", clip, port,
                         width, height, fps, max_frames=fps * seconds, muxer="inprocess")
            )
        finally:
            server.stop(0).wait()
    except Exception as exc:  # noqa: BLE001 - an absent optional dependency is not a failure
        assertions.append(
            _assertion(
                "in-process muxer path is exercisable",
                False,
                f"{type(exc).__name__}: {exc}",
                "PyAV present and the in-process path runs",
            )
        )

    if inprocess is not None:
        runs["stage_b_mock_inprocess_muxer"] = inprocess
        production = inprocess["live_production"]
        assertions.append(
            _assertion(
                "the in-process muxer emits exactly one fragment per captured frame",
                bool(production["frames_muxed_matches_captured"]),
                {
                    "frames_captured": production["frames_captured"],
                    "frames_muxed": production["frames_muxed"],
                },
                "frames muxed == frames captured",
            )
        )
        assertions.append(
            _assertion(
                "the in-process muxer's output decodes",
                inprocess["decode_corroboration"]["status"] == "VERIFIED",
                inprocess["decode_corroboration"],
                "VERIFIED",
            )
        )
        ffmpeg_p50 = live["live_production"]["encode_and_mux_ms_p50"]
        inproc_p50 = production["encode_and_mux_ms_p50"]
        comparable = isinstance(ffmpeg_p50, (int, float)) and isinstance(inproc_p50, (int, float))
        assertions.append(
            _assertion(
                "the in-process muxer costs materially less client-side latency",
                comparable and inproc_p50 < ffmpeg_p50 / 2,
                {"ffmpeg_muxer_ms_p50": ffmpeg_p50, "inprocess_muxer_ms_p50": inproc_p50},
                "in-process preparation under half the ffmpeg muxer's",
            )
        )

    passed = all(a["result"] == "PASS" for a in assertions)
    return {
        "what_this_is": (
            "Verification of the Phase 1B harness against a local mock that speaks "
            "NVIDIA's compiled proto. NOT a Maxine measurement and NOT a Phase 1B result."
        ),
        "media": SYNTHETIC_NOTE,
        "source": profile.describe(),
        "harness_self_verification": "PASS" if passed else "FAIL",
        "measured_harness_overhead": {
            "what_it_is": (
                "Client-side capture-to-sendable cost of each muxing path on THIS "
                "machine, against a mock that does no work. It is the floor below "
                "which no frame age measured by this harness can go, and it must be "
                "subtracted in the reader's head before any Maxine number is judged "
                "against the PRD budget."
            ),
            "ffmpeg_muxer_ms_p50": live["live_production"]["encode_and_mux_ms_p50"],
            "inprocess_muxer_ms_p50": (
                inprocess["live_production"]["encode_and_mux_ms_p50"]
                if inprocess is not None else "NOT MEASURED"
            ),
        },
        "assertions": assertions,
        "runs": {
            name: {
                "determinations": payload["determinations"],
                "timing_ms_since_rpc_start": payload["timing_ms_since_rpc_start"],
                "frame_age": payload["frame_age"],
                "throughput": payload["throughput"],
                "decode_corroboration": payload["decode_corroboration"],
                "error": payload["error"],
            }
            for name, payload in runs.items()
        },
    }


def _options(clone_dir: Path, workspace: Path, label: str, clip: Path, port: int,
             width: int, height: int, fps: int, max_frames: int | None = None,
             muxer: str = "ffmpeg") -> RunOptions:
    return RunOptions(
        channel=ChannelSpec(target=f"127.0.0.1:{port}", mode="insecure"),
        clone_dir=clone_dir,
        workspace=workspace,
        label=label,
        source_path=clip,
        encoder=livesource.LiveEncoderConfig(
            width=width, height=height, fps=fps, gop=fps, muxer=muxer
        ),
        max_frames=max_frames,
    )
