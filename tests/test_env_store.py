"""Đọc/ghi tệp cấu hình .env qua env_store.

env_store là lớp cơ sở mà toàn bộ trang Cài đặt và trang Công cụ dùng để
lưu giá trị — nếu nó đọc/ghi sai thì người dùng mất cấu hình hay thấy giá
trị cũ sau khi bấm Lưu. Kiểm thử dưới đây khóa các hành vi then chốt lại.
"""
from __future__ import annotations

import dotenv
import pytest

from autodub_gui.env_store import (
    bool_to_env,
    env_bool,
    env_to_multiline,
    multiline_to_env,
    read_env,
    write_env,
)


@pytest.fixture
def env_file(tmp_path):
    """Trả về đường dẫn tệp .env tạm — không đụng vào .env thật của dự án."""
    return str(tmp_path / ".env")


# ------------------------------------------------------ read_env / write_env #

def test_roundtrip_simple(env_file):
    write_env({"KEY_A": "hello", "KEY_B": "world"}, env_file)
    result = read_env(env_file)
    assert result["KEY_A"] == "hello"
    assert result["KEY_B"] == "world"


def test_read_returns_empty_when_file_missing(tmp_path):
    assert read_env(str(tmp_path / "nonexistent.env")) == {}


def test_write_preserves_comments_and_order(env_file):
    with open(env_file, "w", encoding="utf-8") as f:
        f.write("# ghi chú quan trọng\nFOO=bar\n# dòng hai\nBAZ=qux\n")
    write_env({"FOO": "updated"}, env_file)
    with open(env_file, encoding="utf-8") as f:
        content = f.read()
    assert "# ghi chú quan trọng" in content
    assert "FOO=updated" in content
    assert "BAZ=qux" in content


def test_write_appends_new_key(env_file):
    write_env({"EXISTING": "1"}, env_file)
    write_env({"NEW_KEY": "42"}, env_file)
    result = read_env(env_file)
    assert result["EXISTING"] == "1"
    assert result["NEW_KEY"] == "42"


def test_write_overwrites_existing_key(env_file):
    write_env({"X": "old"}, env_file)
    write_env({"X": "new"}, env_file)
    assert read_env(env_file)["X"] == "new"


def test_write_empty_value(env_file):
    """Giá trị rỗng phải được ghi và đọc lại đúng (dùng để xóa API Key)."""
    write_env({"SECRET": "token123"}, env_file)
    write_env({"SECRET": ""}, env_file)
    assert read_env(env_file)["SECRET"] == ""


# ------------------------------- giá trị tự do phải sống sót qua python-dotenv #
# Giao diện đọc tệp bằng read_env còn pipeline đọc bằng python-dotenv
# (autodub/config.py). Hai bên phải cho ra đúng chuỗi người dùng gõ.

FREE_TEXT_CASES = [
    ("dấu # giữa dòng", "Kênh review #shorts về linh kiện máy tính"),
    ("dấu # sát đầu dòng", "#1 kênh công nghệ cho người mới"),
    ("bắt đầu bằng nháy đôi", '"giữ nguyên" tên nhân vật'),
    ("bắt đầu bằng nháy đơn", "'tên gốc' giữ nguyên"),
    ("tên biến không xuống dòng", "$HOME và $USER giữ nguyên"),
    ("đường dẫn có dấu \\", r"C:\Users\video\output"),
    ("dấu \\ trước n", r"giữ \n nguyên văn"),
    ("nhiều dấu \\", r"\\server\share"),
]


@pytest.mark.parametrize("label,typed", FREE_TEXT_CASES,
                         ids=[c[0] for c in FREE_TEXT_CASES])
def test_free_text_survives_read_env_and_dotenv(env_file, label, typed):
    write_env({"FREETEXT": typed}, env_file)
    assert read_env(env_file)["FREETEXT"] == typed
    assert dotenv.dotenv_values(env_file)["FREETEXT"] == typed


