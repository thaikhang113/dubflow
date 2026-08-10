"""Các loại nút bấm dùng chung.

Chiều rộng luôn theo `sizeHint()`, không đặt cứng, để chữ tiếng Việt có dấu
không bao giờ bị cắt mất.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QWidget,
)

from autodub_gui import tokens

_ICON_BTN_SIZE = 36
_SPIN_FRAMES = ("Đang xử lý.", "Đang xử lý..", "Đang xử lý...")
_SPIN_INTERVAL_MS = 320


class _BaseButton(QPushButton):
    """Nút có sẵn trạng thái đang chạy: khóa nút và đổi nhãn thành dấu chấm."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Minimum,
                           QSizePolicy.Policy.Fixed)
        self._idle_text = text
        self._busy_text = _SPIN_FRAMES[0]
        self._loading = False
        self._timer_id = 0
        self._frame = 0

    def setText(self, text: str) -> None:  # noqa: N802 — theo quy ước của Qt
        if not self._loading:
            self._idle_text = text
        super().setText(text)

    def is_loading(self) -> bool:
        """Nút có đang ở trạng thái chờ tác vụ nền không."""
        return self._loading

    def set_loading(self, loading: bool, text: str = "") -> None:
        """Bật hoặc tắt trạng thái đang chạy."""
        if loading == self._loading:
            return
        self._loading = loading
        if loading:
            self._frame = 0
            self._busy_text = text or _SPIN_FRAMES[0]
            super().setText(self._busy_text)
            self.setEnabled(False)
            self._timer_id = self.startTimer(_SPIN_INTERVAL_MS)
        else:
            if self._timer_id:
                self.killTimer(self._timer_id)
                self._timer_id = 0
            super().setText(self._idle_text)
            self.setEnabled(True)

    def timerEvent(self, event) -> None:  # noqa: N802 — theo quy ước của Qt
        if event.timerId() != self._timer_id:
            super().timerEvent(event)
            return
        self._frame = (self._frame + 1) % len(_SPIN_FRAMES)
        base = self._busy_text.rstrip(".")
        super().setText(base + "." * (self._frame + 1))


class PrimaryButton(_BaseButton):
    """Nút hành động chính, nền chuyển sắc xanh sang tím."""

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 icon: QIcon | None = None):
        super().__init__(text, parent)
        self.setObjectName("primary")
        if icon is not None:
            self.setIcon(icon)


class GhostButton(_BaseButton):
    """Nút phụ, nền trong suốt chỉ có viền mờ."""

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 icon: QIcon | None = None):
        super().__init__(text, parent)
        self.setObjectName("ghost")
        if icon is not None:
            self.setIcon(icon)


class DangerButton(_BaseButton):
    """Nút cho thao tác dừng hoặc xóa."""

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 icon: QIcon | None = None):
        super().__init__(text, parent)
        self.setObjectName("danger")
        if icon is not None:
            self.setIcon(icon)


class SecondaryButton(_BaseButton):
    """Nút mặc định, viền mờ trên nền tối."""

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 icon: QIcon | None = None):
        super().__init__(text, parent)
        if icon is not None:
            self.setIcon(icon)


class IconButton(QPushButton):
    """Nút vuông chỉ có biểu tượng. Bắt buộc phải kèm chú giải bằng lời."""

    def __init__(self, icon: QIcon, tooltip: str,
                 parent: QWidget | None = None, *,
                 size: int = _ICON_BTN_SIZE, checkable: bool = False):
        super().__init__(parent)
        self.setObjectName("iconbtn")
        self.setIcon(icon)
        self.setIconSize(QSize(int(size * 0.55), int(size * 0.55)))
        # Biểu tượng vuông — đây là trường hợp duy nhất được phép đặt
        # kích thước cứng, vì ô này không chứa chữ.
        self.setFixedSize(size, size)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)


class SegmentedControl(QWidget):
    """Nhóm nút dính liền nhau, mỗi lúc chỉ chọn được một."""

    selection_changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._options = list(options)
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        last = len(self._options) - 1
        for i, (label, _key) in enumerate(self._options):
            btn = QPushButton(label)
            btn.setObjectName("segment")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # Đánh dấu vị trí bằng property thay vì inline style
            # → theme.py sẽ style qua property selector, giữ nguyên :checked
            if i == 0:
                btn.setProperty("position", "first")
            elif i == last:
                btn.setProperty("position", "last")
            self._buttons.append(btn)
            self._group.addButton(btn, i)
            layout.addWidget(btn)
        layout.addStretch()
        if self._buttons:
            self._buttons[0].setChecked(True)
        self._group.idClicked.connect(self._on_clicked)

    def _on_clicked(self, index: int) -> None:
        if 0 <= index < len(self._options):
            self.selection_changed.emit(self._options[index][1])

    def current_key(self) -> str:
        """Mã của lựa chọn đang được chọn."""
        index = self._group.checkedId()
        return self._options[index][1] if index >= 0 else ""

    def set_key(self, key: str) -> None:
        """Chọn mục theo mã, không phát tín hiệu thay đổi."""
        for i, (_label, k) in enumerate(self._options):
            if k == key:
                self._buttons[i].setChecked(True)
                return

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 — quy ước Qt
        super().setEnabled(enabled)
        for btn in self._buttons:
            btn.setEnabled(enabled)
