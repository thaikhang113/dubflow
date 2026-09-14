"""Project listings must reflect reruns and nested artifact changes."""
import json
import os
import wave

import pytest

from autodub_gui import projects


@pytest.fixture
def project_dir(tmp_path):
    work = tmp_path / "example_vi"
    (work / "data").mkdir(parents=True)
    return work


def _state(work, status):
    (work / "data" / "pipeline_state.json").write_text(
        json.dumps({"pipeline": {"status": status}}), encoding="utf-8",
    )


@pytest.mark.parametrize("pending", [False, True])
def test_live_rerun_takes_precedence_over_old_artifacts(project_dir, pending):
    (project_dir / projects.OUTPUT_VIDEO).write_bytes(b"old video")
    if pending:
        (project_dir / projects.PENDING_MARKER).write_text("old hint")
    _state(project_dir, "failed")
    assert projects.load_project(
        str(project_dir), str(project_dir),
    ).status == projects.STATUS_PROCESSING


def test_failed_rerun_does_not_look_completed(project_dir):
    (project_dir / projects.OUTPUT_VIDEO).write_bytes(b"old video")
    _state(project_dir, "failed")
    result = projects.load_project(str(project_dir))
    assert result.status == projects.STATUS_FAILED
    assert result.has_output


@pytest.mark.parametrize("report", ["{invalid", "{}", '{"total_segments": 2}'])
def test_report_without_output_is_not_completion(project_dir, report):
    (project_dir / "data" / "report.json").write_text(report)
    assert projects.load_project(
        str(project_dir),
    ).status != projects.STATUS_COMPLETED


def test_scan_detects_nested_state_updates_without_root_mtime_change(project_dir):
    _state(project_dir, "running")
    parent = str(project_dir.parent)
    assert projects.scan(parent)[0].status == projects.STATUS_PROCESSING
    root_stat = project_dir.stat()
    _state(project_dir, "failed")
    os.utime(project_dir, ns=(root_stat.st_atime_ns, root_stat.st_mtime_ns))
    assert projects.scan(parent)[0].status == projects.STATUS_FAILED


def test_scan_invalidates_running_override_when_job_ends(project_dir):
    (project_dir / projects.OUTPUT_VIDEO).write_bytes(b"video")
    parent = str(project_dir.parent)
    assert projects.scan(
        parent, str(project_dir),
    )[0].status == projects.STATUS_PROCESSING
    assert projects.scan(parent)[0].status == projects.STATUS_COMPLETED


def test_douyin_duration_uses_real_ffprobe(tmp_path):
    from autodub.media.douyin import _ffprobe_duration

    path = tmp_path / "one_second.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 16000)
    assert _ffprobe_duration(path) == pytest.approx(1.0, abs=0.01)
