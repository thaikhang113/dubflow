#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[LOI] Khong tim thay python3."
  exit 1
fi

echo "VoxDub Studio - cai tat ca thanh phan"
echo "Se cai core, Whisper, VieNeu, Paraformer va Chromium."
echo

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

"$PYTHON_BIN" scripts/setup_whisper.py
"$PYTHON_BIN" scripts/setup_vieneu.py
"$PYTHON_BIN" scripts/setup_paraformer.py
"$PYTHON_BIN" scripts/setup_douyin.py

echo
echo "[OK] Cai tat ca thanh phan xong."
echo "Chay ung dung: $PYTHON_BIN -m autodub_gui"
