"""Cài đặt Paraformer — nhận dạng tiếng Trung chính xác hơn Whisper (chạy CPU).

Chạy 1 lần:  py scripts/setup_paraformer.py

Các bước đều resume-safe — chạy lại script sẽ bỏ qua phần đã xong:
  1. Tạo virtualenv .venv-asr
  2. pip install sherpa-onnx numpy (ONNX Runtime — KHÔNG cài torch/GPU)
  3. Tải model Paraformer-large zh (int8, ~230 MB) + silero-VAD (~2 MB)
     + model chấm câu CT-Transformer (~290 MB) về models/paraformer-zh
  4. Nhận dạng thử 1 file (smoke test) → installed_ok.json
  5. Bật ASR_ENGINE=paraformer trong .env
"""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_DIR = os.path.join(PROJECT_ROOT, ".venv-asr")
VENV_PY = os.path.join(VENV_DIR, "Scripts" if os.name == "nt" else "bin",
                       "python.exe" if os.name == "nt" else "python")
MODEL_DIR = os.path.join(PROJECT_ROOT, "models", "paraformer-zh")
MARKER = os.path.join(MODEL_DIR, "installed_ok.json")

#: Phiên bản package ASR. Chốt trần major để lần cài sau không tự nhảy sang
#: bản đổi API — numpy 3.x cũng chưa được sherpa-onnx hỗ trợ.
_ASR_SPECS = ("sherpa-onnx<2.0", "numpy<3.0")
WORKER = os.path.join(PROJECT_ROOT, "autodub", "speech",
                      "asr_paraformer_worker.py")
if not os.path.isfile(WORKER):
    # Bản đóng gói: worker nằm trong data/ (PyInstaller contents_directory).
    for _d in ("data", "_internal"):
        _candidate = os.path.join(PROJECT_ROOT, _d, "autodub", "speech",
                                  "asr_paraformer_worker.py")
        if os.path.isfile(_candidate):
            WORKER = _candidate
            break

_GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
ASR_TARBALL = f"{_GH}/asr-models/sherpa-onnx-paraformer-zh-2023-09-14.tar.bz2"
VAD_URL = f"{_GH}/asr-models/silero_vad.onnx"
PUNCT_TARBALL = (f"{_GH}/punctuation-models/"
                 "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-"
                 "2024-04-12.tar.bz2")


def log(msg: str) -> None:
    print(f"[setup-asr] {msg}", flush=True)


def _download(url: str, dest: str) -> None:
    log(f"tải {os.path.basename(dest)} ...")
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r[setup-asr]   {done >> 20}/{total >> 20} MB", end="",
                      flush=True)
    if total:
        print(flush=True)
    os.replace(tmp, dest)


def _extract_flat(tarball: str, dest_dir: str, wanted: tuple[str, ...]) -> None:
    """Extract only the wanted file names (flattened) from a tar.bz2."""
    os.makedirs(dest_dir, exist_ok=True)
    with tarfile.open(tarball, "r:bz2") as tf:
        for member in tf.getmembers():
            base = os.path.basename(member.name)
            if base in wanted and member.isfile():
                with tf.extractfile(member) as src, \
                        open(os.path.join(dest_dir, base), "wb") as out:
                    shutil.copyfileobj(src, out)


def step_venv() -> None:
    if os.path.isfile(VENV_PY):
        log("venv .venv-asr đã có — bỏ qua")
        return
    log("tạo virtualenv .venv-asr ...")
    subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)


def step_install() -> None:
    probe = subprocess.run([VENV_PY, "-c", "import sherpa_onnx, numpy"],
                           capture_output=True)
    if probe.returncode == 0:
        log("package sherpa-onnx đã cài — bỏ qua")
        return
    log("cài sherpa-onnx + numpy (ONNX, không cần GPU) ...")
    subprocess.run([VENV_PY, "-m", "pip", "install", "--quiet",
                    *_ASR_SPECS], check=True)


