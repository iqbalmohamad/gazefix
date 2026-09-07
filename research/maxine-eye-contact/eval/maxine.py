"""Frozen Maxine Eye Contact invocation (S4, S9, S10).

Design decision: this module *wraps* NVIDIA's own published Eye Contact client
rather than reimplementing the gRPC protocol. The assignment forbids relying on
a remembered API schema or inventing a request format, and NVIDIA's client is
the authoritative implementation of ``nvidia.maxine.eyecontact.v1``. Wrapping it
means the request GazeFix sends is by construction the request NVIDIA defines.

The frozen Phase 1A profile passes **no behaviour or encoding parameter** at
all, so every applied value is NVIDIA's own default. That is the "official /
default behaviour" the protocol requires, and it is the only choice that cannot
be accused of tuning Maxine in its own favour.

The credential never appears on a command line. NVIDIA's client takes
``--api-key`` as an argument, which would expose the key in the process table
and in any captured command string, so this module reads it from the
environment and hands it to the child process through its environment instead,
via a tiny generated launcher that supplies the argument in-process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .redaction import REDACTED, redact

#: Environment variable this package reads the NGC / NVIDIA API key from.
API_KEY_ENV = "NVIDIA_API_KEY"

#: Path to the recorded NVIDIA API specification.
SPEC_PATH = Path(__file__).resolve().parents[1] / "manifests" / "nvidia-api-spec.json"

#: Fallbacks used only if the spec cannot be read. The spec is the source of
#: truth so the endpoint can be corrected from evidence without touching code.
_FALLBACK_TARGET = "grpc.nvcf.nvidia.com:443"
_FALLBACK_FUNCTION_ID = "15c6f1a0-3843-4cde-b5bc-803a4966fbb6"


def load_spec(path=None):
    """Read the recorded NVIDIA API specification."""
    return json.loads(Path(path or SPEC_PATH).read_text(encoding="utf-8"))


def _endpoint():
    try:
        service = load_spec().get("service") or {}
    except (OSError, ValueError):
        return _FALLBACK_TARGET, _FALLBACK_FUNCTION_ID
    return (service.get("target") or _FALLBACK_TARGET,
            service.get("function_id") or _FALLBACK_FUNCTION_ID)


HOSTED_TARGET, HOSTED_FUNCTION_ID = _endpoint()

#: The frozen configuration profile. ``parameter_flags`` is empty on purpose.
FROZEN_PROFILE = {
    "profile_id": "nvidia-client-defaults",
    "description": "NVIDIA's published Eye Contact client invoked with no "
                   "behaviour or encoding parameter flag, so every applied "
                   "value is NVIDIA's own default.",
    "parameter_flags": (),
    "preview_mode": True,
    "target": HOSTED_TARGET,
    "function_id": HOSTED_FUNCTION_ID,
}

#: Phrase NVIDIA's client prints instead of failing; see the known-defect note
#: in manifests/nvidia-api-spec.json.
CLIENT_SWALLOWED_ERROR = "An error occurred:"

FTYP = b"ftyp"
MOOV = b"moov"


class CredentialMissing(RuntimeError):
    """Raised when the NVIDIA credential is not present in the environment."""


def api_key_present(env=None):
    """Whether a credential is available, without reading its value out."""
    env = os.environ if env is None else env
    value = env.get(API_KEY_ENV)
    return bool(value and value.strip())


def require_api_key(env=None):
    """Return the credential or raise with actionable, secret-free guidance."""
    env = os.environ if env is None else env
    value = (env.get(API_KEY_ENV) or "").strip()
    if not value:
        raise CredentialMissing(
            f"{API_KEY_ENV} is not set. Obtain an NVIDIA API key from the "
            "NVIDIA API catalogue and export it in the shell that runs this "
            f"step, for example (PowerShell): $env:{API_KEY_ENV} = '<key>'. "
            "Never place the key in a file inside this repository.")
    return value


def is_streamable(path, probe_bytes=64 * 1024):
    """Whether an MP4 has its ``moov`` atom before ``mdat`` (faststart).

    NVIDIA's client requires ``--streaming`` for such files and rejects it for
    the others, so the flag is an input property, not a tuning knob. The check
    mirrors the intent of NVIDIA's own ``check_streamable`` without importing it.
    """
    with Path(path).open("rb") as stream:
        head = stream.read(probe_bytes)
    ftyp = head.find(FTYP)
    if ftyp < 0:
        return False
    moov = head.find(MOOV, ftyp)
    mdat = head.find(b"mdat", ftyp)
    if moov < 0:
        return False
    return mdat < 0 or moov < mdat


def build_client_argv(client_script, source, output, streaming):
    """Build NVIDIA's client argv for the frozen profile, without the key.

    ``--api-key`` is deliberately absent: it is injected in-process by the
    launcher so the credential never reaches a command line.
    """
    argv = [str(client_script),
            "--preview-mode",
            "--target", HOSTED_TARGET,
            "--function-id", HOSTED_FUNCTION_ID,
            "--input", str(source),
            "--output", str(output)]
    if streaming:
        argv.append("--streaming")
    return argv


_LAUNCHER = """\
import os, runpy, sys
# Inject NVIDIA's --api-key from the environment so the credential never
# appears on a command line or in a process listing.
key = os.environ.pop({env!r}, "")
if not key:
    sys.stderr.write("credential missing in launcher environment\\n")
    raise SystemExit(2)
