"""Trang quản lý kết nối OpenClaw do DubFlow tự vận hành."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
    QWidget,
)

from autodub_gui import tokens
from autodub_gui.pages import BasePage
from autodub_gui.ui.badges import StatusBadge
from autodub_gui.ui.buttons import DangerButton, GhostButton, PrimaryButton
from autodub_gui.ui.cards import Card
from autodub_gui.ui.labels import ElidedLabel
from autodub_gui.ui.table import Column, DataTable
from autodub_gui.ui.toast import TOASTS


class OpenClawPage(BasePage):
    def __init__(self, runtime, parent: QWidget | None = None):
        super().__init__(parent)
        self.runtime = runtime
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, tokens.SP_3, 28, tokens.SP_5)
        root.setSpacing(tokens.SP_4)

        intro = QLabel(
            "Cho OpenClaw điều khiển DubFlow qua kết nối local an toàn. "
            "DubFlow tự nhận link, hỏi tùy chọn còn thiếu và xử lý hàng loạt "
            "bằng pipeline hiện tại.")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_LABEL}px; "
            "background: transparent;")
        root.addWidget(intro)

        connection = Card(padding=tokens.SP_4)
        connection.add_header("Kết nối OpenClaw")
        self.enable_box = QCheckBox("Bật kết nối OpenClaw")
        self.enable_box.setToolTip(
            "Cho phép OpenClaw gọi DubFlow trên máy này.")
        self.enable_box.toggled.connect(self._toggle)
        connection.body.addWidget(self.enable_box)

        self.status = QLabel("")
        self.status.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_META}px; "
            "background: transparent;")
        connection.body.addWidget(self.status)

        self.endpoint_edit = self._readonly_field("Địa chỉ local")
        self.token_edit = self._readonly_field("Token kết nối")
        connection.body.addWidget(self.endpoint_edit)
        connection.body.addWidget(self.token_edit)

        actions = QHBoxLayout()
        self.copy_button = GhostButton("Sao chép thông tin kết nối")
        self.copy_button.clicked.connect(self._copy_connection)
        self.rotate_button = GhostButton("Tạo token mới")
        self.rotate_button.clicked.connect(self._rotate_token)
        self.test_button = PrimaryButton("Kiểm tra kết nối")
        self.test_button.clicked.connect(self._test_connection)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.rotate_button)
        actions.addStretch()
        actions.addWidget(self.test_button)
        connection.body.addLayout(actions)
        root.addWidget(connection)

        batches = Card(padding=tokens.SP_4)
        batches.add_header("Batch từ OpenClaw")
        self.table = DataTable(
            [Column("Batch", stretch=True),
             Column("Trạng thái", width=130),
             Column("Tiến trình", width=100),
             Column("Thao tác", width=125)],
            empty_title="Chưa có batch OpenClaw",
            empty_description="Khi OpenClaw gửi link, batch và tiến trình sẽ hiện ở đây.",
        )
        self.table.setMinimumHeight(220)
        batches.body.addWidget(self.table)
        root.addWidget(batches, 1)

    @staticmethod
    def _readonly_field(label: str) -> QLineEdit:
        field = QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText(label)
        field.setToolTip(label)
        field.setAccessibleName(label)
        return field

    def _toggle(self, enabled: bool) -> None:
        try:
            self.runtime.set_enabled(enabled)
        except OSError as exc:
            self.enable_box.blockSignals(True)
            self.enable_box.setChecked(False)
            self.enable_box.blockSignals(False)
            TOASTS.error("Không bật được OpenClaw.", detail=str(exc))
        self.refresh()

    def _copy_connection(self) -> None:
        payload = (
            f'{{"url":"{self.runtime.endpoint}",'
            f'"authorization":"Bearer {self.runtime.token}"}}')
        QApplication.clipboard().setText(payload)
        TOASTS.success("Đã sao chép thông tin kết nối OpenClaw.")

    def _rotate_token(self) -> None:
        self.runtime.rotate_token()
        self.refresh()
        TOASTS.success("Đã tạo token OpenClaw mới.")

    def _test_connection(self) -> None:
        if self.runtime.running:
            self.status.setText("Kết nối local đang hoạt động.")
            TOASTS.success("OpenClaw đang sẵn sàng.")
        else:
            self.status.setText("OpenClaw đang tắt.")
            TOASTS.warn("Hãy bật kết nối OpenClaw trước.")

    def refresh(self) -> None:
        self.enable_box.blockSignals(True)
        self.enable_box.setChecked(self.runtime.enabled)
        self.enable_box.blockSignals(False)
        self.endpoint_edit.setText(self.runtime.endpoint or "Chưa bật")
        self.token_edit.setText(self.runtime.token if self.runtime.enabled
                                else "Chưa bật")
        self.status.setText(
            "Đang chạy trên máy này." if self.runtime.running
            else "Đang tắt. Bật để OpenClaw kết nối.")
        self.copy_button.setEnabled(self.runtime.running)
        self.rotate_button.setEnabled(True)
        self.test_button.setEnabled(True)
        self._refresh_batches()

    def _refresh_batches(self) -> None:
        self.table.clear_rows()
        for batch in self.runtime.list_batches():
            row = self.table.add_row()
            batch_id = str(batch.get("batch_id", ""))
            state = str(batch.get("status", "running"))
            percent = int(batch.get("percent", 0) or 0)
            self.table.set_widget(row, 0, ElidedLabel(batch_id))
            self.table.set_widget(
                row, 1, StatusBadge(self._status_label(state),
                                    self._status_kind(state)))
            self.table.set_text(row, 2, f"{percent}%")
            actions: list[QWidget] = []
            if state == "running":
                button = DangerButton("Dừng")
                button.clicked.connect(
                    lambda _checked=False, value=batch_id:
                    self._batch_action(value, "cancel"))
                actions.append(button)
            elif state == "failed":
                button = GhostButton("Thử lại")
                button.clicked.connect(
                    lambda _checked=False, value=batch_id:
                    self._batch_action(value, "retry-failed"))
                actions.append(button)
            self.table.set_widgets(row, 3, actions)
        self.table.auto_state()

    def _batch_action(self, batch_id: str, operation: str) -> None:
        action = "cancel" if operation == "cancel" else "retry_failed"
        try:
            self.runtime.handle({"action": action, "batch_id": batch_id})
        except Exception as exc:  # noqa: BLE001
            TOASTS.error("Không cập nhật được batch.", detail=str(exc))
        self.refresh()

    @staticmethod
    def _status_label(state: str) -> str:
        return {
            "running": "Đang chạy",
            "completed": "Hoàn thành",
            "failed": "Lỗi",
            "cancelled": "Đã dừng",
        }.get(state, "Đang chờ")

    @staticmethod
    def _status_kind(state: str) -> str:
        return {
            "running": "processing",
            "completed": "success",
            "failed": "error",
            "cancelled": "warning",
        }.get(state, "neutral")

    def is_running(self) -> bool:
        return self.runtime.running

    def shutdown(self) -> None:
        self.runtime.stop()

    def cleanup(self) -> None:
        self._timer.stop()
