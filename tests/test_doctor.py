from __future__ import annotations

from autodub.config import Settings
from autodub.doctor import (
    DoctorCheck,
    _check_deepseek_ocr,
    _from_preflight,
    repair_script_for,
    run_doctor,
)
from autodub.preflight import CheckResult


def test_doctor_reports_repairable_missing_ocr_without_touching_user_data(
    tmp_path, monkeypatch
):
    settings = Settings.load(override=True)
    settings.ocr_enabled = True
    settings.ocr_venv_python = str(tmp_path / ".venv-ocr" / "python")
    settings.ocr_model_dir = str(tmp_path / "models" / "ocr")
    settings.output_dir = str(tmp_path / "projects")

    monkeypatch.setattr(
        Settings,
        "ocr_configured",
        lambda self: False,
    )

    results = run_doctor(settings)
    ocr = next(item for item in results if item.key == "ocr")

    assert isinstance(ocr, DoctorCheck)
    assert ocr.level == "fail"
    assert ocr.repairable
    assert ocr.repair_script == "scripts/setup_ocr.py"
    assert repair_script_for("ocr") == "scripts/setup_ocr.py"
    assert not (tmp_path / "projects").exists()


def test_doctor_skips_optional_deepseek_when_disabled(monkeypatch):
    settings = Settings.load(override=True)
    settings.deepseek_ocr_enabled = False

    results = run_doctor(settings)

    assert all(item.key != "deepseek_ocr" for item in results)


def test_doctor_reports_installed_deepseek_backend(tmp_path, monkeypatch):
    settings = Settings.load(override=True)
    settings.deepseek_ocr_enabled = True
    settings.deepseek_ocr_venv_python = str(tmp_path / "python")
    settings.deepseek_ocr_model_dir = str(tmp_path / "model")
    Path = __import__("pathlib").Path
    Path(settings.deepseek_ocr_venv_python).touch()
    model_dir = Path(settings.deepseek_ocr_model_dir)
    model_dir.mkdir()
    (model_dir / "installed_ok.json").write_text(
        '{"ok": true, "device_backend": "rocm"}', encoding="utf-8"
    )
    monkeypatch.setattr(
        Settings, "deepseek_ocr_configured", lambda self: True
    )

    result = _check_deepseek_ocr(settings)

    assert result.level == "ok"
    assert "ROCm" in result.message


def test_doctor_never_marks_cookie_values_or_paths_for_repair():
    settings = Settings.load(override=True)
    settings.douyin_cookies_file = "C:/private/douyin-cookies.txt"

    results = run_doctor(settings)

    assert all("private" not in item.message for item in results)
    assert all("private" not in item.advice for item in results)


def test_doctor_routes_ffmpeg_failure_to_download_worker(monkeypatch):
    monkeypatch.setattr("autodub.doctor.os.name", "nt")

    result = _from_preflight(CheckResult(
        "ffmpeg", "FFmpeg", "fail", "missing", "download it"
    ))

    assert result.repair_script == "__ffmpeg__"
