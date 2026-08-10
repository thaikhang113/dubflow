"""Các trang nội dung của ứng dụng.

Mọi trang đều kế thừa `BasePage` để cửa sổ chính có một giao ước chung khi
đóng ứng dụng: hỏi xem trang có việc đang chạy không, yêu cầu dừng, rồi dọn
tài nguyên.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget


class BasePage(QWidget):
    """Lớp cơ sở cho mọi trang. Mặc định không làm gì, trang nào cần thì ghi đè."""

    def is_running(self) -> bool:
        """Trang có tác vụ nền đang chạy không.

        Cửa sổ chính hỏi câu này trước khi đóng để còn kịp cảnh báo người dùng.
        """
        return False

    def has_unsaved_changes(self) -> bool:
        """Trang còn thay đổi chưa lưu không."""
        return False

    def shutdown(self) -> None:
        """Yêu cầu dừng mọi tác vụ nền và chờ chúng kết thúc."""

    def cleanup(self) -> None:
        """Giải phóng tài nguyên: trình phát, tệp đang mở, tiến trình con."""

    def on_shown(self) -> None:
        """Được gọi mỗi khi trang hiện ra, dùng để nạp lại dữ liệu."""

    def on_breakpoint(self, name: str) -> None:
        """Cửa sổ đổi kích thước sang một mốc mới: xl, lg, md hoặc sm."""
