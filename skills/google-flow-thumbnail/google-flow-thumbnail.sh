#!/usr/bin/env bash
set -Eeuo pipefail

OUTPUT_DIR="${1:-}"
[[ -n "$OUTPUT_DIR" ]] || { echo "Usage: google-flow-thumbnail.sh OUTPUT_DIR" >&2; exit 2; }
[[ -d "$OUTPUT_DIR" ]] || { echo "ERROR: Output dir không tồn tại: $OUTPUT_DIR" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/scripts/google_flow_thumbnail.py"
[[ -f "$PY_SCRIPT" ]] || { echo "ERROR: Missing $PY_SCRIPT" >&2; exit 2; }

LOG_FILE="$OUTPUT_DIR/google_flow_thumbnail.log"
{
  echo "== google-flow-thumbnail $(date '+%F %T') =="
  echo "Output dir: $OUTPUT_DIR"
  python3 "$PY_SCRIPT" "$OUTPUT_DIR"
} 2>&1 | tee -a "$LOG_FILE"
exit "${PIPESTATUS[0]}"
