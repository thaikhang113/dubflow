#!/usr/bin/env bash
set -Eeuo pipefail

WHISPER_DIR="${WHISPER_DIR:-$HOME/whisper.cpp}"
WHISPER_MODEL_NAME="${WHISPER_MODEL_NAME:-small}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Thiếu lệnh '$1'"
}

install_system_deps() {
  if command -v ffmpeg >/dev/null 2>&1 && command -v edge-tts >/dev/null 2>&1; then
    echo "OK ffmpeg và edge-tts đã có"
    return 0
  fi
  if [[ "$(id -u)" -ne 0 ]]; then
    fail "Thiếu ffmpeg/edge-tts. Chạy bằng root trong container hoặc cài thủ công: apt-get install -y ffmpeg && pip3 install edge-tts --break-system-packages"
  fi
  apt-get update
  apt-get install -y ffmpeg git cmake build-essential curl python3-pip
  pip3 install edge-tts --break-system-packages
}

install_whisper() {
  if [[ -x "$WHISPER_DIR/build/bin/whisper-cli" && -f "$WHISPER_DIR/models/ggml-${WHISPER_MODEL_NAME}.bin" ]]; then
    echo "OK whisper-cli và model đã có trong $WHISPER_DIR"
    return 0
  fi
  need_cmd git
  need_cmd cmake
  need_cmd curl
  mkdir -p "$(dirname "$WHISPER_DIR")"
  if [[ ! -d "$WHISPER_DIR/.git" ]]; then
    git clone https://github.com/ggerganov/whisper.cpp "$WHISPER_DIR"
  fi
  cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build"
  cmake --build "$WHISPER_DIR/build" -j"$(nproc 2>/dev/null || echo 2)"
  bash "$WHISPER_DIR/models/download-ggml-model.sh" "$WHISPER_MODEL_NAME"
}

install_system_deps
install_whisper

echo "HOÀN TẤT setup runtime. Kiểm tra lại: bash run.sh --doctor"
