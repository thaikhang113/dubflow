"""Khoá hành vi: bấm Dừng ở Trình chỉnh sửa không được để rò khoá việc chung.

Lỗi gốc: _export gọi REGISTRY.start_job nhưng đường huỷ không đi qua
_on_export_done/_on_export_failed, nên finish_job không bao giờ chạy. Hệ quả
người dùng thấy được: sau khi bấm Dừng giữa lúc xuất video, mọi trang khác bị
chặn "đang chạy việc khác" cho tới khi khởi động lại ứng dụng.

Chiều ngược lại cũng được khoá: _start_resynth KHÔNG chiếm khoá việc chung,
nên hủy đường đọc-lại-giọng cũng không được phép nhả khoá đó — làm vậy sẽ xoá
nhầm việc của trang khác đang chạy.

Test chỉ kiểm tra HÀNH VI (khoá có được nhả hay không), không đối chiếu chuỗi
nguồn — gỡ dòng REGISTRY.finish_job khỏi handler là test đỏ ngay.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from autodub_gui.run_state import ActiveJob, RunRegistry


@pytest.fixture()
def registry() -> RunRegistry:
    """Sổ đăng ký riêng cho mỗi test, không đụng thể hiện dùng chung của app."""
    return RunRegistry()


def _page() -> SimpleNamespace:
    """Trang giả: chỉ đủ những gì hai handler huỷ chạm tới."""
    return SimpleNamespace(
        export_panel=SimpleNamespace(set_status=lambda text: None),
        voice_panel=SimpleNamespace(finish_progress=lambda text: None),
        _refresh_export_recovery=lambda: None,
        restore_video=lambda pos: None,
        _export_resume_pos=None,
        _resynth_resume_pos=None,
    )


def test_huy_xuat_video_nha_khoa_viec_dang_chay(registry, monkeypatch):
    """Bấm Dừng giữa lúc xuất video: sổ đăng ký phải trở về trạng thái rảnh."""
    from autodub_gui.pages import editor_export

    monkeypatch.setattr(editor_export, "REGISTRY", registry)
    registry.start_job(ActiveJob(kind="rebuild", title="Xuất video thử"))
    assert registry.is_busy(), "tiền đề: phải đang giữ khoá trước khi huỷ"

    editor_export.VoiceAndExportMixin._on_export_cancelled(_page())

    assert not registry.is_busy(), "huỷ xuất video phải nhả khoá việc đang chạy"
    assert registry.current() is None


def test_huy_doc_lai_giong_khong_xoa_khoa_cua_trang_khac(registry, monkeypatch):
    """Huỷ đọc lại giọng không được nhả khoá mà nó chưa từng chiếm."""
    from autodub_gui.pages import editor_export

    monkeypatch.setattr(editor_export, "REGISTRY", registry)
    registry.start_job(ActiveJob(kind="dub", title="Việc của trang khác"))

    editor_export.VoiceAndExportMixin._on_resynth_cancelled(_page())

    assert registry.is_busy(), (
        "đọc lại giọng không chiếm khoá việc chung, nên hủy nó không được nhả khoá"
    )
    assert registry.current().title == "Việc của trang khác"


def test_huy_xuat_khi_dang_ranh_khong_lam_hong_so_dang_ky(registry, monkeypatch):
    """Huỷ lúc không có việc nào đang chạy: không được ném lỗi."""
    from autodub_gui.pages import editor_export

    monkeypatch.setattr(editor_export, "REGISTRY", registry)

    editor_export.VoiceAndExportMixin._on_export_cancelled(_page())

    assert not registry.is_busy()
