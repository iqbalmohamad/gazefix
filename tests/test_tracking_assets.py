"""Model asset verification and explicit provisioning, entirely offline.

``provision_model`` takes an injectable ``opener`` in place of ``urlopen``, so
every download here is served from memory by ``RecordingOpener``; nothing in
this module touches the network, a webcam, or MediaPipe. The manifest under
test pins a few hundred known bytes instead of the real 3.7 MB release, with
its digest computed from those bytes, so the file runs in a fraction of a
second while exercising the same size, checksum, bound and cleanup rules.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import random
import subprocess
import sys
from urllib.error import URLError

import pytest

from gazefix.tracking import assets, provision
from gazefix.tracking.assets import (
    FACE_LANDMARKER,
    SETUP_COMMAND,
    ModelAssetError,
    ModelManifest,
    ProvisionResult,
    VerifiedModel,
    provision_model,
    sha256_of,
    verify_model,
)


# Private tuning constants of the module under test: the streaming chunk size
# (to build files that span more than one read) and the abort slack above the
# manifest size (to hit the download bound exactly).
CHUNK_BYTES = assets._CHUNK_BYTES
SLACK_BYTES = assets._DOWNLOAD_SLACK_BYTES

PAYLOAD = b"GazeFix tiny model fixture\n" * 12
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
MANIFEST = ModelManifest(
    name="tiny test model",
    filename="tiny_model.task",
    url="https://example.invalid/tiny_model.task",  # reserved TLD: can never resolve
    size_bytes=len(PAYLOAD),
    sha256=DIGEST,
    license="test fixture",
    version="tiny/1",
    source="tests/test_tracking_assets.py",
)
REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    """What ``urlopen`` returns, reduced to the surface ``provision_model`` uses.

    A context manager with ``read(n)`` served from memory. ``max_read`` caps
    each read below ``n`` so a tiny payload still arrives over several partial
    reads, as a socket delivers it; ``fail_after`` raises a connection reset
    once that many bytes have been delivered.
    """

    def __init__(self, payload: bytes, max_read: int | None, fail_after: int | None) -> None:
        self._stream = io.BytesIO(payload)
        self._max_read = max_read
        self._fail_after = fail_after
        self.delivered = 0
        self.reads = 0
        self.closed = False

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.closed = True

    def read(self, n: int = -1) -> bytes:
        self.reads += 1
        if self._fail_after is not None and self.delivered >= self._fail_after:
            raise ConnectionResetError("connection reset by peer")
        if self._max_read is not None and (n < 0 or n > self._max_read):
            n = self._max_read
        chunk = self._stream.read(n)
        self.delivered += len(chunk)
        return chunk


class RecordingOpener:
    """Injectable ``opener``: records every call and serves ``payload`` (or raises ``error``)."""

    def __init__(
        self,
        payload: bytes = PAYLOAD,
        *,
        max_read: int | None = None,
        fail_after: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self._payload = payload
        self._max_read = max_read
        self._fail_after = fail_after
        self._error = error
        self.calls: list[tuple[str, float]] = []
        self.responses: list[FakeResponse] = []

    # Exactly the call shape ``provision_model`` makes (``urlopen(url, timeout=...)``),
    # so a changed call signature fails loudly here rather than at runtime.
    def __call__(self, url: str, *, timeout: float) -> FakeResponse:
        self.calls.append((url, timeout))
        if self._error is not None:
            raise self._error
        response = FakeResponse(self._payload, self._max_read, self._fail_after)
        self.responses.append(response)
        return response


def never_open(url: str, *, timeout: float) -> FakeResponse:
    # ``pytest.fail`` raises a BaseException, so ``provision_model``'s
    # ``except Exception`` cannot turn this into a "download" error.
    pytest.fail(f"opener must not be called (got {url!r}, timeout={timeout})")


def corrupted(payload: bytes) -> bytes:
    """Same length as ``payload`` with one byte flipped: passes the size check, fails the digest."""

    return bytes([payload[0] ^ 0xFF]) + payload[1:]


def entries(directory: Path) -> list[str]:
    """Names in ``directory`` (empty if it does not exist): the leftover-file check."""

    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


FAILURE_MODES = ["wrong-bytes", "oversize", "unreachable", "reset"]


def failing_opener(mode: str) -> tuple[RecordingOpener, str]:
    """An opener whose download must be rejected, with the ``ModelAssetError.kind`` expected."""

    if mode == "wrong-bytes":
        return RecordingOpener(corrupted(PAYLOAD)), "checksum"
    if mode == "oversize":
        return RecordingOpener(bytes(MANIFEST.size_bytes + SLACK_BYTES + 1)), "download"
    if mode == "unreachable":
        return RecordingOpener(error=URLError("no route to host")), "download"
    if mode == "reset":
        return RecordingOpener(max_read=100, fail_after=100), "download"
    raise ValueError(mode)


# --- sha256_of -----------------------------------------------------------------


@pytest.mark.parametrize(
    "size",
    [CHUNK_BYTES + 12_345, 2 * CHUNK_BYTES, 0],
    ids=["one-chunk-and-a-tail", "exact-chunk-multiple", "empty"],
)
def test_sha256_of_streams_files_across_chunk_boundaries(tmp_path: Path, size: int) -> None:
    data = random.Random(size).randbytes(size)  # seeded: identical bytes on every run
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    assert sha256_of(path) == hashlib.sha256(data).hexdigest()


def test_sha256_of_digest_does_not_depend_on_the_chunk_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 7-byte chunk over a 100-byte file forces 15 partial reads; the digest must not change."""

    data = bytes(range(100))
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    monkeypatch.setattr(assets, "_CHUNK_BYTES", 7)
    assert sha256_of(path) == hashlib.sha256(data).hexdigest()


