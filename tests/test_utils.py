import logging
import os

from autodub.utils import (
    asr_timeout_s,
    ensure_dir,
    format_timestamp,
    seg_wav_path,
    setup_logging,
)


def test_data_root_honors_runtime_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DUBFLOW_DATA_DIR", str(tmp_path))
    from autodub.utils import data_root
    assert data_root() == str(tmp_path)

def test_gpu_venv_uses_deepseek_cuda_runtime_when_gpu_venv_missing(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DUBFLOW_DATA_DIR", str(tmp_path))
    deepseek = tmp_path / ".venv-deepseek-ocr"
    deepseek.mkdir()

    from autodub.utils import gpu_venv_dir

    assert gpu_venv_dir() == str(deepseek)

def test_setup_logging_returns_logger():
    logger = setup_logging("test_logger")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_logger"


def test_ensure_dir_creates_directory(tmp_path):
    new_dir = tmp_path / "subdir" / "nested"
    result = ensure_dir(str(new_dir))
    assert os.path.isdir(result)
    assert result == str(new_dir)


def test_ensure_dir_existing_directory(tmp_path):
    result = ensure_dir(str(tmp_path))
    assert os.path.isdir(result)


def test_format_timestamp_zero():
    assert format_timestamp(0.0) == "00:00:00,000"


def test_format_timestamp_seconds():
    assert format_timestamp(3.2) == "00:00:03,200"


def test_format_timestamp_minutes():
    assert format_timestamp(65.5) == "00:01:05,500"


def test_format_timestamp_hours():
    assert format_timestamp(3661.123) == "01:01:01,123"


def test_seg_wav_path_defaults_to_5_digits(tmp_path):
    assert seg_wav_path(str(tmp_path), 7) == str(tmp_path / "seg_00007.wav")


def test_seg_wav_path_scales_past_999(tmp_path):
    assert seg_wav_path(str(tmp_path), 12345) == str(tmp_path / "seg_12345.wav")


def test_seg_wav_path_prefers_existing_legacy_name(tmp_path):
    (tmp_path / "seg_007.wav").write_bytes(b"x")
    assert seg_wav_path(str(tmp_path), 7) == str(tmp_path / "seg_007.wav")


def test_seg_wav_path_prefers_new_name_when_both_exist(tmp_path):
    (tmp_path / "seg_007.wav").write_bytes(b"x")
    (tmp_path / "seg_00007.wav").write_bytes(b"x")
    assert seg_wav_path(str(tmp_path), 7) == str(tmp_path / "seg_00007.wav")

def test_asr_timeout_scales_for_long_audio():
    assert asr_timeout_s(5 * 3600) == 5 * 3600 * 12
    assert asr_timeout_s(None) == 3600
