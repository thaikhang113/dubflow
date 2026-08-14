"""Install optional DeepSeek-OCR in its own CUDA virtualenv."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from setup_support import retry_call

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


def log(message: str) -> None:
    print(f"[setup-deepseek-ocr] {message}", flush=True)


def _has_nvidia_gpu() -> bool:
    try:
        subprocess.run(
            ["nvidia-smi", "-L"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _probe(command: list[str]) -> bool:
    return subprocess.run(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0


def main() -> int:
    if not _has_nvidia_gpu():
        raise SystemExit(
            "DeepSeek-OCR cần NVIDIA GPU. PaddleOCR vẫn dùng được trên CPU.")
    if not os.path.isfile(PYTHON):
        log("Tạo .venv-deepseek-ocr ...")
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)

    if not _probe([PYTHON, "-c", "import torch; assert torch.cuda.is_available()"]):
        log("Cài PyTorch CUDA + Transformers ...")
        retry_call(lambda: subprocess.run(
            [PYTHON, "-m", "pip", "install", "--no-cache-dir",
             "torch==2.6.0", "torchvision==0.21.0",
             "torchaudio==2.6.0",
             "--index-url", "https://download.pytorch.org/whl/cu118"],
            check=True,
        ), attempts=2)
    if not _probe([PYTHON, "-c", "import transformers, PIL, safetensors"]):
        log("Cài Transformers + Pillow ...")
        retry_call(lambda: subprocess.run(
            [PYTHON, "-m", "pip", "install", "--no-cache-dir",
             "transformers>=4.51.1", "Pillow>=10.0", "safetensors>=0.5"],
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
        json.dump({"ok": True, "backend": "deepseek-ocr",
                   "model": MODEL_NAME}, handle, indent=2)
    log("XONG — DeepSeek-OCR sẵn sàng, chỉ chạy khi bật fallback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