# --- verify_model --------------------------------------------------------------


def test_verify_model_missing_file_names_the_setup_command_and_the_path(tmp_path: Path) -> None:
    path = MANIFEST.path_in(tmp_path)
    with pytest.raises(ModelAssetError) as info:
        verify_model(path, MANIFEST)
    exc = info.value
    assert exc.kind == "missing"
    assert exc.path == path
    assert isinstance(exc, RuntimeError)
    assert "python scripts/fetch_model.py" in str(exc)
    assert SETUP_COMMAND in str(exc)
    assert str(path) in str(exc)
    assert MANIFEST.filename in str(exc)


def test_verify_model_treats_a_directory_at_the_path_as_missing(tmp_path: Path) -> None:
    path = MANIFEST.path_in(tmp_path)
    path.mkdir()
    with pytest.raises(ModelAssetError) as info:
        verify_model(path, MANIFEST)
    assert info.value.kind == "missing"
    assert info.value.path == path


def test_verify_model_wrong_size_is_reported_without_hashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = MANIFEST.path_in(tmp_path)
    path.write_bytes(PAYLOAD[:-1])  # truncated by one byte
    monkeypatch.setattr(assets, "sha256_of", lambda _p: pytest.fail("a size mismatch must not be hashed"))
    with pytest.raises(ModelAssetError) as info:
        verify_model(path, MANIFEST)
    exc = info.value
    assert exc.kind == "size"
    assert exc.path == path
    assert f"{len(PAYLOAD) - 1} bytes" in str(exc) and f"{len(PAYLOAD)} bytes" in str(exc)
    assert SETUP_COMMAND in str(exc)


def test_verify_model_right_size_wrong_bytes_is_a_checksum_error(tmp_path: Path) -> None:
    path = MANIFEST.path_in(tmp_path)
    bad = corrupted(PAYLOAD)
    path.write_bytes(bad)
    with pytest.raises(ModelAssetError) as info:
        verify_model(path, MANIFEST)
    exc = info.value
    assert exc.kind == "checksum"
    assert exc.path == path
    assert hashlib.sha256(bad).hexdigest() in str(exc)  # what was found
    assert DIGEST in str(exc)  # what was expected
    assert SETUP_COMMAND in str(exc)


