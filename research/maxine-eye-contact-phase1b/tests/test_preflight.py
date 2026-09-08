"""The gate that refuses to produce a number that is not a Maxine measurement."""

from __future__ import annotations

from pathlib import Path

from streamexp import preflight


def report_for(tmp_path: Path, **overrides):
    arguments = {
        "target": "127.0.0.1:1",
        "clone_dir": tmp_path / "absent-clone",
        "endpoint_confirmed": False,
        "require_ffmpeg": False,
        "require_reachable": False,
    }
    arguments.update(overrides)
    return preflight.run(**arguments)


def named(report, name):
    return next(check for check in report.checks if check.name == name)


def test_an_unconfirmed_endpoint_blocks_the_run(tmp_path: Path):
    report = report_for(tmp_path)
    assert not report.clear
    assert named(report, "nim-endpoint-confirmed").status == "UNKNOWN"
    assert "nim-endpoint-confirmed" in [check.name for check in report.blocked_by]


def test_confirming_the_endpoint_clears_only_that_check(tmp_path: Path):
    report = report_for(tmp_path, endpoint_confirmed=True)
    assert named(report, "nim-endpoint-confirmed").status == "PASS"
    # The absent clone still blocks: NVIDIA's contract is not optional.
    assert named(report, "nvidia-proto-compiled").status == "FAIL"
    assert not report.clear


def test_a_missing_clone_names_the_command_that_fixes_it(tmp_path: Path):
    detail = named(report_for(tmp_path), "nvidia-proto-compiled").detail
    assert "git clone https://github.com/NVIDIA-Maxine/nim-clients.git" in detail


def test_an_unreachable_target_blocks_when_reachability_is_required(tmp_path: Path):
    report = report_for(tmp_path, require_reachable=True)
    assert named(report, "target-tcp-reachable").status == "FAIL"


def test_the_client_gpu_check_informs_and_never_blocks(tmp_path: Path):
    check = named(report_for(tmp_path), "client-has-no-nvidia-requirement")
    assert check.status == "INFO"
    assert not check.blocking
    # Either wording is honest; what matters is that a client GPU is never
    # allowed to make a run look like evidence for a client without one.
    assert "NVIDIA GPU" in check.detail


def test_preview_mode_requires_a_credential_and_says_it_is_not_the_route(tmp_path: Path):
    report = report_for(tmp_path, preview_mode=True)
    names = [check.name for check in report.checks]
    assert "nvidia-api-key-present" in names
    note = named(report, "preview-mode-is-not-the-phase-1b-route")
    assert note.status == "INFO" and not note.blocking


def test_no_check_detail_ever_contains_a_credential(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-do-not-leak-this-value")
    report = report_for(tmp_path, preview_mode=True)
    rendered = str(report.as_dict())
    assert "nvapi-do-not-leak-this-value" not in rendered
    assert named(report, "nvidia-api-key-present").status == "PASS"
