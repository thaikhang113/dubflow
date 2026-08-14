import json
import subprocess
import sys

import pytest

from autodub.config import Settings
from autodub.openclaw_tool import (
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
        cwd=str(tmp_path.parent.parent),
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["ok"] is True
