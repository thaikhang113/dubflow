"""Install optional DeepSeek-OCR in an isolated GPU virtualenv."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from setup_support import retry_call

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.environ.get("DUBFLOW_DATA_DIR", ROOT)
VENV = os.path.join(DATA_ROOT, ".venv-deepseek-ocr")
PYTHON = os.path.join(
    VENV, "Scripts" if os.name == "nt" else "bin",
    "python.exe" if os.name == "nt" else "python",
)
MODEL_DIR = os.path.join(DATA_ROOT, "models", "deepseek-ocr")
MARKER = os.path.join(MODEL_DIR, "installed_ok.json")
MODEL_NAME = "deepseek-ai/DeepSeek-OCR"
DEFAULT_ROCM_INDEX = "https://download.pytorch.org/whl/rocm6.4"
SUPPORTED_PYTHON = ((3, 10), (3, 11), (3, 12))
DEEPSEEK_PYTHON_PACKAGES = (
    "transformers>=4.51.1",
    "Pillow>=10.0",
    "safetensors>=0.5",
    "addict",
    "matplotlib",
    "requests",
)


def log(message: str) -> None:
    print(f"[setup-deepseek-ocr] {message}", flush=True)


def validate_python_version(version: tuple[int, int]) -> None:
    if version not in SUPPORTED_PYTHON:
        supported = ", ".join(
            f"{major}.{minor}" for major, minor in SUPPORTED_PYTHON)
        raise RuntimeError(
            f"DeepSeek-OCR cần Python {supported}; đang dùng "
            f"{version[0]}.{version[1]}.")


def _probe(command: list[str]) -> bool:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _has_nvidia_gpu() -> bool:
    return _probe(["nvidia-smi", "-L"])


def _has_amd_gpu(platform_name: str | None = None) -> bool:
    platform_name = platform_name or sys.platform
    if platform_name != "win32":
        try:
            result = subprocess.run(
                ["lspci"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return _probe(["rocminfo"])
        output = (result.stdout or "").lower()
        return result.returncode == 0 and (
            "amd" in output or "ati" in output or "radeon" in output
        )
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_VideoController).Name",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = (result.stdout or "").lower()
    return result.returncode == 0 and ("amd" in output or "radeon" in output)


def select_backend(
    platform_name: str,
    *,
    nvidia_available: bool,
    amd_available: bool,
) -> str:
    if nvidia_available:
        return "cuda"
    if amd_available:
        return "directml" if platform_name == "win32" else "rocm"
    raise RuntimeError(
        "DeepSeek-OCR cần NVIDIA CUDA hoặc AMD ROCm/DirectML. "
        "Máy hiện không có backend GPU tương thích; dùng PaddleOCR."
    )


def _rocm_index() -> str:
    return os.environ.get("DUBFLOW_TORCH_INDEX_URL", DEFAULT_ROCM_INDEX)

def _planned_backend() -> str:
    path = os.environ.get("DUBFLOW_BACKEND_PLAN", "")
    try:
        with open(path, encoding="utf-8") as handle:
            value = str(json.load(handle).get("ocr_backend", ""))
    except (OSError, ValueError, TypeError):
        return ""
    return {
        "deepseek-cuda": "cuda",
        "deepseek-rocm": "rocm",
        "deepseek-directml": "directml",
    }.get(value, "")


def _torch_ready(backend: str) -> bool:
    if backend == "directml":
        return _probe([
            PYTHON, "-c",
            "import torch_directml; torch_directml.device()",
        ])
    return _probe([
        PYTHON, "-c",
        "import torch; assert torch.cuda.is_available()",
    ])


def _install_torch(backend: str) -> None:
    if backend == "cuda":
        command = [
            PYTHON, "-m", "pip", "install", "--no-cache-dir",
            "torch==2.6.0", "torchvision==0.21.0", "torchaudio==2.6.0",
            "--index-url", "https://download.pytorch.org/whl/cu118",
        ]
    elif backend == "rocm":
        command = [
            PYTHON, "-m", "pip", "install", "--no-cache-dir",
            "torch", "torchvision", "torchaudio",
            "--index-url", _rocm_index(),
        ]
    else:
        command = [
            PYTHON, "-m", "pip", "install", "--no-cache-dir",
            "torch-directml",
        ]
    retry_call(lambda: subprocess.run(command, check=True), attempts=2)


def main() -> int:
    validate_python_version(sys.version_info[:2])
    backend = _planned_backend() or select_backend(
        sys.platform,
        nvidia_available=_has_nvidia_gpu(),
        amd_available=_has_amd_gpu(),
    )
    log(f"Backend GPU: {backend}")
    if not os.path.isfile(PYTHON):
        log("Tạo .venv-deepseek-ocr ...")
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)

    if not _torch_ready(backend):
        log(f"Cài PyTorch backend {backend} ...")
        _install_torch(backend)
    if not _torch_ready(backend):
        raise SystemExit(
            f"Đã cài backend {backend} nhưng không nhận được GPU. "
            "Kiểm tra driver rồi bấm Tải lại; PaddleOCR vẫn dùng được."
        )
    if not _probe([
        PYTHON, "-c",
        "import transformers, PIL, safetensors, addict, matplotlib, requests",
    ]):
        log("Cài Transformers + Pillow ...")
        retry_call(lambda: subprocess.run(
            [PYTHON, "-m", "pip", "install", "--no-cache-dir",
             *DEEPSEEK_PYTHON_PACKAGES],
            check=True,
        ), attempts=2)

    os.makedirs(MODEL_DIR, exist_ok=True)
    subprocess.run(
        [PYTHON, "-c",
         "from transformers import AutoConfig; "
         f"AutoConfig.from_pretrained({MODEL_NAME!r}, "
         f"cache_dir={MODEL_DIR!r}, trust_remote_code=True)"],
        check=True,
        timeout=900,
    )
    with open(MARKER, "w", encoding="utf-8") as handle:
        json.dump({
            "ok": True,
            "backend": "deepseek-ocr",
            "device_backend": backend,
            "model": MODEL_NAME,
        }, handle, indent=2)
    log("XONG — DeepSeek-OCR sẵn sàng, chỉ chạy khi bật fallback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