@pytest.mark.parametrize("label,typed", FREE_TEXT_CASES,
                         ids=[c[0] for c in FREE_TEXT_CASES])
def test_free_text_reads_back_after_reload(env_file, label, typed):
    """Lần ghi sau đọc lại dòng đã trích dẫn, không bị nhân đôi dấu \\."""
    write_env({"FREETEXT": typed}, env_file)
    write_env({"OTHER": "x"}, env_file)
    assert read_env(env_file)["FREETEXT"] == typed
    assert dotenv.dotenv_values(env_file)["FREETEXT"] == typed


def test_multiline_glossary_reaches_pipeline_as_real_newlines(env_file):
    """Bảng thuật ngữ nhiều dòng: read_env giữ \\n, pipeline nhận xuống dòng thật."""
    typed = "AI = trí tuệ nhân tạo # giữ nguyên tiếng Anh\nGPU = card đồ họa"
    write_env({"TRANSLATE_GLOSSARY": multiline_to_env(typed)}, env_file)

    assert read_env(env_file)["TRANSLATE_GLOSSARY"] == multiline_to_env(typed)
    raw = dotenv.dotenv_values(env_file)["TRANSLATE_GLOSSARY"]
    assert env_to_multiline(raw) == typed


# ponytail: dotenv nội suy ${TÊN_BIẾN} ngay cả trong giá trị được trích dẫn,
# nên giá trị vừa có " #" vừa có ${…} vẫn mất phần biến. Muốn chặn hẳn thì
# phải bỏ python-dotenv ở autodub/config.py, không sửa được từ phía ghi.


def test_dollar_name_value_reaches_pipeline_literally(env_file, monkeypatch):
    """$NAME phải tới pipeline nguyên văn, không bị thay bằng biến môi trường."""
    monkeypatch.setenv("TRANSLATE_DOMAIN", "env-value")
    write_env({"TRANSLATE_DOMAIN": "giá $TRANSLATE_DOMAIN giữ nguyên"},
              env_file)
    assert read_env(env_file)["TRANSLATE_DOMAIN"] == (
        "giá $TRANSLATE_DOMAIN giữ nguyên")
    assert dotenv.dotenv_values(env_file)["TRANSLATE_DOMAIN"] == (
        "giá $TRANSLATE_DOMAIN giữ nguyên")


PLAIN_VALUES = ["0", "true", "balanced", "12.5", "", "/home/user/video"]


@pytest.mark.parametrize("plain", PLAIN_VALUES)
def test_plain_values_stay_byte_identical(env_file, plain):
    write_env({"PLAIN": plain}, env_file)
    with open(env_file, encoding="utf-8") as f:
        assert f"PLAIN={plain}\n" in f.read()
    assert read_env(env_file)["PLAIN"] == plain
    assert dotenv.dotenv_values(env_file)["PLAIN"] == plain


# ---------------------------------------------------------------- env_bool -- #

@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("True", True), ("TRUE", True),
    ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("off", False),
    ("", False), ("garbage", False),
])
def test_env_bool_parsing(raw, expected):
    assert env_bool(raw) is expected


def test_env_bool_default_is_used_on_empty():
    assert env_bool("", default=True) is True
    assert env_bool("", default=False) is False


# --------------------------------------------------------------- bool_to_env #

def test_bool_to_env_true():
    assert bool_to_env(True) == "true"


def test_bool_to_env_false():
    assert bool_to_env(False) == "false"


# -------------------------------------------- multiline round-trip ---------- #

def test_multiline_roundtrip():
    original = "line one\nline two\nline three"
    encoded = multiline_to_env(original)
    assert "\n" not in encoded   # phải nằm trên 1 dòng trong .env
    assert env_to_multiline(encoded) == original


def test_multiline_preserves_empty_lines():
    """Dòng trống giữa các câu lệnh prompt là có nghĩa — không được mất."""
    original = "first\n\nthird"
    assert env_to_multiline(multiline_to_env(original)) == original
