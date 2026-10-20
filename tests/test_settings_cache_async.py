"""Khoá hành vi: xoá dữ liệu tạm KHÔNG được chạy trên luồng giao diện.

Lỗi gốc: _remove_cache_files quét os.walk cả thư mục kết quả rồi os.remove
từng tệp NGAY TRONG slot của nút bấm — thư mục càng nhiều dự án thì giao diện
đứng hình càng lâu. Test này khoá đúng hệ quả người dùng thấy: bấm nút phải
trả về ngay, việc quét nằm ở luồng nền.
"""
from __future__ import annotations

import time

import pytest

from autodub_gui.pages.settings_panels import MaintenancePanel


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class FakeSettings:
    output_dir = ""


def _panel(qt_app, monkeypatch, tmp_path, *, walk_delay=0.0):
    """Panel thật với ConfirmDialog luôn đồng ý và os.walk bị làm chậm."""
    from autodub_gui.pages import settings_panels
    from autodub_gui.ui import modal

    monkeypatch.setattr(
        modal.ConfirmDialog, "ask",
        staticmethod(lambda *a, **k: (True, "")))

    real_walk = settings_panels.os.walk

    def slow_walk(path):
        """Giả lập cây thư mục lớn: mỗi bước quét tốn thời gian thật."""
        time.sleep(walk_delay)
        yield from real_walk(path)

    monkeypatch.setattr(settings_panels.os, "walk", slow_walk)

    settings = FakeSettings()
    settings.output_dir = str(tmp_path)
    return MaintenancePanel(lambda: settings)


def test_bam_xoa_tra_ve_ngay_khong_cho_quet_xong(qt_app, monkeypatch, tmp_path):
    """Bấm nút phải trả về trong vài chục ms dù việc quét rất chậm.

    Trước khi sửa, os.walk chạy đồng bộ trong slot nên thời gian gọi _clear_cache
    xấp xỉ thời gian quét. Nay việc quét nằm ở QThread nên phải ngắn hơn hẳn.
    """
    (tmp_path / "du-an").mkdir()
    (tmp_path / "du-an" / "thumbnail.jpg").write_text("x")

    panel = _panel(qt_app, monkeypatch, tmp_path, walk_delay=0.25)

    started = time.monotonic()
    panel._clear_cache()
    elapsed = time.monotonic() - started

    # Quét thật tốn >= 0.25 s; trả về tức thì nghĩa là đã đẩy sang luồng nền.
    assert elapsed < 0.2, (
        f"_clear_cache chặn luồng GUI {elapsed:.3f}s — việc quét phải ở luồng nền"
    )

    # Dọn dẹp: chờ luồng nền xong để không rò thread sang test khác.
    panel.cleanup()


def test_luong_nen_giu_tham_chieu_va_cleanup_cho_no_xong(qt_app, monkeypatch,
                                                         tmp_path):
    """Panel phải giữ tham chiếu luồng nền để teardown còn chờ được."""
    panel = _panel(qt_app, monkeypatch, tmp_path, walk_delay=0.05)

    panel._clear_cache()

    assert panel._cache_worker is not None, (
        "phải giữ tham chiếu QThread, nếu không cleanup không chờ được nó"
    )

    panel.cleanup()


def test_quet_that_su_xoa_duoc_tep_luu_tam(qt_app, monkeypatch, tmp_path):
    """Việc xoá vẫn phải làm đúng việc của nó, không chỉ chạy nền cho có."""
    from autodub_gui.projects import INDEX_FILE, THUMB_FILE

    du_an = tmp_path / "du-an"
    du_an.mkdir()
    (du_an / THUMB_FILE).write_text("x")
    (du_an / INDEX_FILE).write_text("x")
    (du_an / "waveform_peaks_track2.json").write_text("x")
    giu_lai = du_an / "dubbed_video.mp4"
    giu_lai.write_text("giu nguyen")

    panel = _panel(qt_app, monkeypatch, tmp_path, walk_delay=0.0)
    panel._clear_cache()
    panel.cleanup()

    assert not (du_an / THUMB_FILE).exists()
    assert not (du_an / INDEX_FILE).exists()
    assert not (du_an / "waveform_peaks_track2.json").exists()
    assert giu_lai.is_file(), "video kết quả không được bị xoá"
