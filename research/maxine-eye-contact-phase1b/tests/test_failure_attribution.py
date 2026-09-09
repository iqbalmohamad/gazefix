"""A failed call must never be reported as a verdict on the service.

The experiment exists to answer one question, and the most damaging way to get
it wrong is to answer ``NO`` when the truth is "the call did not complete". Each
test here pins one of the paths that used to do exactly that.
"""

from __future__ import annotations

from pathlib import Path

import grpc
import pytest
from conftest import build_progressive_mp4

from streamexp import mockserver, source
from streamexp.channel import ChannelError, wait_until_ready
from streamexp.clock import RealtimeSchedule
from streamexp.progressive import ProgressiveMp4Reader
from streamexp.session import RedirectGazeSession, SessionResult
from streamexp.stages import _attribution
from streamexp.timing import Timeline


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(build_progressive_mp4([900] * 30))
    return path


def aborting_servicer(interfaces, code, details, after_bytes=0):
    class Aborting(interfaces.pb2_grpc.MaxineEyeContactServiceServicer):
        def RedirectGaze(self, request_iterator, context):  # noqa: N802
            seen = 0
            for request in request_iterator:
                if request.HasField("config"):
                    yield interfaces.pb2.RedirectGazeResponse(config=request.config)
                    continue
                if not request.HasField("video_file_data"):
                    continue
                seen += len(request.video_file_data)
                if seen >= after_bytes:
                    context.abort(code, details)
    return Aborting()


def run_against(interfaces, servicer, clip: Path):
    from streamexp import source as source_module

    server = grpc.server(__import__("concurrent.futures", fromlist=["x"]).ThreadPoolExecutor(4))
    interfaces.pb2_grpc.add_MaxineEyeContactServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            _profile, index = source_module.probe(clip)
            session = RedirectGazeSession(interfaces, interfaces.stub(channel))
            return session.run(
                source_module.paced_units(clip, index, 4096), RealtimeSchedule()
            )
    finally:
        server.stop(0).wait()


def test_a_server_failure_is_not_reported_as_no_streaming(interfaces, clip):
    """The blocker: an aborted call used to fabricate an EOS and report NO."""
    result = run_against(
        interfaces,
        aborting_servicer(interfaces, grpc.StatusCode.RESOURCE_EXHAUSTED, "busy", 8_000),
        clip,
    )
    assert result.error is not None
    assert result.output_before_eos() == "NOT MEASURED", (
        "a failed call must not read as evidence that the service cannot stream"
    )
    assert result.timeline.first("input_eos") is None, "EOS was never reached"
    assert result.timeline.first("input_aborted") is not None


def test_the_servers_status_survives_verbatim(interfaces, clip):
    result = run_against(
        interfaces,
        aborting_servicer(interfaces, grpc.StatusCode.INVALID_ARGUMENT, "bad container", 1),
        clip,
    )
    assert result.grpc_status == "INVALID_ARGUMENT"
    assert result.grpc_details == "bad container"
    assert _attribution(result)["blame"].startswith("SERVER")


def test_generator_exit_is_not_blamed_on_the_sender(interfaces, clip):
    """gRPC abandoning the request iterator is the RPC dying, not a sender fault."""
    result = run_against(
        interfaces,
        aborting_servicer(interfaces, grpc.StatusCode.INTERNAL, "boom", 1),
        clip,
    )
    assert "GeneratorExit" not in (result.error or "")
    assert (result.error or "").startswith("_MultiThreadedRendezvous") or "INTERNAL" in (
        result.error or ""
    )


def test_a_clean_run_reaches_eos_and_blames_nothing(interfaces, clip):
    server, port = mockserver.serve(interfaces, mockserver.MockConfig(mode="streaming"))
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            _profile, index = source.probe(clip)
            session = RedirectGazeSession(interfaces, interfaces.stub(channel))
            result = session.run(source.paced_units(clip, index, 4096), RealtimeSchedule())
    finally:
        server.stop(0).wait()
    assert result.timeline.first("input_eos") is not None
    assert result.timeline.first("input_aborted") is None
    assert _attribution(result)["blame"].startswith("NONE")


def _bare_result() -> SessionResult:
    return SessionResult(timeline=Timeline(), reader=ProgressiveMp4Reader())


def test_our_own_deadline_is_blamed_on_the_harness_not_the_server():
    result = _bare_result()
    result.error = "deadline"
    result.grpc_status = "DEADLINE_EXCEEDED"
    blame = _attribution(result)["blame"]
    assert blame.startswith("HARNESS")
    assert "--rpc-timeout" in blame


def test_an_interrupted_run_is_not_a_result():
    result = _bare_result()
    result.interrupted = True
    result.error = "KeyboardInterrupt: "
    assert _attribution(result)["blame"].startswith("OPERATOR")
    assert result.output_before_eos() == "NOT MEASURED"


def test_a_parser_fault_is_blamed_on_the_harness_and_says_so():
    """The transport worked; only our indexing failed. That is not a NIM failure."""
    result = _bare_result()
    result.reader_error = "Mp4Error: box 'xxxx' declares size 3"
    blame = _attribution(result)["blame"]
    assert blame.startswith("HARNESS PARSER")
    assert "do not read this as a service failure" in blame


def test_output_seen_before_eos_survives_a_later_failure():
    """If usable output appeared while still sending, that already happened."""
    result = _bare_result()
    result.timeline.mark("first_usable_frame")
    result.error = "the call later died"
    assert result.output_before_eos() == "YES"


def test_a_channel_that_never_becomes_ready_is_a_setup_error(tmp_path):
    channel = grpc.insecure_channel("127.0.0.1:1")
    try:
        with pytest.raises(ChannelError, match="did not become ready"):
            wait_until_ready(channel, timeout_s=1.0)
    finally:
        channel.close()