def test_verify_model_returns_the_verified_identity(tmp_path: Path) -> None:
    path = MANIFEST.path_in(tmp_path)
    path.write_bytes(PAYLOAD)
    verified = verify_model(path, MANIFEST)
    assert verified == VerifiedModel(MANIFEST, path, len(PAYLOAD), DIGEST)
    assert verified.manifest is MANIFEST
    assert verified.size_bytes == MANIFEST.size_bytes


def test_verify_model_wraps_a_read_error_as_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Injected rather than produced with chmod: permission bits are ignored by
    # root, so a chmod-based test would pass or fail depending on who runs it.
    path = MANIFEST.path_in(tmp_path)
    path.write_bytes(PAYLOAD)
    failure = OSError(5, "Input/output error")

    def unreadable(_path: Path) -> str:
        raise failure

    monkeypatch.setattr(assets, "sha256_of", unreadable)
    with pytest.raises(ModelAssetError) as info:
        verify_model(path, MANIFEST)
    assert info.value.kind == "unreadable"
    assert info.value.path == path
    assert info.value.__cause__ is failure


# --- provision_model -----------------------------------------------------------


def test_provision_reuses_a_verified_file_without_opening_the_network(tmp_path: Path) -> None:
    target = MANIFEST.path_in(tmp_path)
    target.write_bytes(PAYLOAD)

    result = provision_model(tmp_path, MANIFEST, opener=never_open)

    assert result == ProvisionResult(
        VerifiedModel(MANIFEST, target, len(PAYLOAD), DIGEST), downloaded=False, download_ms=0.0
    )
    assert entries(tmp_path) == [MANIFEST.filename]  # no temporary was ever created


def test_provision_downloads_a_missing_file_into_place(tmp_path: Path) -> None:
    directory = tmp_path / "models" / "nested"  # created on demand, parents included
    target = MANIFEST.path_in(directory)
    opener = RecordingOpener(max_read=50)

    result = provision_model(directory, MANIFEST, opener=opener, timeout_s=2.5)

    assert result.downloaded is True
    assert result.verified == VerifiedModel(MANIFEST, target, len(PAYLOAD), DIGEST)
    assert result.download_ms >= 0.0
    assert target.read_bytes() == PAYLOAD
    assert entries(directory) == [MANIFEST.filename]  # no ``.download`` temporary left behind
    assert opener.calls == [(MANIFEST.url, 2.5)]
    (response,) = opener.responses
    assert response.closed  # the response context was exited
    # Streamed in 50-byte partial reads plus the empty read that ends the stream.
    assert response.reads == math.ceil(len(PAYLOAD) / 50) + 1


def test_provision_rejects_a_download_with_wrong_bytes(tmp_path: Path) -> None:
    target = MANIFEST.path_in(tmp_path)
    opener = RecordingOpener(corrupted(PAYLOAD))
    with pytest.raises(ModelAssetError) as info:
        provision_model(tmp_path, MANIFEST, opener=opener)
    assert info.value.kind == "checksum"
    assert not target.exists()
    assert entries(tmp_path) == []
    assert opener.responses[0].closed


def test_provision_aborts_a_download_that_exceeds_the_size_bound(tmp_path: Path) -> None:
    target = MANIFEST.path_in(tmp_path)
    bound = MANIFEST.size_bytes + SLACK_BYTES
    opener = RecordingOpener(bytes(bound + 1))
    with pytest.raises(ModelAssetError) as info:
        provision_model(tmp_path, MANIFEST, opener=opener)
    exc = info.value
    assert exc.kind == "download"
    assert exc.path == target
    assert "exceeded" in str(exc) and MANIFEST.url in str(exc)
    assert entries(tmp_path) == []
    assert opener.responses[0].closed


