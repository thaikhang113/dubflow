"""Trang Phụ đề — cấu hình kiểu chữ, nền và hiển thị.

Tách phần Phụ đề của trang Cài đặt ra thành trang riêng. Gồm mọi mục về
màu sắc, kích thước, vị trí, cách ngắt dòng và hiệu ứng karaoke.
"""
from __future__ import annotations

from autodub_gui.pages import settings_fields as spec
from autodub_gui.pages.tool_page_base import ToolPage


class SubtitleToolPage(ToolPage):
    """Tùy chỉnh kiểu chữ, nền và hiệu ứng hiển thị của phụ đề."""

    TAB = spec.TAB_SUBTITLE
    TITLE = "Phụ đề"
    SUBTITLE = ("Tùy chỉnh kiểu chữ, màu sắc, vị trí và cách hiển thị phụ đề "
                "trên video.")
    EXPANDED = {"Mặc định", "Kiểu chữ"}
    SAVE_LABEL = "Lưu cấu hình phụ đề"
    SAVED_TOAST = "Đã lưu cấu hình phụ đề."
