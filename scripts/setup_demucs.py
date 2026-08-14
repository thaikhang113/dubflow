"""Install Demucs and its model into a persistent virtualenv.

The installer is safe to run again: completed venv, packages, model cache and
smoke marker are reused independently.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import wave

from setup_support import retry_call

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.environ.get("DUBFLOW_DATA_DIR", PROJECT_ROOT)
VENV_DIR = os.path.join(DATA_ROOT, ".venv-demucs")
VENV_PY = os.path.join(
    VENV_DIR,
    "Scripts" if os.name == "nt" else "bin",
    "python.exe" if os.name == "nt" else "python",
)
MODEL_DIR = os.path.join(DATA_ROOT, "models", "demucs")
TORCH_HOME = os.path.join(MODEL_DIR, "torch")
MARKER = os.path.join(MODEL_DIR, "installed_ok.json")
WORKER = os.path.join(PROJECT_ROOT, "autodub", "media", "demucs_worker.py")
if not os.path.isfile(WORKER):
    for directory in ("data", "_internal"):
        candidate = os.path.join(
            PROJECT_ROOT, directory, "autodub", "media", "demucs_worker.py"
        )
        if os.path.isfile(candidate):
            WORKER = candidate
            break

DEMUCS_SPEC = "demucs>=4.0.0,<5.0.0"


def log(message: str) -> None:
    print(f"[setup-demucs] {message}", flush=True)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["TORCH_HOME"] = TORCH_HOME
    return env


def step_venv() -> None:
    if os.path.isfile(VENV_PY):
        log("venv .venv-demucs đã có — bỏ qua")
        return
    log("tạo virtualenv .venv-demucs ...")
    subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)


def step_install() -> None:
    probe = subprocess.run(
        [VENV_PY, "-c", "import demucs, soundfile"],
        capture_output=True,
    )
    if probe.returncode == 0:
        log("Demucs và soundfile đã cài — bỏ qua")
        return
    log("cài Demucs và dependency âm thanh ...")
    retry_call(
        lambda: subprocess.run(
            [
                VENV_PY,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--no-cache-dir",
                "--retries",
                "5",
                "--timeout",
                "120",
                DEMUCS_SPEC,
                "soundfile>=0.13.0,<1.0.0",
            ],
            check=True,
        ),
        attempts=3,
    )


def step_smoke() -> None:
    if os.path.isfile(MARKER):
        log("smoke test đã đạt — bỏ qua")
        return
    if not os.path.isfile(WORKER):
        raise SystemExit(f"!! không thấy worker script: {WORKER}")

    os.makedirs(MODEL_DIR, exist_ok=True)
    smoke_wav = os.path.join(MODEL_DIR, "smoke_test.wav")
    with wave.open(smoke_wav, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44_100)
        wav_file.writeframes(b"\x00\x00" * 44_100 * 2)

    log("chạy smoke test Demucs (tải htdemucs lần đầu có thể mất vài phút) ...")
    try:
        result = subprocess.run(
            [
                VENV_PY,
                WORKER,
                "--input",
                smoke_wav,
                "--vocals",
                os.path.join(MODEL_DIR, "smoke_vocals.wav"),
                "--no-vocals",
                os.path.join(MODEL_DIR, "smoke_no_vocals.wav"),
                "--model",
                "htdemucs",
                "--chunked",
            ],
            env=_env(),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    finally:
        for name in ("smoke_test.wav", "smoke_vocals.wav", "smoke_no_vocals.wav"):
            try:
                os.remove(os.path.join(MODEL_DIR, name))
            except OSError:
                pass

    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if result.returncode != 0 or not any('"ok": true' in line.lower() for line in lines):
        raise SystemExit(
            f"!! smoke test Demucs thất bại (exit {result.returncode}):\n"
            f"{(result.stdout or '')[-800:]}\n{(result.stderr or '')[-800:]}"
        )

    with open(MARKER, "w", encoding="utf-8") as marker:
        json.dump(
            {"ok": True, "model": "htdemucs", "backend": "demucs"},
            marker,
            ensure_ascii=False,
            indent=2,
        )
    log("smoke test PASS")


def main() -> None:
    log("Cài Demucs — tách giọng khỏi nhạc nền")
    step_venv()
    step_install()
    retry_call(step_smoke, attempts=3)
    log("XONG — Demucs chạy trong .venv-demucs.")


if __name__ == "__main__":
    main()
