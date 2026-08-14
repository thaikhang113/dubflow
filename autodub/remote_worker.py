"""File-queue worker contract for remote OpenClaw jobs."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

_TOP_LEVEL_KEYS = {"job_id", "request", "branding"}
_REQUEST_KEYS = {
    "url", "file_path", "source_lang", "voice", "clone_voice",
    "clone_source", "clone_reference_audio", "bg_mode", "bg_duck_db",
    "skip_video", "output_dir", "resume_dir", "subtitle_mode",
    "blur_regions", "subtitle_style", "mirror", "ocr_enabled", "target",
}
_BRANDING_KEYS = {
    "logo_path", "intro_path", "outro_path", "vision_enabled",
    "logo_opacity", "logo_scale", "logo_position", "logo_region",
}
_SETTINGS_KEYS = {
    "translate_enabled", "translate_batch_size", "translate_cps_budget",
    "translate_domain", "translate_context", "translate_pronouns",
    "translate_glossary", "translate_style_notes", "generate_metadata",
}


class JobValidationError(ValueError):
    pass


def request_from_payload(payload: dict):
    from autodub.pipeline import DubRequest

    request_data = dict(payload.get("request", {}))
    request_data.update(payload.get("branding", {}))
    request_data.pop("logo_position", None)
    return DubRequest(**request_data)


def _root(root: str) -> Path:
    return Path(root).expanduser().resolve()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _validate_job(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise JobValidationError("job must be an object")
    unknown = set(payload) - (_TOP_LEVEL_KEYS | {"settings"})
    if unknown:
        raise JobValidationError(f"unknown job fields: {sorted(unknown)}")
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip() or "/" in job_id or "\\" in job_id:
        raise JobValidationError("job_id must be a safe non-empty filename")
    for name, allowed in (("request", _REQUEST_KEYS), ("branding", _BRANDING_KEYS)):
        value = payload.get(name, {})
        if not isinstance(value, dict):
            raise JobValidationError(f"{name} must be an object")
        unknown = set(value) - allowed
        if unknown:
            raise JobValidationError(f"unknown {name} fields: {sorted(unknown)}")
    settings = payload.get("settings", {})
    if not isinstance(settings, dict):
        raise JobValidationError("settings must be an object")
    unknown = set(settings) - _SETTINGS_KEYS
    if unknown:
        raise JobValidationError(f"unknown settings fields: {sorted(unknown)}")
    return dict(payload)


def settings_from_payload(payload: dict, settings):
    overrides = payload.get("settings", {})
    if not overrides:
        return settings
    try:
        return replace(settings, **overrides)
    except TypeError as exc:
        raise JobValidationError(f"invalid settings override: {exc}") from exc


def _job_paths(root: Path, job_id: str) -> list[Path]:
    return [root / folder / f"{job_id}.json" for folder in ("inbox", "running", "status")]


def submit_job(root: str, payload: dict) -> str:
    job = _validate_job(payload)
    base = _root(root)
    if any(path.exists() for path in _job_paths(base, job["job_id"])):
        raise JobValidationError(f"job already exists: {job['job_id']}")
    _atomic_json(base / "inbox" / f"{job['job_id']}.json", job)
    _atomic_json(
        base / "status" / f"{job['job_id']}.json",
        {
            "job_id": job["job_id"],
            "status": "queued",
            "percent": 0,
            "step": "queued",
            "detail": "",
            "output": {},
            "warnings": [],
            "error": "",
        },
    )
    return job["job_id"]


def load_job(root: str, job_id: str) -> dict:
    if not isinstance(job_id, str) or "/" in job_id or "\\" in job_id:
        raise JobValidationError("invalid job_id")
    base = _root(root)
    for path in _job_paths(base, job_id):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise JobValidationError(f"invalid job JSON: {job_id}") from exc
    raise FileNotFoundError(job_id)


def cancel_job(root: str, job_id: str) -> None:
    if not isinstance(job_id, str) or not job_id or "/" in job_id or "\\" in job_id:
        raise JobValidationError("invalid job_id")
    base = _root(root)
    marker = base / "cancel" / job_id
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="ascii")


def _write_status(root: Path, job_id: str, **changes) -> None:
    path = root / "status" / f"{job_id}.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current = {"job_id": job_id}
    current.update(changes)
    _atomic_json(path, current)


def run_worker(root: str, settings, stop_event=None, poll_s: float = 1.0) -> None:
    """Process queued jobs serially until ``stop_event`` is set."""
    from autodub.pipeline import DubPipeline

    base = _root(root)
    (base / "inbox").mkdir(parents=True, exist_ok=True)
    while stop_event is None or not stop_event.is_set():
        jobs = sorted((base / "inbox").glob("*.json"))
        if not jobs:
            time.sleep(poll_s)
            continue
        inbox_path = jobs[0]
        job_id = inbox_path.stem
        running_path = base / "running" / inbox_path.name
        running_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(inbox_path, running_path)
        except OSError:
            continue
        try:
            payload = _validate_job(json.loads(running_path.read_text(encoding="utf-8")))
            _write_status(base, job_id, status="running", step="pipeline")
            request = request_from_payload(payload)
            job_settings = settings_from_payload(payload, settings)
            cancel_event = threading.Event()
            watcher = threading.Thread(
                target=_watch_cancel,
                args=(base, job_id, cancel_event, stop_event),
                daemon=True,
            )
            watcher.start()

            def on_progress(event):
                percent = round(
                    (event.current / event.total) * 100
                    if event.total else 0
                )
                _write_status(
                    base, job_id, status="running", step=event.step,
                    percent=percent, detail=event.detail,
                )

            result = DubPipeline(
                job_settings, progress=on_progress, cancel_event=cancel_event,
            ).run(request)
            final_status = "cancelled" if cancel_event.is_set() else result.status
            _write_status(
                base,
                job_id, status=final_status,
                percent=100,
                step="done",
                output=result.report,
            )
        except Exception as exc:
            _write_status(base, job_id, status="failed", error=str(exc))
        finally:
            try:
                running_path.unlink()
            except OSError:
                pass


def _watch_cancel(root: Path, job_id: str, cancel_event, stop_event) -> None:
    marker = root / "cancel" / job_id
    while not cancel_event.is_set():
        if marker.exists() or (stop_event is not None and stop_event.is_set()):
            cancel_event.set()
            return
        time.sleep(0.25)
