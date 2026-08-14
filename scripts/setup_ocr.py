"""Install optional local PaddleOCR into .venv-ocr.

PaddlePaddle support varies by Python/platform. Failure is explicit and does
not modify the main application environment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from setup_support import retry_call

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.environ.get("DUBFLOW_DATA_DIR", ROOT)
VENV = os.path.join(DATA_ROOT, ".venv-ocr")
PYTHON = os.path.join(VENV, "Scripts" if os.name == "nt" else "bin",
                      "python.exe" if os.name == "nt" else "python")
MODEL_DIR = os.path.join(DATA_ROOT, "models", "ocr")
MARKER = os.path.join(MODEL_DIR, "installed_ok.json")
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", MODEL_DIR)


def log(message: str) -> None:
    print(f"[setup-ocr] {message}", flush=True)

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


def _supported_python() -> str:
    if (3, 10) <= sys.version_info < (3, 14):
        return sys.executable
    candidates = []
    if os.name == "nt":
        candidates.append(["py", "-3.11", "-c",
                           "import sys; print(sys.executable)"])
    candidates.extend((["uv", "python", "find", "3.11"],
                        ["python3.11"]))
    for command in candidates:
        try:
            found = subprocess.check_output(
                command, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            continue
        if found and os.path.isfile(found):
            return found
    raise SystemExit(
        "OCR cần Python 3.10–3.13; khuyên dùng Python 3.11. "
        "Cài Python 3.11 hoặc uv rồi chạy lại cai_dat_all.")


def main() -> int:
    python = _supported_python()
    if not os.path.isfile(PYTHON):
        log("Tạo .venv-ocr ...")
        subprocess.run([python, "-m", "venv", VENV], check=True)
    probe = subprocess.run([PYTHON, "-c", "import paddleocr"],
                           capture_output=True)
    gpu_available = _has_nvidia_gpu()
    cuda_probe = subprocess.run(
        [PYTHON, "-c",
         "import paddle; print(int(paddle.is_compiled_with_cuda()))"],
        capture_output=True,
        text=True,
    )
    paddle_has_cuda = cuda_probe.returncode == 0 and "1" in cuda_probe.stdout
    if probe.returncode != 0 or (gpu_available and not paddle_has_cuda):
        log("Cài PaddlePaddle + PaddleOCR ...")
        if gpu_available:
            gpu_index = os.environ.get(
                "PADDLE_CUDA_INDEX_URL",
                "https://www.paddlepaddle.org.cn/packages/stable/cu118/",
            )
            log("Phát hiện NVIDIA GPU — thử cài PaddlePaddle GPU ...")
            try:
                retry_call(lambda: subprocess.run(
                    [PYTHON, "-m", "pip", "install", "--no-cache-dir",
                     "paddlepaddle-gpu", "-i", gpu_index],
                    check=True,
                ), attempts=2)
            except subprocess.CalledProcessError:
                log("Bản GPU không tương thích — chuyển sang PaddlePaddle CPU")
                retry_call(lambda: subprocess.run(
                    [PYTHON, "-m", "pip", "install", "--no-cache-dir",
                     "paddlepaddle"],
                    check=True,
                ), attempts=2)
        else:
            retry_call(lambda: subprocess.run(
                [PYTHON, "-m", "pip", "install", "--no-cache-dir",
                 "paddlepaddle"],
                check=True,
            ), attempts=2)
        retry_call(lambda: subprocess.run(
            [PYTHON, "-m", "pip", "install", "--no-cache-dir", "paddleocr"],
            check=True,
        ), attempts=2)
    os.makedirs(MODEL_DIR, exist_ok=True)
    subprocess.run([PYTHON, "-c", "from paddleocr import PaddleOCR; "
                    "PaddleOCR(lang='ch')"], check=True, timeout=900)
    with open(MARKER, "w", encoding="utf-8") as f:
        json.dump({"ok": True, "backend": "paddleocr"}, f, indent=2)
    log("Smoke test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
