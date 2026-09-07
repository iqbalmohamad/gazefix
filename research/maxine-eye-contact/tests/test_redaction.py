"""Credential redaction and secret scanning."""

from eval import redaction

FAKE_KEY = "nvapi-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"


def test_secret_keyed_values_are_redacted():
    out = redaction.redact({"Authorization": "Bearer " + FAKE_KEY, "clip": "P1A-01"})
    assert out["Authorization"] == redaction.REDACTED
    assert out["clip"] == "P1A-01"


def test_secret_key_matching_ignores_case_and_spacing():
    for key in ("API_KEY", "api-key", " Api Key ", "X-API-KEY"):
        assert redaction.redact({key: FAKE_KEY})[key] == redaction.REDACTED


def test_nested_structures_are_redacted():
    out = redaction.redact({"a": [{"token": FAKE_KEY}, {"ok": 1}]})
    assert out["a"][0]["token"] == redaction.REDACTED
    assert out["a"][1]["ok"] == 1


def test_key_shaped_value_is_redacted_under_an_innocent_key():
    out = redaction.redact({"command": ["--api-key", FAKE_KEY]})
    assert FAKE_KEY not in "".join(out["command"])


def test_bearer_and_jwt_shapes_are_redacted():
    assert FAKE_KEY not in redaction.redact_text("Bearer " + FAKE_KEY)
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefghijkl"  # phase1a-allowlist-fixture
    assert jwt not in redaction.redact_text(jwt)


def test_scan_text_finds_a_key():
    assert redaction.scan_text(f"key={FAKE_KEY}")


def test_scan_text_is_quiet_on_clean_content():
    assert redaction.scan_text("clip P1A-01 sha256 " + "a" * 64) == []


def test_scan_tree_reports_and_redacts_its_own_findings(tmp_path):
    (tmp_path / "m.json").write_text(f'{{"k": "{FAKE_KEY}"}}', encoding="utf-8")
    (tmp_path / "clean.json").write_text('{"k": "ok"}', encoding="utf-8")
    findings = redaction.scan_tree(tmp_path)
    assert len(findings) == 1
    path, matches = findings[0]
    assert path.name == "m.json"
    assert all(FAKE_KEY not in m for m in matches)


def test_scan_tree_ignores_binary_suffixes(tmp_path):
    (tmp_path / "v.mp4").write_text(FAKE_KEY, encoding="utf-8")
    assert redaction.scan_tree(tmp_path) == []


def test_credential_from_env_treats_blank_as_absent():
    assert redaction.credential_from_env("GAZEFIX_NOT_SET_XYZ") is None


def test_credential_from_env_strips(monkeypatch):
    monkeypatch.setenv("GAZEFIX_TMP_KEY", "  value  ")
    assert redaction.credential_from_env("GAZEFIX_TMP_KEY") == "value"
    monkeypatch.setenv("GAZEFIX_TMP_KEY", "   ")
    assert redaction.credential_from_env("GAZEFIX_TMP_KEY") is None


def test_allowlist_marker_exempts_only_its_own_line(tmp_path):
    path = tmp_path / "fixtures.py"
    path.write_text(
        f'exempt = "{FAKE_KEY}"  # {redaction.ALLOWLIST_MARKER}\n'
        f'leaked = "{FAKE_KEY}"\n', encoding="utf-8")
    findings = redaction.scan_tree(tmp_path)
    assert len(findings) == 1
    _, matches = findings[0]
    assert len(matches) == 1 and matches[0].startswith("line 2:")


def test_scan_lines_reports_line_numbers():
    hits = redaction.scan_lines(f"clean\nkey={FAKE_KEY}\nclean")
    assert [n for n, _ in hits] == [2]


def test_this_package_is_free_of_credentials():
    """The committed evaluation package must never contain a credential."""
    import pathlib
    root = pathlib.Path(redaction.__file__).resolve().parents[1]
    assert redaction.scan_tree(root) == []
