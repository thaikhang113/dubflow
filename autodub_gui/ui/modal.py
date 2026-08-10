"""Hộp thoại xác nhận.

Mọi thao tác phá hủy (xóa dự án, xóa câu thoại, khôi phục mặc định) đều phải
đi qua `ConfirmDialog`. Nguyên văn lỗi kỹ thuật luôn nằm sau nút "Chi tiết",
không bao giờ hiện thẳng ở dòng chính.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout,
    QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.ui.buttons import (
    DangerButton, GhostButton, PrimaryButton, SecondaryButton,
)

_MIN_W = 480
_MAX_W = 640
_ICON_PX = 28
_DETAIL_H = 160

# kiểu hộp thoại -> (hàm vẽ biểu tượng, màu tiêu đề)
_KINDS = {
    "info": (icons.help_circle, tokens.ACCENT_BLUE),
    "warning": (icons.warning, tokens.WARNING),
    "danger": (icons.trash, tokens.DANGER),
    "error": (icons.error, tokens.DANGER),
    "success": (icons.check, tokens.SUCCESS),
}


class ConfirmDialog(QDialog):
    """Hộp thoại xác nhận: tiêu đề, thông điệp, ô tích tùy chọn và chi tiết."""

    def __init__(self, parent: QWidget | None, title: str, message: str, *,
                 kind: str = "warning", confirm_label: str = "Đồng ý",
                 cancel_label: str = "Hủy", detail: str = "",
                 checkbox_label: str | None = None,
                 checkbox_checked: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(_MIN_W)
        self.setMaximumWidth(_MAX_W)
        self._checkbox: QCheckBox | None = None
        self._detail_box: QPlainTextEdit | None = None

        icon_fn, color = _KINDS.get(kind, _KINDS["warning"])
        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_6, tokens.SP_5,
                                tokens.SP_6, tokens.SP_5)
        root.setSpacing(tokens.SP_4)

        head = QHBoxLayout()
        head.setSpacing(tokens.SP_3)
        icon_label = QLabel()
        icon_label.setPixmap(icon_fn(color).pixmap(_ICON_PX, _ICON_PX))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        head.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        texts = QVBoxLayout()
        texts.setSpacing(tokens.SP_2)
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"color: {color}; font-size: {tokens.FS_CARD_TITLE}px; "
            f"font-weight: 700; background: transparent;")
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        message_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
            f"background: transparent;")
        texts.addWidget(title_label)
        texts.addWidget(message_label)
        head.addLayout(texts, 1)
        root.addLayout(head)

        if checkbox_label:
            self._checkbox = QCheckBox(checkbox_label)
            self._checkbox.setChecked(checkbox_checked)
            root.addWidget(self._checkbox)

        if detail:
            self._detail_box = QPlainTextEdit(detail)
            self._detail_box.setReadOnly(True)
            self._detail_box.setVisible(False)
            self._detail_box.setMinimumHeight(_DETAIL_H)
            self._detail_box.setStyleSheet(
                f"QPlainTextEdit {{ background: {tokens.BG_INPUT}; "
                f"color: {tokens.TEXT_MUTED}; font-family: {tokens.FONT_MONO}; "
                f"font-size: {tokens.FS_META}px; "
                f"border: 1px solid {tokens.BORDER_SUBTLE}; "
                f"border-radius: 8px; }}")
            root.addWidget(self._detail_box)

        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.SP_2)
        if detail:
            btn_detail = GhostButton("Chi tiết")
            btn_detail.setCheckable(True)
            btn_detail.toggled.connect(self._toggle_detail)
            buttons.addWidget(btn_detail)
        buttons.addStretch()
        if cancel_label:
            btn_cancel = SecondaryButton(cancel_label)
            btn_cancel.clicked.connect(self.reject)
            buttons.addWidget(btn_cancel)
        confirm_cls = DangerButton if kind in ("danger", "error") else PrimaryButton
        btn_ok = confirm_cls(confirm_label)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        buttons.addWidget(btn_ok)
        root.addLayout(buttons)

    def _toggle_detail(self, shown: bool) -> None:
        if self._detail_box is not None:
            self._detail_box.setVisible(shown)
            self.adjustSize()

    def checkbox_checked(self) -> bool:
        """Ô tích phụ có đang được đánh dấu không."""
        return bool(self._checkbox and self._checkbox.isChecked())

    @staticmethod
    def ask(parent: QWidget | None, title: str, message: str, *,
            kind: str = "warning", confirm_label: str = "Đồng ý",
            cancel_label: str = "Hủy", detail: str = "",
            checkbox_label: str | None = None,
            checkbox_checked: bool = True) -> tuple[bool, bool]:
        """Trả về cặp (người dùng đã đồng ý, trạng thái ô tích)."""
        dialog = ConfirmDialog(
            parent, title, message, kind=kind, confirm_label=confirm_label,
            cancel_label=cancel_label, detail=detail,
            checkbox_label=checkbox_label, checkbox_checked=checkbox_checked)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return accepted, dialog.checkbox_checked()

    @staticmethod
    def show_error(parent: QWidget | None, title: str, message: str,
                   detail: str = "") -> None:
        """Báo lỗi một chiều: chuyện gì xảy ra, vì sao, làm gì bây giờ."""
        ConfirmDialog.ask(parent, title, message, kind="error",
                          confirm_label="Đã hiểu", cancel_label="",
                          detail=detail)


def confirm_discard(parent: QWidget | None, what: str) -> bool:
    """Hỏi trước khi bỏ những thay đổi chưa lưu."""
    accepted, _ = ConfirmDialog.ask(
        parent, "Còn thay đổi chưa lưu",
        f"{what} đang có thay đổi chưa lưu. Nếu rời đi bây giờ, "
        f"những thay đổi đó sẽ mất. Bạn vẫn muốn rời đi?",
        kind="warning", confirm_label="Rời đi", cancel_label="Ở lại")
    return accepted
