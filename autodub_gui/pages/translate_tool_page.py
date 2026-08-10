"""Trang Dịch thuật — ngữ cảnh video và kiểm tra kết nối máy chủ.

Mô hình, lời nhắc và API Key đã chuyển hẳn lên máy chủ VoxDub, nên trang này
không còn ô API Key nào. Thứ còn lại là NGỮ CẢNH: những gì người làm kênh
biết về video mà máy không tự đoán chính xác được — chủ đề, xưng hô, thuật
ngữ phải dịch cố định.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from autodub_gui.pages import settings_fields as spec
from autodub_gui.pages.settings_panels import ConnectionChecks
from autodub_gui.pages.tool_page_base import ToolPage


class TranslateToolPage(ToolPage):
    """Ngữ cảnh dịch và trạng thái kết nối tới máy chủ."""

    TAB = spec.TAB_TRANSLATE
    TITLE = "Dịch thuật"
    SUBTITLE = ("Bản dịch do máy chủ VoxDub thực hiện. Điền ngữ cảnh video ở "
                "đây để kết quả bám đúng chủ đề và cách xưng hô của kênh bạn.")
    EXPANDED = {"Ngữ cảnh video"}
    SAVE_LABEL = "Lưu cấu hình dịch"
    SAVED_TOAST = "Đã lưu cấu hình dịch."

    def extra_panels(self) -> list[QWidget]:
        self.checks_panel = ConnectionChecks()
        return [self.checks_panel]

    def cleanup(self) -> None:
        panel = getattr(self, "checks_panel", None)
        if panel is not None and hasattr(panel, "cleanup"):
            panel.cleanup()
