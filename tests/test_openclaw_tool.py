import json
import subprocess
import sys
from pathlib import Path

import pytest

from autodub.config import Settings
from autodub.openclaw_tool import (
    _aggregate_status,
    handle,
    load_batch_status,
)


def test_prepare_extracts_links_and_returns_minimal_questions():
    result = handle(
        {
            "action": "prepare",
            "text": "Làm video này https://example.com/a và https://example.com/b",
        },
        settings=Settings(),
    )

    assert result["ok"] is True
    assert result["links"] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert {question["id"] for question in result["questions"]} == {
        "voice",
        "translate_style",
        "subtitle_mode",
    }


def test_submit_creates_one_job_per_link_and_manifest(tmp_path):
    result = handle(
        {
            "action": "submit",
            "links": ["https://example.com/a", "https://example.com/b"],
            "options": {
                "voice": "Trúc Ly",
                "translate_style": "social",
                "subtitle_mode": "burn",
            },
        },
        queue_root=str(tmp_path),
        settings=Settings(),
    )

    assert result["ok"] is True
    assert len(result["job_ids"]) == 2
    manifest = json.loads(
        (tmp_path / "batches" / f"{result['batch_id']}.json").read_text()
    )
    assert manifest["job_ids"] == result["job_ids"]
    assert len(list((tmp_path / "inbox").glob("*.json"))) == 2
    job = json.loads(
        (tmp_path / "inbox" / f"{result['job_ids'][0]}.json").read_text()
    )
    assert job["request"]["source_lang"] == "zh-CN"
    assert job["settings"]["translate_batch_size"] == 20


def test_status_aggregates_jobs_and_cancel_marks_each_job(tmp_path):
    submitted = handle(
        {
            "action": "submit",
            "links": ["https://example.com/a"],
            "options": {},
        },
        queue_root=str(tmp_path),
        settings=Settings(),
    )
    job_id = submitted["job_ids"][0]
    status_path = tmp_path / "status" / f"{job_id}.json"
    payload = json.loads(status_path.read_text())
    payload.update({"status": "completed", "percent": 100})
    status_path.write_text(json.dumps(payload), encoding="utf-8")

    status = load_batch_status(str(tmp_path), submitted["batch_id"])
    assert status["counts"] == {"completed": 1}
    assert status["percent"] == 100

    payload["status"] = "queued"
    payload["percent"] = 0
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    cancelled = handle(
        {
            "action": "cancel",
            "batch_id": submitted["batch_id"],
        },
        queue_root=str(tmp_path),
        settings=Settings(),
    )
    assert cancelled["cancelled"] == [job_id]
    assert (tmp_path / "cancel" / job_id).is_file()


def test_status_handles_empty_batch_manifest_without_dividing_by_zero(tmp_path):
    batch_id = "batch-empty"
    (tmp_path / "batches").mkdir()
    (tmp_path / "batches" / f"{batch_id}.json").write_text(
        json.dumps({"batch_id": batch_id, "job_ids": []}),
        encoding="utf-8",
    )

    status = load_batch_status(str(tmp_path), batch_id)

    assert status["ok"] is True
    assert status["status"] == "running"
    assert status["percent"] == 0
    assert status["counts"] == {}
    assert status["jobs"] == []


def test_tool_rejects_unknown_options_and_local_files(tmp_path):
    with pytest.raises(ValueError):
        handle(
            {
                "action": "submit",
                "links": ["C:\\video.mp4"],
                "options": {"shell": "del *"},
            },
            queue_root=str(tmp_path),
            settings=Settings(),
        )


