"""Maxine request construction, credential handling and failure detection."""

import pytest

from eval import maxine, redaction

FAKE_KEY = "nvapi-" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4"


def _mp4(path, streamable):
    """Minimal MP4 atom layout: ftyp then either moov or mdat first."""
    ftyp = (8).to_bytes(4, "big") + b"ftyp"
    second = b"moov" if streamable else b"mdat"
    path.write_bytes(ftyp + (8).to_bytes(4, "big") + second + b"\0" * 64)
    return path


def test_streamable_detection(tmp_path):
    assert maxine.is_streamable(_mp4(tmp_path / "s.mp4", True))
    assert not maxine.is_streamable(_mp4(tmp_path / "t.mp4", False))


def test_streamable_detection_on_a_non_mp4(tmp_path):
    path = tmp_path / "x.mp4"
    path.write_bytes(b"not an mp4 at all")
    assert not maxine.is_streamable(path)


def test_frozen_profile_sends_no_tuning_parameter():
    assert list(maxine.FROZEN_PROFILE["parameter_flags"]) == []


def test_client_argv_uses_the_recorded_endpoint():
    argv = maxine.build_client_argv("/c/eye-contact.py", "in.mp4", "out.mp4", False)
    assert "--preview-mode" in argv
    assert argv[argv.index("--target") + 1] == maxine.HOSTED_TARGET
    assert argv[argv.index("--function-id") + 1] == maxine.HOSTED_FUNCTION_ID


def test_client_argv_never_carries_the_credential():
    argv = maxine.build_client_argv("/c/eye-contact.py", "in.mp4", "out.mp4", True)
    assert "--api-key" not in argv
    assert not any("nvapi-" in part for part in argv)


def test_streaming_flag_follows_the_input_not_a_preference():
    with_flag = maxine.build_client_argv("/c/c.py", "i", "o", True)
    without = maxine.build_client_argv("/c/c.py", "i", "o", False)
    assert "--streaming" in with_flag and "--streaming" not in without


def test_endpoint_comes_from_the_recorded_spec():
    spec = maxine.load_spec()
    assert spec["service"]["target"] == maxine.HOSTED_TARGET
    assert spec["service"]["function_id"] == maxine.HOSTED_FUNCTION_ID


def test_launcher_reads_the_key_from_the_environment_only():
    source = maxine.launcher_source("/c/eye-contact.py")
    assert maxine.API_KEY_ENV in source
    assert "os.environ.pop" in source
    assert "nvapi-" not in source


def test_api_key_presence_check():
    assert not maxine.api_key_present({})
    assert not maxine.api_key_present({maxine.API_KEY_ENV: "   "})
    assert maxine.api_key_present({maxine.API_KEY_ENV: FAKE_KEY})


def test_require_api_key_message_names_the_variable_and_leaks_nothing():
    with pytest.raises(maxine.CredentialMissing) as excinfo:
        maxine.require_api_key({})
    assert maxine.API_KEY_ENV in str(excinfo.value)
    assert "nvapi-" not in str(excinfo.value)


def test_run_clip_refuses_without_a_credential(tmp_path):
    source = _mp4(tmp_path / "i.mp4", False)
    with pytest.raises(maxine.CredentialMissing):
        maxine.run_clip("/c/c.py", source, tmp_path / "o.mp4",
                        tmp_path / "l.py", env={})


def _run(tmp_path, *, returncode, stdout="", stderr="", write_output=b"out"):
    source = _mp4(tmp_path / "i.mp4", False)
    output = tmp_path / "o.mp4"
    calls = {}

    def runner(command, cwd, env, timeout):
        calls["command"] = command
        calls["env"] = env
        if write_output is not None:
            output.write_bytes(write_output)
        return {"returncode": returncode, "stdout": stdout, "stderr": stderr}

    ticks = iter([100.0, 107.5])
    record = maxine.run_clip("/c/eye-contact.py", source, output, tmp_path / "l.py",
                             env={maxine.API_KEY_ENV: FAKE_KEY}, runner=runner,
                             clock=lambda: next(ticks))
    return record, calls


def test_successful_run_is_recorded_with_labelled_turnaround(tmp_path):
    record, _ = _run(tmp_path, returncode=0)
    assert record["success"] is True
    assert record["failures"] == []
    assert record["hosted_turnaround_s"] == 7.5
    assert record["hosted_turnaround_label"] == (
        "HOSTED BATCH/API TURNAROUND - NOT REALTIME LATENCY")


def test_credential_reaches_the_child_only_through_its_environment(tmp_path):
    record, calls = _run(tmp_path, returncode=0)
    assert calls["env"][maxine.API_KEY_ENV] == FAKE_KEY
    assert not any(FAKE_KEY in str(part) for part in calls["command"])
    assert not any(FAKE_KEY in str(part) for part in record["command"])


def test_nonzero_exit_is_a_failure(tmp_path):
    record, _ = _run(tmp_path, returncode=1)
    assert not record["success"]
    assert any("exited 1" in f for f in record["failures"])


def test_missing_output_is_a_failure(tmp_path):
    record, _ = _run(tmp_path, returncode=0, write_output=None)
    assert not record["success"]
    assert "no output file was written" in record["failures"]


def test_empty_output_is_a_failure(tmp_path):
    record, _ = _run(tmp_path, returncode=0, write_output=b"")
    assert not record["success"]
    assert "output file is empty" in record["failures"]


def test_swallowed_client_error_is_caught_despite_exit_zero(tmp_path):
    """NVIDIA's client prints and continues instead of failing; exit 0 lies."""
    record, _ = _run(tmp_path, returncode=0,
                     stdout="An error occurred: StatusCode.UNAUTHENTICATED")
    assert not record["success"]
    assert any("swallowed error" in f for f in record["failures"])


def test_recorded_output_is_redacted(tmp_path):
    record, _ = _run(tmp_path, returncode=1,
                     stderr=f"authorization: Bearer {FAKE_KEY}")
    assert FAKE_KEY not in record["stderr_tail"]
    assert redaction.REDACTED in record["stderr_tail"]


def test_whole_record_survives_a_secret_scan(tmp_path):
    import json
    record, _ = _run(tmp_path, returncode=1, stdout=f"key={FAKE_KEY}",
                     stderr=f"Bearer {FAKE_KEY}")
    assert redaction.scan_text(json.dumps(record)) == []
