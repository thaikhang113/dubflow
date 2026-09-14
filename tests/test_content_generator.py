"""Bước nội dung đăng bài của thư mục youtube trong dự án.

Trước đây bước này luôn ghi một ``youtube_post.txt`` toàn tiêu đề trống vì phần
viết tự động mất máy chủ. Nay nó chạy bằng đúng endpoint OpenAI-compatible mà
người dùng cấu hình ở trang Dịch thuật: có endpoint thì mới có tệp đăng bài,
không có thì thư mục chỉ còn lời thoại và ảnh bìa gốc.
"""
from __future__ import annotations

import json

import pytest

from autodub.config import Settings
from autodub.content import generator
from autodub.providers.openai_compatible import (
    OpenAICompatibleError,
    OpenAICompatibleProvider,
)

_SEGMENTS = [
    {"id": 1, "text": "大家好", "text_vi": "Xin chào mọi người"},
    {"id": 2, "text": "今天很开心", "text_vi": "Hôm nay rất vui"},
]


def _configured(**overrides) -> Settings:
    values = {"translation_endpoint": "https://api.test/v1",
              "translation_api_key": "secret",
              "translation_model": "qwen3:4b"}
    values.update(overrides)
    return Settings(**values)


def _run(tmp_path, settings, segments=None) -> dict:
    return generator.generate_content(
        segments=[dict(s) for s in (segments or _SEGMENTS)],
        source_url=None,
        output_dir=str(tmp_path),
        settings=settings,
    )


def test_skips_post_files_without_endpoint(tmp_path) -> None:
    result = _run(tmp_path, Settings(translation_endpoint="",
                                     translation_model=""))

    assert result["metadata"] == {}
    assert result["post_file"] is None
    assert result["metadata_file"] is None
    assert not (tmp_path / "youtube_post.txt").exists()
    assert not (tmp_path / "youtube_metadata.json").exists()
    # Hai tệp này thì luôn có: lời thoại thuần chữ, dán vào ô mô tả được ngay.
    assert "Xin chào mọi người" in (
        tmp_path / "script_vi.txt").read_text(encoding="utf-8")
    assert "大家好" in (
        tmp_path / "script_original.txt").read_text(encoding="utf-8")


def test_writes_post_file_when_endpoint_answers(tmp_path, monkeypatch) -> None:
    seen: dict = {}

    def fake_complete(self, prompt, **_kwargs):
        seen["prompt"] = prompt
        return {
            "title": "  Review điện thoại mới  ",
            "description": "Cận cảnh máy mới trong 3 phút.",
            "hashtags": ["#dubflow", "  ", "#congnghe"],
            "tiktok": {"title": "Máy mới có đáng?", "hashtags": ["#review"]},
            "facebook": {"description": "Bản lồng tiếng Việt.", "junk": 5},
        }

    monkeypatch.setattr(OpenAICompatibleProvider, "complete_object",
                        fake_complete)
    result = _run(tmp_path, _configured())

    assert "Xin chào mọi người" in seen["prompt"]
    meta = result["metadata"]
    assert meta["title"] == "Review điện thoại mới"
    assert meta["hashtags"] == ["#dubflow", "#congnghe"]
    assert "junk" not in meta["facebook"]
    post = (tmp_path / "youtube_post.txt").read_text(encoding="utf-8")
    assert "TIÊU ĐỀ:\nReview điện thoại mới" in post
    assert "Bản lồng tiếng Việt." in post
    assert result["post_file"] == str(tmp_path / "youtube_post.txt")
    stored = json.loads(
        (tmp_path / "youtube_metadata.json").read_text(encoding="utf-8"))
    assert stored["tiktok"]["title"] == "Máy mới có đáng?"


def test_empty_model_answer_still_skips_post_file(tmp_path,
                                                  monkeypatch) -> None:
    monkeypatch.setattr(OpenAICompatibleProvider, "complete_object",
                        lambda self, prompt, **_kw: {"title": "   "})
    result = _run(tmp_path, _configured())

    assert result["metadata"] == {}
    assert not (tmp_path / "youtube_post.txt").exists()


def test_prompt_and_fields_are_bounded(monkeypatch) -> None:
    seen: dict = {}

    def fake_complete(self, prompt, **_kwargs):
        seen["prompt"] = prompt
        return {"title": "t" * 400, "description": "d"}

    monkeypatch.setattr(OpenAICompatibleProvider, "complete_object",
                        fake_complete)
    meta = generator.generate_social_metadata(
        "", "nội dung " * 4000, video_title="x" * 500,
        settings=_configured())

    assert len(meta["title"]) <= 90
    assert len(seen["prompt"]) < 8000


def test_provider_failure_reaches_the_pipeline_handler(
    monkeypatch,
) -> None:
    """Bước đăng bài là bước phụ: lỗi phải nổi lên để nơi gọi tự quyết định."""

    def boom(self, prompt, **_kwargs):
        raise OpenAICompatibleError("endpoint không trả lời")

    monkeypatch.setattr(OpenAICompatibleProvider, "complete_object", boom)
    with pytest.raises(OpenAICompatibleError):
        generator.generate_social_metadata("", "lời thoại",
                                           settings=_configured())


def test_clean_metadata_keeps_only_usable_parts() -> None:
    """Model hay trả hashtag lẫn số/null: chỉ phần tử chữ mới được giữ."""
    meta = generator._clean_metadata({
        "title": "A",
        "hashtags": ["#x", 1, None, "  "],
        "tiktok": "not-a-dict",
        "description": "",
        "facebook": {"hashtags": []},
    })

    assert meta == {"title": "A", "hashtags": ["#x"]}


def test_metadata_rejects_non_string_text_fields() -> None:
    assert generator._clean_metadata({
        "title": {"unexpected": "object"},
        "description": ["not", "text"],
        "tiktok": {"title": 42},
        "facebook": {"description": True},
    }) == {}


def test_empty_regeneration_removes_old_generated_post_files(
    tmp_path, monkeypatch,
) -> None:
    for filename in ("youtube_post.txt", "youtube_metadata.json"):
        (tmp_path / filename).write_text("old generated content")
    monkeypatch.setattr(OpenAICompatibleProvider, "complete_object",
                        lambda self, prompt, **_kw: {})
    result = _run(tmp_path, _configured())
    assert result["metadata"] == {}
    assert not (tmp_path / "youtube_post.txt").exists()
    assert not (tmp_path / "youtube_metadata.json").exists()


@pytest.mark.parametrize("raw, expected", [
    ('{"title":"A"}', {"title": "A"}),
    ('```json\n{"title":"A"}\n```', {"title": "A"}),
])
def test_complete_object_parses_endpoint_response(raw, expected):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": raw}}]}

    class Session:
        def post(self, *args, **kwargs):
            return Response()

    provider = OpenAICompatibleProvider(
        "http://127.0.0.1:12345", "", "model", session=Session(),
    )
    assert provider.complete_object("prompt") == expected


def test_complete_object_redacts_provider_error():
    class Session:
        def post(self, *args, **kwargs):
            raise OSError("failed with secret-key")

    provider = OpenAICompatibleProvider(
        "http://127.0.0.1:12345", "secret-key", "model", session=Session(),
    )
    with pytest.raises(OpenAICompatibleError) as raised:
        provider.complete_object("prompt")
    assert "secret-key" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
