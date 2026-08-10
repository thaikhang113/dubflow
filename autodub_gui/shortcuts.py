"""Phím tắt của ứng dụng.

Bảng phím tắt được khai báo một lần ở đây rồi dùng lại cho cả việc đăng ký
lẫn việc hiển thị trong trang Trợ giúp, nhờ vậy hai nơi không bao giờ lệch nhau.

Nguyên tắc quan trọng: khi con trỏ đang ở trong một ô nhập chữ, phím tắt chỉ
gồm một ký tự (như phím cách) phải nhường lại cho ô nhập, nếu không người
dùng sẽ không gõ được tiếng Việt.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QLineEdit, QPlainTextEdit, QTextEdit, QWidget,
)


@dataclass(frozen=True)
class Shortcut:
    """Một phím tắt: tổ hợp phím, việc nó làm và phạm vi áp dụng."""

    keys: str
    action: str
    scope: str


# Phím tắt dùng ở mọi nơi trong ứng dụng
GLOBAL_SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut("Ctrl+N", "Tạo dự án mới", "Toàn ứng dụng"),
    Shortcut("Ctrl+,", "Mở Cài đặt", "Toàn ứng dụng"),
    Shortcut("F1", "Mở Trợ giúp", "Toàn ứng dụng"),
    Shortcut("Ctrl+1", "Trang chủ", "Toàn ứng dụng"),
    Shortcut("Ctrl+2", "Tạo dự án", "Toàn ứng dụng"),
    Shortcut("Ctrl+3", "Dự án của tôi", "Toàn ứng dụng"),
    Shortcut("Ctrl+4", "Xử lý hàng loạt", "Toàn ứng dụng"),
    Shortcut("Ctrl+5", "Tải xuống", "Toàn ứng dụng"),
    Shortcut("Ctrl+6", "Cài đặt", "Toàn ứng dụng"),
    Shortcut("Ctrl+7", "Trợ giúp", "Toàn ứng dụng"),
)

# Phím tắt chỉ có tác dụng trong Trình chỉnh sửa
EDITOR_SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut("Space", "Phát hoặc tạm dừng video", "Trình chỉnh sửa"),
    Shortcut("J", "Lùi 5 giây", "Trình chỉnh sửa"),
    Shortcut("K", "Phát hoặc tạm dừng video", "Trình chỉnh sửa"),
    Shortcut("L", "Tiến 5 giây", "Trình chỉnh sửa"),
    Shortcut("Ctrl+S", "Lưu phụ đề ngay", "Trình chỉnh sửa"),
    Shortcut("Ctrl+Z", "Hoàn tác", "Trình chỉnh sửa"),
    Shortcut("Ctrl+Shift+Z", "Làm lại", "Trình chỉnh sửa"),
    Shortcut("Delete", "Xóa câu đang chọn", "Trình chỉnh sửa"),
    Shortcut("Ctrl+E", "Mở phần Xuất video", "Trình chỉnh sửa"),
    Shortcut("Left", "Lùi 1 giây", "Trình chỉnh sửa"),
    Shortcut("Right", "Tiến 1 giây", "Trình chỉnh sửa"),
    Shortcut("Shift+Left", "Lùi 5 giây", "Trình chỉnh sửa"),
    Shortcut("Shift+Right", "Tiến 5 giây", "Trình chỉnh sửa"),
    Shortcut("Ctrl+Left", "Về câu trước", "Trình chỉnh sửa"),
    Shortcut("Ctrl+Right", "Sang câu sau", "Trình chỉnh sửa"),
    Shortcut("F11", "Xem video toàn màn hình", "Trình chỉnh sửa"),
    Shortcut("Ctrl+F", "Tìm trong danh sách phụ đề", "Dự án, Trình chỉnh sửa"),
)

ALL_SHORTCUTS: tuple[Shortcut, ...] = GLOBAL_SHORTCUTS + EDITOR_SHORTCUTS

_TEXT_WIDGETS = (QLineEdit, QPlainTextEdit, QTextEdit)


def typing_in_text_field() -> bool:
    """Con trỏ có đang nằm trong một ô nhập chữ không.

    Dùng để nhường phím cho bộ gõ tiếng Việt thay vì nuốt mất.
    """
    widget = QApplication.focusWidget()
    return isinstance(widget, _TEXT_WIDGETS)


def bind(parent: QWidget, keys: str, callback, *,
         skip_when_typing: bool = False) -> QShortcut:
    """Gắn một phím tắt vào widget cha và trả về đối tượng vừa tạo."""
    shortcut = QShortcut(QKeySequence(keys), parent)

    def _run() -> None:
        if skip_when_typing and typing_in_text_field():
            return
        callback()

    shortcut.activated.connect(_run)
    return shortcut


def install_global_shortcuts(window) -> list[QShortcut]:
    """Đăng ký các phím tắt dùng chung cho cửa sổ chính."""
    from autodub_gui.app import (
        ROW_BATCH, ROW_DOWNLOAD, ROW_HELP, ROW_HOME, ROW_NEW, ROW_PROJECTS,
        ROW_SETTINGS,
    )

    rows = (ROW_HOME, ROW_NEW, ROW_PROJECTS, ROW_BATCH, ROW_DOWNLOAD,
            ROW_SETTINGS, ROW_HELP)
    created: list[QShortcut] = []
    created.append(bind(window, "Ctrl+N",
                        lambda: window.switch_page(ROW_NEW)))
    created.append(bind(window, "Ctrl+,",
                        lambda: window.switch_page(ROW_SETTINGS)))
    created.append(bind(window, "F1",
                        lambda: window.switch_page(ROW_HELP)))
    for index, row in enumerate(rows, start=1):
        created.append(bind(window, f"Ctrl+{index}",
                            lambda r=row: window.switch_page(r)))
    window._shortcuts = created      # giữ tham chiếu để Qt không thu hồi
    return created


def install_editor_shortcuts(page) -> list[QShortcut]:
    """Đăng ký phím tắt riêng cho Trình chỉnh sửa.

    Phím cách và phím Delete phải nhường lại cho ô nhập chữ, nếu không người
    dùng sẽ không gõ được khoảng trắng khi sửa lời thoại.
    """
    created = [
        bind(page, "Space", page.toggle_play, skip_when_typing=True),
        # J/K/L — bộ phím quen thuộc của dân dựng phim (lùi/dừng/tiến).
        bind(page, "J", lambda: page.player.nudge_back(big=True),
             skip_when_typing=True),
        bind(page, "K", page.toggle_play, skip_when_typing=True),
        bind(page, "L", lambda: page.player.nudge_forward(big=True),
             skip_when_typing=True),
        bind(page, "Delete", page.delete_selected, skip_when_typing=True),
        bind(page, "Ctrl+S", page.save_now),
        bind(page, "Ctrl+Z", page.undo),
        bind(page, "Ctrl+Shift+Z", page.redo),
        bind(page, "Ctrl+E", page.open_export_tab),
        bind(page, "Ctrl+F", page.focus_search),
        bind(page, "F11", page.player.open_fullscreen),
        bind(page, "Left", lambda: page.player.nudge_back(),
             skip_when_typing=True),
        bind(page, "Right", lambda: page.player.nudge_forward(),
             skip_when_typing=True),
        bind(page, "Shift+Left", lambda: page.player.nudge_back(big=True),
             skip_when_typing=True),
        bind(page, "Shift+Right", lambda: page.player.nudge_forward(big=True),
             skip_when_typing=True),
        bind(page, "Ctrl+Left", page.player.previous_segment),
        bind(page, "Ctrl+Right", page.player.next_segment),
    ]
    page._shortcuts = created
    return created
