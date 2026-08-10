"""Huy hiệu trạng thái nhỏ, viền bo tròn trên nền tối.

Sáu kiểu: hoàn thành, đang xử lý, cảnh báo, lỗi, trung tính và nhấn mạnh.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from autodub_gui import tokens

# kiểu huy hiệu -> (màu chữ, màu nền)
KINDS: dict[str, tuple[str, str]] = {
    "success":    (tokens.SUCCESS, tokens.SUCCESS_BG),
    "processing": (tokens.PROCESSING, tokens.PROCESSING_BG),
    "warning":    (tokens.WARNING, tokens.WARNING_BG),
    "error":      (tokens.DANGER, tokens.DANGER_BG),
    "neutral":    (tokens.TEXT_SECONDARY, tokens.NEUTRAL_BG),
    "accent":     (tokens.ACCENT_PURPLE, tokens.PURPLE_BG),
}
_DEFAULT_KIND = "neutral"

_PAD_X = 10
_HEIGHT = 22
_RADIUS = 7
_MIN_W = 54

# Ánh xạ trạng thái dự án sang kiểu huy hiệu tương ứng
STATUS_KIND: dict[str, str] = {
    "completed": "success",
    "processing": "processing",
    "pending": "warning",
    "locked": "accent",
    "failed": "error",
    "queued": "neutral",
}


class StatusBadge(QWidget):
    """Huy hiệu chữ ngắn, tự co giãn theo độ dài chữ bên trong."""

    def __init__(self, text: str = "", kind: str = _DEFAULT_KIND,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        self._kind = kind if kind in KINDS else _DEFAULT_KIND
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_state(self, text: str, kind: str = _DEFAULT_KIND) -> None:
        """Đổi chữ và kiểu màu của huy hiệu."""
        self._text = text
        self._kind = kind if kind in KINDS else _DEFAULT_KIND
        self.setToolTip(text)
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def kind(self) -> str:
        return self._kind

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(tokens.FS_BADGE + 1)
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def sizeHint(self) -> QSize:  # noqa: N802 — theo quy ước của Qt
        width = QFontMetrics(self._font()).horizontalAdvance(self._text)
        return QSize(max(_MIN_W, width + _PAD_X * 2), _HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 — theo quy ước của Qt
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fg, bg = KINDS[self._kind]
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, _RADIUS, _RADIUS)
        painter.fillPath(path, QColor(bg))
        painter.setPen(QPen(QColor(fg), 1))
        painter.drawPath(path)
        painter.setFont(self._font())
        painter.setPen(QColor(fg))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()
