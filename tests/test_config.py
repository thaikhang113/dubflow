import os

import pytest

from autodub.config import ConfigError, Settings
from autodub.utils import app_root


def test_settings_load_env_vars(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("WHISPER_MODEL", "large-v3")
    monkeypatch.setenv("DEFAULT_SOURCE_LANG", "en-US")
    monkeypatch.setenv("AUDIO_SAMPLE_RATE", "16000")
    monkeypatch.setenv("OUTPUT_DIR", "./output")

    settings = Settings.load()

    assert settings.whisper_model == "large-v3"
    assert settings.default_source_lang == "en-US"
    assert settings.audio_sample_rate == 16000
    # Relative output dirs anchor at the app root (exe folder when frozen).
    assert settings.output_dir == os.path.join(app_root(), "output")


def test_settings_defaults(monkeypatch):
    """When optional env vars are not set, Settings should use defaults."""
    # Prevent load_dotenv from loading .env file values
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)

    for var in ("WHISPER_MODEL", "ASR_ENGINE", "DEFAULT_SOURCE_LANG",
                "QUALITY_PRESET", "AUDIO_SAMPLE_RATE", "OUTPUT_DIR",
                "VIDEO_URL"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings.load()

    # Paraformer mặc định cho tiếng Trung.
    assert settings.quality_preset == "balanced"
    assert settings.whisper_model == "auto"
    assert settings.asr_engine == "paraformer"
    assert settings.default_source_lang == "zh-CN"
    assert settings.audio_sample_rate == 16000
    assert settings.output_dir == os.path.join(app_root(), "output")
    assert settings.video_url == ""


def test_quality_presets(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    for var in ("WHISPER_MODEL", "HQ_BACKGROUND",
                "TRANSLATE_ANALYSIS", "TRANSLATE_REVIEW"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("QUALITY_PRESET", "fast")
    s = Settings.load()
    assert s.whisper_model == "medium"
    assert s.hq_background is False
    monkeypatch.setenv("QUALITY_PRESET", "quality")
    s = Settings.load()
    assert s.whisper_model == "auto"
    assert s.hq_background is True
    # Explicit env var beats the preset
    monkeypatch.setenv("WHISPER_MODEL", "small")
    assert Settings.load().whisper_model == "small"


def test_resolved_whisper_model():
    s = Settings(whisper_model="auto")
    assert s.resolved_whisper_model(cuda_available=True) == "large-v3"
    assert s.resolved_whisper_model(cuda_available=False) == "medium"
    s2 = Settings(whisper_model="small")
    assert s2.resolved_whisper_model(cuda_available=True) == "small"


def test_timing_settings_clamped(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("TIMING_MAX_ATEMPO", "2.0")   # trần cứng 1.3
    monkeypatch.setenv("TIMING_MAX_DRIFT_S", "99")
    monkeypatch.setenv("BG_DUCK_VOICE_DB", "5")      # duck không được dương
    s = Settings.load()
    assert s.timing_max_atempo == 1.3
    assert s.timing_max_drift_s == 5.0
    assert s.bg_duck_voice_db == 0.0


def test_settings_require_raises_on_missing():
    with pytest.raises(ConfigError, match="OUTPUT_DIR"):
        Settings(output_dir="").require("output_dir")


def test_settings_require_passes_when_set():
    Settings(output_dir="./out").require("output_dir")


def test_subtitle_style_from_settings(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("SUBTITLE_POSITION", "middle")
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "30")
    monkeypatch.setenv("SUBTITLE_COLOR", "#FFFF00")
    style = Settings.load().subtitle_style()
    assert style["position"] == "middle"
    assert style["font_size"] == 30
    assert style["color"] == "#FFFF00"


def test_subtitle_position_typo_falls_back(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("SUBTITLE_POSITION", "sideways")
    assert Settings.load().subtitle_position == "bottom"


def test_vi_output_dir_default_and_override():
    assert Settings(output_dir="./out").vi_output_dir().replace("\\", "/") == "./out/VN"
    assert Settings(vietnamese_output_dir="D:/VN").vi_output_dir() == "D:/VN"


def test_translate_defaults(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    for var in ("TRANSLATE_ENABLED", "TRANSLATE_BATCH_SIZE",
                "TRANSLATION_ENDPOINT", "TRANSLATION_API_KEY",
                "TRANSLATION_MODEL"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.load()
    assert s.translate_enabled is True
    assert s.translate_batch_size == 20
    assert s.translation_endpoint == ""
    assert s.translation_model == ""

def test_worker_mode_defaults_to_auto_and_accepts_manual(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.delenv("WORKER_MODE", raising=False)
    assert Settings.load().worker_mode == "auto"
    monkeypatch.setenv("WORKER_MODE", "manual")
    assert Settings.load().worker_mode == "manual"


def test_ocr_defaults_and_paths(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    for var in ("OCR_ENABLED", "OCR_MIN_CONFIDENCE",
                "OCR_MAX_REGION_AREA", "OCR_SUBTITLE_Y_MIN",
                "OCR_SAMPLE_INTERVAL"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.load()
    assert s.ocr_enabled is True
    assert s.ocr_min_confidence == 0.8
    assert s.ocr_max_region_area == 0.25
    assert s.ocr_subtitle_y_min == 0.65
    assert s.ocr_sample_interval == 1.0
    expected_suffix = (
        ".venv-ocr/Scripts/python.exe"
        if os.name == "nt"
        else ".venv-ocr/bin/python"
    )
    assert s.ocr_venv_python_path().replace("\\", "/").endswith(expected_suffix)


def test_clone_defaults(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    for var in ("VIENEU_CLONE_ENABLED", "VIENEU_CLONE_SOURCE",
                "VIENEU_CLONE_REFERENCE_AUDIO"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.load()
    assert s.vieneu_clone_enabled is False
    assert s.vieneu_clone_source == "video"
    assert s.vieneu_clone_reference_audio == ""


def test_translate_batch_size_capped_for_api_stability(monkeypatch):
    """Batch mặc định vừa phải, cấu hình không vượt trần client."""
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("TRANSLATE_BATCH_SIZE", "500")
    assert Settings.load().translate_batch_size == 40


def test_translate_enabled_off(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("TRANSLATE_ENABLED", "false")
    assert Settings.load().translate_enabled is False


def test_speed_defaults(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    for var in ("VIDEO_SPEED", "VOICE_SPEED", "TRANSLATE_CPS_BUDGET"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.load()
    assert s.video_speed == 1.0
    assert s.voice_speed == 1.0
    assert s.translate_cps_budget == 12.5


def test_speed_env_overrides(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("VIDEO_SPEED", "0.82")
    monkeypatch.setenv("VOICE_SPEED", "1.2")
    monkeypatch.setenv("TRANSLATE_CPS_BUDGET", "11")
    s = Settings.load()
    assert s.video_speed == 0.82
    assert s.voice_speed == 1.2
    assert s.translate_cps_budget == 11.0


def test_video_speed_clamped(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("VIDEO_SPEED", "0.1")
    assert Settings.load().video_speed == 0.5
    monkeypatch.setenv("VIDEO_SPEED", "1.5")   # never speeds UP the video
    assert Settings.load().video_speed == 1.0


def test_env_float_typo_falls_back(monkeypatch):
    """A typo in a float .env var must not crash GUI import (env_float)."""
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("VIDEO_SPEED", "fast")
    monkeypatch.setenv("TRANSLATE_CPS_BUDGET", "twelve")
    s = Settings.load()
    assert s.video_speed == 1.0
    assert s.translate_cps_budget == 12.5


def test_voice_speed_clamped(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("VOICE_SPEED", "5.0")
    assert Settings.load().voice_speed == 2.0
    monkeypatch.setenv("VOICE_SPEED", "0.1")
    assert Settings.load().voice_speed == 0.5


def test_whisper_beam_size_default_and_clamp(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.delenv("WHISPER_BEAM_SIZE", raising=False)
    assert Settings.load().whisper_beam_size == 5   # mặc định = thư viện
    monkeypatch.setenv("WHISPER_BEAM_SIZE", "1")
    assert Settings.load().whisper_beam_size == 1
    monkeypatch.setenv("WHISPER_BEAM_SIZE", "99")
    assert Settings.load().whisper_beam_size == 10
    monkeypatch.setenv("WHISPER_BEAM_SIZE", "0")
    assert Settings.load().whisper_beam_size == 1


def test_vieneu_workers_env_wins_over_governor(monkeypatch):
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("VIENEU_MAX_WORKERS", "8")
    assert Settings.load().vieneu_max_workers == 8


def test_vieneu_workers_adaptive_by_ram(monkeypatch):
    import autodub.config as config
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.delenv("VIENEU_MAX_WORKERS", raising=False)
    monkeypatch.setattr("autodub.config.os.cpu_count", lambda: 16)

    # RAM dư nhiều → dùng tới trần tự tính (máy khỏe không còn bị kẹp ở 3)
    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 12.0)
    config._governor_logged = True   # đã log rồi — test không cần log
    assert Settings.load().vieneu_max_workers == 6

    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 7.0)
    assert Settings.load().vieneu_max_workers == 2

    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 3.0)
    assert Settings.load().vieneu_max_workers == 1

    # Không đọc được RAM → giữ mặc định cũ (3)
    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: None)
    assert Settings.load().vieneu_max_workers == 3


def test_vieneu_workers_capped_by_cores(monkeypatch):
    import autodub.config as config
    monkeypatch.setattr("autodub.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.delenv("VIENEU_MAX_WORKERS", raising=False)
    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 32.0)
    config._governor_logged = True
    # 4 nhân → tối đa 2 tiến trình dù RAM dư
    monkeypatch.setattr("autodub.config.os.cpu_count", lambda: 4)
    assert Settings.load().vieneu_max_workers == 2

def test_effective_vieneu_workers_caps_saved_setting_by_free_ram(monkeypatch):
    from autodub.config import effective_vieneu_workers

    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 2.0)
    assert effective_vieneu_workers(7) == 1

    monkeypatch.setattr("autodub.sysinfo.available_ram_gb", lambda: 4.0)
    assert effective_vieneu_workers(7) == 2
