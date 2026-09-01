"""Cài đặt Whisper ASR vào virtualenv riêng (.venv-whisper).

Chạy 1 lần:  py scripts/setup_whisper.py

Sau khi cài, faster-whisper + ctranslate2 chạy trong .venv-whisper qua
tiến trình con. Worker được kèm trong bản phân phối để wizard luôn tìm được
đúng file, còn model và virtualenv vẫn nằm ngoài exe.

Các bước đều resume-safe — chạy lại sẽ bỏ qua phần đã xong:
  1. Tạo virtualenv .venv-whisper (Python hiện tại)
  2. pip install faster-whisper<2.0
  3. Tải model Whisper về models/whisper/ (smoke test kéo về lần đầu)
  4. Smoke test: nhận dạng 1 file 2 giây → installed_ok.json
"""
import json
import os
import subprocess
import sys
import wave

from setup_support import find_bundled_worker, retry_call

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.environ.get("DUBFLOW_DATA_DIR", PROJECT_ROOT)
VENV_DIR = os.path.join(DATA_ROOT, ".venv-whisper")
VENV_PY = os.path.join(VENV_DIR, "Scripts" if os.name == "nt" else "bin",
                       "python.exe" if os.name == "nt" else "python")
MODEL_DIR = os.path.join(DATA_ROOT, "models", "whisper")
MARKER = os.path.join(MODEL_DIR, "installed_ok.json")

#: Chốt trần major — ctranslate2 (dep của faster-whisper) thay đổi
#: API subprocess protocol giữa major version.
_WHISPER_SPEC = "faster-whisper<2.0"

# Worker script của app — dùng để smoke test
def _find_worker() -> str:
    return find_bundled_worker(
        os.path.join("autodub", "speech", "asr_whisper_worker.py"),
        PROJECT_ROOT,
    )


def log(msg: str) -> None:
    print(f"[setup-whisper] {msg}", flush=True)


def _detected_backend(stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}".lower()
    if "rocm" in text:
        return "rocm"
    if "trên gpu" in text or "on gpu" in text:
        return "cuda"
    return "cpu"


def step_venv() -> None:
    if os.path.isfile(VENV_PY):
        log("venv .venv-whisper đã có — bỏ qua")
        return
    log("tạo virtualenv .venv-whisper ...")
    subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)


def step_install() -> None:
    probe = subprocess.run([VENV_PY, "-c", "import faster_whisper"],
                           capture_output=True)
    if probe.returncode == 0:
        log("faster-whisper đã cài — bỏ qua")
        return
    log("cài faster-whisper (ctranslate2, CPU/GPU) ...")
    retry_call(
        lambda: subprocess.run(
            [VENV_PY, "-m", "pip", "install", "--quiet",
             "--no-cache-dir", "--retries", "5", "--timeout", "120",
             _WHISPER_SPEC],
            check=True,
        ),
        attempts=3,
    )


def step_smoke() -> None:
    worker = _find_worker()
    if not worker:
        raise SystemExit(
            "!! không thấy worker script trong bản cài. "
            "Hãy tải lại bản DubFlow mới hoặc build lại.")
    if os.path.isfile(MARKER):
        log("smoke test đã đạt — bỏ qua")
        return

    os.makedirs(MODEL_DIR, exist_ok=True)

    # Tạo 2 giây im lặng 16 kHz để test pipeline (model tự tải về lần đầu)
    smoke_wav = os.path.join(MODEL_DIR, "smoke_test.wav")
    with wave.open(smoke_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 32000)

    log("chạy smoke test (tải model lần đầu có thể mất vài phút) ...")
    try:
        proc = subprocess.run(
            [VENV_PY, worker,
             "--audio",     smoke_wav,
             "--model",     "medium",      # model nhỏ cho smoke test nhanh
             "--language",  "zh",
             "--model-dir", MODEL_DIR],
            input="",        # stdin rỗng — worker dùng arg --audio trực tiếp
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    finally:
        try:
            os.remove(smoke_wav)
        except OSError:
            pass

    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    ok = any('"done"' in line for line in lines)
    if not ok:
        raise SystemExit(
            f"!! smoke test thất bại (exit {proc.returncode}):\n"
            f"{proc.stdout[-500:]}\n{proc.stderr[-300:]}")

    with open(MARKER, "w", encoding="utf-8") as f:
        json.dump({"ok": True, "model": "medium",
                   "backend": "faster-whisper",
                   "device_backend": _detected_backend(
                       proc.stdout or "", proc.stderr or "")}, f,
                  ensure_ascii=False, indent=2)
    log("smoke test PASS")


def main() -> None:
    log("Cài đặt Whisper ASR vào venv riêng — giảm ~112 MB kích thước exe")
    log(f"Model cache: {MODEL_DIR}")
    step_venv()
    step_install()
    retry_call(step_smoke, attempts=3)
    log("XONG — Whisper chạy trong .venv-whisper (không bundle trong exe).")


if __name__ == "__main__":
    main()
