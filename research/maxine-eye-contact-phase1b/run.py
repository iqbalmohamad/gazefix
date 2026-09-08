#!/usr/bin/env python3
"""Maxine Eye Contact Phase 1B — realtime streaming feasibility harness.

RESEARCH/EXPERIMENT ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION.

    python research/maxine-eye-contact-phase1b/run.py preflight
    python research/maxine-eye-contact-phase1b/run.py stage-a --source clip.mp4
    python research/maxine-eye-contact-phase1b/run.py stage-b --source clip.mp4
    python research/maxine-eye-contact-phase1b/run.py selftest

``selftest`` runs both stages against a local mock that speaks NVIDIA's compiled
proto. It verifies the harness and establishes nothing whatsoever about Maxine.
Every other command needs a real Eye Contact NIM at ``--target``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from streamexp import livesource, preflight, proto  # noqa: E402
from streamexp.channel import ChannelSpec  # noqa: E402
from streamexp.stages import RunOptions, run_stage_a, run_stage_b  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE = REPO_ROOT / "experiments" / "maxine-phase1b"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command",
                        choices=["preflight", "stage-a", "stage-b", "mock", "selftest"])
    parser.add_argument("--target", default="127.0.0.1:8001",
                        help="host:port of the Eye Contact NIM (default: %(default)s)")
    parser.add_argument("--mode", default="insecure",
                        choices=["insecure", "tls", "mtls", "preview"],
                        help="channel mode, mirroring NVIDIA's client")
    parser.add_argument("--ssl-root-cert", type=Path)
    parser.add_argument("--ssl-key", type=Path)
    parser.add_argument("--ssl-cert", type=Path)
    parser.add_argument("--function-id", default="",
                        help="NVCF function id; preview mode only, and preview mode "
                             "is not the Phase 1B route")
    parser.add_argument("--nvidia-client", type=Path, default=None,
                        help="path to a clone of NVIDIA-Maxine/nim-clients "
                             "(default: <workspace>/nvidia-client)")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE,
                        help="run artifacts directory (default: %(default)s)")
    parser.add_argument("--source", type=Path,
                        help="Stage A: the streamable MP4 to feed. "
                             "Stage B: the clip whose frames are replayed at capture cadence.")
    parser.add_argument("--label", default="",
                        help="subdirectory for this run's artifacts")
    parser.add_argument("--chunk-size", type=int, default=proto.DATA_CHUNK_SIZE,
                        help="bytes per request message (default: NVIDIA's 65536)")
    parser.add_argument("--i-have-confirmed-nim-endpoint", action="store_true",
                        help="operator attests a self-hosted Eye Contact NIM serves --target")
    parser.add_argument("--no-decode-check", action="store_true",
                        help="skip decoding the prefix that was called usable")
    parser.add_argument("--no-config", action="store_true",
                        help="do not send the initial RedirectGazeConfig message")

    live = parser.add_argument_group("Stage B / live source")
    live.add_argument("--frame-source", default="file", choices=["file", "camera"])
    live.add_argument("--camera-device", default="")
    live.add_argument("--camera-backend", default="",
                     help="ffmpeg capture backend: dshow, v4l2 or avfoundation")
    live.add_argument("--width", type=int, default=1280)
    live.add_argument("--height", type=int, default=720)
    live.add_argument("--fps", type=int, default=30)
    live.add_argument("--gop", type=int, default=30)
    live.add_argument("--max-frames", type=int, default=None)
    live.add_argument("--frag-keyframe", action="store_true",
                     help="fragment per keyframe instead of per frame")
    live.add_argument("--muxer", default="ffmpeg", choices=["ffmpeg", "inprocess"],
                     help="ffmpeg: the widely-deployed muxer, best for proving the NIM "
                          "accepts the container. inprocess: PyAV plus streamexp.fmp4, "
                          "roughly 4 ms of client-side latency instead of 73 ms "
                          "(default: %(default)s)")

    mock = parser.add_argument_group("mock server")
    mock.add_argument("--mock-mode", default="streaming",
                      choices=["streaming", "transactional"])
    mock.add_argument("--mock-port", type=int, default=0)
    mock.add_argument("--mock-chunk-delay-ms", type=float, default=0.0)
    mock.add_argument("--mock-first-output-delay-ms", type=float, default=0.0)
    return parser


def resolve_client(args: argparse.Namespace) -> Path:
    return args.nvidia_client or (args.workspace / "nvidia-client")


def make_options(args: argparse.Namespace, label: str) -> RunOptions:
    return RunOptions(
        channel=ChannelSpec(
            target=args.target,
            mode=args.mode,
            ssl_root_cert=args.ssl_root_cert,
            ssl_key=args.ssl_key,
            ssl_cert=args.ssl_cert,
            function_id=args.function_id or None,
        ),
        clone_dir=resolve_client(args),
        workspace=args.workspace,
        label=label,
        source_path=args.source,
        chunk_size=args.chunk_size,
        send_config=not args.no_config,
        encoder=livesource.LiveEncoderConfig(
            width=args.width,
            height=args.height,
            fps=args.fps,
            gop=args.gop,
            fragment_per_frame=not args.frag_keyframe,
            muxer=args.muxer,
        ),
        frame_source=args.frame_source,
        camera_device=args.camera_device,
        camera_backend=args.camera_backend,
        max_frames=args.max_frames,
        decode_check=not args.no_decode_check,
    )


def command_preflight(args: argparse.Namespace) -> int:
    report = preflight.run(
        target=args.target,
        clone_dir=resolve_client(args),
        endpoint_confirmed=args.i_have_confirmed_nim_endpoint,
        preview_mode=args.mode == "preview",
    )
    print(json.dumps(report.as_dict(), indent=2))
    if not report.clear:
        print("\nPREFLIGHT NOT CLEAR — blocked by: "
              + ", ".join(c.name for c in report.blocked_by), file=sys.stderr)
        return 2
    print("\nPREFLIGHT CLEAR", file=sys.stderr)
    return 0


def _gate(args: argparse.Namespace) -> int:
    report = preflight.run(
        target=args.target,
        clone_dir=resolve_client(args),
        endpoint_confirmed=args.i_have_confirmed_nim_endpoint,
        preview_mode=args.mode == "preview",
    )
    if not report.clear:
        print(json.dumps(report.as_dict(), indent=2), file=sys.stderr)
        print("\nRefusing to run: preflight is not clear. A measurement taken "
              "without these preconditions would not be a Maxine result.",
              file=sys.stderr)
        return 2
    return 0


def command_stage(args: argparse.Namespace, stage: str) -> int:
    gate = _gate(args)
    if gate:
        return gate
    label = args.label or f"stage-{stage.lower()}"
    options = make_options(args, label)
    runner = run_stage_a if stage == "A" else run_stage_b
    payload = runner(options)
    print(json.dumps(payload, indent=2))
    return 0 if not payload["error"] else 1


def command_mock(args: argparse.Namespace) -> int:
    from streamexp import mockserver  # noqa: PLC0415

    interfaces = proto.load(resolve_client(args))
    server, port = mockserver.serve(
        interfaces,
        mockserver.MockConfig(
            mode=args.mock_mode,
            chunk_delay_ms=args.mock_chunk_delay_ms,
            first_output_delay_ms=args.mock_first_output_delay_ms,
        ),
        args.mock_port,
    )
    print(f"mock RedirectGaze ({args.mock_mode}) on 127.0.0.1:{port} — NOT MAXINE")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(0).wait()
    return 0


def command_selftest(args: argparse.Namespace) -> int:
    from streamexp.selftest import run_selftest  # noqa: PLC0415

    report = run_selftest(
        clone_dir=resolve_client(args),
        workspace=args.workspace / "selftest",
        width=args.width,
        height=args.height,
        fps=args.fps,
        seconds=max(1, (args.max_frames or 90) // max(1, args.fps)),
    )
    print(json.dumps(report, indent=2))
    return 0 if report["harness_self_verification"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.workspace = args.workspace.expanduser().resolve()
    if args.command == "preflight":
        return command_preflight(args)
    if args.command == "stage-a":
        return command_stage(args, "A")
    if args.command == "stage-b":
        return command_stage(args, "B")
    if args.command == "mock":
        return command_mock(args)
    return command_selftest(args)


if __name__ == "__main__":
    raise SystemExit(main())
