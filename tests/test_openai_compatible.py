import json

import pytest

from autodub.providers.openai_compatible import (
    OpenAICompatibleError,
    OpenAICompatibleProvider,
    normalize_endpoint,
)


def test_normalize_endpoint_removes_duplicate_api_suffix():
    assert normalize_endpoint("https://example.test/v1/") == "https://example.test/v1"
    assert normalize_endpoint("https://example.test") == "https://example.test/v1"


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


def test_provider_error_does_not_include_api_key():
    class Session:
        def get(self, url, headers, timeout):
            raise RuntimeError("secret")

    provider = OpenAICompatibleProvider("https://example.test", "secret", session=Session())
    with pytest.raises(OpenAICompatibleError) as exc:
        provider.list_models()
    assert "secret" not in str(exc.value)
