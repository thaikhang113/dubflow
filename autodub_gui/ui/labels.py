"""Nhãn chữ có sẵn cơ chế chống tràn và chống cắt chữ.

Quy tắc: nhãn dài phải hoặc tự xuống dòng, hoặc rút gọn bằng dấu ba chấm
kèm chú giải đầy đủ. Không bao giờ để chữ bị cắt mà người dùng không có
cách nào xem được bản đầy đủ.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from autodub_gui import tokens

_MIN_ELIDE_W = 40


class ElidedLabel(QLabel):
    """Nhãn một dòng: rút gọn bằng dấu ba chấm, chú giải giữ bản đầy đủ."""

    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight):
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(_MIN_ELIDE_W)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 — theo quy ước của Qt
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply()

    def full_text(self) -> str:
        """Trả về nguyên văn chưa rút gọn."""
        return self._full

    def _apply(self) -> None:
        width = max(self.width(), _MIN_ELIDE_W)
        shown = QFontMetrics(self.font()).elidedText(self._full, self._mode, width)
        QLabel.setText(self, shown)

    def resizeEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        super().resizeEvent(event)
        self._apply()


def styled_label(text: str, *, size: int = tokens.FS_BODY,
                 color: str = tokens.TEXT_PRIMARY, weight: int = 400,
                 wrap: bool = False, parent: QWidget | None = None) -> QLabel:
    """Nhãn thường với cỡ chữ, màu và độ đậm lấy từ token."""
    lbl = QLabel(text, parent)
    lbl.setWordWrap(wrap)
    lbl.setStyleSheet(
        f"QLabel {{ color: {color}; font-size: {size}px; "
        f"font-weight: {weight}; background: transparent; border: none; }}")
    return lbl


def title_label(text: str, parent: QWidget | None = None) -> QLabel:
    """Tiêu đề mục, cỡ 17px in đậm."""
    return styled_label(text, size=tokens.FS_SECTION,
                        color=tokens.TEXT_PRIMARY, weight=700, parent=parent)
