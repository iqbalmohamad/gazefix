"""Blocking precondition gate.

Phase 1A stopped because three preconditions were absent from the engineering
environment. Phase 1B's preconditions are different and stricter, and the same
discipline applies: the harness refuses to run rather than produce a number
that looks like a Maxine measurement but is not one.

Two of these checks cannot be cleared by software and are deliberately left
that way:

``nim-endpoint-confirmed``
    A human must confirm that a **self-hosted** Eye Contact NIM is actually
    serving at the target. The Phase 1A record documents unresolved
    contradictory evidence about the hosted developer-preview endpoint's
    lifetime; the Phase 1B route is explicitly the self-hosted NIM, and no
    reachability probe can tell a live NIM from anything else answering on a
    port.

``client-has-no-nvidia-requirement``
    Recorded, not asserted. The PRD forbids requiring NVIDIA or CUDA hardware
    on the client. The harness reports whether a local NVIDIA GPU is present so
    that a result taken on a machine that happens to have one is never read as
    evidence that a client without one would work.
"""

from __future__ import annotations

import os
import shutil
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import proto


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    """``PASS`` / ``FAIL`` / ``UNKNOWN`` / ``INFO``."""
    detail: str
    blocking: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "status": self.status,
            "blocking": self.blocking,
            "detail": self.detail,
        }


@dataclass
class PreflightReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    @property
    def blocked_by(self) -> list[Check]:
        return [c for c in self.checks if c.blocking and c.status != "PASS"]

    @property
    def clear(self) -> bool:
        return not self.blocked_by

    def as_dict(self) -> dict[str, Any]:
        return {
            "clear": self.clear,
            "blocked_by": [c.name for c in self.blocked_by],
            "checks": [c.as_dict() for c in self.checks],
        }


def _tcp_reachable(target: str, timeout: float = 5.0) -> tuple[bool, str]:
    if ":" not in target:
        return False, f"target {target!r} is not host:port"
    host, _, port = target.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, f"TCP connect to {target} succeeded"
    except (OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def local_nvidia_gpu_present() -> bool:
    if shutil.which("nvidia-smi"):
        return True
    return any(Path("/dev").glob("nvidia*"))


def run(
    *,
    target: str,
    clone_dir: Path,
    endpoint_confirmed: bool,
    preview_mode: bool = False,
    require_ffmpeg: bool = True,
    require_reachable: bool = True,
) -> PreflightReport:
    report = PreflightReport()

    try:
        import grpc  # noqa: PLC0415 - presence is exactly what is being checked

        report.add(Check("grpcio-available", "PASS", f"grpcio {grpc.__version__}"))
    except ImportError:
        report.add(
            Check(
                "grpcio-available",
                "FAIL",
                "python -m pip install grpcio grpcio-tools",
            )
        )

    try:
        interfaces = proto.load(clone_dir)
        report.add(
            Check(
                "nvidia-proto-compiled",
                "PASS",
                f"{interfaces.proto_path} sha256={interfaces.proto_sha256} "
                f"clone={proto.git_revision(clone_dir)}",
            )
        )
    except proto.ProtoError as exc:
        report.add(
            Check(
                "nvidia-proto-compiled",
                "FAIL",
                f"{exc} — {proto.clone_command(clone_dir)}",
            )
        )

    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        report.add(
            Check(
                f"{tool}-on-path",
                "PASS" if found else "FAIL",
                found or f"{tool} not found; install a build and put it on PATH",
                blocking=require_ffmpeg,
            )
        )

    if require_reachable:
        ok, detail = _tcp_reachable(target)
        report.add(Check("target-tcp-reachable", "PASS" if ok else "FAIL", detail))
    else:
        report.add(
            Check("target-tcp-reachable", "PASS", "skipped: local mock run", blocking=False)
        )

    report.add(
        Check(
            "nim-endpoint-confirmed",
            "PASS" if endpoint_confirmed else "UNKNOWN",
            "A human must confirm a self-hosted Maxine Eye Contact NIM is serving at "
            f"{target} and record its image tag and version. Pass "
            "--i-have-confirmed-nim-endpoint once that is true."
            if not endpoint_confirmed
            else "operator confirmed a self-hosted NIM is serving at the target",
        )
    )

    if preview_mode:
        # The hosted developer-preview API is not the Phase 1B production
        # route. It is still gated here so that a run which uses it cannot
        # silently proceed without the credential it requires.
        has_key = bool(os.environ.get("NVIDIA_API_KEY"))
        report.add(
            Check(
                "nvidia-api-key-present",
                "PASS" if has_key else "FAIL",
                "NVIDIA_API_KEY is set in this shell (value never read into any artifact)"
                if has_key
                else "set NVIDIA_API_KEY in the shell that runs the experiment; never in a file",
            )
        )
        report.add(
            Check(
                "preview-mode-is-not-the-phase-1b-route",
                "INFO",
                "Phase 1B evaluates the self-hosted NIM. A preview-API measurement "
                "characterises NVIDIA's hosted function, not the Phase 1B backend.",
                blocking=False,
            )
        )

    gpu = local_nvidia_gpu_present()
    report.add(
        Check(
            "client-has-no-nvidia-requirement",
            "INFO",
            "no local NVIDIA GPU detected on this client — a passing run here is "
            "evidence the client needs none"
            if not gpu
            else "a local NVIDIA GPU IS present on this client; a passing run here does "
            "NOT establish that a client without one would work",
            blocking=False,
        )
    )

    return report
