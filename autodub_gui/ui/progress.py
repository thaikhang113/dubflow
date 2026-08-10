"""Thanh tiến trình mỏng và chỉ báo lưu tự động."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from autodub_gui import tokens

_BAR_H = 5
_DOT = "●"          # chấm tròn đặc — ký tự hình học, không phải biểu tượng cảm xúc
_SPIN_MS = 400

# trạng thái lưu -> (màu chấm, nhãn hiển thị)
_SAVE_STATES: dict[str, tuple[str, str]] = {
    "idle":   (tokens.TEXT_MUTED, "Lưu tự động"),
    "saving": (tokens.PROCESSING, "Đang lưu"),
    "saved":  (tokens.SUCCESS, "Đã lưu"),
    "error":  (tokens.DANGER, "Lỗi lưu"),
}


class ThinProgressBar(QProgressBar):
    """Thanh tiến trình cao 5px, không hiện số phần trăm bên trong."""

    def __init__(self, parent: QWidget | None = None, *,
                 color: str = tokens.PRIMARY):
        super().__init__(parent)
        self.setTextVisible(False)
        self.setRange(0, 100)
        self.setValue(0)
        # Chỉ là thanh đồ họa, không chứa chữ, nên đặt chiều cao cứng là an toàn.
        self.setFixedHeight(_BAR_H)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        """Đổi màu phần đã chạy cho khớp trạng thái của mục."""
        self.setStyleSheet(
            f"QProgressBar {{ background: {tokens.TRACK_BG}; border: none; "
            f"border-radius: {_BAR_H // 2 + 1}px; height: {_BAR_H}px; }}"
            f"QProgressBar::chunk {{ background: {color}; "
            f"border-radius: {_BAR_H // 2 + 1}px; }}")

    def set_indeterminate(self, on: bool) -> None:
        """Chế độ chưa rõ phần trăm, dùng khi đang chờ tác vụ chưa đo được."""
        self.setRange(0, 0) if on else self.setRange(0, 100)


class SaveIndicator(QWidget):
    """Chấm màu kèm chữ: Lưu tự động, Đang lưu, Đã lưu, Lỗi lưu."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._dot = QLabel(_DOT)
        self._text = QLabel("")
        self._text.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_LABEL}px; "
            f"background: transparent;")
        layout.addWidget(self._dot)
        layout.addWidget(self._text)
        self._timer = QTimer(self)
        self._timer.setInterval(_SPIN_MS)
        self._timer.timeout.connect(self._tick)
        self._dots = 0
        self._state = "idle"
        self._label = _SAVE_STATES["idle"][1]
        self.set_state("idle")

    def state(self) -> str:
        return self._state

    def set_state(self, state: str, detail: str = "") -> None:
        """Đổi trạng thái: idle, saving, saved hoặc error."""
        color, label = _SAVE_STATES.get(state, _SAVE_STATES["idle"])
        self._state = state
        self._dot.setStyleSheet(
            f"color: {color}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        self._label = label
        self._text.setText(f"{label} {detail}".strip())
        self.setToolTip(detail or label)
        if state == "saving":
            self._dots = 0
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        self._text.setText(self._label + "." * self._dots)
