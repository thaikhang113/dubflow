"""Kiểm thử danh sách trắng của ``update_settings``.

Bối cảnh: bản gốc ghi MỌI cặp key/value vào .env qua ``dotenv.set_key`` mà không
kiểm tra gì, nên một người giữ token OpenClaw có thể đổi ``TRANSLATION_ENDPOINT``
và chuyển toàn bộ lời thoại sang máy kẻ tấn công. Các bài dưới đây khoá lại hành
vi đúng: chỉ tám khoá mà ``get_settings`` phơi ra mới ghi được.
"""
import os

import pytest

from autodub.config import Settings
from autodub.openclaw_tools_registry import (
    _WRITABLE,
    dispatch_tool,
    get_settings,
)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Cô lập .env và chặn rò rỉ os.environ giữa các bài kiểm thử.

    ``update_settings`` kết thúc bằng ``Settings.load(override=True)``, hàm này
    gọi ``load_dotenv`` và ghi thẳng vào ``os.environ`` — monkeypatch không tự
    dọn những khoá đó, nên dọn tay ở đây.
    """
    before = set(os.environ)
    monkeypatch.setenv("DUBFLOW_DATA_DIR", str(tmp_path))
    yield tmp_path
    for key in set(os.environ) - before:
        os.environ.pop(key, None)


def _env_text(tmp_path) -> str:
    path = tmp_path / ".env"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _call(updates):
    return dispatch_tool(
        "update_settings", {"updates": updates}, settings=Settings()
    )


def test_rejects_translation_endpoint_redirect(tmp_path):
    """Lỗ hổng chính: đổi endpoint dịch để hớt lời thoại."""
    result = _call({"TRANSLATION_ENDPOINT": "http://attacker.example/"})

    assert result["ok"] is False
    assert "TRANSLATION_ENDPOINT" in result["error"]
    assert "attacker" not in _env_text(tmp_path)


@pytest.mark.parametrize(
    "key",
    [
        "TRANSLATION_ENDPOINT",
        "TRANSLATION_API_KEY",
        "TRANSLATION_MODEL",
        "BILIBILI_COOKIES_FILE",
        "DOUYIN_COOKIES_FILE",
        "BRANDING_LOGO_PATH",
        "BRANDING_INTRO_PATH",
        "BRANDING_OUTRO_PATH",
        "OUTPUT_DIR",
        "PATH",
        "DUBFLOW_DATA_DIR",
        "VIENEU_VENV_PYTHON",
    ],
)
def test_rejects_every_sensitive_key(tmp_path, key):
    """Khoá ngoài danh sách trắng đều bị từ chối, kể cả tên viết thường."""
    for spelling in (key, key.lower()):
        result = _call({spelling: "x"})
        assert result["ok"] is False, spelling
        assert "danh sách trắng" in result["error"], spelling
    assert _env_text(tmp_path) == ""


def test_rejects_newline_in_key_name(tmp_path):
    """``set_key`` không trích dẫn TÊN khoá: xuống dòng sẽ đẻ ra khoá mới."""
    result = _call({"SAFE\nTRANSLATION_ENDPOINT": "http://attacker.example/"})

    assert result["ok"] is False
    assert "tên khoá không hợp lệ" in result["error"]
    assert _env_text(tmp_path) == ""


def test_rejects_newline_in_value(tmp_path):
    """Xuống dòng trong giá trị cũng phá cấu trúc tệp .env."""
    result = _call(
        {"TRANSLATE_DOMAIN": "a\nTRANSLATION_ENDPOINT=http://attacker.example/"}
    )

    assert result["ok"] is False
    assert "TRANSLATE_DOMAIN" in result["error"]
    assert "attacker" not in _env_text(tmp_path)


def test_rejects_control_characters_in_value(tmp_path):
    assert _call({"TRANSLATE_DOMAIN": "a\x00b"})["ok"] is False
    assert _call({"TRANSLATE_DOMAIN": "a\rb"})["ok"] is False
    assert _env_text(tmp_path) == ""


def test_rejects_value_outside_allowed_choices(tmp_path):
    assert _call({"SUBTITLE_MODE": "evil"})["ok"] is False
    assert _call({"QUALITY_PRESET": "ultra"})["ok"] is False
    assert _env_text(tmp_path) == ""


def test_rejects_speed_outside_documented_range(tmp_path):
    """Miền giá trị theo config.py: VIDEO_SPEED 0.5-1.0, VOICE_SPEED 0.5-2.0."""
    assert _call({"VIDEO_SPEED": 9.9})["ok"] is False
    assert _call({"VIDEO_SPEED": 0.1})["ok"] is False
    assert _call({"VOICE_SPEED": 3.0})["ok"] is False
    assert _call({"VIDEO_SPEED": "khong-phai-so"})["ok"] is False
    assert _call({"VIDEO_SPEED": float("nan")})["ok"] is False
    assert _call({"VIDEO_SPEED": True})["ok"] is False
    assert _env_text(tmp_path) == ""


def test_rejects_non_string_and_empty_batches(tmp_path):
    assert _call({})["ok"] is False
    assert _call({1: "x"})["ok"] is False
    result = dispatch_tool(
        "update_settings", {"updates": "khong-phai-dict"}, settings=Settings()
    )
    assert result["ok"] is False
    assert _env_text(tmp_path) == ""


def test_rejected_batch_writes_nothing_at_all(tmp_path):
    """Kiểm tra trước cả lô: nửa hợp lệ không được ghi khi nửa kia bị từ chối."""
    result = _call(
        {
            "TRANSLATE_DOMAIN": "chu de tot",
            "TRANSLATION_ENDPOINT": "http://attacker.example/",
        }
    )

    assert result["ok"] is False
    assert _env_text(tmp_path) == ""


def test_accepts_whitelisted_keys_and_round_trips(tmp_path):
    result = _call(
        {
            "TRANSLATE_ENABLED": False,
            "TRANSLATE_DOMAIN": "review cong nghe",
            "SUBTITLE_MODE": "burn",
            "QUALITY_PRESET": "fast",
            "VIDEO_SPEED": 0.82,
            "VOICE_SPEED": 1.1,
        }
    )

    assert result["ok"] is True
    assert set(result["updated_keys"]) == {
        "TRANSLATE_ENABLED",
        "TRANSLATE_DOMAIN",
        "SUBTITLE_MODE",
        "QUALITY_PRESET",
        "VIDEO_SPEED",
        "VOICE_SPEED",
    }

    reloaded = Settings.load(override=True)
    assert reloaded.translate_enabled is False
    assert reloaded.translate_domain == "review cong nghe"
    assert reloaded.subtitle_mode == "burn"
    assert reloaded.quality_preset == "fast"
    assert reloaded.video_speed == pytest.approx(0.82)
    assert reloaded.voice_speed == pytest.approx(1.1)


def test_accepts_lowercase_key_spelling(tmp_path):
    result = _call({"translate_domain": "chu de"})
    assert result["ok"] is True
    assert result["updated_keys"] == ["TRANSLATE_DOMAIN"]
    assert "TRANSLATE_DOMAIN" in _env_text(tmp_path)


def test_writable_keys_are_exactly_the_readable_surface():
    """Bất biến: đọc được khoá nào thì ghi được đúng khoá đó, không hơn."""
    exposed = set(get_settings()["settings"])
    assert {key.lower() for key in _WRITABLE} == exposed


def test_whitelist_never_contains_a_secret_or_path_key():
    """Chốt chặn hồi quy: không bao giờ nới danh sách trắng sang khoá nguy hiểm."""
    forbidden = ("ENDPOINT", "API_KEY", "TOKEN", "COOKIES", "PATH", "DIR")
    for key in _WRITABLE:
        assert not any(word in key for word in forbidden), key
