"""Huy hiệu Vox trên thanh tiêu đề — số dư và lối vào trang nạp.

Đây là chỗ duy nhất người dùng nhìn thấy tài nguyên của mình trong lúc làm
việc, nên nó phải luôn đúng: mọi lượt gọi máy chủ trả về ``balanceAfter`` và
``SaasClient`` cập nhật vào ``device["balance"]``; widget này chỉ việc đọc
lại sau mỗi việc chạy xong.

Ẩn hoàn toàn khi máy chủ tắt hệ thống credit (``creditEnabled=false``) — lúc
đó mọi thứ miễn phí và một con số vô nghĩa chỉ gây bối rối.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from autodub_gui import tokens
from autodub_gui.ui.style import clear_background


class _BalanceWorker(QThread):
    """Đọc số dư ở luồng nền — gọi mạng trên luồng giao diện làm app đứng."""

    ready = Signal(int, bool)     # balance, ok

    def run(self) -> None:
        from autodub.saas_client import SaasError, get_client

        try:
            self.ready.emit(get_client().balance(), True)
        except SaasError:
            self.ready.emit(0, False)


class CreditWidget(QWidget):
    """Huy hiệu "1.234 Vox", bấm vào mở trang Tài khoản."""

    clicked = Signal()

    #: Dưới ngưỡng này thì huy hiệu chuyển màu cảnh báo — đủ sớm để người
    #: dùng kịp nạp trước khi đang chạy dở một video dài thì hết.
    LOW_THRESHOLD = 200

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._worker: _BalanceWorker | None = None
        self._balance = 0
        self._enabled = True

        row = QHBoxLayout(self)
        row.setContentsMargins(tokens.SP_3, 6, tokens.SP_3, 6)
        row.setSpacing(tokens.SP_1)

        self._label = QLabel("— Vox")
        clear_background(self._label)
        row.addWidget(self._label)

        self.setCursor(self.cursor())
        self.setToolTip("Số Vox còn lại. Bấm để mở trang Tài khoản.")
        self._restyle()

    # -- Trạng thái ----------------------------------------------------

    def set_balance(self, balance: int) -> None:
        self._balance = max(0, int(balance or 0))
        self._label.setText(f"{self._balance:,} Vox".replace(",", "."))
        self._restyle()

    def set_credit_enabled(self, enabled: bool) -> None:
        """Máy chủ tắt hệ thống credit thì ẩn hẳn huy hiệu."""
        self._enabled = bool(enabled)
        self.setVisible(self._enabled)

    def refresh(self) -> None:
        """Đọc lại số dư từ máy chủ (bỏ qua nếu đang có lượt đọc chạy dở)."""
        if not self._enabled:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        worker = _BalanceWorker(self)
        worker.ready.connect(self._on_ready)
        self._worker = worker
        worker.start()

    def wait_for_idle(self, timeout_ms: int = 5000) -> None:
        """Chờ luồng nền xong — hủy QThread đang chạy làm Qt crash cứng."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(timeout_ms)

    def _on_ready(self, balance: int, ok: bool) -> None:
        self._worker = None
        if ok:
            self.set_balance(balance)
        else:
            # Mất mạng: giữ nguyên con số cũ và nói rõ nó có thể đã cũ, thay
            # vì hiện 0 Vox làm người dùng tưởng mình vừa mất sạch.
            self.setToolTip("Chưa đọc lại được số dư (mất kết nối). "
                            "Con số hiển thị là lần đọc gần nhất.")

    # -- Hiển thị ------------------------------------------------------

    def _restyle(self) -> None:
        low = self._balance < self.LOW_THRESHOLD
        color = tokens.WARNING if low else tokens.TEXT_PRIMARY
        background = tokens.WARNING_BG if low else tokens.BG_INPUT
        border = tokens.WARNING if low else tokens.BORDER_DEFAULT
        self.setStyleSheet(
            f"CreditWidget {{ background: {background}; "
            f"border: 1px solid {border}; "
            f"border-radius: {tokens.RADIUS_MD}px; }}")
        self._label.setStyleSheet(
            f"color: {color}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")

    def mouseReleaseEvent(self, event) -> None:   # noqa: N802 — Qt đặt tên
        self.clicked.emit()
        super().mouseReleaseEvent(event)