def test_provision_accepts_exactly_the_size_bound_and_then_fails_verification(tmp_path: Path) -> None:
    """The bound is exclusive: ``size + slack`` bytes are written, then rejected by the size check."""

    bound = MANIFEST.size_bytes + SLACK_BYTES
    with pytest.raises(ModelAssetError) as info:
        provision_model(tmp_path, MANIFEST, opener=RecordingOpener(bytes(bound)))
    assert info.value.kind == "size"
    assert entries(tmp_path) == []


def test_provision_wraps_an_opener_failure_as_a_download_error(tmp_path: Path) -> None:
    target = MANIFEST.path_in(tmp_path)
    failure = URLError("name resolution failed")
    opener = RecordingOpener(error=failure)
    with pytest.raises(ModelAssetError) as info:
        provision_model(tmp_path, MANIFEST, opener=opener)
    exc = info.value
    assert exc.kind == "download"
    assert exc.path == target
    assert exc.__cause__ is failure
    assert MANIFEST.url in str(exc)
    assert opener.calls == [(MANIFEST.url, 60.0)]  # default timeout reaches the opener
    assert entries(tmp_path) == []  # the temporary opened before the request is gone


def test_provision_wraps_a_mid_stream_read_failure_and_removes_the_partial_file(tmp_path: Path) -> None:
    opener = RecordingOpener(max_read=100, fail_after=100)  # 100 bytes arrive, then the connection drops
    with pytest.raises(ModelAssetError) as info:
        provision_model(tmp_path, MANIFEST, opener=opener)
    assert info.value.kind == "download"
    assert isinstance(info.value.__cause__, ConnectionResetError)
    assert opener.responses[0].delivered == 100
    assert entries(tmp_path) == []


def test_provision_force_redownloads_over_a_valid_file(tmp_path: Path) -> None:
    target = MANIFEST.path_in(tmp_path)
    target.write_bytes(PAYLOAD)
    opener = RecordingOpener()

    result = provision_model(tmp_path, MANIFEST, opener=opener, force=True)

    assert result.downloaded is True
    assert opener.calls == [(MANIFEST.url, 60.0)]
    assert result.verified == VerifiedModel(MANIFEST, target, len(PAYLOAD), DIGEST)
    assert target.read_bytes() == PAYLOAD
    assert entries(tmp_path) == [MANIFEST.filename]


@pytest.mark.parametrize("mode", FAILURE_MODES)
def test_provision_force_keeps_the_valid_file_when_the_download_fails(tmp_path: Path, mode: str) -> None:
    target = MANIFEST.path_in(tmp_path)
    target.write_bytes(PAYLOAD)
    opener, expected_kind = failing_opener(mode)
    with pytest.raises(ModelAssetError) as info:
        provision_model(tmp_path, MANIFEST, opener=opener, force=True)
    assert info.value.kind == expected_kind
    assert target.read_bytes() == PAYLOAD
    assert entries(tmp_path) == [MANIFEST.filename]
    assert verify_model(target, MANIFEST).sha256 == DIGEST


def test_provision_replaces_a_corrupt_file_with_a_verified_download(tmp_path: Path) -> None:
    target = MANIFEST.path_in(tmp_path)
    target.write_bytes(b"not the model")
    opener = RecordingOpener()

    result = provision_model(tmp_path, MANIFEST, opener=opener)

    assert result.downloaded is True
    assert opener.calls == [(MANIFEST.url, 60.0)]
    assert target.read_bytes() == PAYLOAD
    assert entries(tmp_path) == [MANIFEST.filename]


