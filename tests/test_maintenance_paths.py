"""Maintenance commands must use writable user data in installed builds."""
from types import SimpleNamespace

import pytest

from autodub import utils
from autodub_gui import system_open
from autodub_gui.pages import settings_panels


@pytest.mark.parametrize("command, child", [
    ("_open_config", ""),
    ("_open_models", "models"),
    ("_export_diagnostics", "dubflow_diagnostics.txt"),
])
def test_maintenance_uses_data_root(tmp_path, monkeypatch, command, child):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(utils, "data_root", lambda: str(data))
    monkeypatch.setattr(utils, "app_root", lambda: str(tmp_path / "install"))
    opened = []
    monkeypatch.setattr(system_open, "open_folder",
                        lambda path: (opened.append(path) is None, ""))
    monkeypatch.setattr(settings_panels.TOASTS, "success",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        settings_panels.ConfirmDialog, "show_error",
        lambda *_args, **_kwargs: pytest.fail("Unexpected write error"),
    )
    panel = SimpleNamespace(
        DIAGNOSTIC_FILE="dubflow_diagnostics.txt",
        _diagnostic_lines=lambda: ["test diagnostics"],
        _open_config=lambda: None,
    )
    getattr(settings_panels.MaintenancePanel, command)(panel)
    if command == "_export_diagnostics":
        assert (data / child).read_text(encoding="utf-8") == "test diagnostics"
    else:
        assert opened == [str(data / child)]
    assert not (tmp_path / "install").exists()