def test_retry_failed_replaces_failed_job_in_batch(tmp_path):
    submitted = handle(
        {
            "action": "submit",
            "links": ["https://example.com/a"],
            "options": {},
        },
        queue_root=str(tmp_path),
        settings=Settings(),
    )
    old_id = submitted["job_ids"][0]
    status_path = tmp_path / "status" / f"{old_id}.json"
    status = json.loads(status_path.read_text())
    status.update({"status": "failed", "error": "network"})
    status_path.write_text(json.dumps(status), encoding="utf-8")

    retried = handle(
        {"action": "retry_failed", "batch_id": submitted["batch_id"]},
        queue_root=str(tmp_path),
        settings=Settings(),
    )

    assert retried["job_ids"] and retried["job_ids"][0] != old_id
    manifest = json.loads(
        (tmp_path / "batches" / f"{submitted['batch_id']}.json").read_text()
    )
    assert manifest["job_ids"] == retried["job_ids"]


def test_retry_failed_rolls_back_partial_replacements(monkeypatch, tmp_path):
    import autodub.openclaw_tool as tool_module

    submitted = handle(
        {
            "action": "submit",
            "links": ["https://example.com/a", "https://example.com/b"],
            "options": {},
        },
        queue_root=str(tmp_path),
        settings=Settings(),
    )
    for job_id in submitted["job_ids"]:
        status_path = tmp_path / "status" / f"{job_id}.json"
        status = json.loads(status_path.read_text())
        status["status"] = "failed"
        status_path.write_text(json.dumps(status), encoding="utf-8")

    original_submit = tool_module.submit_job
    calls = 0

    def fail_second_submit(root, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("retry queue failure")
        return original_submit(root, payload)

    monkeypatch.setattr(tool_module, "submit_job", fail_second_submit)
    with pytest.raises(OSError, match="retry queue failure"):
        handle(
            {"action": "retry_failed", "batch_id": submitted["batch_id"]},
            queue_root=str(tmp_path),
            settings=Settings(),
        )

    assert not list((tmp_path / "inbox").glob("*-retry-*.json"))
    retry_statuses = list((tmp_path / "status").glob("*-retry-*.json"))
    assert len(retry_statuses) == 1
    assert json.loads(retry_statuses[0].read_text())["status"] == "cancelled"

def test_cli_emits_utf8_json_on_windows(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "autodub.openclaw_tool",
            "--queue",
            str(tmp_path),
        ],
        input=json.dumps(
            {"action": "prepare", "text": "https://example.com/video"}
        ).encode("utf-8"),
        capture_output=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["ok"] is True

def test_status_keeps_translation_pending_distinct_from_failed(tmp_path):
    submitted = handle(
        {
            "action": "submit",
            "links": ["https://example.com/a"],
            "options": {},
        },
        queue_root=str(tmp_path),
        settings=Settings(),
    )
    job_id = submitted["job_ids"][0]
    status_path = tmp_path / "status" / f"{job_id}.json"
    payload = json.loads(status_path.read_text())
    payload.update({"status": "translate_pending", "percent": 60})
    status_path.write_text(json.dumps(payload), encoding="utf-8")

    status = load_batch_status(str(tmp_path), submitted["batch_id"])

    assert status["status"] == "translate_pending"
    assert status["counts"] == {"translate_pending": 1}
    assert status["percent"] == 60

def test_mixed_completed_and_cancelled_batch_is_terminal():
    jobs = [{"status": "completed"}, {"status": "cancelled"}]
    assert _aggregate_status(jobs) == "cancelled"

def test_submit_rolls_back_jobs_when_manifest_write_fails(monkeypatch, tmp_path):
    import autodub.openclaw_tool as tool_module

    original_replace = tool_module.os.replace

    def fail_manifest_replace(source, destination):
        if destination.parent.name == "batches":
            raise OSError("manifest disk failure")
        return original_replace(source, destination)

    monkeypatch.setattr(tool_module.os, "replace", fail_manifest_replace)

    with pytest.raises(OSError, match="manifest disk failure"):
        handle(
            {
                "action": "submit",
                "links": ["https://example.com/a", "https://example.com/b"],
                "options": {},
            },
            queue_root=str(tmp_path),
            settings=Settings(),
        )

    assert not list((tmp_path / "inbox").glob("*.json"))
    statuses = list((tmp_path / "status").glob("*.json"))
    assert len(statuses) == 2
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["status"] == "cancelled"
        for path in statuses
    )
