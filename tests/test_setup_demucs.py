import importlib.util
import sys
from pathlib import Path


def _module():
    scripts = Path(__file__).parents[1] / "scripts"
    sys.path.insert(0, str(scripts))
    path = scripts / "setup_demucs.py"
    spec = importlib.util.spec_from_file_location("setup_demucs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rocm_index_can_be_overridden(monkeypatch):
    module = _module()
    monkeypatch.setenv("DUBFLOW_TORCH_INDEX_URL", "https://example.invalid/rocm")
    assert module._rocm_index() == "https://example.invalid/rocm"


def test_rocm_is_disabled_on_windows(monkeypatch):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    assert module._has_rocm() is False
