import json
import threading

import pytest

from autodub.remote_worker import (
    JobValidationError,
    cancel_job,
    load_job,
    submit_job,
)


def test_submit_job_writes_whitelisted_payload_and_loads_it(tmp_path):
    job_id = submit_job(
        str(tmp_path),
        {
            "job_id": "job-1",
            "request": {"file_path": str(tmp_path / "input.mp4")},
            "branding": {"vision_enabled": True},
        },
    )

    assert job_id == "job-1"
    assert load_job(str(tmp_path), job_id)["job_id"] == job_id
    assert (tmp_path / "inbox" / "job-1.json").is_file()


def test_submit_job_rejects_unknown_fields_and_duplicate_ids(tmp_path):
    with pytest.raises(JobValidationError):
        submit_job(str(tmp_path), {"job_id": "job-1", "shell": "del *"})

    submit_job(str(tmp_path), {"job_id": "job-1", "request": {}})
    with pytest.raises(JobValidationError):
        submit_job(str(tmp_path), {"job_id": "job-1", "request": {}})


def test_submit_job_cleans_partial_files_when_status_write_fails(
    monkeypatch, tmp_path
):
    import autodub.remote_worker as worker_module

    original_atomic_json = worker_module._atomic_json
    calls = 0

    def fail_status_write(path, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("status disk failure")
        return original_atomic_json(path, payload)

    monkeypatch.setattr(worker_module, "_atomic_json", fail_status_write)

    with pytest.raises(OSError, match="status disk failure"):
        submit_job(str(tmp_path), {"job_id": "job-1", "request": {}})

    assert not (tmp_path / "inbox" / "job-1.json").exists()
    assert not (tmp_path / "status" / "job-1.json").exists()


def test_cancel_job_writes_marker(tmp_path):
    submit_job(str(tmp_path), {"job_id": "job-1", "request": {}})

    cancel_job(str(tmp_path), "job-1")

    assert (tmp_path / "cancel" / "job-1").is_file()


def test_cancel_queued_job_is_terminal_before_worker_starts(tmp_path):
    submit_job(str(tmp_path), {"job_id": "job-1", "request": {}})

    cancel_job(str(tmp_path), "job-1")

    status = json.loads(
        (tmp_path / "status" / "job-1.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "cancelled"
    assert status["percent"] == 100
    assert not (tmp_path / "inbox" / "job-1.json").exists()


def test_load_job_rejects_malformed_json(tmp_path):
    path = tmp_path / "status"
    path.mkdir()
    (path / "job-1.json").write_text("{", encoding="utf-8")

    with pytest.raises(JobValidationError):
        load_job(str(tmp_path), "job-1")


def test_worker_request_payload_merges_branding_fields():
    from autodub.remote_worker import request_from_payload

    request = request_from_payload({
        "request": {"file_path": "input.mp4"},
        "branding": {"logo_path": "logo.png", "vision_enabled": True},
    })

    assert request.file_path == "input.mp4"
    assert request.logo_path == "logo.png"
    assert request.vision_enabled is True


def test_worker_settings_payload_overrides_only_allowed_settings():
    from autodub.config import Settings
    from autodub.remote_worker import settings_from_payload

    settings = settings_from_payload(
        {"settings": {"translate_batch_size": 7}},
        Settings(),
    )

    assert settings.translate_batch_size == 7

@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_worker_stops_cancel_watcher_after_terminal_job(
    monkeypatch, tmp_path, outcome
):
    import autodub.pipeline as pipeline_module
    import autodub.remote_worker as worker_module

    stop_event = threading.Event()
    watcher_threads = []
    cancel_events = []
    original_watch = worker_module._watch_cancel

    def watch_cancel(*args):
        watcher_threads.append(threading.current_thread())
        return original_watch(*args)

    class FakePipeline:
        def __init__(self, _settings, *, cancel_event, progress):
            del progress
            cancel_events.append(cancel_event)

        def run(self, _request):
            stop_event.set()
            if outcome == "failed":
                raise RuntimeError("pipeline failed")
            return type("Result", (), {
                "status": "completed",
                "report": {},
            })()

    monkeypatch.setattr(worker_module, "_watch_cancel", watch_cancel)
    monkeypatch.setattr(pipeline_module, "DubPipeline", FakePipeline)
    submit_job(
        str(tmp_path),
        {"job_id": "job-1", "request": {"file_path": "input.mp4"}},
    )

    worker_module.run_worker(
        str(tmp_path),
        type("Settings", (), {})(),
        stop_event=stop_event,
        poll_s=0.01,
    )

    assert cancel_events and cancel_events[0].is_set()
    assert watcher_threads and not watcher_threads[0].is_alive()