sys.argv = [{script!r}] + sys.argv[1:] + ["--api-key", key]
sys.path.insert(0, os.path.dirname(os.path.abspath({script!r})))
runpy.run_path({script!r}, run_name="__main__")
"""


def launcher_source(client_script):
    """Source of the in-process launcher that supplies ``--api-key``."""
    return _LAUNCHER.format(env=API_KEY_ENV, script=str(client_script))


def run_clip(client_script, source, output, launcher_path, env=None,
             python_executable=None, cwd=None, timeout=1800, runner=None,
             clock=None):
    """Run one clip through the hosted endpoint under the frozen profile.

    Returns a record with timing, exit status, redacted output and the
    success determination. Nothing returned by this function contains the key.
    """
    env = dict(os.environ if env is None else env)
    key = (env.get(API_KEY_ENV) or "").strip()
    if not key:
        raise CredentialMissing(
            f"{API_KEY_ENV} is not set in the environment for this run")

    python_executable = python_executable or sys.executable
    streaming = is_streamable(source)
    client_argv = build_client_argv(client_script, source, output, streaming)
    command = [str(python_executable), str(launcher_path), *client_argv[1:]]

    clock = clock or time.time
    started = clock()
    completed = (runner or _default_runner)(command, cwd, env, timeout)
    finished = clock()

    stdout = completed.get("stdout") or ""
    stderr = completed.get("stderr") or ""
    out_path = Path(output)
    size = out_path.stat().st_size if out_path.is_file() else 0
    swallowed = CLIENT_SWALLOWED_ERROR in stdout or CLIENT_SWALLOWED_ERROR in stderr

    failures = []
    if completed.get("returncode") != 0:
        failures.append(f"client exited {completed.get('returncode')}")
    if not out_path.is_file():
        failures.append("no output file was written")
    elif size == 0:
        failures.append("output file is empty")
    if swallowed:
        failures.append("NVIDIA client reported a swallowed error on its output")

    return {
        "source": str(source).replace("\\", "/"),
        "output": str(output).replace("\\", "/"),
        "streaming_mode": streaming,
        "profile": {k: (list(v) if isinstance(v, tuple) else v)
                    for k, v in FROZEN_PROFILE.items()},
        # The recorded command is the redacted one; the key was never in it.
        "command": [redact(str(part)) for part in command],
        "api_key_source": f"environment variable {API_KEY_ENV} ({REDACTED})",
        "returncode": completed.get("returncode"),
        "stdout_tail": redact(stdout[-4000:]),
        "stderr_tail": redact(stderr[-4000:]),
        "output_bytes": size,
        "hosted_turnaround_s": round(finished - started, 3),
        "hosted_turnaround_label": "HOSTED BATCH/API TURNAROUND - NOT REALTIME LATENCY",
        "success": not failures,
        "failures": failures,
    }


def _default_runner(command, cwd, env, timeout):
    try:
        completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                   text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "timeout expired"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": None, "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}"}
    return {"returncode": completed.returncode, "stdout": completed.stdout,
            "stderr": completed.stderr}