def test_the_channel_carries_no_keepalive_pings():
    """NVIDIA's client passes no channel options; pings could draw a GOAWAY
    exactly when the NIM goes quiet, which is what Stage A must observe."""
    from streamexp.channel import CHANNEL_OPTIONS

    names = [name for name, _value in CHANNEL_OPTIONS]
    assert not any("keepalive" in name for name in names)
    assert "grpc.max_receive_message_length" in names


def test_a_non_h264_source_is_refused_before_the_run(tmp_path: Path):
    path = tmp_path / "hevc.mp4"
    data = build_progressive_mp4([300, 300])
    # 'avc1' also appears in the ftyp brand list, so rewrite the LAST occurrence,
    # which is the stsd sample entry the codec is actually read from.
    cut = data.rfind(b"avc1")
    assert cut > 0
    path.write_bytes(data[:cut] + b"hvc1" + data[cut + 4 :])
    profile, _index = source.probe(path)
    assert profile.codec == "hvc1"
    from streamexp.stages import _check_stage_a_source

    with pytest.raises(source.SourceUnsuitable, match="not H.264"):
        _check_stage_a_source(profile)


# -- gaps found by the completeness critic ------------------------------


def test_an_unclassifiable_container_is_not_reported_as_moov_last():
    """Giving up on parsing must not become an observation about the service.

    The 'cannot classify' fallback exists to bound retention. Reusing MOOV_LAST
    for it turned a harness limitation into kill condition 3 OBSERVED.
    """
    from streamexp.progressive import Layout, ProgressiveMp4Reader
    from streamexp.stages import _determinations

    reader = ProgressiveMp4Reader()
    reader._unclassified_cap = 512
    reader.feed(b"\x00\x00\x00\x08free" + b"\xff" * 2000, 0.0)
    assert reader.layout is Layout.UNCLASSIFIED
    assert reader.classification_error

    result = SessionResult(timeline=Timeline(), reader=reader)
    determinations = _determinations(result, "A", 10)
    assert determinations["kill_condition_3_whole_file_interface"].startswith("NOT MEASURED")
    assert determinations["output_indexable_before_eos"] == "NOT MEASURED"


def test_a_parser_fault_is_not_a_hard_no():
    result = _bare_result()
    result.timeline.mark("input_eos")
    result.reader_error = "Mp4Error: box 'zzzz' declares size 3"
    assert result.output_before_eos() == "NOT MEASURED"


def test_an_unclassified_container_is_not_a_hard_no():
    from streamexp.progressive import Layout, ProgressiveMp4Reader

    reader = ProgressiveMp4Reader()
    reader.layout = Layout.UNCLASSIFIED
    reader.classification_error = "gave up"
    result = SessionResult(timeline=Timeline(), reader=reader)
    result.timeline.mark("input_eos")
    assert result.output_before_eos() == "NOT MEASURED"


def test_a_sender_failure_is_blamed_on_the_client_not_the_server():
    """The field built to prevent misattribution was itself misattributing."""
    result = _bare_result()
    result.sender_error = "sender: RuntimeError: camera vanished"
    result.error = result.sender_error
    result.grpc_status = "UNKNOWN"
    attribution = _attribution(result)
    assert attribution["blame"].startswith("CLIENT/HARNESS")
    assert "camera vanished" in attribution["blame"]
    assert attribution["sender_error"]


def test_stage_b_refuses_a_run_that_produced_no_frames(interfaces, nvidia_clone, tmp_path):
    """ffmpeg emits a valid init segment for an empty track and exits 0, so a
    zero-frame run used to report a confident YES built on no video at all."""
    from streamexp import livesource, mockserver
    from streamexp.stages import RunOptions, run_stage_b

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(build_progressive_mp4([900] * 30))

    server, port = mockserver.serve(interfaces, mockserver.MockConfig(mode="streaming"))
    try:
        with pytest.raises(livesource.LiveSourceError, match="no frames"):
            run_stage_b(
                RunOptions(
                    channel=__import__(
                        "streamexp.channel", fromlist=["ChannelSpec"]
                    ).ChannelSpec(target=f"127.0.0.1:{port}", mode="insecure"),
                    clone_dir=nvidia_clone,
                    workspace=tmp_path,
                    label="zero",
                    source_path=clip,
                    encoder=livesource.LiveEncoderConfig(width=64, height=48, fps=30),
                    max_frames=0,
                )
            )
    finally:
        server.stop(0).wait()


def test_the_default_preset_does_not_change_the_h264_profile():
    """ultrafast emits Constrained Baseline; every other preset emits High.

    Stage B is meant to vary the container against Stage A, not the coded
    bitstream profile as well.
    """
    from streamexp.livesource import LiveEncoderConfig

    assert LiveEncoderConfig().preset != "ultrafast"


def test_stage_b_refuses_a_run_longer_than_its_own_deadline(nvidia_clone, tmp_path: Path):
    from streamexp import livesource
    from streamexp.channel import ChannelSpec
    from streamexp.stages import RunOptions, run_stage_b

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(build_progressive_mp4([900] * 300))
    with pytest.raises(source.SourceUnsuitable, match="--max-frames"):
        run_stage_b(
            RunOptions(
                channel=ChannelSpec(target="127.0.0.1:1", mode="insecure"),
                clone_dir=nvidia_clone,
                workspace=tmp_path,
                label="long",
                source_path=clip,
                encoder=livesource.LiveEncoderConfig(width=64, height=48, fps=30),
                rpc_timeout_s=2.0,
            )
        )
