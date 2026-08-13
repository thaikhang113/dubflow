import json

from autodub.pipeline_state import (
    grouped_settings,
    load_pipeline_state,
    mark_interrupted,
    record_event,
    save_pipeline_state,
)
from autodub.progress import ProgressEvent
from autodub.progress import ProgressReporter


def test_pipeline_state_round_trips_and_records_events(tmp_path):
    work_dir = str(tmp_path / "project")
    state = load_pipeline_state(work_dir)
    save_pipeline_state(work_dir, state)

    record_event(work_dir, ProgressEvent("asr", "start"))
    record_event(work_dir, ProgressEvent("asr", "done", detail="10 câu"))
    mark_interrupted(work_dir, "interrupted", "user cancelled")

    loaded = load_pipeline_state(work_dir)
    assert loaded["version"] == 1
    assert loaded["pipeline"]["current_step"] == "asr"
    assert loaded["pipeline"]["completed_steps"] == ["asr"]
    assert loaded["pipeline"]["status"] == "interrupted"
    assert loaded["pipeline"]["last_error"] == "user cancelled"


def test_invalid_state_returns_safe_default(tmp_path):
    work_dir = str(tmp_path / "project")
    state_path = tmp_path / "project" / "data" / "pipeline_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{broken", encoding="utf-8")

    state = load_pipeline_state(work_dir)
    assert state["version"] == 1
    assert state["pipeline"]["status"] == "new"


def test_progress_reporter_persists_without_callback(tmp_path):
    work_dir = str(tmp_path / "project")
    reporter = ProgressReporter(state_work_dir=work_dir)
    reporter.emit("translate", "start")
    state = load_pipeline_state(work_dir)
    assert state["pipeline"]["current_step"] == "translate"
    assert state["steps"]["translate"]["status"] == "running"


def test_grouped_settings_keeps_stage_snapshots_without_secrets():
    groups = grouped_settings(
        {"voice": "female", "subtitle_mode": "burn", "logo_path": "logo.png"},
        {"asr_engine": "whisper", "voice_speed": 1.1,
         "translation_api_key": "must-not-be-copied"},
    )
    assert groups["recognition"]["asr_engine"] == "whisper"
    assert groups["voice"]["voice"] == "female"
    assert groups["export"]["subtitle_mode"] == "burn"
    assert groups["merge"] == {}
    assert "translation_api_key" not in groups["translation"]
