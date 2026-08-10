"""Màn chào lần chạy đầu tiên.

Hiện đúng MỘT lần cho mỗi máy (đánh dấu bằng tệp trong thư mục dữ liệu tạm):
kể ngắn gọn ứng dụng làm được gì, máy đang thiếu gì và cách cài từng phần —
mỗi mục có nút sao chép lệnh giống trang Trợ giúp. Người dùng đóng hộp là
dùng được ngay; mọi thứ trong này đều xem lại được ở trang Trợ giúp.
"""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from autodub_gui import icons, tokens
from autodub_gui.ui.buttons import GhostButton, PrimaryButton

_MARKER = "first_run_done"
_MIN_W = 560

#: (tên, mô tả ngắn, lệnh cài, hàm kiểm tra đã sẵn sàng chưa)
_CHECKS = (
    ("FFmpeg — ghép hình và tiếng",
     "Bắt buộc. Tải bản đầy đủ, giải nén rồi thêm thư mục bin vào đường "
     "dẫn hệ thống.",
     "", lambda s: bool(shutil.which("ffmpeg"))),
    ("Bộ giọng đọc VieNeu",
     "Tùy chọn — để lồng tiếng offline. Không cài vẫn dùng được bộ giọng "
     "CapCut (cần mạng). Chạy một lần, khoảng vài phút.",
     "py scripts/setup_vieneu.py", lambda s: s.vieneu_configured()),
    ("Dịch tự động",
     "Chạy qua máy chủ VoxDub — không cần cấu hình gì. Máy mới được tặng "
     "Vox dùng thử; xem số dư ở trang Tài khoản.",
     "", lambda s: s.translate_enabled),
)


def _marker_path() -> str:
    from autodub_gui.pages.new_project_page import cache_dir

    return os.path.join(cache_dir(), _MARKER)


def is_first_run() -> bool:
    """Máy này đã từng chạy ứng dụng chưa (chưa có tệp đánh dấu)."""
    return not os.path.isfile(_marker_path())


def mark_done() -> None:
    """Ghi tệp đánh dấu để lần sau không hiện màn chào nữa."""
    try:
        with open(_marker_path(), "w", encoding="utf-8") as f:
            f.write("shown\n")
    except OSError:
        pass  # không ghi được thì lần sau hiện lại, không sao


class FirstRunDialog(QDialog):
    """Màn chào: ứng dụng làm gì, máy thiếu gì, cài thế nào."""

    settings_requested = False   # người dùng bấm "Mở Cài đặt" hay không

    def __init__(self, settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Chào mừng đến VoxDub Studio")
        self.setModal(True)
        self.setMinimumWidth(_MIN_W)

        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SP_6, tokens.SP_5,
                                tokens.SP_6, tokens.SP_5)
        root.setSpacing(tokens.SP_4)

        title = QLabel("Chào mừng đến VoxDub Studio")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_SECTION}px; "
            f"font-weight: 700; background: transparent;")
        intro = QLabel(
            "Ứng dụng tự động lồng tiếng video sang tiếng Việt: tách nhạc "
            "nền, nghe lời thoại, dịch, đọc bằng giọng Việt tự nhiên rồi ghép "
            "lại thành video hoàn chỉnh. Dưới đây là tình trạng máy của bạn:")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FS_BODY}px; "
            f"background: transparent;")
        root.addWidget(title)
        root.addWidget(intro)

        for name, description, command, probe in _CHECKS:
            root.addLayout(self._check_row(settings, name, description,
                                           command, probe))

        note = QLabel(
            "Bạn xem lại được toàn bộ hướng dẫn này ở trang Trợ giúp, và đổi "
            "mọi lựa chọn ở trang Cài đặt.")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {tokens.TEXT_MUTED}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        root.addWidget(note)

        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.SP_2)
        btn_settings = GhostButton("Mở Cài đặt")
        btn_settings.clicked.connect(self._open_settings)
        buttons.addWidget(btn_settings)
        buttons.addStretch()
        btn_start = PrimaryButton("Bắt đầu dùng")
        btn_start.setDefault(True)
        btn_start.clicked.connect(self.accept)
        buttons.addWidget(btn_start)
        root.addLayout(buttons)

    def _check_row(self, settings, name: str, description: str,
                   command: str, probe) -> QVBoxLayout:
        try:
            ready = bool(settings is not None and probe(settings))
        except Exception:  # noqa: BLE001 — không kiểm tra được thì coi là chưa
            ready = False
        column = QVBoxLayout()
        column.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(tokens.SP_2)
        icon = QLabel()
        icon_fn = icons.check if ready else icons.warning
        color = tokens.SUCCESS if ready else tokens.WARNING
        icon.setPixmap(icon_fn(color).pixmap(16, 16))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        label = QLabel(name)
        label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FS_LABEL}px; "
            f"font-weight: 600; background: transparent;")
        state = QLabel("đã sẵn sàng" if ready else "chưa sẵn sàng")
        state.setStyleSheet(
            f"color: {color}; font-size: {tokens.FS_META}px; "
            f"background: transparent;")
        head.addWidget(icon)
        head.addWidget(label)
        head.addWidget(state)
        head.addStretch()
        if command and not ready:
            copy_button = GhostButton("Sao chép lệnh cài")
            copy_button.setToolTip(command)
            copy_button.clicked.connect(
                lambda _c=False, cmd=command: self._copy(cmd))
            head.addWidget(copy_button)
        column.addLayout(head)
        if not ready:
            body = QLabel(description)
            body.setWordWrap(True)
            body.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; "
                f"font-size: {tokens.FS_META}px; background: transparent;")
            column.addWidget(body)
        return column

    def _copy(self, command: str) -> None:
        QApplication.clipboard().setText(command)
        from autodub_gui.ui.toast import TOASTS
        TOASTS.success("Đã sao chép lệnh. Dán vào cửa sổ dòng lệnh rồi chạy.")

    def _open_settings(self) -> None:
        self.settings_requested = True
        self.accept()


def maybe_show_first_run(window) -> bool:
    """Hiện màn chào nếu là lần chạy đầu. Trả về True nếu đã hiện.

    Gọi sau khi cửa sổ chính hiện lên. Phiên chạy thử tự động
    (AUTODUB_SMOKE) bỏ qua vì hộp thoại modal sẽ chặn phiên đó.
    """
    if os.environ.get("AUTODUB_SMOKE") == "1":
        return False
    if not is_first_run():
        return False
    from autodub.config import Settings

    try:
        settings = Settings.load(override=True)
    except Exception:  # noqa: BLE001 — cấu hình hỏng thì vẫn chào được
        settings = None
    dialog = FirstRunDialog(settings, window)
    dialog.exec()
    mark_done()
    if dialog.settings_requested:
        from autodub_gui.app import ROW_SETTINGS
        window.switch_page(ROW_SETTINGS)
    return True
