import json

import pytest

from autodub.providers.openai_compatible import (
    OpenAICompatibleError,
    OpenAICompatibleProvider,
    build_translation_prompt,
    normalize_endpoint,
)
from autodub.pipeline import _api_translation_batches

def test_api_translation_batches_cap_large_configured_batch():
    batches = _api_translation_batches(list(range(25)), 40)
    assert [len(batch) for batch in batches] == [25]


def test_normalize_endpoint_removes_duplicate_api_suffix():
    assert normalize_endpoint("https://example.test/v1/") == "https://example.test/v1"
    assert normalize_endpoint("https://example.test") == "https://example.test/v1"

def test_public_http_endpoint_is_allowed_for_legacy_servers():
    assert normalize_endpoint("http://example.test") == "http://example.test/v1"

def test_local_http_endpoint_is_allowed():
    assert normalize_endpoint("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1"


def test_list_models_sends_bearer_and_returns_ids():
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "qwen3:4b"}, {"id": "gemma"}]}

    class Session:
        def get(self, url, headers, timeout):
            assert url == "https://example.test/v1/models"
            assert headers["Authorization"] == "Bearer secret"
            return Response()

    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "secret", session=Session()
    )
    assert provider.list_models() == ["qwen3:4b", "gemma"]


def test_chat_completion_builds_voxdub_json_prompt():
    seen = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"segments":[{"id":1,"text_vi":"Xin chào"}]}'}}]}

    class Session:
        def post(self, url, headers, json, timeout):
            seen.update(url=url, headers=headers, payload=json)
            return Response()

    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "secret", model="qwen3:4b", session=Session()
    )
    result = provider.translate(
        [{"id": 1, "text": "你好", "duration": 2.0}],
        {"pronouns": "mình - các bạn", "styleNotes": "tự nhiên"},
        previous=[{"id": 0, "text": "前一句"}],
    )
    assert result == [{"id": 1, "text_vi": "Xin chào"}]
    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert "mình - các bạn" in seen["payload"]["messages"][1]["content"]
    assert "前一句" in seen["payload"]["messages"][1]["content"]

def test_shorten_translation_requests_only_concise_text():
    seen = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {
                "content": '{"segments":[{"id":1,"text_vi":"Câu ngắn."}]}'}}]}

    class Session:
        def post(self, url, headers, json, timeout):
            seen.update(url=url, payload=json)
            return Response()

    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "", model="qwen3:4b", session=Session())
    result = provider.shorten_translations(
        [{"id": 1, "text": "原文", "text_vi": "Bản dịch dài.", "max_chars": 8}]
    )

    assert result == [{"id": 1, "text_vi": "Câu ngắn."}]
    assert "max_chars" in seen["payload"]["messages"][1]["content"]
    assert "Bản dịch dài." in seen["payload"]["messages"][1]["content"]

def test_check_model_sends_minimal_chat_request():
    seen = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class Session:
        def post(self, url, headers, json, timeout):
            seen.update(url=url, payload=json)
            return Response()

    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "secret",
        model="qwen3:4b", session=Session())
    provider.check_model()
    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert seen["payload"]["model"] == "qwen3:4b"


def test_provider_error_does_not_include_api_key():
    class Session:
        def get(self, url, headers, timeout):
            raise RuntimeError("secret")

    provider = OpenAICompatibleProvider("https://example.test", "secret", session=Session())
    with pytest.raises(OpenAICompatibleError) as exc:
        provider.list_models()
    assert "secret" not in str(exc.value)

def test_translate_retries_rate_limit_with_retry_after(monkeypatch):
    waits = []

    class Response:
        status_code = 429
        headers = {"Retry-After": "7"}

        def raise_for_status(self):
            raise RuntimeError("429 Client Error")

    class Success:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {
                "content": '{"segments":[{"id":1,"text_vi":"Xin chao"}]}'}}]}

    class Session:
        def __init__(self):
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return Response() if self.calls == 1 else Success()

    monkeypatch.setattr("autodub.providers.openai_compatible.time.sleep",
                        waits.append)
    result = OpenAICompatibleProvider(
        "https://example.test/v1", "", model="m", session=Session()
    ).translate([{"id": 1, "text": "你好"}])
    assert result[0]["text_vi"] == "Xin chao"
    assert waits == [7.0]

def test_translate_timeout_scales_with_prompt_size():
    seen = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {
                "content": '{"segments":[{"id":1,"text_vi":"Xin chao"}]}'}}]}

    class Session:
        def post(self, url, headers, json, timeout):
            seen["timeout"] = timeout
            return Response()

    segments = [{"id": 1, "text": "x" * 4000}]
    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "", model="m", session=Session())
    provider.translate(segments)

    prompt_size = len(build_translation_prompt(segments))
    expected = max(180, min(1800, 120 + prompt_size // 16))
    assert seen["timeout"] == expected
