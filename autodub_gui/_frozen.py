"""Khởi tạo môi trường khi chạy dưới dạng exe đóng gói (PyInstaller).

Gọi ``init()`` một lần thật sớm trong ``app.main()``. Khi chạy từ source
các bước gần như no-op (chỉ thêm PATH phụ), nên dev không bị ảnh hưởng.
"""
from __future__ import annotations

import functools
import os
import subprocess
import sys

from autodub.utils import app_root


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def browsers_dir() -> str:
    """Thư mục chứa Chromium của Playwright — nằm cạnh app để bản đóng gói
    tự quản lý, không rơi vào %LOCALAPPDATA% mặc định."""
    return os.path.join(app_root(), "pw-browsers")


def libs_dir() -> str:
    """Thư mục thư viện Python người dùng tự cài thêm (pip --target).

    Các tính năng tùy chọn (Douyin/playwright...) không đóng trong exe —
    script 'Cai dat tinh nang Douyin.bat' cài chúng vào đây để exe nhỏ gọn.
    """
    return os.path.join(app_root(), "libs")


def _prepend_path(*dirs: str) -> None:
    existing = os.environ.get("PATH", "")
    extra = [d for d in dirs if os.path.isdir(d) and d not in existing]
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra) + os.pathsep + existing


_windows_hidden = False


def _hide_subprocess_windows() -> None:
    """Chặn cửa sổ console đen nháy lên khi app gọi tiến trình con.

    Mỗi lần app gọi ffmpeg / ffprobe / yt-dlp / nvidia-smi / worker giọng đọc,
    Windows mở một cửa sổ console và đóng ngay — nhìn rất mất chuyên nghiệp,
    nhất là lần chạy đầu khi app phải tạo ảnh đại diện cho hàng loạt dự án.

    Vá một chỗ duy nhất ở đây thay vì rải cờ CREATE_NO_WINDOW ra từng lời gọi
    (rải tay chắc chắn sẽ sót). Áp dụng cho CẢ bản chạy từ mã nguồn lẫn bản
    đóng gói — người dùng thấy như nhau ở cả hai.
    """
    global _windows_hidden
    if os.name != "nt" or _windows_hidden:
        return
    _windows_hidden = True
    original_init = subprocess.Popen.__init__

    @functools.wraps(original_init)
    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("creationflags", 0)
        kwargs["creationflags"] |= subprocess.CREATE_NO_WINDOW
        # Chỉ CREATE_NO_WINDOW là chưa đủ trong mọi cách khởi động: khi ứng
        # dụng được mở từ Explorer hoặc bằng pythonw, một số tiến trình con
        # vẫn kịp hiện cửa sổ. Ép thêm SW_HIDE ở mức STARTUPINFO để chặn nốt.
        info = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = info
        original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = patched_init


def init() -> None:
    root = app_root()

    # ffmpeg.exe / yt-dlp.exe thả cạnh exe (hoặc trong bin/) là dùng được ngay,
    # không cần người dùng chỉnh PATH hệ thống.
    _prepend_path(root, os.path.join(root, "bin"))

    # Chromium của Playwright sống cạnh app (nút tải trong tab Cài đặt).
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", browsers_dir())

    # Thư viện tùy chọn người dùng tự cài (libs/) — APPEND để package đóng
    # trong exe luôn thắng, libs/ chỉ bổ sung những gì exe không có.
    libs = libs_dir()
    if os.path.isdir(libs) and libs not in sys.path:
        sys.path.append(libs)

    # Không để cửa sổ console nháy lên khi gọi ffmpeg và các tiến trình con
    # khác. Làm cho mọi kiểu chạy, không riêng bản đóng gói.
    _hide_subprocess_windows()

    if not is_frozen():
        return

    # Đường dẫn tương đối (thư mục output, downloads…) neo vào cạnh exe
    # thay vì CWD bất kỳ mà shortcut khởi chạy.
    os.chdir(root)
