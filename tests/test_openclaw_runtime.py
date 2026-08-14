from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from autodub.openclaw_runtime import OpenClawRuntime


def _request(url: str, token: str, method: str = "GET",
             payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_runtime_starts_loopback_api_and_requires_token(tmp_path):
    runtime = OpenClawRuntime(data_dir=tmp_path)
    runtime.start(worker=False)
    try:
        assert runtime.endpoint.startswith("http://127.0.0.1:")
        status, payload = _request(
            runtime.endpoint + "/health", runtime.token)
        assert status == 200
        assert payload == {"ok": True, "service": "dubflow-openclaw"}

        status, payload = _request(runtime.endpoint + "/health", "wrong")
        assert status == 401
        assert payload["ok"] is False
    finally:
        runtime.stop()


def test_runtime_prepare_and_submit_use_existing_tool_contract(tmp_path):
    runtime = OpenClawRuntime(data_dir=tmp_path)
    runtime.start(worker=False)
    try:
        status, prepared = _request(
            runtime.endpoint + "/v1/prepare",
            runtime.token,
            "POST",
            {"action": "prepare", "text": "https://example.com/video"},
        )
        assert status == 200
        assert prepared["links"] == ["https://example.com/video"]

        status, submitted = _request(
            runtime.endpoint + "/v1/submit",
            runtime.token,
            "POST",
            {"action": "submit",
             "links": ["https://example.com/video"],
             "options": {"voice": "Truc Ly"}},
        )
        assert status == 200
        assert submitted["status"] == "queued"
        assert (tmp_path / "openclaw_queue" / "batches"
                / f"{submitted['batch_id']}.json").is_file()
    finally:
        runtime.stop()


def test_runtime_persists_enabled_state_and_rotates_token(tmp_path):
    runtime = OpenClawRuntime(data_dir=tmp_path)
    old_token = runtime.token
    runtime.set_enabled(True)
    assert runtime.enabled is True
    runtime.stop()

    restored = OpenClawRuntime(data_dir=tmp_path)
    assert restored.enabled is True
    assert restored.token == old_token
    restored.rotate_token()
    assert restored.token != old_token
    restored.set_enabled(False)
    restored.stop()

def test_runtime_builds_dynamic_connection_prompt(tmp_path):
    runtime = OpenClawRuntime(data_dir=tmp_path)
    runtime.start(worker=False)
    try:
        prompt = runtime.connection_prompt()
        assert runtime.endpoint in prompt
        assert runtime.token in prompt
        for text in (
            "GET /health",
            "POST /v1/prepare",
            "POST /v1/submit",
            "GET /v1/batches/{batch_id}",
            "retry-failed",
        ):
            assert text in prompt
    finally:
        runtime.stop()

def test_runtime_health_check_uses_local_api(tmp_path):
    runtime = OpenClawRuntime(data_dir=tmp_path)
    runtime.start(worker=False)
    try:
        assert runtime.check_health() == (
            True, "DubFlow API phản hồi /health.")
    finally:
        runtime.stop()

def test_runtime_health_check_reports_disabled_api(tmp_path):
    runtime = OpenClawRuntime(data_dir=tmp_path)
    assert runtime.check_health() == (False, "DubFlow API đang tắt.")
