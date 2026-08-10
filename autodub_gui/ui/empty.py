"""Ba màn hình thay thế khi chưa có nội dung: trống, đang tải và lỗi."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.ui.buttons import GhostButton, PrimaryButton
from autodub_gui.ui.style import clear_background

_ICON_PX = 40
_SPIN_MS = 380
# Chỗ trống tối thiểu để nội dung không bị dính sát mép trên của khung chứa
# khi khung bị bóp thấp.
_MIN_H = 150


def _icon_label(icon: QIcon, size: int = _ICON_PX) -> QLabel:
    """Nhãn chỉ chứa một biểu tượng, căn giữa."""
    lbl = QLabel()
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setPixmap(icon.pixmap(size, size))
    lbl.setStyleSheet("background: transparent; border: none;")
    return lbl


class _StateBase(QWidget):
    """Khung chung: biểu tượng ở giữa, tiêu đề, mô tả và nút hành động."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(_MIN_H)
        # Nền trong suốt để phần này ăn theo nền của thẻ chứa nó. Bảng kiểu
        # chung của ứng dụng đặt nền cho MỌI QWidget, nên nếu không xóa đi
        # thì ở đây hiện ra một khối tối hình chữ nhật, trông như bị dán đè
        # lên thẻ chứ không phải một phần của thẻ.
        clear_background(self)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(tokens.SP_6, tokens.SP_6,
                                      tokens.SP_6, tokens.SP_6)
        self._root.setSpacing(tokens.SP_3)
        self._root.addStretch()

    def _add_title(self, text: str, color: str = tokens.TEXT_SECONDARY,
                   size: int = tokens.FS_CARD_TITLE) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {color}; font-size: {size}px; font-weight: 600; "
            f"background: transparent;")
        self._root.addWidget(lbl)
        return lbl

    def _add_desc(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_LABEL}px; "
            f"background: transparent;")
        self._root.addWidget(lbl)
        return lbl

    def _add_buttons(self, *buttons: QWidget) -> None:
        row = QHBoxLayout()
        row.setSpacing(tokens.SP_2)
        row.addStretch()
        for btn in buttons:
            row.addWidget(btn)
        row.addStretch()
        self._root.addLayout(row)

    def _close(self) -> None:
        self._root.addStretch()


class EmptyState(_StateBase):
    """Danh sách hoặc lưới chưa có dữ liệu, luôn kèm một lời mời hành động."""

    action_clicked = Signal()
    secondary_clicked = Signal()

    def __init__(self, title: str = "Chưa có dữ liệu", description: str = "",
                 action_label: str = "", parent: QWidget | None = None, *,
                 icon: QIcon | None = None, secondary_label: str = ""):
        super().__init__(parent)
        self._root.addWidget(_icon_label(icon or icons.folder(tokens.TEXT_DISABLED)))
        self._title = self._add_title(title)
        self._description = self._add_desc(description)
        self._description.setVisible(bool(description))
        buttons: list[QWidget] = []
        if action_label:
            btn = PrimaryButton(action_label)
            btn.clicked.connect(self.action_clicked.emit)
            buttons.append(btn)
        if secondary_label:
            btn2 = GhostButton(secondary_label)
            btn2.clicked.connect(self.secondary_clicked.emit)
            buttons.append(btn2)
        if buttons:
            self._add_buttons(*buttons)
        self._close()

    def set_message(self, title: str, description: str = "") -> None:
        """Đổi tiêu đề và mô tả mà không phải dựng lại widget."""
        self._title.setText(title)
        self._description.setText(description)
        self._description.setVisible(bool(description))


class LoadingState(_StateBase):
    """Đang đọc dữ liệu từ ổ đĩa. Mọi việc quá 2 giây đều phải có chỉ báo này."""

    def __init__(self, text: str = "Đang tải dữ liệu",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._base = text
        self._label = self._add_title(text, color=tokens.TEXT_SECONDARY,
                                      size=tokens.FS_BODY)
        self._close()
        self._n = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_SPIN_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_text(self, text: str) -> None:
        """Đổi dòng chữ mô tả việc đang làm."""
        self._base = text

    def _tick(self) -> None:
        self._n = (self._n + 1) % 4
        self._label.setText(self._base + "." * self._n)

    def hideEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        self._timer.start()
        super().showEvent(event)


class ErrorState(_StateBase):
    """Không đọc được dữ liệu: nêu rõ chuyện gì, vì sao và làm gì bây giờ."""

    retry_clicked = Signal()
    action_clicked = Signal()

    def __init__(self, title: str = "Không mở được dữ liệu",
                 description: str = "", parent: QWidget | None = None, *,
                 retry_label: str = "Thử lại", action_label: str = ""):
        super().__init__(parent)
        self._root.addWidget(_icon_label(icons.error(tokens.DANGER)))
        self._title = self._add_title(title, color=tokens.DANGER)
        self._desc = self._add_desc(description)
        self._desc.setVisible(bool(description))
        buttons: list[QWidget] = []
        if retry_label:
            btn = GhostButton(retry_label)
            btn.clicked.connect(self.retry_clicked.emit)
            buttons.append(btn)
        if action_label:
            btn2 = PrimaryButton(action_label)
            btn2.clicked.connect(self.action_clicked.emit)
            buttons.append(btn2)
        if buttons:
            self._add_buttons(*buttons)
        self._close()

    def set_description(self, text: str) -> None:
        """Đổi phần mô tả chi tiết bên dưới tiêu đề."""
        self._desc.setText(text)
        self._desc.setVisible(bool(text))

    def set_message(self, title: str, description: str = "") -> None:
        """Đổi cả tiêu đề lẫn mô tả trong một lần gọi."""
        self._title.setText(title)
        self.set_description(description)
