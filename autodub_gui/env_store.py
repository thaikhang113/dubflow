"""Đọc và ghi tệp cấu hình của ứng dụng.

Tệp cấu hình luôn nằm cạnh ứng dụng (cùng thư mục với tệp chạy khi đã đóng
gói) nên không phụ thuộc vào thư mục làm việc hiện tại. Khi ghi, thứ tự dòng
và các dòng ghi chú đều được giữ nguyên; khóa lạ do người dùng tự thêm cũng
không bị mất.
"""
from __future__ import annotations

import os

from autodub.utils import app_root

ENV_PATH = os.path.join(app_root(), ".env")

_TRUE_WORDS = ("1", "true", "yes", "on")
_FALSE_WORDS = ("0", "false", "no", "off")


def read_env(path: str = ENV_PATH) -> dict[str, str]:
    """Đọc toàn bộ cặp khóa và giá trị, bỏ qua dòng trống và dòng ghi chú."""
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()
    return values


def write_env(updates: dict[str, str], path: str = ENV_PATH) -> None:
    """Cập nhật các khóa trong tệp cấu hình, giữ nguyên thứ tự và ghi chú.

    Khóa chưa có sẽ được thêm vào cuối tệp.
    """
    lines: list[str] = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()

    remaining = dict(updates)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                lines[i] = f"{key}={remaining.pop(key)}"

    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        for key, val in remaining.items():
            lines.append(f"{key}={val}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def env_to_multiline(value: str) -> str:
    """Đổi giá trị một dòng có ký tự xuống dòng thoát thành nhiều dòng thật."""
    return value.replace("\\n", "\n")


def multiline_to_env(value: str) -> str:
    """Gói đoạn văn nhiều dòng thành một dòng để lưu vào tệp cấu hình."""
    return value.strip().replace("\r\n", "\n").replace("\n", "\\n")


def env_bool(value: str, default: bool = False) -> bool:
    """Hiểu các cách viết đúng và sai khác nhau của một giá trị bật tắt."""
    text = (value or "").strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return default


def bool_to_env(value: bool) -> str:
    """Ghi giá trị bật tắt về tệp cấu hình theo đúng một kiểu duy nhất."""
    return "true" if value else "false"
