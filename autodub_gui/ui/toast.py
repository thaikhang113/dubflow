"""Thông báo nổi ở góc dưới bên phải cửa sổ chính.

Dùng cho phản hồi ngắn như đã lưu, đã xong hay cảnh báo nhẹ. Việc xác nhận
thao tác phá hủy và báo lỗi nghiêm trọng vẫn dùng hộp thoại trong `ui/modal.py`.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QObject, QPoint, QPropertyAnimation, QTimer, Qt,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from autodub_gui import tokens
from autodub_gui.ui.effects import soft_shadow

_WIDTH = 340
_MARGIN = 20
_GAP = 10
_TTL_MS = 4000
_TTL_ERROR_MS = 8000
_ANIM_MS = 150
_SLIDE_PX = 8
_MAX_STACK = 3

# loại thông báo -> màu vạch dọc bên trái
_KIND_COLOR: dict[str, str] = {
    "info": tokens.ACCENT_BLUE,
    "success": tokens.SUCCESS,
    "warn": tokens.WARNING,
    "error": tokens.DANGER,
}


class _Toast(QFrame):
    """Một thẻ thông báo đơn lẻ."""

    def __init__(self, parent: QWidget, kind: str, text: str, *,
                 detail: str = "", action_label: str = "", on_action=None):
        super().__init__(parent)
        color = _KIND_COLOR.get(kind, tokens.ACCENT_BLUE)
        self.setStyleSheet(
            f"QFrame {{ background: {tokens.BG_PANEL}; "
            f"border: 1px solid {tokens.BORDER_DEFAULT}; "
            f"border-left: 3px solid {color}; "
            f"border-radius: {tokens.RADIUS_LG}px; }}")
        self.setFixedWidth(_WIDTH)
        soft_shadow(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_4, tokens.SP_3,
                                tokens.SP_2, tokens.SP_3)
        root.setSpacing(tokens.SP_2)

        top = QHBoxLayout()
        top.setSpacing(tokens.SP_2)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
            f"background: transparent; border: none;")
        top.addWidget(label, 1)

        close = QPushButton("×")   # dấu nhân — ký tự chữ, không phải biểu tượng cảm xúc
        close.setObjectName("iconbtn")
        close.setFixedSize(22, 22)
        close.setToolTip("Đóng thông báo")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        top.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(top)

        if detail or action_label:
            row = QHBoxLayout()
            row.setSpacing(tokens.SP_2)
            row.addStretch()
            if detail:
                btn_detail = QPushButton("Chi tiết")
                btn_detail.setObjectName("ghost")
                btn_detail.clicked.connect(lambda: self._show_detail(text, detail))
                row.addWidget(btn_detail)
            if action_label and on_action is not None:
                btn = QPushButton(action_label)
                btn.setObjectName("ghost")
                btn.clicked.connect(lambda: (self.dismiss(), on_action()))
                row.addWidget(btn)
            root.addLayout(row)

        self._anim: QPropertyAnimation | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_TTL_ERROR_MS if kind == "error" else _TTL_MS)
        self._timer.timeout.connect(self.dismiss)

    def _show_detail(self, title: str, detail: str) -> None:
        from autodub_gui.ui.modal import ConfirmDialog
        ConfirmDialog.ask(self.window(), "Chi tiết lỗi kỹ thuật", title,
                          kind="error", detail=detail,
                          confirm_label="Đóng", cancel_label="")

    def start(self) -> None:
        """Bắt đầu đếm giờ tự tắt."""
        self._timer.start()

    def dismiss(self) -> None:
        """Đóng thông báo ngay lập tức."""
        self._timer.stop()
        self.hide()
        TOASTS.remove(self)
        self.deleteLater()


class ToastManager(QObject):
    """Quản lý hàng đợi thông báo: xếp chồng tối đa ba cái, tự tắt sau 4 giây."""

    def __init__(self) -> None:
        super().__init__()
        self._host: QWidget | None = None
        self._items: list[_Toast] = []

    def attach(self, host: QWidget) -> None:
        """Gắn vào cửa sổ chính, gọi một lần lúc khởi tạo ứng dụng."""
        self._host = host

    def info(self, text: str, action_label: str = "", on_action=None) -> None:
        self._push("info", text, action_label=action_label, on_action=on_action)

    def success(self, text: str, action_label: str = "", on_action=None) -> None:
        self._push("success", text, action_label=action_label, on_action=on_action)

    def warn(self, text: str, action_label: str = "", on_action=None) -> None:
        self._push("warn", text, action_label=action_label, on_action=on_action)

    def error(self, text: str, detail: str = "",
              action_label: str = "", on_action=None) -> None:
        self._push("error", text, detail=detail,
                   action_label=action_label, on_action=on_action)

    def _push(self, kind: str, text: str, **kwargs) -> None:
        host = self._host
        if host is None or not host.isVisible():
            return
        while len(self._items) >= _MAX_STACK:
            self._items[0].dismiss()
        toast = _Toast(host, kind, text, **kwargs)
        self._items.append(toast)
        toast.show()
        self._relayout()
        self._animate_in(toast)
        toast.start()

    def _animate_in(self, toast: _Toast) -> None:
        """Hiện dần và trượt lên 8px trong 150ms."""
        end = toast.pos()
        start = QPoint(end.x(), end.y() + _SLIDE_PX)
        anim = QPropertyAnimation(toast, b"pos", toast)
        anim.setDuration(_ANIM_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(start)
        anim.setEndValue(end)
        toast._anim = anim
        anim.start()

    def remove(self, toast: _Toast) -> None:
        """Bỏ một thông báo khỏi hàng đợi rồi xếp lại các cái còn lại."""
        if toast in self._items:
            self._items.remove(toast)
        self._relayout()

    def _relayout(self) -> None:
        host = self._host
        if host is None:
            return
        y = host.height() - _MARGIN
        for toast in reversed(self._items):
            height = toast.sizeHint().height()
            y -= height
            toast.setGeometry(host.width() - _WIDTH - _MARGIN, y,
                              _WIDTH, height)
            toast.raise_()
            y -= _GAP

    def reposition(self) -> None:
        """Gọi lại khi cửa sổ chính đổi kích thước."""
        self._relayout()


TOASTS = ToastManager()
