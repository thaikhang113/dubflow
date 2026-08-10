"""Vòng tròn chữ cái đầu trên nền chuyển sắc — đại diện cho giọng đọc.

Không dùng tệp ảnh: mỗi tên được băm ổn định (zlib.crc32) để chọn một cặp màu
trong `tokens.AVATAR_GRADIENTS`, nhờ vậy cùng một tên luôn ra cùng một màu
qua các lần mở ứng dụng.
"""
from __future__ import annotations

import zlib

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from autodub_gui import tokens


def gradient_for(name: str) -> tuple[str, str]:
    """Cặp màu ổn định cho một tên — cùng tên thì cùng màu mãi mãi."""
    pairs = tokens.AVATAR_GRADIENTS
    index = zlib.crc32(name.encode("utf-8")) % len(pairs)
    return pairs[index]


def initial_of(name: str) -> str:
    """Chữ cái đầu của TỪ CUỐI trong tên (tên riêng tiếng Việt đứng cuối)."""
    words = (name or "").strip().split()
    return words[-1][0].upper() if words else "?"


class InitialAvatar(QWidget):
    """Vòng tròn nền chuyển sắc chéo, ở giữa là chữ cái đầu màu trắng."""

    def __init__(self, name: str = "", size: int = 44,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._name = name
        self._size = size
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_name(self, name: str) -> None:
        if name == self._name:
            return
        self._name = name
        self.update()

    def name(self) -> str:
        return self._name

    def sizeHint(self) -> QSize:  # noqa: N802 — theo quy ước của Qt
        return QSize(self._size, self._size)

    def paintEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)

        start, end = gradient_for(self._name)
        grad = QLinearGradient(QPointF(rect.topLeft()),
                               QPointF(rect.bottomRight()))
        grad.setColorAt(0.0, QColor(start))
        grad.setColorAt(1.0, QColor(end))

        path = QPainterPath()
        path.addEllipse(rect)
        painter.fillPath(path, grad)

        font = QFont(self.font())
        font.setPixelSize(int(self._size * 0.42))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(tokens.TEXT_ON_ACCENT))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                         initial_of(self._name))
        painter.end()
