"""Credential redaction and secret scanning.

Nothing this package writes to disk may contain an API key. Two defences:
``redact`` scrubs values before they are serialised, and ``scan_text`` /
``scan_tree`` re-check written artifacts afterwards.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REDACTED = "<REDACTED>"

#: Header and field names whose values are never recorded.
SECRET_KEYS = (
    "authorization", "auth", "api_key", "apikey", "api-key",
    "nvidia_api_key", "nvcf_api_key", "ngc_api_key", "x-api-key",
    "token", "access_token", "bearer", "password", "secret",
    "credential", "credentials", "cookie", "set-cookie",
)

#: Value shapes that look like a credential regardless of the key they sit under.
SECRET_PATTERNS = (
    # NVIDIA personal / NGC API keys are published as ``nvapi-`` prefixed.
    re.compile(r"nvapi-[A-Za-z0-9_\-]{16,}"),
    # NGC legacy base64-ish keys and generic long opaque tokens after a marker.
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|apikey|token|secret)\b\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{16,}"),
    # JSON Web Tokens.
    re.compile(r"\beyJ[A-Za-z0-9._\-]{20,}"),
)


def _is_secret_key(key):
    return str(key).strip().lower().replace(" ", "") in SECRET_KEYS


def redact(value):
    """Recursively replace secret-keyed values and secret-shaped strings."""
    if isinstance(value, dict):
        return {k: (REDACTED if _is_secret_key(k) else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text):
    """Replace every secret-shaped substring in ``text``."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scan_text(text):
    """Return every secret-shaped match in ``text``."""
    hits = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            hits.append(match.group(0))
    return hits


#: A line carrying this marker is exempt from the tree scan. It exists so the
#: detector's own fixtures can be credential-shaped without the repository-wide
#: scan failing forever. The exemption is per line, so a real credential
#: elsewhere in the same file still fails the scan, and every use is greppable.
ALLOWLIST_MARKER = "phase1a-allowlist-fixture"


def scan_lines(text):
    """Return ``(line_number, match)`` for every unexempted secret-shaped hit."""
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOWLIST_MARKER in line:
            continue
        for match in scan_text(line):
            hits.append((number, match))
    return hits


def scan_tree(root, suffixes=(".json", ".md", ".csv", ".txt", ".log", ".py", ".html")):
    """Scan a directory tree for secret-shaped content.

    Returns a list of ``(path, matches)`` for every file with a hit. Matches are
    themselves redacted so a scan report can never leak the value it found.
    Lines carrying ``ALLOWLIST_MARKER`` are skipped.
    """
    findings = []
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = scan_lines(text)
        if hits:
            findings.append((path, [f"line {n}: {redact_text(m)}" for n, m in hits]))
    return findings


def credential_from_env(variable):
    """Read a credential from the environment.

    Returns ``None`` when unset or blank. The value is never logged, echoed or
    written to a manifest by this package.
    """
    value = os.environ.get(variable)
    if value is None:
        return None
    value = value.strip()
    return value or None
