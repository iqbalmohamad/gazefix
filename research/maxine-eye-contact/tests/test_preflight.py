"""Preflight gate."""

from eval import maxine, paths, preflight


def _workspace(tmp_path):
    return paths.Workspace(tmp_path / "ws").ensure()


def test_missing_footage_is_a_blocking_failure(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    report = preflight.run(inputs, _workspace(tmp_path), env={})
    footage = next(c for c in report["checks"]
                   if c["check"] == "product-owner-footage-present")
    assert footage["status"] == "FAIL"
    assert "product-owner-footage-present" in report["blocking_failures"]


def test_footage_present_passes_that_check(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "speaking-smiling.mp4").write_bytes(b"x")
    report = preflight.run(inputs, _workspace(tmp_path), env={})
    footage = next(c for c in report["checks"]
                   if c["check"] == "product-owner-footage-present")
    assert footage["status"] == "PASS"


def test_absent_inputs_directory_is_handled(tmp_path):
    report = preflight.run(tmp_path / "nope", _workspace(tmp_path), env={})
    assert "product-owner-footage-present" in report["blocking_failures"]


def test_missing_credential_is_a_blocking_failure(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    report = preflight.run(inputs, _workspace(tmp_path), env={})
    assert "nvidia-credential" in report["blocking_failures"]


def test_credential_check_reads_the_documented_variable(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    report = preflight.run(inputs, _workspace(tmp_path),
                           env={maxine.API_KEY_ENV: "nvapi-" + "k" * 24})
    check = next(c for c in report["checks"] if c["check"] == "nvidia-credential")
    assert check["status"] == "PASS"
    assert "nvapi-" not in check["detail"]


def test_hosted_availability_is_never_assumed(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    report = preflight.run(inputs, _workspace(tmp_path), env={})
    check = next(c for c in report["checks"]
                 if c["check"] == "hosted-api-availability-confirmed")
    assert check["status"] != "PASS"
    assert "hosted-api-availability-confirmed" in report["blocking_failures"]


def test_frozen_reference_drift_is_a_blocking_failure(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    monkeypatch.setattr(preflight.provenance, "verify_frozen_refs",
                        lambda root=None: [{"ref": "m3-geometric-baseline",
                                            "expected": "a", "actual": "b",
                                            "ok": False}])
    report = preflight.run(inputs, _workspace(tmp_path), env={})
    assert "frozen-references-unchanged" in report["blocking_failures"]


def test_remote_execution_is_refused_while_anything_blocks(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    assert preflight.run(inputs, _workspace(tmp_path), env={})["may_execute_remotely"] is False
