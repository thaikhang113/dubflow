"""Mở tệp và thư mục bằng chương trình mặc định của hệ điều hành.

Gom về một chỗ để mọi trang báo lỗi theo cùng một cách, thay vì mỗi nơi tự
gọi rồi im lặng khi thất bại.
"""
from __future__ import annotations

import os
import subprocess
import sys


def open_folder(path: str) -> tuple[bool, str]:
    """Mở một thư mục trong trình quản lý tệp.

    Trả về cặp (thành công, thông điệp giải thích khi thất bại).
    """
    if not path:
        return False, "Chưa có thư mục nào để mở."
    target = path if os.path.isdir(path) else os.path.dirname(path)
    if not os.path.isdir(target):
        return False, ("Không tìm thấy thư mục này nữa. Có thể nó đã bị đổi "
                       "tên hoặc xóa khỏi máy.")
    return _launch(target)


def open_file(path: str) -> tuple[bool, str]:
    """Mở một tệp bằng ứng dụng mặc định của hệ điều hành."""
    if not path:
        return False, "Chưa có tệp nào để mở."
    if not os.path.isfile(path):
        return False, ("Không tìm thấy tệp này nữa. Có thể nó đã bị di chuyển "
                       "hoặc xóa khỏi máy.")
    return _launch(path)


def reveal_file(path: str) -> tuple[bool, str]:
    """Mở thư mục chứa tệp và chọn sẵn tệp đó."""
    if not path or not os.path.exists(path):
        return open_folder(os.path.dirname(path or ""))
    if os.name == "nt":
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return True, ""
        except OSError as e:
            return False, f"Không mở được thư mục: {e}"
    return open_folder(os.path.dirname(path))


def open_url(url: str) -> tuple[bool, str]:
    """Mở một liên kết web trong trình duyệt mặc định."""
    if not url or not url.lower().startswith(("http://", "https://")):
        return False, "Liên kết không hợp lệ."
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    if QDesktopServices.openUrl(QUrl(url)):
        return True, ""
    return False, "Trình duyệt không mở được liên kết này."


def _launch(target: str) -> tuple[bool, str]:
    """Gọi lệnh mở của từng hệ điều hành."""
    try:
        if os.name == "nt":
            os.startfile(target)  # noqa: S606 — đường dẫn do chính ứng dụng tạo
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return True, ""
    except OSError as e:
        return False, f"Hệ điều hành không mở được: {e}"
