"""Không để cửa sổ console đen nháy lên khi ứng dụng gọi tiến trình con.

Lần chạy đầu tiên ứng dụng phải tạo ảnh đại diện cho từng dự án bằng ffmpeg.
Nếu thiếu cờ CREATE_NO_WINDOW, Windows mở một cửa sổ console cho mỗi lần gọi
rồi đóng ngay — người dùng thấy màn hình nháy liên tục.

Bản vá nằm ở autodub_gui/_frozen.py và phải chạy cho CẢ bản chạy từ mã nguồn
lẫn bản đóng gói (trước đây chỉ áp dụng cho bản đóng gói).
"""
from __future__ import annotations

import os
import subprocess

import pytest

from autodub_gui import _frozen

CREATE_NO_WINDOW = 0x08000000


@pytest.fixture
def ban_va_sach(monkeypatch):
    """Cho phép gọi lại bản vá trên một bản sao Popen.__init__ còn sạch."""
    lan_goi: list[dict] = []

    def gia_lap_init(self, *args, **kwargs):
        lan_goi.append(kwargs)

    monkeypatch.setattr(subprocess.Popen, "__init__", gia_lap_init,
                        raising=False)
    monkeypatch.setattr(_frozen, "_windows_hidden", False)
    return lan_goi


@pytest.mark.skipif(os.name != "nt", reason="chỉ có ý nghĩa trên Windows")
def test_popen_duoc_them_co_an_cua_so(ban_va_sach):
    _frozen._hide_subprocess_windows()
    subprocess.Popen(["ffmpeg", "-version"])
    assert ban_va_sach, "Popen không được gọi"
    assert ban_va_sach[0]["creationflags"] & CREATE_NO_WINDOW


@pytest.mark.skipif(os.name != "nt", reason="chỉ có ý nghĩa trên Windows")
def test_giu_nguyen_co_ma_noi_goi_da_dat(ban_va_sach):
    """Cờ sẵn có của nơi gọi phải được giữ, bản vá chỉ THÊM cờ ẩn cửa sổ."""
    _frozen._hide_subprocess_windows()
    subprocess.Popen(["ffmpeg"], creationflags=subprocess.CREATE_NEW_CONSOLE)
    co = ban_va_sach[0]["creationflags"]
    assert co & CREATE_NO_WINDOW
    assert co & subprocess.CREATE_NEW_CONSOLE


@pytest.mark.skipif(os.name != "nt", reason="chỉ có ý nghĩa trên Windows")
def test_goi_nhieu_lan_khong_chong_them_lop(ban_va_sach):
    """Gọi lặp lại không được bọc thêm lớp — sẽ làm chậm mọi lần gọi sau."""
    _frozen._hide_subprocess_windows()
    lan_dau = subprocess.Popen.__init__
    _frozen._hide_subprocess_windows()
    assert subprocess.Popen.__init__ is lan_dau


def test_an_cua_so_ca_khi_chay_tu_ma_nguon(monkeypatch):
    """Lỗi cũ: bản vá nằm sau `if not is_frozen(): return` nên chạy từ mã
    nguồn vẫn nháy cửa sổ. Kiểm tra init() gọi bản vá trước nhánh đó."""
    da_goi: list[str] = []
    monkeypatch.setattr(_frozen, "is_frozen", lambda: False)
    monkeypatch.setattr(_frozen, "_hide_subprocess_windows",
                        lambda: da_goi.append("an_cua_so"))
    monkeypatch.setattr(_frozen, "_prepend_path", lambda *a: None)
    monkeypatch.setattr(os, "chdir", lambda _p: da_goi.append("doi_thu_muc"))

    _frozen.init()

    assert da_goi == ["an_cua_so"], (
        "init() phải ẩn cửa sổ console ngay cả khi chạy từ mã nguồn, và "
        "không đổi thư mục làm việc khi chưa đóng gói")
