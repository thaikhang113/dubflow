#!/usr/bin/env bash
set -Eeuo pipefail

runtime_dirs=(
  /data/data
  /data/secrets
  /data/jobs
  /data/output
  /data/models
  /data/browser
)
mkdir -p "${runtime_dirs[@]}"

whisper_root=/data/models/whisper.cpp
mkdir -p "$whisper_root/build/bin" "$whisper_root/models"
chown app:app "${runtime_dirs[@]}" "$whisper_root" "$whisper_root/build" \
  "$whisper_root/build/bin" "$whisper_root/models"
if [[ ! -x "$whisper_root/build/bin/whisper-cli" ]]; then
  cp /opt/whisper.cpp/build/bin/whisper-cli "$whisper_root/build/bin/whisper-cli"
  chown app:app "$whisper_root/build/bin/whisper-cli"
fi
if [[ ! -s "$whisper_root/models/ggml-small.bin" ]]; then
  gosu app bash /opt/whisper.cpp/models/download-ggml-model.sh small "$whisper_root/models"
fi

gosu app chromium \
  --headless=new \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir=/data/browser \
  about:blank \
  >/data/data/chromium.log 2>&1 &

gosu app python - <<'PY'
import json
from web_tool.config import Settings
from web_tool.integrations import runtime_doctor

print(json.dumps(runtime_doctor(Settings.from_env(), []), ensure_ascii=False))
PY

exec gosu app uvicorn web_tool.app:create_app \
  --factory \
  --host "${TOOL_BIND_HOST:-0.0.0.0}" \
  --port "${TOOL_BIND_PORT:-18793}"
