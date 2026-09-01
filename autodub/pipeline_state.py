"""Persistent per-project pipeline state.

State lives beside pipeline artifacts so resume does not depend on app cache.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from autodub.workdir import data_path

STATE_VERSION = 1
STATE_FILENAME = "pipeline_state.json"
STEP_SETTING_GROUPS = {
    "prepare": ("source", "mirror", "ocr", "blur", "branding"),
    "recognition": ("asr", "whisper", "paraformer"),
    "translation": ("translate", "metadata", "glossary"),
    "voice": ("voice", "vieneu", "clone"),
    "merge": ("bg_", "timing", "audio", "parallel", "skip_video", "video_speed"),
    "export": ("subtitle", "output", "content", "karaoke"),
}


def _path(work_dir: str) -> str:
    return data_path(work_dir, STATE_FILENAME, create_dir=True)


def _default(work_dir: str) -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "project_id": os.path.basename(os.path.normpath(work_dir)),
        "source": {},
        "settings": {},
        "pipeline": {
            "current_step": "",
            "completed_steps": [],
            "status": "new",
            "last_error": "",
            "updated_at": "",
        },
        "steps": {},
        "artifacts": {},
    }


def load_pipeline_state(work_dir: str) -> dict[str, Any]:
    """Load state, returning a safe default for missing or invalid JSON."""
    path = _path(work_dir)
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError, TypeError):
        return _default(work_dir)
    if not isinstance(value, dict) or value.get("version") != STATE_VERSION:
        return _default(work_dir)
    return value


def save_pipeline_state(work_dir: str, state: dict[str, Any]) -> None:
    """Write state atomically inside the project's data directory."""
    path = _path(work_dir)
    directory = os.path.dirname(path)
    fd, temp_path = tempfile.mkstemp(
        prefix=".pipeline_state.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def update_pipeline_state(work_dir: str, **changes: Any) -> dict[str, Any]:
    state = load_pipeline_state(work_dir)
    for section, values in changes.items():
        if isinstance(values, dict):
            state.setdefault(section, {}).update(values)
        else:
            state[section] = values
    state["pipeline"]["updated_at"] = datetime.now(
        timezone.utc).isoformat()
    save_pipeline_state(work_dir, state)
    return state


def record_event(work_dir: str, event, *, status: str | None = None) -> dict[str, Any]:
    """Persist one ProgressEvent without changing its public shape."""
    state = load_pipeline_state(work_dir)
    step = str(getattr(event, "step", "") or "")
    event_status = status or str(getattr(event, "status", "") or "")
    pipeline = state["pipeline"]
    steps = state.setdefault("steps", {})
    if step == "done":
        pipeline["status"] = "completed"
        pipeline["current_step"] = ""
        pipeline["completed_steps"] = sorted(
            set(pipeline.get("completed_steps", [])))
    else:
        step_state = steps.setdefault(step, {
            "status": "pending",
            "started_at": "",
            "finished_at": "",
            "last_detail": "",
            "current": 0,
            "total": 0,
        })
        step_state["last_detail"] = str(getattr(event, "detail", "") or "")
        step_state["current"] = int(getattr(event, "current", 0) or 0)
        step_state["total"] = int(getattr(event, "total", 0) or 0)
        if event_status == "start":
            step_state["status"] = "running"
            step_state["started_at"] = datetime.now(timezone.utc).isoformat()
        elif event_status in ("done", "skip"):
            step_state["status"] = "done"
            step_state["finished_at"] = datetime.now(timezone.utc).isoformat()
        elif event_status == "error":
            step_state["status"] = "error"
            step_state["finished_at"] = datetime.now(timezone.utc).isoformat()
        pipeline["current_step"] = step
        if event_status in ("done", "skip"):
            completed = set(pipeline.get("completed_steps", []))
            completed.add(step)
            pipeline["completed_steps"] = sorted(completed)
        if event_status == "error":
            pipeline["last_error"] = str(getattr(event, "detail", "") or "")
            pipeline["status"] = "failed"
        elif event_status == "start":
            pipeline["status"] = "running"
    pipeline["last_event"] = {
        "step": step,
        "status": event_status,
        "detail": str(getattr(event, "detail", "") or ""),
        "current": int(getattr(event, "current", 0) or 0),
        "total": int(getattr(event, "total", 0) or 0),
    }
    pipeline["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_pipeline_state(work_dir, state)
    return state


def mark_interrupted(work_dir: str, status: str, error: str = "") -> dict[str, Any]:
    return update_pipeline_state(
        work_dir,
        pipeline={
            "status": status,
            "last_error": error,
        },
    )


def grouped_settings(request: dict[str, Any],
                     runtime: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Create readable per-stage setting snapshots without secrets."""
    source = {**runtime, **request}
    source = {
        key: value for key, value in source.items()
        if key not in {
            "translation_api_key",
            "bilibili_cookies_file",
            "douyin_cookies_file",
        }
    }
    groups: dict[str, dict[str, Any]] = {}
    for stage, prefixes in STEP_SETTING_GROUPS.items():
        groups[stage] = {
            key: value for key, value in source.items()
            if any(key == prefix or key.startswith(prefix)
                   for prefix in prefixes)
        }
    return groups
