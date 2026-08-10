"""Lưới an toàn khi ứng dụng gặp lỗi không lường trước (crash).

Mặc định PySide6 chỉ in traceback ra console — bản đóng gói không có console
nên ứng dụng "chết im lặng" và người dùng không biết chuyện gì xảy ra. Móc
``sys.excepthook`` ở đây bảo đảm mọi lỗi thoát ra khỏi vòng lặp sự kiện đều:

1. được ghi đầy đủ vào tệp log (``logs/voxdub.log``), và
2. hiện hộp thoại tiếng Việt với nút mở thư mục log để người dùng gửi kèm
   khi cần trợ giúp.

Lỗi trong luồng nền (``threading.excepthook``) chỉ ghi log — không được đụng
vào GUI từ ngoài luồng chính.
"""
from __future__ import annotations

import logging
import sys
import threading
import traceback

logger = logging.getLogger("autodub.crash")

#: Chỉ hiện một hộp thoại crash cho mỗi phiên — lỗi lặp lại (ví dụ trong
#: paintEvent) sẽ bắn liên tục và chồng hộp thoại đến khi treo máy.
_dialog_shown = False


def _format(exc_type, exc_value, exc_tb) -> str:
    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))


def _support_url() -> str:
    """Địa chỉ biểu mẫu báo lỗi, đọc an toàn vì đang trong lúc app gặp lỗi."""
    try:
        from autodub.config import Settings

        return Settings.load(override=True).support_url
    except Exception:  # noqa: BLE001 — cấu hình hỏng thì đành bỏ nút gửi
        return ""


def _show_dialog(detail: str) -> None:
    global _dialog_shown
    if _dialog_shown:
        return
    _dialog_shown = True
    try:
        from autodub.utils import logs_dir
        from autodub_gui.system_open import open_folder, open_url
        from autodub_gui.ui.modal import ConfirmDialog

        support = _support_url()
        message = (
            "VoxDub vừa gặp một lỗi ngoài dự kiến. Công việc đang chạy có thể "
            "bị gián đoạn — hãy lưu lại rồi khởi động lại ứng dụng.\n\n"
            "Chi tiết lỗi đã được ghi vào tệp log. ")
        if support:
            message += ("Bấm Gửi báo lỗi để mở biểu mẫu hỗ trợ — nhớ đính kèm "
                        "tệp log mới nhất (thư mục log sẽ được mở sẵn).")
            confirm = "Gửi báo lỗi"
        else:
            message += ("Nếu lỗi lặp lại, hãy gửi tệp log mới nhất trong thư "
                        "mục log cho người hỗ trợ.")
            confirm = "Mở thư mục log"
        accepted, _ = ConfirmDialog.ask(
            None, "Ứng dụng gặp lỗi không mong muốn", message,
            kind="error", confirm_label=confirm,
            cancel_label="Đóng", detail=detail)
        if accepted:
            open_folder(logs_dir())
            if support:
                open_url(support)
    except Exception:
        # Hộp thoại cũng hỏng (Qt đã chết?) — log là chỗ dựa cuối cùng.
        logger.exception("Không hiện được hộp thoại crash")
    finally:
        # Cho phép báo lần sau nếu người dùng tiếp tục dùng app.
        _dialog_shown = False


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    detail = _format(exc_type, exc_value, exc_tb)
    logger.critical("Lỗi không được xử lý (crash):\n%s", detail)
    _show_dialog(detail)


def _thread_excepthook(hook_args) -> None:
    if hook_args.exc_type is SystemExit:
        return
    detail = _format(hook_args.exc_type, hook_args.exc_value,
                     hook_args.exc_traceback)
    name = getattr(hook_args.thread, "name", "?")
    logger.critical("Lỗi không được xử lý trong luồng %s:\n%s", name, detail)


def install_crash_handler() -> None:
    """Gọi một lần trong ``main()`` sau khi có ``QApplication``."""
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
