"""Cache paths must never depend on the working directory."""
import os

import pytest

from autodub import utils


@pytest.mark.parametrize("home", ["~", "relative-home"])
def test_cache_consumers_use_absolute_fallback(monkeypatch, tmp_path, home):
    from autodub.speech.tts import capcut_catalog
    from autodub_gui import theme, voice_preview
    from autodub_gui.pages.new_project_page import cache_dir

    monkeypatch.setattr(os.path, "expanduser", lambda _: home)
    monkeypatch.setattr(utils.tempfile, "gettempdir", lambda: str(tmp_path))
    expected = tmp_path / ".voxdub_cache"
    assert utils.cache_root() == str(expected)
    assert capcut_catalog.device_file() == str(expected / "capcut_device.json")
    assert voice_preview._cache_dir() == str(expected / "previews")
    assert cache_dir() == str(expected)
    arrow = theme._triangle_asset("cache_test", 10, 6, theme.TEXT_MUTED)
    assert os.path.normpath(arrow) == str(expected / "ui" / "cache_test.png")
    assert os.path.isfile(arrow)


def test_cache_keeps_existing_home_location(monkeypatch, tmp_path):
    monkeypatch.setattr(os.path, "expanduser", lambda _: str(tmp_path))
    assert utils.cache_root() == str(tmp_path / ".voxdub_cache")
