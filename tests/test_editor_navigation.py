from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture
def window(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTODUB_SMOKE", "1")
    monkeypatch.setenv("DUBFLOW_BOOTSTRAP_SYNC", "1")
    monkeypatch.setenv("DUBFLOW_DATA_DIR", str(tmp_path))
    from autodub_gui.app import MainWindow, ROW_EDITOR

    class Editor(QWidget):
        _work_dir = ""
        reject_open = False
        load_error = ""

        def open_work_dir(self, path):
            if self.reject_open:
                ConfirmDialog.show_error(
                    self, "Không mở được dự án này",
                    "Không có bản dịch", detail="rejected")
                return
            self._work_dir = path

    class ConfirmDialog:
        @staticmethod
        def show_error(parent, _title, _message, *, detail="", **_kwargs):
            parent.load_error = detail

    def create_page(self, row):
        return Editor(self.pages) if row == ROW_EDITOR else QWidget(self.pages)

    monkeypatch.setattr(MainWindow, "_create_page", create_page)
    monkeypatch.setattr(MainWindow, "refresh_system_status", lambda self: None)
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    app.processEvents()
    yield win
    win._force_close = True
    win.close()
    app.processEvents()


def _make_current_page_unsaved(window):
    current = window.pages.currentWidget()
    current.has_unsaved_changes = lambda: True
    return current


def _reject_discard(monkeypatch):
    from autodub_gui.ui import modal

    monkeypatch.setattr(
        modal.ConfirmDialog,
        "ask",
        lambda *_args, **_kwargs: (False, False),
    )


def test_first_project_open_displays_loaded_editor(window):
    from autodub_gui.app import ROW_EDITOR

    window.open_editor("first-project")

    editor = window._page_widgets[ROW_EDITOR]
    assert editor._work_dir == "first-project"
    assert window.pages.currentWidget() is editor
    assert editor.isVisible()


def test_cancel_navigation_does_not_load_project(window, monkeypatch):
    from autodub_gui.app import ROW_EDITOR

    current = _make_current_page_unsaved(window)
    _reject_discard(monkeypatch)

    window.open_editor("unwanted-project")

    assert window.pages.currentWidget() is current
    editor = window._page_widgets.get(ROW_EDITOR)
    assert editor is None or not editor._work_dir


def test_rejected_editor_open_preserves_current_page(window):
    from autodub_gui.app import ROW_EDITOR

    page = window._ensure_page(ROW_EDITOR)
    page.reject_open = True
    current = window.pages.currentWidget()

    window.open_editor("rejected-project")

    assert not page._work_dir
    assert window.pages.currentWidget() is current
    assert page.load_error


def test_sidebar_without_project_still_opens_launcher(window):
    from autodub_gui.app import ROW_EDITOR, ROW_EDITOR_LAUNCHER

    window.switch_page(ROW_EDITOR)

    assert window.pages.currentWidget() is window._page_widgets[ROW_EDITOR_LAUNCHER]
