"""Thanh tab dạng viên thuốc — thay QTabBar ở trang Cài đặt.

Một hàng nút bo tròn trong khung nền mờ; nút đang chọn có nền chuyển sắc.
Giao diện giống ảnh mẫu, còn hành vi giữ nguyên kiểu tab: `changed(int)` phát
ra chỉ số của tab vừa chọn.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from autodub_gui import tokens


class PillTabBar(QWidget):
    """Hàng nút viên thuốc, mỗi lúc chỉ chọn được một."""

    changed = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pillTabBar")
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(4)
        self._layout.addStretch()
        self._group.idClicked.connect(self.changed.emit)

    def add_tab(self, label: str, icon: QIcon | None = None) -> None:
        """Thêm một tab; tab đầu tiên tự được chọn."""
        btn = QPushButton(label)
        btn.setObjectName("pillTab")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon is not None:
            btn.setIcon(icon)
        index = len(self._buttons)
        self._group.addButton(btn, index)
        self._buttons.append(btn)
        # Chèn trước stretch cuối để các nút dồn về bên trái.
        self._layout.insertWidget(index, btn)
        if index == 0:
            btn.setChecked(True)

    def current_index(self) -> int:
        return max(self._group.checkedId(), 0)

    def set_tab_text(self, index: int, label: str) -> None:
        """Đổi nhãn một tab — dùng khi nhãn mang số đếm thay đổi theo dữ liệu."""
        if 0 <= index < len(self._buttons):
            self._buttons[index].setText(label)

    def set_current_index(self, index: int) -> None:
        """Chọn tab theo chỉ số và phát tín hiệu như khi người dùng bấm."""
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
            self.changed.emit(index)

    def count(self) -> int:
        return len(self._buttons)
