"""gRPC channel construction for the three target shapes.

Mirrors the modes NVIDIA's own client supports, and nothing else:

``insecure``
    A self-hosted NIM on a trusted network, ``--ssl-mode DISABLED``.
``tls`` / ``mtls``
    A self-hosted NIM behind TLS, with the same file arguments NVIDIA uses.
``preview``
    NVIDIA's hosted NVCF developer-preview function. **Not the Phase 1B
    route** — kept only so a measurement against it is possible and clearly
    labelled, never as a substitute when the self-hosted NIM is unavailable.

The credential, when one is used, is read from ``NVIDIA_API_KEY`` in the
environment and placed only in call metadata. It never reaches a command line,
a manifest, an artifact, or a log.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

#: Channel options sized for 64 KiB payloads with headroom, matching what a
#: NIM deployment is expected to accept. Kept explicit so a message-size
#: failure is never mistaken for a service limitation.
CHANNEL_OPTIONS: Sequence[tuple[str, Any]] = (
    ("grpc.max_send_message_length", 32 * 1024 * 1024),
    ("grpc.max_receive_message_length", 32 * 1024 * 1024),
)
# Only message-size limits, which widen what is accepted and change nothing on
# the wire. Deliberately NO HTTP/2 keepalive: NVIDIA's client passes no channel
# options at all, and a gRPC server's default minimum received-ping interval is
# five minutes with two strikes before GOAWAY(too_many_pings). A server clears
# that strike counter only when it writes frames — so 30-second pings would be
# harmless while the NIM streams and would kill the call precisely when it went
# quiet, which is the one behaviour Stage A exists to observe.


class ChannelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChannelSpec:
    target: str
    mode: str = "insecure"
    ssl_root_cert: Path | None = None
    ssl_key: Path | None = None
    ssl_cert: Path | None = None
    function_id: str | None = None

    def describe(self) -> dict[str, Any]:
        """Connection description safe to write into an artifact."""
        return {
            "target": self.target,
            "mode": self.mode,
            "function_id": self.function_id or "",
            "credential_source": "NVIDIA_API_KEY environment variable"
            if self.mode == "preview"
            else "none",
        }


def wait_until_ready(channel, timeout_s: float = 30.0) -> None:
    """Block until the channel is actually usable, or raise.

    A TCP connect to the Triton frontend succeeds as soon as the socket is
    listening, which can precede the model being READY, and nothing re-checks
    between preflight and the RPC. Establishing the channel first turns a
    connection race into a setup error with no determination attached, instead
    of a failed measurement that reads like a verdict on the service.
    """
    import grpc  # noqa: PLC0415

    try:
        grpc.channel_ready_future(channel).result(timeout=timeout_s)
    except grpc.FutureTimeoutError as exc:
        raise ChannelError(
            f"channel did not become ready within {timeout_s:.0f}s. The port "
            "accepts TCP but no gRPC service answered; check the NIM is serving "
            "and its model is READY before running a stage."
        ) from exc


def build(spec: ChannelSpec):  # noqa: ANN201 - returns grpc.Channel
    import grpc  # noqa: PLC0415 - imported here so the module is importable without it

    if spec.mode == "insecure":
        return grpc.insecure_channel(spec.target, options=list(CHANNEL_OPTIONS))
    if spec.mode == "preview":
        return grpc.secure_channel(
            spec.target, grpc.ssl_channel_credentials(), options=list(CHANNEL_OPTIONS)
        )
    if spec.mode == "tls":
        if spec.ssl_root_cert is None:
            raise ChannelError("tls mode requires --ssl-root-cert")
        credentials = grpc.ssl_channel_credentials(
            root_certificates=spec.ssl_root_cert.read_bytes()
        )
        return grpc.secure_channel(spec.target, credentials, options=list(CHANNEL_OPTIONS))
    if spec.mode == "mtls":
        if not (spec.ssl_root_cert and spec.ssl_key and spec.ssl_cert):
            raise ChannelError("mtls mode requires --ssl-root-cert, --ssl-key and --ssl-cert")
        credentials = grpc.ssl_channel_credentials(
            root_certificates=spec.ssl_root_cert.read_bytes(),
            private_key=spec.ssl_key.read_bytes(),
            certificate_chain=spec.ssl_cert.read_bytes(),
        )
        return grpc.secure_channel(spec.target, credentials, options=list(CHANNEL_OPTIONS))
    raise ChannelError(f"unknown channel mode {spec.mode!r}")


def call_metadata(spec: ChannelSpec) -> tuple[tuple[str, str], ...] | None:
    """Per-call metadata, constructed exactly as NVIDIA's ``utils.py`` does."""
    if spec.mode != "preview":
        return None
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        raise ChannelError("preview mode requires NVIDIA_API_KEY in the environment")
    if not spec.function_id:
        raise ChannelError("preview mode requires --function-id")
    return (
        ("authorization", f"Bearer {key}"),
        ("function-id", spec.function_id),
    )
