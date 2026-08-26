import pytest
import sys
import os
import subprocess
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_installer_selects_cuda_for_nvidia():
    from scripts import setup_deepseek_ocr

    assert setup_deepseek_ocr.select_backend(
        "win32", nvidia_available=True, amd_available=False
    ) == "cuda"


def test_installer_selects_rocm_for_linux_amd():
    from scripts import setup_deepseek_ocr

    assert setup_deepseek_ocr.select_backend(
        "linux", nvidia_available=False, amd_available=True
    ) == "rocm"


def test_linux_amd_detection_does_not_require_rocm_preinstalled(monkeypatch):
    from scripts import setup_deepseek_ocr

    class Result:
        returncode = 0
        stdout = "03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Radeon RX 6600"

    monkeypatch.setattr(setup_deepseek_ocr.subprocess, "run", lambda *_a, **_k: Result())

    assert setup_deepseek_ocr._has_amd_gpu("linux")


def test_installer_selects_directml_for_windows_amd():
    from scripts import setup_deepseek_ocr

    assert setup_deepseek_ocr.select_backend(
        "win32", nvidia_available=False, amd_available=True
    ) == "directml"


def test_installer_rejects_cpu_without_supported_backend():
    from scripts import setup_deepseek_ocr

    with pytest.raises(RuntimeError, match="NVIDIA CUDA|AMD ROCm|DirectML"):
        setup_deepseek_ocr.select_backend(
            "linux", nvidia_available=False, amd_available=False
        )


def test_installer_rejects_unsupported_python():
    from scripts import setup_deepseek_ocr

    with pytest.raises(RuntimeError, match="3.10"):
        setup_deepseek_ocr.validate_python_version((3, 13))


def test_installer_log_survives_windows_cp1252_console():
    env = dict(
        os.environ,
        PYTHONIOENCODING="cp1252",
        PYTHONPATH=str(Path(__file__).resolve().parents[1] / "scripts"),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts import setup_deepseek_ocr; "
            "setup_deepseek_ocr.log('Tạo môi trường')",
        ],
        capture_output=True,
        env=env,
    )

    assert result.returncode == 0
    assert "Tạo môi trường" in result.stdout.decode("utf-8")


def test_worker_uses_eager_float16_for_rocm():
    from autodub.media.deepseek_ocr_worker import runtime_options

    assert runtime_options("rocm", cuda_ready=True, bf16_ready=True) == (
        "cuda", "float16", "eager"
    )


def test_worker_uses_directml_without_cuda():
    from autodub.media.deepseek_ocr_worker import runtime_options

    assert runtime_options("directml", cuda_ready=False, bf16_ready=False) == (
        "directml", "float16", "eager"
    )


def test_rocm_runtime_uses_float16_eager_and_reports_backend():
    from autodub.media import deepseek_ocr_worker

    assert deepseek_ocr_worker.runtime_backend("rocm") == "rocm"
    assert deepseek_ocr_worker.runtime_options(
        "rocm", cuda_ready=True, bf16_ready=True
    ) == ("cuda", "float16", "eager")


def test_worker_rejects_unavailable_gpu_backend():
    from autodub.media.deepseek_ocr_worker import runtime_options

    with pytest.raises(RuntimeError, match="GPU backend"):
        runtime_options("rocm", cuda_ready=False, bf16_ready=False)

def test_amd_gpu_prefers_deepseek_when_configured():
    from autodub.media.ocr import preferred_ocr_backend

    class Settings:
        ocr_backend = "hybrid"
        deepseek_ocr_enabled = True

        @staticmethod
        def deepseek_ocr_configured():
            return True

    class GPU:
        vendor = "amd"
        compute_available = True
        compute_backend = "rocm"

    assert preferred_ocr_backend(Settings(), GPU()) == "deepseek"

def test_amd_gpu_falls_back_to_paddle_when_deepseek_unavailable():
    from autodub.media.ocr import preferred_ocr_backend

    class Settings:
        ocr_backend = "hybrid"
        deepseek_ocr_enabled = False

        @staticmethod
        def deepseek_ocr_configured():
            return False

    class GPU:
        vendor = "amd"
        compute_available = True
        compute_backend = "directml"

    assert preferred_ocr_backend(Settings(), GPU()) == "paddle"

def test_hardware_plan_activates_installed_deepseek(
    monkeypatch, tmp_path
):
    from autodub.media.ocr import preferred_ocr_backend

    plan = tmp_path / "backend-plan.json"
    plan.write_text('{"ocr_backend": "deepseek-rocm"}', encoding="utf-8")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "installed_ok.json").write_text("{}", encoding="utf-8")
    python = tmp_path / "python"
    python.touch()
    monkeypatch.setenv("DUBFLOW_BACKEND_PLAN", str(plan))

    class Settings:
        ocr_backend = "hybrid"
        deepseek_ocr_enabled = False

        @staticmethod
        def deepseek_ocr_configured():
            return False

        @staticmethod
        def deepseek_ocr_venv_python_path():
            return str(python)

        @staticmethod
        def deepseek_ocr_model_dir_path():
            return str(model_dir)

    assert preferred_ocr_backend(Settings()) == "deepseek"
