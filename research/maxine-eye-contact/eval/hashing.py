"""Content hashing and canonical JSON for auditable manifests.

Every manifest this package writes is canonical JSON: UTF-8, sorted keys,
two-space indent, ``\\n`` newlines, trailing newline. That makes a manifest
byte-reproducible, so a manifest's own SHA-256 is a meaningful freeze token.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CHUNK = 1024 * 1024


def sha256_file(path):
    """Return the lowercase hex SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data):
    """Return the lowercase hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def canonical_json(value):
    """Serialise ``value`` to the canonical manifest text form."""
    return json.dumps(value, indent=2, sort_keys=True,
                      ensure_ascii=False, allow_nan=False) + "\n"


def write_json(path, value):
    """Write ``value`` as canonical JSON and return its SHA-256."""
    text = canonical_json(value)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return sha256_bytes(text.encode("utf-8"))


def read_json(path):
    """Read a JSON document."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def manifest_digest(value):
    """Return the SHA-256 a manifest would have when written canonically."""
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def verify_file(path, expected_sha256):
    """Return ``(ok, actual)`` for a file against an expected digest."""
    path = Path(path)
    if not path.is_file():
        return False, None
    actual = sha256_file(path)
    return actual == expected_sha256, actual
