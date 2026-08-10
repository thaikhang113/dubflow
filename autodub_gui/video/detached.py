"""Cửa sổ xem video tách rời: toàn màn hình hoặc cửa sổ nhỏ nổi trên cùng.

Dùng cửa sổ riêng thay vì phóng to cả ứng dụng, để người dùng vẫn thấy thanh
bên và quay lại được ngay khi đóng.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QDialog, QGraphicsScene, QGraphicsView, QVBoxLayout, QWidget,
)

from autodub_gui import tokens

try:
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False


class DetachedVideoWindow(QDialog):
    """Cửa sổ chỉ có hình ảnh, không viền."""

    closed = Signal()

    def __init__(self, player, parent: QWidget | None = None, *,
                 fullscreen: bool = False,
                 size: tuple[int, int] = (320, 180)):
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if not fullscreen:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setWindowTitle("Xem video")
        self._player = player
        self._fullscreen = fullscreen
        self._size = size

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QGraphicsView()
        self.view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.view.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setStyleSheet(
            f"QGraphicsView {{ background: {tokens.BG_VIDEO}; border: none; }}")
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        layout.addWidget(self.view)

        self.item = QGraphicsVideoItem() if HAS_MULTIMEDIA else None
        if self.item is not None:
            self.scene.addItem(self.item)
        self.setToolTip("Bấm Esc hoặc nhấn đúp để đóng cửa sổ này")

    def show_video(self) -> None:
        """Chuyển luồng hình ảnh sang cửa sổ này rồi mở nó."""
        if self.item is not None:
            self._player.setVideoOutput(self.item)
        if self._fullscreen:
            self.showFullScreen()
        else:
            self.resize(*self._size)
            self.show()
        self._fit()

    def _fit(self) -> None:
        size = self.view.size()
        if self.item is not None:
            self.item.setSize(size)
        self.scene.setSceneRect(0, 0, size.width(), size.height())
        self.view.fitInView(self.scene.sceneRect(),
                            Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        super().resizeEvent(event)
        self._fit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 — quy ước Qt
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        self.closed.emit()
        super().closeEvent(event)
