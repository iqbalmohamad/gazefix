"""Provisioning and integrity checks for the approved Face Landmarker bundle."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import tempfile
from typing import BinaryIO, Callable
from urllib.request import urlopen


FACE_LANDMARKER_MODEL_ID = "face_landmarker/float16/1"
FACE_LANDMARKER_MODEL_FILENAME = "face_landmarker.task"
FACE_LANDMARKER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
FACE_LANDMARKER_MODEL_SHA256 = (
    "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
)
FACE_LANDMARKER_MODEL_SIZE_BYTES = 3_758_596
FACE_LANDMARKER_MODEL_LICENSE = "Apache-2.0"
DEFAULT_FACE_LANDMARKER_MODEL_PATH = (
    Path(".models") / FACE_LANDMARKER_MODEL_FILENAME
)


class ModelAssetError(RuntimeError):
    """Raised when the approved model cannot be provisioned or verified."""


@dataclass(frozen=True, slots=True)
class VerifiedModelAsset:
    """Identity of a model file that passed the pinned integrity check."""

    path: Path
    sha256: str
    size_bytes: int
    model_id: str = FACE_LANDMARKER_MODEL_ID


def calculate_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return a lowercase SHA-256 digest without loading the bundle into memory."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_face_landmarker_model(path: Path) -> VerifiedModelAsset:
    """Verify that *path* is the exact model bundle approved for GazeFix M1."""

    model_path = Path(path)
    if not model_path.is_file():
        raise ModelAssetError(f"Face Landmarker model not found: {model_path}")

    size_bytes = model_path.stat().st_size
    actual_sha256 = calculate_sha256(model_path)
    if actual_sha256 != FACE_LANDMARKER_MODEL_SHA256:
        raise ModelAssetError(
            "Face Landmarker model SHA-256 mismatch: "
            f"expected {FACE_LANDMARKER_MODEL_SHA256}, got {actual_sha256}"
        )
    if size_bytes != FACE_LANDMARKER_MODEL_SIZE_BYTES:
        # The digest comparison is authoritative. Keep the size check explicit so
        # diagnostics also detect a stale manifest if the constants ever diverge.
        raise ModelAssetError(
            "Face Landmarker model size mismatch: "
            f"expected {FACE_LANDMARKER_MODEL_SIZE_BYTES}, got {size_bytes}"
        )
    return VerifiedModelAsset(
        path=model_path,
        sha256=actual_sha256,
        size_bytes=size_bytes,
    )


UrlOpener = Callable[..., BinaryIO]


def provision_face_landmarker_model(
    destination: Path = DEFAULT_FACE_LANDMARKER_MODEL_PATH,
    *,
    opener: UrlOpener = urlopen,
    timeout_seconds: float = 60.0,
) -> VerifiedModelAsset:
    """Download and atomically install the approved model after verification.

    The caller must invoke this operation explicitly. A valid existing bundle is
    reused, while an invalid existing file remains untouched unless a verified
    replacement has downloaded successfully.
    """

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    model_path = Path(destination)
    try:
        return verify_face_landmarker_model(model_path)
    except ModelAssetError:
        pass

    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{model_path.name}.",
            suffix=".download",
            dir=model_path.parent,
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            with opener(FACE_LANDMARKER_MODEL_URL, timeout=timeout_seconds) as source:
                shutil.copyfileobj(source, output)

        verified = verify_face_landmarker_model(temporary_path)
        temporary_path.replace(model_path)
        temporary_path = None
        return VerifiedModelAsset(
            path=model_path,
            sha256=verified.sha256,
            size_bytes=verified.size_bytes,
        )
    except ModelAssetError:
        raise
    except Exception as exc:
        raise ModelAssetError(
            f"Could not provision Face Landmarker model: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