@pytest.mark.parametrize("mode", FAILURE_MODES)
def test_provision_leaves_a_corrupt_file_untouched_when_the_download_fails(tmp_path: Path, mode: str) -> None:
    target = MANIFEST.path_in(tmp_path)
    corrupt = corrupted(PAYLOAD)  # right size, wrong digest: the tracker would reject it
    target.write_bytes(corrupt)
    opener, expected_kind = failing_opener(mode)
    with pytest.raises(ModelAssetError) as info:
        provision_model(tmp_path, MANIFEST, opener=opener)
    assert info.value.kind == expected_kind
    assert opener.calls == [(MANIFEST.url, 60.0)]  # the corrupt copy did trigger a download attempt
    assert target.read_bytes() == corrupt
    assert entries(tmp_path) == [MANIFEST.filename]


@pytest.mark.parametrize("timeout_s", [0, -1.0])
def test_provision_rejects_a_non_positive_timeout_before_touching_the_disk(tmp_path: Path, timeout_s: float) -> None:
    directory = tmp_path / "models"
    with pytest.raises(ValueError):
        provision_model(directory, MANIFEST, opener=never_open, timeout_s=timeout_s)
    assert not directory.exists()


# --- gazefix.tracking.provision.main (scripts/fetch_model.py) -------------------


