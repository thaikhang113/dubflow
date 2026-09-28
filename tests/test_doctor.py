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

def test_doctor_reports_planned_vsr_fallback_without_repair(tmp_path, monkeypatch):
    settings = Settings.load(override=True)
    monkeypatch.setattr("autodub.doctor.data_root", lambda: str(tmp_path))
    (tmp_path / "backend-plan.json").write_text(
        '{"ocr_backend": "paddleocr", "vsr_backend": "fallback"}',
        encoding="utf-8",
    )

    result = __import__("autodub.doctor", fromlist=["_check_vsr"])._check_vsr(
        settings
    )

    assert result.level == "ok"
    assert "fallback" in result.message.lower()
    assert not result.repairable


def test_douyin_doctor_requires_real_import_and_chromium(tmp_path, monkeypatch):
    import autodub.doctor as doctor

    monkeypatch.setattr(doctor, "data_root", lambda: str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "pw-browsers"))
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(doctor.importlib, "import_module", lambda _name: object())
    result = doctor._check_douyin()
    assert result.level == "fail"
    assert result.repairable

    browser_root = tmp_path / "pw-browsers"
    (browser_root / "chromium-1234").mkdir(parents=True)
    result = doctor._check_douyin()
    assert result.level == "ok"


def test_douyin_doctor_catches_python_abi_import_error(tmp_path, monkeypatch):
    import autodub.doctor as doctor

    (tmp_path / "pw-browsers" / "chromium-1234").mkdir(parents=True)
    monkeypatch.setattr(doctor, "data_root", lambda: str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "pw-browsers"))
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda _name: object())

    def import_module(name):
        if name == "greenlet":
            raise ModuleNotFoundError("greenlet._greenlet")
        return object()

    monkeypatch.setattr(doctor.importlib, "import_module", import_module)
    result = doctor._check_douyin()

    assert result.level == "fail"
    assert result.repairable