def step_models() -> None:
    os.makedirs(MODEL_DIR, exist_ok=True)

    if not (os.path.isfile(os.path.join(MODEL_DIR, "model.int8.onnx"))
            and os.path.isfile(os.path.join(MODEL_DIR, "tokens.txt"))):
        log("tải model Paraformer-large zh (~230 MB) ...")
        tarball = os.path.join(MODEL_DIR, "paraformer.tar.bz2")
        _download(ASR_TARBALL, tarball)
        _extract_flat(tarball, MODEL_DIR, ("model.int8.onnx", "tokens.txt"))
        os.remove(tarball)
    else:
        log("model Paraformer đã có — bỏ qua")

    vad = os.path.join(MODEL_DIR, "silero_vad.onnx")
    if not os.path.isfile(vad):
        _download(VAD_URL, vad)
    else:
        log("silero_vad.onnx đã có — bỏ qua")

    punct_dir = os.path.join(MODEL_DIR, "punct")
    if not os.path.isfile(os.path.join(punct_dir, "model.onnx")):
        try:
            log("tải model chấm câu CT-Transformer (~290 MB) ...")
            tarball = os.path.join(MODEL_DIR, "punct.tar.bz2")
            _download(PUNCT_TARBALL, tarball)
            _extract_flat(tarball, punct_dir, ("model.onnx",))
            os.remove(tarball)
        except Exception as e:  # noqa: BLE001 — chấm câu là tùy chọn
            log(f"!! không tải được model chấm câu ({e}) — bỏ qua, "
                "Paraformer vẫn chạy được (không có dấu câu)")
    else:
        log("model chấm câu đã có — bỏ qua")


def step_smoke() -> None:
    if os.path.isfile(MARKER):
        log("smoke test đã đạt — bỏ qua")
        return
    log("chạy thử nhận dạng 1 file (smoke test) ...")
    smoke_wav = os.path.join(MODEL_DIR, "smoke_test.wav")
    # 2 giây im lặng 16 kHz — chỉ cần worker chạy hết pipeline tới {"done"}.
    gen = (f"import numpy as np, wave\n"
           f"w = wave.open({smoke_wav!r}, 'wb')\n"
           f"w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)\n"
           f"w.writeframes(np.zeros(32000, dtype=np.int16).tobytes())\n"
           f"w.close()\n")
    subprocess.run([VENV_PY, "-c", gen], check=True)
    result = subprocess.run(
        [VENV_PY, WORKER, "--audio", smoke_wav, "--model-dir", MODEL_DIR],
        capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    os.remove(smoke_wav)
    lines = [l for l in (result.stdout or "").splitlines() if l.strip()]
    ok = any('"done"' in l for l in lines)
    if not ok:
        raise SystemExit(f"!! smoke test thất bại:\n{result.stdout}\n"
                         f"{(result.stderr or '')[-500:]}")
    with open(MARKER, "w", encoding="utf-8") as f:
        json.dump({"ok": True, "model": "paraformer-zh-2023-09-14",
                   "backend": "sherpa-onnx"}, f, ensure_ascii=False, indent=2)
    log("smoke test PASS")


def step_enable_env() -> None:
    env_path = os.path.join(PROJECT_ROOT, ".env")
    lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith("ASR_ENGINE="):
            lines[i] = "ASR_ENGINE=paraformer"
            found = True
            break
    if not found:
        lines.append("ASR_ENGINE=paraformer")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log("đã bật ASR_ENGINE=paraformer trong .env")


def main() -> None:
    log("Cài đặt Paraformer — nhận dạng tiếng Trung chính xác hơn (chạy CPU)")
    if not os.path.isfile(WORKER):
        raise SystemExit(f"!! không thấy worker script: {WORKER}")
    step_venv()
    step_install()
    step_models()
    step_smoke()
    step_enable_env()
    log("XONG — mở app, video tiếng Trung sẽ được nhận dạng bằng Paraformer "
        "(ngôn ngữ khác tự dùng Whisper).")


if __name__ == "__main__":
    main()