def test_main_verify_only_reports_a_missing_model_offline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = provision.main(["--verify-only", "--model-dir", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report["verified"] is False
    assert report["error_kind"] == "missing"
    assert report["path"] == str(FACE_LANDMARKER.path_in(tmp_path))
    assert SETUP_COMMAND in report["error"] and report["path"] in report["error"]
    assert report["model"]["filename"] == FACE_LANDMARKER.filename == "face_landmarker.task"
    assert report["model"]["sha256"] == FACE_LANDMARKER.sha256
    assert entries(tmp_path) == []  # verify-only never downloads or creates anything


def test_main_verify_only_reports_a_verified_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[Path] = []

    def fake_verify(path: Path, manifest: ModelManifest = FACE_LANDMARKER) -> VerifiedModel:
        seen.append(path)
        return VerifiedModel(MANIFEST, path, len(PAYLOAD), DIGEST)

    monkeypatch.setattr(provision, "verify_model", fake_verify)
    monkeypatch.setattr(
        provision, "provision_model", lambda *a, **k: pytest.fail("--verify-only must never provision")
    )

    code = provision.main(["--verify-only", "--model-dir", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert seen == [FACE_LANDMARKER.path_in(tmp_path)]
    assert report["verified"] is True and report["downloaded"] is False
    assert report["sha256"] == DIGEST and report["size_bytes"] == len(PAYLOAD)
    assert "error_kind" not in report


@pytest.mark.parametrize(
    ("extra_argv", "expected_timeout", "expected_force"),
    [([], 60.0, False), (["--force", "--timeout", "2.5"], 2.5, True)],
    ids=["defaults", "force-and-timeout"],
)
def test_main_provisions_with_the_parsed_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra_argv: list[str],
    expected_timeout: float,
    expected_force: bool,
) -> None:
    seen: list[tuple[Path, float, bool]] = []
    target = FACE_LANDMARKER.path_in(tmp_path)

    # The same keyword-only shape ``main`` uses, so an added or renamed argument fails here.
    def fake_provision(directory: Path, *, timeout_s: float, force: bool) -> ProvisionResult:
        seen.append((directory, timeout_s, force))
        return ProvisionResult(
            VerifiedModel(MANIFEST, target, len(PAYLOAD), DIGEST), downloaded=True, download_ms=12.5
        )

    monkeypatch.setattr(provision, "provision_model", fake_provision)
    monkeypatch.setattr(
        provision, "verify_model", lambda *a, **k: pytest.fail("main must leave verification to provision_model")
    )

    code = provision.main(["--model-dir", str(tmp_path), *extra_argv])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert seen == [(tmp_path, expected_timeout, expected_force)]
    assert report["verified"] is True and report["downloaded"] is True
    assert report["download_ms"] == 12.5
    assert report["sha256"] == DIGEST and report["size_bytes"] == len(PAYLOAD)
    assert report["path"] == str(target)


def test_main_reports_a_provisioning_failure_as_exit_code_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = FACE_LANDMARKER.path_in(tmp_path)

    def failing_provision(directory: Path, *, timeout_s: float, force: bool) -> ProvisionResult:
        raise ModelAssetError("download", f"Could not download {FACE_LANDMARKER.url}: no route to host", target)

    monkeypatch.setattr(provision, "provision_model", failing_provision)
    code = provision.main(["--model-dir", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report["verified"] is False
    assert report["error_kind"] == "download"
    assert report["error"].startswith("Could not download ")
    assert "downloaded" not in report


@pytest.mark.parametrize("timeout", ["0", "-3"])
def test_main_rejects_a_non_positive_timeout_as_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], timeout: str
) -> None:
    monkeypatch.setattr(
        provision, "provision_model", lambda *a, **k: pytest.fail("a rejected --timeout must not provision")
    )
    with pytest.raises(SystemExit) as info:
        provision.main(["--model-dir", str(tmp_path), "--timeout", timeout])
    assert info.value.code == 2
    captured = capsys.readouterr()
    assert "--timeout must be positive" in captured.err
    assert captured.out == ""  # a usage error prints no JSON report


def test_main_falls_back_to_the_default_model_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    default_dir = tmp_path / "LocalAppData" / "GazeFix" / "models"
    monkeypatch.setattr(provision, "default_model_directory", lambda: default_dir)
    code = provision.main(["--verify-only"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1 and report["error_kind"] == "missing"
    assert report["path"] == str(FACE_LANDMARKER.path_in(default_dir))
    assert not default_dir.exists()


def test_fetch_model_script_runs_the_provisioning_cli(tmp_path: Path) -> None:
    """``scripts/fetch_model.py`` is a thin wrapper; run it for real in verify-only mode (offline)."""

    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "fetch_model.py"), "--verify-only", "--model-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
    )
    assert completed.returncode == 1, completed.stderr
    report = json.loads(completed.stdout)
    assert report["error_kind"] == "missing"
    assert report["path"] == str(FACE_LANDMARKER.path_in(tmp_path))


def test_permission_errors_on_the_model_path_are_reported_as_unreadable(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pathlib import Path

    from gazefix.tracking.assets import FACE_LANDMARKER, ModelAssetError, verify_model

    target = FACE_LANDMARKER.path_in(tmp_path)
    original = Path.is_file

    def denied(self):  # type: ignore[no-untyped-def]
        if self == target:
            raise PermissionError(13, "Permission denied")
        return original(self)

    monkeypatch.setattr(Path, "is_file", denied)
    try:
        verify_model(target)
    except ModelAssetError as exc:
        assert exc.kind == "unreadable"
    else:
        raise AssertionError("a permission error must be classified, not raised raw")


def test_install_failures_are_not_reported_as_download_failures(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import hashlib
    import io
    import os

    from gazefix.tracking import assets

    payload = b"model-bytes"
    manifest = assets.ModelManifest(
        name="tiny", filename="tiny.task", url="https://example.invalid/tiny.task",
        size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
        license="test", version="1", source="test",
    )

    class Response(io.BytesIO):
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *exc):  # type: ignore[no-untyped-def]
            return None

    def opener(url, timeout):  # type: ignore[no-untyped-def]
        return Response(payload)

    def failing_replace(src, dst):  # type: ignore[no-untyped-def]
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(os, "replace", failing_replace)
    try:
        assets.provision_model(tmp_path, manifest, opener=opener)
    except assets.ModelAssetError as exc:
        assert exc.kind == "install"
        assert "could not be replaced" in str(exc) and "Close GazeFix" in str(exc)
    else:
        raise AssertionError("a failed install must be reported")
    assert not list(tmp_path.glob("*.download"))
    assert not manifest.path_in(tmp_path).exists()
