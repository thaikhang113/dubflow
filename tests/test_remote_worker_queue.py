import json

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


def test_cancel_job_writes_marker(tmp_path):
    submit_job(str(tmp_path), {"job_id": "job-1", "request": {}})

    cancel_job(str(tmp_path), "job-1")

    assert (tmp_path / "cancel" / "job-1").is_file()


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
