#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[LOI] Khong tim thay python3."
  exit 1
fi

echo "DubFlow - cai tat ca thanh phan"
echo "Se cai runtime .venv, Demucs, Whisper, VieNeu, Paraformer, PaddleOCR va Chromium."
echo

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

VENV_PY="$PWD/.venv/bin/python"
if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
  "$VENV_PY" -m ensurepip --upgrade
fi
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

"$PYTHON_BIN" scripts/setup_whisper.py
"$PYTHON_BIN" scripts/setup_vieneu.py
"$PYTHON_BIN" scripts/setup_paraformer.py
"$PYTHON_BIN" scripts/setup_ocr.py || echo "[CANH BAO] OCR khong cai duoc - app van chay voi blur thu cong"
"$PYTHON_BIN" scripts/setup_douyin.py
"$PYTHON_BIN" scripts/setup_demucs.py

echo
echo "[OK] Cai tat ca thanh phan xong."
echo "Chay ung dung: ./chay_app.sh"
