"""Trang Giọng đọc AI — thư viện giọng tách khỏi trang Cài đặt.

Phần lưới giọng dùng lại nguyên `VoiceLibraryTab`, chỉ khác ở chỗ trang này
có chân trang Hủy và Lưu riêng, ghi thẳng xuống tệp cấu hình mà không đụng
tới những mục khác của trang Cài đặt.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from autodub_gui.pages import settings_fields as spec
from autodub_gui.pages.tool_page_base import ToolPage
from autodub_gui.pages.voice_library import VoiceLibraryTab


class VoiceToolPage(ToolPage):
    """Chọn giọng đọc, phong cách và nghe thử trước khi lưu."""

    TAB = spec.TAB_VOICE
    TITLE = "Giọng đọc AI"
    SUBTITLE = ("Chọn giọng và phong cách cho video lồng tiếng. "
                "Bấm nghe thử để so trước khi lưu.")
    SAVE_LABEL = "Lưu giọng đọc"
    SAVED_TOAST = "Đã lưu giọng đọc."

    def _build_body(self) -> QWidget:
        # Thư viện giọng tự lo phần cuộn bên trong, không bọc thêm QScrollArea.
        self.voice_panel = VoiceLibraryTab(self._current_settings)
        self.voice_panel.changed.connect(self._mark_dirty)
        return self.voice_panel

    def fields(self):
        # Thẻ Giọng đọc không có mục nào trong bảng khai báo — mọi giá trị
        # đều do thư viện giọng tự quản.
        return []

    def load_extra(self, env: dict[str, str]) -> None:
        self.voice_panel.load(env)

    def collect_extra(self) -> dict[str, str]:
        return self.voice_panel.values()

    def _current_settings(self):
        """Cấu hình phản ánh đúng giọng đang chọn trên màn hình.

        Nghe thử phải dùng giọng vừa bấm, chứ không phải giọng đã lưu lần
        trước, nếu không nút nghe thử thành vô nghĩa.
        """
        from dataclasses import replace

        from autodub.config import Settings

        settings = Settings.load(override=True)
        panel = getattr(self, "voice_panel", None)
        if panel is None:
            return settings
        values = panel.values()
        changes: dict = {}
        if values.get("VIENEU_VOICE"):
            changes["vieneu_voice"] = values["VIENEU_VOICE"]
        if values.get("VIENEU_STYLE"):
            changes["vieneu_style"] = values["VIENEU_STYLE"]
        return replace(settings, **changes) if changes else settings

    def cleanup(self) -> None:
        panel = getattr(self, "voice_panel", None)
        if panel is not None and hasattr(panel, "cleanup"):
            panel.cleanup()
