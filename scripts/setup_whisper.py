"""Cài đặt Whisper ASR vào virtualenv riêng (.venv-whisper).

Chạy 1 lần:  py scripts/setup_whisper.py

Sau khi cài, faster-whisper + ctranslate2 chạy trong .venv-whisper qua
tiến trình con (asr_whisper_worker.py) — không cần bundle trong exe,
giảm ~112 MB kích thước bản phân phối.

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

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_DIR = os.path.join(PROJECT_ROOT, ".venv-whisper")
VENV_PY = os.path.join(VENV_DIR, "Scripts" if os.name == "nt" else "bin",
                       "python.exe" if os.name == "nt" else "python")
MODEL_DIR = os.path.join(PROJECT_ROOT, "models", "whisper")
MARKER = os.path.join(MODEL_DIR, "installed_ok.json")

#: Chốt trần major — ctranslate2 (dep của faster-whisper) thay đổi
#: API subprocess protocol giữa major version.
_WHISPER_SPEC = "faster-whisper<2.0"

# Worker script của app — dùng để smoke test
WORKER = os.path.join(PROJECT_ROOT, "autodub", "speech",
                      "asr_whisper_worker.py")
if not os.path.isfile(WORKER):
    for _d in ("data", "_internal"):
        _c = os.path.join(PROJECT_ROOT, _d, "autodub", "speech",
                          "asr_whisper_worker.py")
        if os.path.isfile(_c):
            WORKER = _c
            break


def log(msg: str) -> None:
    print(f"[setup-whisper] {msg}", flush=True)


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
    subprocess.run([VENV_PY, "-m", "pip", "install", "--quiet",
                    _WHISPER_SPEC], check=True)


def step_smoke() -> None:
    if os.path.isfile(MARKER):
        log("smoke test đã đạt — bỏ qua")
        return

    if not os.path.isfile(WORKER):
        raise SystemExit(f"!! không thấy worker script: {WORKER}")

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
            [VENV_PY, WORKER,
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

    lines = [l.strip() for l in (proc.stdout or "").splitlines() if l.strip()]
    ok = any('"done"' in l for l in lines)
    if not ok:
        raise SystemExit(
            f"!! smoke test thất bại (exit {proc.returncode}):\n"
            f"{proc.stdout[-500:]}\n{proc.stderr[-300:]}")

    with open(MARKER, "w", encoding="utf-8") as f:
        json.dump({"ok": True, "model": "medium",
                   "backend": "faster-whisper"}, f,
                  ensure_ascii=False, indent=2)
    log("smoke test PASS")


def main() -> None:
    log("Cài đặt Whisper ASR vào venv riêng — giảm ~112 MB kích thước exe")
    log(f"Model cache: {MODEL_DIR}")
    step_venv()
    step_install()
    step_smoke()
    log("XONG — Whisper chạy trong .venv-whisper (không bundle trong exe).")


if __name__ == "__main__":
    main()
