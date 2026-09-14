"""Tests for DubPipeline._load_translation validation."""
import json

import pytest

from autodub.config import Settings
from autodub.languages import get_target
from autodub.pipeline import DubPipeline


@pytest.fixture
def pipeline():
    return DubPipeline(Settings())


@pytest.fixture
def target_vi():
    return get_target("vi")


def _write(tmp_path, data, raw=None):
    path = tmp_path / "transcript_vi.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


SEGMENTS = [
    {"id": 1, "text": "hello", "start": 0.0, "end": 2.0, "duration": 2.0},
    {"id": 2, "text": "world", "start": 2.0, "end": 4.0, "duration": 2.0},
]


def test_valid_translation_loads(pipeline, target_vi, tmp_path):
    translated = [{**s, "text_vi": f"vi {s['text']}"} for s in SEGMENTS]
    path = _write(tmp_path, translated)
    result = pipeline._load_translation(path, SEGMENTS, target_vi)
    assert len(result) == 2
    # Terminal punctuation is enforced on load (manual translations too).
    assert result[0]["text_vi"] == "vi hello."
    # Slots annotated: real window until the next line starts.
    assert result[0]["slot"] == 2.0

def test_translation_load_preserves_detected_speaker_voice(
    pipeline, target_vi, tmp_path
):
    original = [
        {**SEGMENTS[0], "speaker_id": "speaker_01", "voice": "Clone A"},
        SEGMENTS[1],
    ]
    translated = [{**s, "text_vi": f"vi {s['text']}"} for s in SEGMENTS]
    path = _write(tmp_path, translated)

    result = pipeline._load_translation(path, original, target_vi)

    assert result[0]["speaker_id"] == "speaker_01"
    assert result[0]["voice"] == "Clone A"


def test_invalid_json_raises(pipeline, target_vi, tmp_path):
    path = _write(tmp_path, None, raw='```json\n[{"id": 1}]\n```')
    with pytest.raises(ValueError, match="Invalid JSON"):
        pipeline._load_translation(path, SEGMENTS, target_vi)


def test_missing_text_field_raises(pipeline, target_vi, tmp_path):
    translated = [{**SEGMENTS[0], "text_vi": "ok"}, dict(SEGMENTS[1])]  # seg 2 untranslated
    path = _write(tmp_path, translated)
    with pytest.raises(ValueError, match="text_vi"):
        pipeline._load_translation(path, SEGMENTS, target_vi)


def test_empty_array_raises(pipeline, target_vi, tmp_path):
    path = _write(tmp_path, [])
    with pytest.raises(ValueError, match="non-empty"):
        pipeline._load_translation(path, SEGMENTS, target_vi)


def test_non_array_raises(pipeline, target_vi, tmp_path):
    path = _write(tmp_path, {"segments": []})
    with pytest.raises(ValueError, match="non-empty"):
        pipeline._load_translation(path, SEGMENTS, target_vi)


def test_count_mismatch_warns_but_loads(pipeline, target_vi, tmp_path):
    translated = [{**SEGMENTS[0], "text_vi": "vi"}]
    path = _write(tmp_path, translated)
    result = pipeline._load_translation(path, SEGMENTS, target_vi)
    assert len(result) == 1

def test_quality_report_does_not_require_missing_usage_snapshot() -> None:
    report = DubPipeline._build_quality_report(
        get_target("vi"),
        SEGMENTS,
        {},
        Settings(),
    )
    assert report["translate_usage"] == {}


# -- Lùi sang dịch tay khi endpoint hỏng ---------------------------------- #

def _vi_target():
    return get_target("vi")


def test_endpoint_failure_falls_back_to_manual_translation(monkeypatch):
    """Mất mạng / JSON hỏng không được xóa bỏ phần nghe-chép đã mất vài phút."""
    from autodub.providers.openai_compatible import OpenAICompatibleError

    pipeline = DubPipeline(Settings())

    def boom(*_args, **_kwargs):
        raise OpenAICompatibleError("Không nối được tới endpoint")

    monkeypatch.setattr(pipeline, "_auto_translate", boom)
    translated, reason = pipeline._try_auto_translate(
        SEGMENTS, _vi_target(), _request(), "work")

    assert translated is None
    assert "endpoint" in reason


