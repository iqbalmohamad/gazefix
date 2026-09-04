"""Model-asset manifest, integrity verification, and explicit provisioning.

The face landmarker model is not shipped in the repository or downloaded at
runtime. ``verify_model`` is what the tracker runs at initialisation (offline,
a few milliseconds for a 3.7 MB file); ``provision_model`` is only ever called
by the explicit setup command (``scripts/fetch_model.py``). A file that is
missing, truncated, or not byte-identical to the pinned release yields a
``ModelAssetError`` whose message says what to do; nothing here reads or
writes webcam frames.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import math
import os
from pathlib import Path
import tempfile
import time
from typing import BinaryIO, Callable
from urllib.request import urlopen


logger = logging.getLogger(__name__)

# Streaming a download or a hash never holds the whole file in memory.
_CHUNK_BYTES = 1024 * 1024
# A download that grows past the expected size is aborted: the manifest pins
# an exact byte count, so anything larger cannot verify and must not fill the
# disk.
_DOWNLOAD_SLACK_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """Identity of one pinned, verified model release."""

    name: str
    filename: str
    url: str
    size_bytes: int
    sha256: str
    license: str
    version: str
    source: str

    def path_in(self, directory: Path) -> Path:
        return Path(directory) / self.filename


FACE_LANDMARKER = ModelManifest(
    name="MediaPipe Face Landmarker (float16) task bundle",
    filename="face_landmarker.task",
    url=(
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
    size_bytes=3_758_596,
    sha256="64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    license="Apache-2.0 (model cards: BlazeFace short-range, Face Mesh V2, Blendshape V2)",
    version="face_landmarker/float16/1 (object last modified 2023-05-03)",
    source="Google MediaPipe model storage (mediapipe-models bucket)",
)

SETUP_COMMAND = "python scripts/fetch_model.py"


class ModelAssetError(RuntimeError):
    """The model file cannot be used; ``kind`` classifies why and the message is actionable."""

    def __init__(self, kind: str, message: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.path = path


@dataclass(frozen=True, slots=True)
class VerifiedModel:
    """A model file that was byte-verified against its manifest."""

    manifest: ModelManifest
    path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ProvisionResult:
    verified: VerifiedModel
    downloaded: bool
    download_ms: float


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(path: Path, manifest: ModelManifest = FACE_LANDMARKER) -> VerifiedModel:
    """Return the verified identity of ``path`` or raise ``ModelAssetError``.

    Checks existence, exact size, then the SHA-256 digest. The size check
    comes first so a truncated download is reported as such without hashing.
    """

    model_path = Path(path)
    try:
        exists = model_path.is_file()
    except OSError as exc:
        raise ModelAssetError(
            "unreadable", f"{model_path} could not be read: {exc}", model_path
        ) from exc
    if not exists:
        raise ModelAssetError(
            "missing",
            f"{manifest.filename} not found at {model_path}. Run `{SETUP_COMMAND}` "
            f"once to download it from the documented source, or point "
            f"--model-dir at the directory that contains it.",
            model_path,
        )
    try:
        size = model_path.stat().st_size
        if size != manifest.size_bytes:
            raise ModelAssetError(
                "size",
                f"{model_path} is {size} bytes but the pinned {manifest.version} "
                f"release is {manifest.size_bytes} bytes (truncated or a different "
                f"version). Run `{SETUP_COMMAND}` to replace it.",
                model_path,
            )
        digest = sha256_of(model_path)
    except OSError as exc:
        raise ModelAssetError(
            "unreadable", f"{model_path} could not be read: {exc}", model_path
        ) from exc
    if digest != manifest.sha256:
        raise ModelAssetError(
            "checksum",
            f"{model_path} has SHA-256 {digest}, expected {manifest.sha256} for the "
            f"pinned {manifest.version} release. Run `{SETUP_COMMAND}` to replace it.",
            model_path,
        )
    return VerifiedModel(manifest, model_path, size, digest)


UrlOpener = Callable[..., BinaryIO]


def provision_model(
    directory: Path,
    manifest: ModelManifest = FACE_LANDMARKER,
    *,
    opener: UrlOpener = urlopen,
    timeout_s: float = 60.0,
    force: bool = False,
) -> ProvisionResult:
    """Download the pinned model into ``directory`` unless a verified copy exists.

    Explicit setup only; the application never calls this. The download is
    streamed to a temporary file in the same directory, bounded by the
    manifest size, verified, and then moved into place atomically, so a
    failed or interrupted download leaves no partial model behind and a
    valid existing file is never damaged. ``opener`` is ``urllib``'s
    ``urlopen`` by default and is injectable for tests.
    """

    if not timeout_s > 0 or math.isnan(timeout_s):
        raise ValueError("timeout_s must be positive")
    target_dir = Path(directory)
    target = manifest.path_in(target_dir)
    if not force:
        try:
            return ProvisionResult(verify_model(target, manifest), downloaded=False, download_ms=0.0)
        except ModelAssetError as exc:
            logger.info(
                "Model asset needs provisioning",
                extra={"event": "model_provision_needed", "reason": exc.kind, "path": str(target)},
            )
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ModelAssetError(
            "directory", f"Model directory {target_dir} cannot be used: {exc}", target
        ) from exc
    started = time.perf_counter()
    temporary: Path | None = None
    try:
        try:
            output = tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{manifest.filename}.", suffix=".download",
                dir=target_dir, delete=False,
            )
        except OSError as exc:
            raise ModelAssetError(
                "install", f"Cannot write into the model directory {target_dir}: {exc}", target
            ) from exc
        with output:
            temporary = Path(output.name)
            limit = manifest.size_bytes + _DOWNLOAD_SLACK_BYTES
            written = 0
            with opener(manifest.url, timeout=timeout_s) as source:
                while True:
                    chunk = source.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limit:
                        raise ModelAssetError(
                            "download",
                            f"Download from {manifest.url} exceeded the expected "
                            f"{manifest.size_bytes} bytes; aborted.",
                            target,
                        )
                    try:
                        output.write(chunk)
                    except OSError as exc:
                        raise ModelAssetError(
                            "install", f"Cannot write the model into {target_dir}: {exc}", target
                        ) from exc
        try:
            verified = verify_model(temporary, manifest)
        except ModelAssetError as exc:
            # The temporary file is removed below; report the download, not
            # a path that no longer exists.
            raise ModelAssetError(
                exc.kind,
                f"The file downloaded from {manifest.url} did not verify ({exc.kind}); "
                f"nothing was installed at {target}. Check the network path and retry.",
                target,
            ) from exc
        try:
            os.replace(temporary, target)
        except OSError as exc:
            raise ModelAssetError(
                "install",
                f"Downloaded and verified, but {target} could not be replaced: {exc}. "
                "Close GazeFix if it is running (the model file may be in use) and retry.",
                target,
            ) from exc
        temporary = None
        download_ms = round((time.perf_counter() - started) * 1000.0, 1)
        logger.info(
            "Model asset downloaded and verified",
            extra={
                "event": "model_provisioned",
                "path": str(target),
                "sha256": verified.sha256,
                "size_bytes": verified.size_bytes,
                "download_ms": download_ms,
            },
        )
        return ProvisionResult(
            VerifiedModel(manifest, target, verified.size_bytes, verified.sha256),
            downloaded=True,
            download_ms=download_ms,
        )
    except ModelAssetError:
        raise
    except Exception as exc:
        raise ModelAssetError(
            "download", f"Could not download {manifest.url}: {exc}", target
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
