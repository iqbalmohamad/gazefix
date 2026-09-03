from __future__ import annotations

from io import BytesIO
import hashlib
from pathlib import Path

import pytest

from gazefix.tracking import model_asset
from gazefix.tracking.model_asset import ModelAssetError


def approve_bytes(monkeypatch: pytest.MonkeyPatch, content: bytes) -> None:
    monkeypatch.setattr(
        model_asset,
        "FACE_LANDMARKER_MODEL_SHA256",
        hashlib.sha256(content).hexdigest(),
    )
    monkeypatch.setattr(
        model_asset,
        "FACE_LANDMARKER_MODEL_SIZE_BYTES",
        len(content),
    )


def test_model_asset_verification_checks_digest_and_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = b"approved model bytes"
    approve_bytes(monkeypatch, approved)
    model_path = tmp_path / "face_landmarker.task"
    model_path.write_bytes(approved)

    verified = model_asset.verify_face_landmarker_model(model_path)

    assert verified.path == model_path
    assert verified.sha256 == hashlib.sha256(approved).hexdigest()
    assert verified.size_bytes == len(approved)

    model_path.write_bytes(b"tampered")
    with pytest.raises(ModelAssetError, match="SHA-256 mismatch"):
        model_asset.verify_face_landmarker_model(model_path)


def test_explicit_provisioning_verifies_before_atomic_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = b"downloaded approved model"
    approve_bytes(monkeypatch, approved)
    destination = tmp_path / "models" / "face_landmarker.task"
    calls: list[tuple[str, float]] = []

    def opener(url: str, *, timeout: float) -> BytesIO:
        calls.append((url, timeout))
        return BytesIO(approved)

    verified = model_asset.provision_face_landmarker_model(
        destination,
        opener=opener,
        timeout_seconds=12.0,
    )

    assert destination.read_bytes() == approved
    assert verified.path == destination
    assert calls == [(model_asset.FACE_LANDMARKER_MODEL_URL, 12.0)]
    assert not tuple(destination.parent.glob("*.download"))


def test_failed_provisioning_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = b"approved"
    approve_bytes(monkeypatch, approved)
    destination = tmp_path / "face_landmarker.task"
    destination.write_bytes(b"existing invalid model")

    def opener(_url: str, *, timeout: float) -> BytesIO:
        assert timeout == 60.0
        return BytesIO(b"also invalid")

    with pytest.raises(ModelAssetError, match="SHA-256 mismatch"):
        model_asset.provision_face_landmarker_model(destination, opener=opener)

    assert destination.read_bytes() == b"existing invalid model"
    assert not tuple(tmp_path.glob("*.download"))


def test_digest_streaming_validates_chunk_size(tmp_path: Path) -> None:
    path = tmp_path / "asset"
    path.write_bytes(b"abc")

    assert model_asset.calculate_sha256(path, chunk_size=1) == hashlib.sha256(
        b"abc"
    ).hexdigest()
    with pytest.raises(ValueError, match="positive"):
        model_asset.calculate_sha256(path, chunk_size=0)
