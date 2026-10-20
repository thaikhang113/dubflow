"""Kiểm chứng nút cài đặt VSR trên trang Cài đặt.

Người dùng cuối không bao giờ mở terminal: nút phải tự chạy script cài đặt
trong nền, hiển thị tiến trình, và báo lỗi bằng tiếng Việt có dấu. Bộ test này
kiểm chứng hành vi thật của panel, không đối chiếu chuỗi nguồn.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from autodub_gui.pages.settings_panels import VsrPanel

ROOT = Path(__file__).parents[1]


class FakeSettings:
    """Cấu hình giả: chỉ cần đúng những gì VsrPanel đọc."""

    def __init__(self, *, configured: bool, enabled: bool = True):
        self._configured = configured
        self.vsr_enabled = enabled
        self.vsr_mode = "sttn-det"

    def vsr_configured(self) -> bool:
        return self._configured


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def captured_worker(monkeypatch):
    """Chặn SetupScriptWorker: ghi lại tham số, không chạy tiến trình nào."""
    from autodub_gui import workers_setup

    made = []

    class FakeWorker:
        def __init__(self, script_rel, parent=None, args=None):
            self.script_rel = script_rel
            self.args = list(args or ())
            self.started = False
            self._running = False
            self.listeners = {}
            made.append(self)

        def _signal(self, name):
            class _Sig:
                @staticmethod
                def connect(slot):
                    self.listeners[name] = slot

            return _Sig()

        @property
        def log(self):
            return self._signal("log")

        @property
        def finished_ok(self):
            return self._signal("ok")

        @property
        def failed(self):
            return self._signal("fail")

        def isRunning(self):  # noqa: N802 - tên API của QThread
            return self._running

        def start(self):
            self.started = True
            self._running = True

        def wait(self, _timeout=None):
            self._running = False
            return True

        # -- mô phỏng tín hiệu phát ra từ luồng nền --
        def emit_log(self, text):
            self.listeners["log"](text)

        def emit_ok(self):
            self._running = False
            self.listeners["ok"]()

        def emit_fail(self, err):
            self._running = False
            self.listeners["fail"](err)

    monkeypatch.setattr(workers_setup, "SetupScriptWorker", FakeWorker)
    return made


def _confirmed(monkeypatch):
    """Người dùng bấm đồng ý trong hộp thoại xác nhận."""
    from autodub_gui.ui.modal import ConfirmDialog

    monkeypatch.setattr(ConfirmDialog, "ask",
                        staticmethod(lambda *a, **k: (True, False)))


def _panel(*, configured=False, enabled=True, live=None):
    state = live if live is not None else {}
    if not state:
        state["installed"] = configured
    return VsrPanel(lambda: FakeSettings(configured=state["installed"],
                                         enabled=enabled)), state


# ---------------------------------------------------- dòng trạng thái VSR

def test_status_warns_when_vsr_not_installed(qt_app):
    panel, _ = _panel(configured=False)
    assert "Chưa cài VSR" in panel.status.text()
    assert "không cần mở terminal" in panel.status.text()


def test_status_reports_installed_vsr(qt_app):
    panel, _ = _panel(configured=True)
    assert "Đã cài VSR" in panel.status.text()
    assert "Cài đặt lại" in panel.btn_install.text()


def test_status_respects_disabled_vsr(qt_app):
    panel, _ = _panel(configured=False, enabled=False)
    assert "VSR đang tắt" in panel.status.text()


# ------------------------------------------------------------- nút bấm

def test_clicking_button_asks_before_running(
        monkeypatch, qt_app, captured_worker):
    """Bấm nút luôn hỏi trước; từ chối thì không chạy gì."""
    from autodub_gui.ui.modal import ConfirmDialog

    asked = []
    monkeypatch.setattr(
        ConfirmDialog, "ask",
        staticmethod(lambda *a, **k: (asked.append(a[1:]), (False, False))[1]))
    panel, _ = _panel(configured=False)
    panel.btn_install.click()
    assert asked, "nút phải hỏi xác nhận trước khi cài"
    assert captured_worker == []


def test_confirmed_click_runs_setup_vsr_in_background(
        monkeypatch, qt_app, captured_worker):
    _confirmed(monkeypatch)
    panel, _ = _panel(configured=False)
    panel.btn_install.click()

    assert len(captured_worker) == 1
    worker = captured_worker[0]
    assert worker.script_rel == "scripts/setup_vsr.py"
    assert worker.args == []            # script không nhận tham số nào
    assert worker.started is True
    assert "Đang cài đặt" in panel.status.text()


def test_log_lines_stream_into_status(
        monkeypatch, qt_app, captured_worker):
    _confirmed(monkeypatch)
    panel, _ = _panel(configured=False)
    panel.btn_install.click()
    captured_worker[0].emit_log("[setup-vsr] Cài dependency VSR ...")
    assert panel.status.text() == "[setup-vsr] Cài dependency VSR ..."


def test_second_click_while_running_does_not_start_again(
        monkeypatch, qt_app, captured_worker):
    _confirmed(monkeypatch)
    panel, _ = _panel(configured=False)
    panel.btn_install.click()
    panel.btn_install.click()
    assert len(captured_worker) == 1


def test_failure_shows_vietnamese_error_without_losing_progress(
        monkeypatch, qt_app, captured_worker):
    _confirmed(monkeypatch)
    from autodub_gui.ui.modal import ConfirmDialog

    errors = []
    monkeypatch.setattr(
        ConfirmDialog, "show_error",
        staticmethod(lambda *a, **k: errors.append((a, k))))
    panel, _ = _panel(configured=False)
    panel.btn_install.click()
    captured_worker[0].emit_fail(
        "setup_vsr.py kết thúc với mã lỗi 1:\nboom")

    assert errors, "thất bại phải hiện hộp thoại báo lỗi"
    args, kwargs = errors[0]
    assert args[1] == "Không cài được AI xóa phụ đề VSR"
    assert "kiểm tra kết nối mạng" in args[2]
    assert "boom" in kwargs["detail"]
    assert "thất bại" in panel.status.text()
    assert panel.btn_install.isEnabled()


def test_success_refreshes_status_and_notifies_changes(
        monkeypatch, qt_app, captured_worker):
    _confirmed(monkeypatch)
    panel, state = _panel(configured=False)
    changed = []
    panel.changed.connect(lambda: changed.append(1))
    panel.btn_install.click()
    state["installed"] = True
    captured_worker[0].emit_ok()

    assert "Đã cài VSR" in panel.status.text()
    assert "Cài đặt lại" in panel.btn_install.text()
    assert changed == [1]
    assert panel.btn_install.isEnabled()


# ------------------------------------------------------------- lắp ghép

def test_panel_is_wired_into_advanced_settings_tab(qt_app):
    """Bảng VSR phải thật sự nằm trên thẻ Cài đặt nâng cao."""
    from autodub_gui.pages import settings_fields as spec
    from autodub_gui.pages import settings_page

    page = settings_page.SettingsPage()
    try:
        panels = page._extra_panels(spec.TAB_ADVANCED)
        assert any(isinstance(p, VsrPanel) for p in panels)
        assert isinstance(page.vsr_panel, VsrPanel)
    finally:
        page.cleanup()
        page.deleteLater()
        qt_app.processEvents()


def test_setup_worker_estimates_vsr_progress():
    """Tiến độ phải có ước lượng riêng cho setup_vsr.py, không dùng mặc định."""
    from autodub_gui.workers_setup import _SCRIPT_LINES_ESTIMATE

    assert _SCRIPT_LINES_ESTIMATE.get("setup_vsr.py")


def test_setup_vsr_script_takes_no_arguments():
    """Nút bấm không được truyền tham số lạ cho script cài đặt."""
    source = (ROOT / "scripts" / "setup_vsr.py").read_text(encoding="utf-8")
    assert "argparse" not in source and "sys.argv" not in source


def test_vsr_text_is_vietnamese_with_diacritics():
    """Mọi chữ người dùng đọc được đều phải là tiếng Việt có dấu."""
    import unicodedata

    panel, _ = _panel(configured=False)
    texts = [panel.btn_install.text(), panel.btn_install.toolTip(),
             panel.status.text(), panel._title.text()]
    joined = " ".join(texts)
    assert "Cài đặt" in joined or "cài đặt" in joined
    decomposed = unicodedata.normalize("NFD", joined)
    assert any(unicodedata.combining(ch) for ch in decomposed), (
        "chữ trên bảng VSR phải có dấu tiếng Việt")
