"""A local test double that speaks the real ``RedirectGaze`` contract.

**This is not Maxine, and no measurement taken against it is a Maxine result.**
It exists for one purpose: to prove that the harness itself is correct — that
it really keeps one RPC open, really paces its input, really reads responses
while still sending, really indexes arriving frames, really detects the case
where nothing is usable before end of stream, and really holds no unbounded
queue.

It is compiled from NVIDIA's own ``.proto``, so the messages it exchanges are
the real ones; what it does with them is deliberately trivial. Two behaviours
are offered because the harness must be shown to distinguish them:

``streaming``
    Echo input bytes back as they arrive, after an optional per-chunk delay.
    A harness that works will report usable output before input EOS.

``transactional``
    Retain everything until the client half-closes, then emit. A harness that
    works will report **no** usable output before input EOS — the Stage A kill
    signal — rather than quietly waiting.
"""

from __future__ import annotations

import time
from concurrent import futures
from dataclasses import dataclass
from typing import Any, Iterator

CHUNK = 64 * 1024


@dataclass
class MockConfig:
    mode: str = "streaming"
    """``streaming`` or ``transactional``."""
    chunk_delay_ms: float = 0.0
    """Simulated per-chunk server work."""
    first_output_delay_ms: float = 0.0
    """Simulated model warm-up before the first output byte."""
    echo_config: bool = True


def build_servicer(interfaces: Any, config: MockConfig):
    """Create a servicer class bound to NVIDIA's generated messages."""
    pb2 = interfaces.pb2
    pb2_grpc = interfaces.pb2_grpc

    class MockEyeContactService(pb2_grpc.MaxineEyeContactServiceServicer):
        def RedirectGaze(self, request_iterator, context) -> Iterator[Any]:  # noqa: N802
            started = time.perf_counter()
            emitted_any = False
            buffered = bytearray()

            for request in request_iterator:
                if request.HasField("config"):
                    if config.echo_config:
                        yield pb2.RedirectGazeResponse(config=request.config)
                    continue
                if not request.HasField("video_file_data"):
                    continue
                payload = request.video_file_data

                if config.mode == "transactional":
                    buffered.extend(payload)
                    continue

                if not emitted_any and config.first_output_delay_ms:
                    time.sleep(config.first_output_delay_ms / 1000.0)
                if config.chunk_delay_ms:
                    time.sleep(config.chunk_delay_ms / 1000.0)
                emitted_any = True
                yield pb2.RedirectGazeResponse(video_file_data=bytes(payload))

            if config.mode == "transactional":
                if config.first_output_delay_ms:
                    time.sleep(config.first_output_delay_ms / 1000.0)
                for offset in range(0, len(buffered), CHUNK):
                    if config.chunk_delay_ms:
                        time.sleep(config.chunk_delay_ms / 1000.0)
                    yield pb2.RedirectGazeResponse(
                        video_file_data=bytes(buffered[offset : offset + CHUNK])
                    )
            context.set_trailing_metadata(
                (("mock-elapsed-s", f"{time.perf_counter() - started:.3f}"),)
            )

    return MockEyeContactService()


def serve(interfaces: Any, config: MockConfig, port: int = 0) -> tuple[Any, int]:
    """Start the mock on ``port`` (0 picks a free one). Returns ``(server, port)``."""
    import grpc  # noqa: PLC0415 - only needed when the mock is actually used

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=4),
        options=[
            ("grpc.max_send_message_length", 32 * 1024 * 1024),
            ("grpc.max_receive_message_length", 32 * 1024 * 1024),
        ],
    )
    interfaces.pb2_grpc.add_MaxineEyeContactServiceServicer_to_server(
        build_servicer(interfaces, config), server
    )
    bound = server.add_insecure_port(f"127.0.0.1:{port}")
    server.start()
    return server, bound
