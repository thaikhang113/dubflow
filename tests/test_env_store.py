"""Đọc/ghi tệp cấu hình .env qua env_store.

env_store là lớp cơ sở mà toàn bộ trang Cài đặt và trang Công cụ dùng để
lưu giá trị — nếu nó đọc/ghi sai thì người dùng mất cấu hình hay thấy giá
trị cũ sau khi bấm Lưu. Kiểm thử dưới đây khóa các hành vi then chốt lại.
"""
from __future__ import annotations

import os

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
