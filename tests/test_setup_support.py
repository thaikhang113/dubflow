from scripts.setup_support import is_nonempty_file, retry_call, smoke_request
from autodub_gui.workers_setup import format_setup_failure, setup_environment


def test_retry_call_retries_transient_failure():
    attempts = []

    def operation():
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("temporary network failure")
        return "ok"

    assert retry_call(operation, attempts=3, delay=0, sleep=lambda _: None) == "ok"
    assert len(attempts) == 3


def test_retry_call_raises_last_error_after_limit():
    def operation():
        raise OSError("still offline")

    try:
        retry_call(operation, attempts=2, delay=0, sleep=lambda _: None)
    except OSError as exc:
        assert str(exc) == "still offline"
    else:
        raise AssertionError("retry_call did not raise")


def test_is_nonempty_file_rejects_missing_and_empty(tmp_path):
    path = tmp_path / "artifact.bin"
    assert not is_nonempty_file(path)
    path.write_bytes(b"")
    assert not is_nonempty_file(path)
    path.write_bytes(b"ok")
    assert is_nonempty_file(path)


def test_smoke_request_matches_worker_protocol():
    assert smoke_request("C:/audio.wav") == '{"audio": "C:/audio.wav"}\n'


def test_setup_environment_overrides_stale_data_root():
    env = setup_environment({"DUBFLOW_DATA_DIR": "old"}, "D:/data", "D:/app")
    assert env["DUBFLOW_DATA_DIR"] == "D:/data"
    assert env["DUBFLOW_APP_ROOT"] == "D:/app"
    assert env["DUBFLOW_BACKEND_PLAN"].replace("\\", "/") == (
        "D:/data/backend-plan.json"
    )


def test_setup_failure_keeps_script_tail():
    message = format_setup_failure("setup_vsr.py", 2, ["pip failed"])
    assert "setup_vsr.py" in message
    assert "2" in message
    assert "pip failed" in message
