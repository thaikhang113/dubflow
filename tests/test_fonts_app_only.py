"""Bảo đảm phông phụ đề chỉ lấy từ thư mục phông của dự án.

Chữ phụ đề được ghi thẳng lên video bằng libass, mà libass chỉ đọc phông từ
thư mục `fonts/` của dự án. Nếu giao diện cho chọn phông có sẵn trong máy,
video xuất ra trên máy khác sẽ sai phông hoặc mất dấu tiếng Việt.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_GUI = _ROOT / "autodub_gui"

# Những cách gọi bị cấm vì chúng liệt kê phông của hệ điều hành
_FORBIDDEN = (
    re.compile(r"\bsystem_vietnamese_fonts\b"),
    re.compile(r"QFontDatabase\s*\.\s*families\s*\("),
)

# fonts.py được phép nhắc tới QFontDatabase để nạp phông của dự án,
# nhưng vẫn không được gọi hai thứ ở trên.
_SOURCE_FILES = tuple(p for p in _GUI.rglob("*.py")
                      if "__pycache__" not in p.parts)


def test_no_system_font_listing_in_gui() -> None:
    """Không tệp giao diện nào được liệt kê phông của hệ điều hành."""
    offenders: list[str] = []
    for path in _SOURCE_FILES:
        rel = path.relative_to(_ROOT).as_posix()
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern.search(line) for pattern in _FORBIDDEN):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    if offenders:
        pytest.fail(
            "Phông phụ đề chỉ được lấy từ thư mục fonts/ của dự án:\n"
            + "\n".join(offenders))


def test_fonts_module_no_longer_exports_system_helper() -> None:
    """Hàm liệt kê phông hệ thống phải đã bị xóa hẳn."""
    from autodub_gui import fonts

    assert not hasattr(fonts, "system_vietnamese_fonts")


def test_fonts_module_exposes_project_helpers() -> None:
    """Các hàm thay thế phải có mặt."""
    from autodub_gui import fonts

    for name in ("app_font_families", "default_subtitle_font",
                 "font_choices", "has_app_fonts", "fonts_dir"):
        assert hasattr(fonts, name), f"fonts.py thiếu {name}"


def test_fonts_dir_points_into_project() -> None:
    from autodub_gui import fonts

    assert fonts.fonts_dir().replace("\\", "/").endswith("/fonts")


def test_warning_suffix_is_accented_vietnamese() -> None:
    """Hậu tố cảnh báo phải viết tiếng Việt có dấu."""
    from autodub_gui.fonts import NO_VIETNAMESE_SUFFIX

    assert "không hiển thị được dấu tiếng Việt" in NO_VIETNAMESE_SUFFIX


def test_fallback_font_defined() -> None:
    """Thư mục phông trống thì vẫn phải có phương án dự phòng rõ ràng."""
    from autodub_gui.fonts import FALLBACK_FONT

    assert FALLBACK_FONT.strip()


def test_style_dialog_uses_project_font_source() -> None:
    """Hộp thoại kiểu phụ đề phải lấy phông qua hàm dùng chung."""
    text = (_GUI / "style_dialog.py").read_text(encoding="utf-8")
    assert "font_choices" in text
    assert "sys_fonts" not in text
