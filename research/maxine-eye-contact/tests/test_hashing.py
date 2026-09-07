"""Manifest hashing and canonical JSON."""

import json

import pytest

from eval import hashing


def test_sha256_file_matches_known_vector(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    assert hashing.sha256_file(path) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_sha256_file_reads_beyond_one_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(hashing, "CHUNK", 7)
    payload = b"x" * 100
    path = tmp_path / "b.bin"
    path.write_bytes(payload)
    assert hashing.sha256_file(path) == hashing.sha256_bytes(payload)


def test_canonical_json_is_key_order_independent():
    assert hashing.canonical_json({"b": 1, "a": 2}) == hashing.canonical_json({"a": 2, "b": 1})


def test_canonical_json_ends_with_single_newline():
    text = hashing.canonical_json({"a": 1})
    assert text.endswith("}\n") and not text.endswith("\n\n")


def test_manifest_digest_matches_written_file(tmp_path):
    value = {"z": [1, 2], "a": {"n": None}}
    written = hashing.write_json(tmp_path / "m.json", value)
    assert written == hashing.manifest_digest(value)
    assert hashing.sha256_file(tmp_path / "m.json") == written


def test_write_json_round_trips(tmp_path):
    value = {"clips": [{"id": "P1A-01", "sha": "ab"}]}
    hashing.write_json(tmp_path / "m.json", value)
    assert hashing.read_json(tmp_path / "m.json") == value


def test_canonical_json_refuses_nan():
    with pytest.raises(ValueError):
        hashing.canonical_json({"x": float("nan")})


def test_verify_file_detects_change(tmp_path):
    path = tmp_path / "c.bin"
    path.write_bytes(b"one")
    digest = hashing.sha256_file(path)
    assert hashing.verify_file(path, digest) == (True, digest)
    path.write_bytes(b"two")
    ok, actual = hashing.verify_file(path, digest)
    assert not ok and actual != digest


def test_verify_file_reports_missing(tmp_path):
    assert hashing.verify_file(tmp_path / "nope", "x") == (False, None)


def test_written_manifest_is_valid_utf8_json(tmp_path):
    hashing.write_json(tmp_path / "m.json", {"note": "café — dash"})
    assert json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["note"]
