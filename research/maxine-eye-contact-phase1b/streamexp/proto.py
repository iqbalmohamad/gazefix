"""Load NVIDIA's own ``RedirectGaze`` service contract.

The harness never restates the wire protocol. It compiles and imports
``eyecontact.proto`` from a local clone of NVIDIA's ``nim-clients`` repository,
so the messages it sends are by construction the messages NVIDIA defines. If
the clone is missing, the harness stops and says so — it does not fall back to
a hand-written stub, because a hand-written stub would let a Phase 1B result be
produced against an interface NVIDIA does not actually serve.

The SHA-256 of the ``.proto`` that was compiled is recorded with every run, so
a later reader can tell which revision of the contract a measurement belongs to.
"""

from __future__ import annotations

import hashlib
import importlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

PROTO_RELATIVE = Path("eye-contact/protos/proto/nvidia/maxine/eyecontact/v1/eyecontact.proto")
INTERFACES_RELATIVE = Path("eye-contact/interfaces")

#: NVIDIA sends the MP4 in 64 KiB chunks (``eye-contact/scripts/constants.py``).
#: The harness uses the same size so chunking is not a variable between a
#: harness measurement and NVIDIA's own client.
DATA_CHUNK_SIZE = 64 * 1024


class ProtoError(RuntimeError):
    """Raised when NVIDIA's contract cannot be located or compiled."""


@dataclass(frozen=True)
class Interfaces:
    """The compiled contract, plus the provenance of the file it came from."""

    pb2: ModuleType
    pb2_grpc: ModuleType
    proto_path: Path
    proto_sha256: str
    interfaces_dir: Path

    def stub(self, channel):  # noqa: ANN001 - grpc.Channel, kept untyped to avoid the import
        return self.pb2_grpc.MaxineEyeContactServiceStub(channel)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def compile_protos(clone_dir: Path, force: bool = False) -> Path:
    """Compile NVIDIA's proto into ``<clone>/eye-contact/interfaces``.

    Uses ``grpc_tools.protoc`` with the same include path and output directory
    NVIDIA's own ``compile_protos.sh`` uses.
    """
    proto_path = clone_dir / PROTO_RELATIVE
    if not proto_path.is_file():
        raise ProtoError(
            f"NVIDIA proto not found at {proto_path}. Clone "
            "https://github.com/NVIDIA-Maxine/nim-clients.git and pass its path."
        )
    interfaces = clone_dir / INTERFACES_RELATIVE
    interfaces.mkdir(parents=True, exist_ok=True)
    generated = interfaces / "eyecontact_pb2_grpc.py"
    if generated.is_file() and not force:
        return interfaces

    try:
        from grpc_tools import protoc  # noqa: PLC0415 - optional, only needed to compile
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ProtoError(
            "grpcio-tools is required to compile NVIDIA's proto: pip install grpcio-tools"
        ) from exc

    include = proto_path.parent
    code = protoc.main(
        [
            "protoc",
            f"-I={include}",
            f"--python_out={interfaces}",
            f"--pyi_out={interfaces}",
            f"--grpc_python_out={interfaces}",
            str(proto_path),
        ]
    )
    if code != 0:
        raise ProtoError(f"protoc failed with exit code {code}")
    return interfaces


def load(clone_dir: Path, force_compile: bool = False) -> Interfaces:
    """Compile if needed, then import NVIDIA's generated modules."""
    clone_dir = clone_dir.expanduser().resolve()
    interfaces = compile_protos(clone_dir, force=force_compile)
    if str(interfaces) not in sys.path:
        sys.path.insert(0, str(interfaces))
    try:
        pb2 = importlib.import_module("eyecontact_pb2")
        pb2_grpc = importlib.import_module("eyecontact_pb2_grpc")
    except ImportError as exc:
        raise ProtoError(f"could not import NVIDIA's generated modules from {interfaces}: {exc}") from exc

    proto_path = clone_dir / PROTO_RELATIVE
    return Interfaces(
        pb2=pb2,
        pb2_grpc=pb2_grpc,
        proto_path=proto_path,
        proto_sha256=sha256_file(proto_path),
        interfaces_dir=interfaces,
    )


def clone_command(destination: Path) -> str:
    """The exact command an operator should run to obtain the contract."""
    return f"git clone https://github.com/NVIDIA-Maxine/nim-clients.git {destination}"


def git_revision(clone_dir: Path) -> str:
    """Commit SHA of the clone, so a run records which client revision it used."""
    try:
        result = subprocess.run(
            ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return "UNKNOWN"
    return result.stdout.strip() or "UNKNOWN"
