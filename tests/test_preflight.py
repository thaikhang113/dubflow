"""Kiểm tra autodub.preflight — logic thuần, không cần Qt."""
import os

import pytest

from autodub.config import Settings
from autodub.preflight import (
    CheckResult,
    _check_asr,
    _check_disk,
    _check_vieneu,
    _total_ram_gb,
    blocking_failures,
    run_preflight,
    warnings_of,
)


@pytest.fixture
def settings():
    return Settings.load(override=True)


def test_run_preflight_returns_results(settings):
    results = run_preflight(settings)
    assert results, "phải có ít nhất một mục kiểm tra"
    for r in results:
        assert isinstance(r, CheckResult)
        assert r.level in ("ok", "warn", "fail")
        assert r.key and r.title and r.message
        # Mục không đạt phải có lời khuyên để người dùng tự xử lý.
        if r.level in ("warn", "fail"):
            assert r.advice


def test_run_preflight_never_raises(monkeypatch, settings):
    # Một mục nổ tung cũng không được chặn các mục khác.
    import autodub.preflight as pf

    def _boom(_settings):
        raise RuntimeError("nổ")

    monkeypatch.setattr(pf, "_check_ffmpeg", _boom)
    results = pf.run_preflight(settings)
    assert any(r.key == "internal" for r in results)


def test_blocking_and_warning_filters():
    results = [
        CheckResult("a", "A", "ok", "x"),
        CheckResult("b", "B", "warn", "x", "y"),
        CheckResult("c", "C", "fail", "x", "y"),
    ]
    assert [r.key for r in blocking_failures(results)] == ["c"]
    assert [r.key for r in warnings_of(results)] == ["b"]
    assert results[0].ok and not results[1].ok


def test_check_disk_missing_dir_walks_to_parent(tmp_path):
    # OUTPUT_DIR chưa tồn tại (lần chạy đầu) → đo ổ đĩa cha, không nổ.
    settings = Settings.load(override=True)
    settings.output_dir = str(tmp_path / "chua" / "ton" / "tai")
    result = _check_disk(settings)
    assert result.key == "disk"
    assert result.level in ("ok", "warn", "fail")


def test_check_vieneu_not_configured(settings, monkeypatch):
    """Chưa cài VieNeu chỉ là cảnh báo — giọng CapCut vẫn lồng tiếng được."""
    monkeypatch.setattr(Settings, "vieneu_configured", lambda self: False)
    result = _check_vieneu(settings)
    assert result.level == "warn"
    assert "setup_vieneu" in result.advice


def test_check_asr_paraformer_not_configured(settings, monkeypatch):
    settings.asr_engine = "paraformer"
    monkeypatch.setattr(Settings, "paraformer_configured", lambda self: False)
    result = _check_asr(settings)
    assert result.level == "fail"
    assert "Whisper" in result.advice


def test_check_asr_accepts_dedicated_venv_without_app_import(
    settings, monkeypatch
):
    """Packaged app must validate its dedicated Whisper runtime."""
    import builtins

    import autodub.preflight as preflight

    settings.asr_engine = "whisper"
    monkeypatch.setattr(Settings, "whisper_venv_configured",
                        lambda self: True)
    real_import = builtins.__import__

    def without_bundled_whisper(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("not bundled in the application")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_bundled_whisper)
    monkeypatch.setattr(preflight.os.path, "isdir", lambda _path: False)

    result = _check_asr(settings)

    assert result.level == "warn"
    assert "Thiếu thư viện faster-whisper" not in result.message


def test_check_asr_uses_configured_model_cache(settings, monkeypatch, tmp_path):
    import builtins

    settings.asr_engine = "whisper"
    settings.whisper_model = "tiny"
    monkeypatch.setattr(Settings, "whisper_venv_configured",
                        lambda self: True)
    model_root = tmp_path / "models" / "whisper"
    model_dir = model_root / (
        f"models--Systran--faster-whisper-{settings.whisper_model}")
    model_dir.mkdir(parents=True)
    monkeypatch.setattr(Settings, "whisper_model_dir_path",
                        lambda self: str(model_root))
    real_import = builtins.__import__

    def without_bundled_whisper(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("not bundled in the application")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_bundled_whisper)

    result = _check_asr(settings)

    assert result.level == "ok"
    assert "đã có sẵn" in result.message


def test_check_asr_requires_venv_or_in_process_package(settings, monkeypatch):
    import builtins

    settings.asr_engine = "whisper"
    monkeypatch.setattr(Settings, "whisper_venv_configured",
                        lambda self: False)
    real_import = builtins.__import__

    def without_whisper(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_whisper)

    result = _check_asr(settings)

    assert result.level == "fail"
    assert "setup_whisper.py" in result.advice


def test_total_ram_readable():
    total = _total_ram_gb()
    # Trên máy thật phải đọc được số dương; 0.0 chỉ khi API hỏng.
    assert total >= 0.0


def test_logs_dir_and_file_logging(tmp_path, monkeypatch):
    from autodub import utils

    monkeypatch.setattr(utils, "app_root", lambda: str(tmp_path))
    monkeypatch.setattr(utils, "_FILE_HANDLER", None)
    path = utils.init_file_logging()
    assert path == os.path.join(str(tmp_path), "logs", "voxdub.log")
    assert os.path.isdir(os.path.dirname(path))
    # Gọi lại phải trả về cùng tệp, không thêm handler thứ hai.
    assert utils.init_file_logging() == path
    import logging
    root = logging.getLogger("autodub")
    file_handlers = [h for h in root.handlers
                     if getattr(h, "baseFilename", "") == path]
    assert len(file_handlers) == 1
    # Dọn: gỡ handler để không giữ tệp mở sang test khác.
    for h in file_handlers:
        root.removeHandler(h)
        h.close()
    monkeypatch.setattr(utils, "_FILE_HANDLER", None)
