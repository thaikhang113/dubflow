"""Chip lọc dạng viên thuốc — dùng ở thư viện giọng đọc.

`ChipRow` là một hàng chip trong đó luôn có chip "Tất cả" đứng đầu; mỗi lúc
chỉ chọn được một chip, giống `SegmentedControl` nhưng các nút tách rời nhau
và bo tròn hẳn.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from autodub_gui import tokens
from autodub_gui.ui.style import clear_background

_ANY = ""


class FilterChip(QPushButton):
    """Một chip nhỏ, bấm để chọn, bấm chip khác để đổi."""

    def __init__(self, text: str, key: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.key = key
        self.setObjectName("chip")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class ChipRow(QWidget):
    """Một hàng chip có nhãn ở đầu; chip "Tất cả" được thêm ngầm."""

    selection_changed = Signal(str)      # key đang chọn, "" nghĩa là tất cả

    def __init__(self, label: str, options: list[tuple[str, str]],
                 parent: QWidget | None = None):
        super().__init__(parent)
        clear_background(self)
        self._chips: list[FilterChip] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SP_2)

        caption = QLabel(label)
        caption.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")
        # Rộng tối thiểu để các hàng chip thẳng cột với nhau; nhãn dài hơn
        # vẫn tự nở ra chứ không bị cắt.
        caption.setMinimumWidth(86)
        layout.addWidget(caption)

        for text, key in [("All", _ANY), *options]:
            chip = FilterChip(text, key)
            self._group.addButton(chip)
            self._chips.append(chip)
            layout.addWidget(chip)
        layout.addStretch()

        self._chips[0].setChecked(True)
        self._group.buttonClicked.connect(
            lambda btn: self.selection_changed.emit(btn.key))

    def current_key(self) -> str:
        """Key của chip đang chọn ("" là Tất cả)."""
        btn = self._group.checkedButton()
        return btn.key if btn is not None else _ANY

    def set_key(self, key: str) -> None:
        """Chọn chip theo key, không phát tín hiệu."""
        for chip in self._chips:
            if chip.key == key:
                chip.setChecked(True)
                return
        self._chips[0].setChecked(True)