def test_disabled_auto_translation_reports_no_error_reason(monkeypatch):
    pipeline = DubPipeline(Settings())
    monkeypatch.setattr(pipeline, "_auto_translate",
                        lambda *a, **k: None)

    translated, reason = pipeline._try_auto_translate(
        SEGMENTS, _vi_target(), _request(), "work")

    assert translated is None
    assert reason == ""


def test_missing_translation_config_is_still_a_hard_error(monkeypatch):
    """Thiếu endpoint/model: một nút "Lưu" là xong, không dúi người dùng sang
    dịch tay im lặng."""
    from autodub.config import ConfigError

    pipeline = DubPipeline(Settings())

    def missing(*_args, **_kwargs):
        raise ConfigError("Thiếu cấu hình dịch: endpoint")

    monkeypatch.setattr(pipeline, "_auto_translate", missing)
    with pytest.raises(ConfigError):
        pipeline._try_auto_translate(SEGMENTS, _vi_target(), _request(), "work")


def test_cancellation_during_translation_is_not_swallowed(monkeypatch):
    from autodub.progress import PipelineCancelled

    pipeline = DubPipeline(Settings())

    def cancelled(*_args, **_kwargs):
        raise PipelineCancelled("cancelled")

    monkeypatch.setattr(pipeline, "_auto_translate", cancelled)
    with pytest.raises(PipelineCancelled):
        pipeline._try_auto_translate(SEGMENTS, _vi_target(), _request(), "work")


def test_successful_translation_reports_no_reason(monkeypatch):
    pipeline = DubPipeline(Settings())
    translated_rows = [{**SEGMENTS[0], "text_vi": "xin chào"}]
    monkeypatch.setattr(pipeline, "_auto_translate",
                        lambda *a, **k: translated_rows)

    result, reason = pipeline._try_auto_translate(
        SEGMENTS, _vi_target(), _request(), "work")

    assert result == translated_rows
    assert reason == ""


def test_hint_file_names_the_failure_reason(tmp_path):
    from autodub.text.translate_hint import write_hint

    path = write_hint(str(tmp_path), get_target("vi"), "zh-CN",
                      manual_reason="timeout sau 4 lần thử")
    text = open(path, encoding="utf-8").read()

    assert "Lỗi vừa gặp: timeout sau 4 lần thử" in text


def test_hint_file_stays_plain_when_the_user_chose_manual(tmp_path):
    from autodub.text.translate_hint import write_hint

    path = write_hint(str(tmp_path), get_target("vi"), "zh-CN",
                      settings=Settings(translate_enabled=False))
    text = open(path, encoding="utf-8").read()

    assert "Lỗi vừa gặp" not in text
    assert '"Dịch tự động" TẮT' in text


def _request():
    from autodub.pipeline import DubRequest

    return DubRequest(source_lang="zh-CN")

def test_same_source_and_target_skips_translation_configuration() -> None:
    pipeline = DubPipeline(Settings())

    result = pipeline._auto_translate(
        SEGMENTS,
        get_target("vi"),
        "vi",
    )

    assert [item["text_vi"] for item in result] == ["hello", "world"]


def test_auto_translation_splits_a_failed_large_batch(monkeypatch):
    from autodub.providers import openai_compatible

    calls = []

    class Provider:
        def __init__(self, *args):
            pass

        def translate(self, segments, context=None, previous=None):
            calls.append(len(segments))
            if len(segments) > 2:
                raise openai_compatible.OpenAICompatibleError("request timeout")
            return [
                {"id": item["id"], "text_vi": f"vi {item['id']}"}
                for item in segments
            ]

    monkeypatch.setattr(openai_compatible, "OpenAICompatibleProvider", Provider)
    settings = Settings(
        translation_endpoint="http://127.0.0.1:11434",
        translation_model="test-model",
        translate_batch_size=4,
    )
    segments = [
        {"id": i, "text": f"line {i}", "duration": 1.0}
        for i in range(4)
    ]

    result = DubPipeline(settings)._auto_translate_openai(
        segments, get_target("vi"), "zh", None
    )

    assert [item["id"] for item in result] == [0, 1, 2, 3]
    assert calls == [4, 2, 2]
