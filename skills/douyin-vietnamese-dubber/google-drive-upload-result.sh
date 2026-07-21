#!/usr/bin/env bash
set -Eeuo pipefail

RESULT_DIR="${1:-}"
RCLONE_BIN="${RCLONE_BIN:-/home/haonguyen/.local/bin/rclone}"
RCLONE_REMOTE="${RCLONE_REMOTE:-openclaw-gdrive}"
RCLONE_DRIVE_FOLDER="${RCLONE_DRIVE_FOLDER:-OpenClaw/Douyin Vietsub}"
GOOGLE_DRIVE_REUPLOAD="${GOOGLE_DRIVE_REUPLOAD:-0}"
GOOGLE_DRIVE_PUBLIC_LINK="${GOOGLE_DRIVE_PUBLIC_LINK:-1}"
STATUS_FILE=""
LOG_FILE=""
LINK_FILE=""

fail() {
  echo "ERROR: $*" >&2
  write_status "error" "$*" "" || true
  exit 1
}

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

write_status() {
  local status="$1"
  local message="$2"
  local link="${3:-}"
  local uploaded_path="${4:-}"
  [[ -n "$STATUS_FILE" ]] || return 0
  python3 - "$STATUS_FILE" "$status" "$message" "$link" "$uploaded_path" "$RESULT_DIR" "$RCLONE_REMOTE" "$RCLONE_DRIVE_FOLDER" <<'PY'
import json, os, sys, time
path, status, message, link, uploaded_path, result_dir, remote, folder = sys.argv[1:]
data = {
    "status": status,
    "message": message,
    "link": link,
    "uploaded_path": uploaded_path,
    "result_dir": result_dir,
    "remote": remote,
    "folder": folder,
    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
}

[[ -n "$RESULT_DIR" ]] || { echo "Usage: google-drive-upload-result.sh RESULT_DIR" >&2; exit 2; }
[[ -d "$RESULT_DIR" ]] || { echo "ERROR: Thư mục kết quả không tồn tại: $RESULT_DIR" >&2; exit 2; }
RESULT_DIR="$(cd "$RESULT_DIR" && pwd)"
STATUS_FILE="$RESULT_DIR/google_drive_upload_status.json"
LOG_FILE="$RESULT_DIR/google_drive_upload.log"
LINK_FILE="$RESULT_DIR/google_drive_video_link.txt"
VIDEO_FILE="$RESULT_DIR/final_video_vi.mp4"
[[ -f "$VIDEO_FILE" ]] || fail "Thiếu final_video_vi.mp4 trong $RESULT_DIR"
[[ -x "$RCLONE_BIN" ]] || fail "Không tìm thấy rclone executable tại $RCLONE_BIN"

if [[ -s "$LINK_FILE" && "$GOOGLE_DRIVE_REUPLOAD" != "1" ]]; then
  link="$(head -n 1 "$LINK_FILE" | tr -d '\r')"
  [[ -n "$link" ]] || fail "File cache link rỗng: $LINK_FILE"
  write_status "cached" "Dùng lại Google Drive link cache" "$link" ""
  echo "$link"
  exit 0
fi

job_name="$(basename "$RESULT_DIR")"
remote_dir="${RCLONE_REMOTE}:${RCLONE_DRIVE_FOLDER}/${job_name}"
remote_file="${remote_dir}/final_video_vi.mp4"

{
  echo "== google-drive-upload $(date '+%F %T') =="
  echo "Result dir: $RESULT_DIR"
  echo "Video: $VIDEO_FILE"
  echo "Remote dir: $remote_dir"
  "$RCLONE_BIN" version | head -20
} >> "$LOG_FILE" 2>&1

write_status "uploading" "Đang upload video lên Google Drive" "" "$remote_file"
"$RCLONE_BIN" copy "$VIDEO_FILE" "$remote_dir" --progress --drive-chunk-size "${RCLONE_DRIVE_CHUNK_SIZE:-64M}" >> "$LOG_FILE" 2>&1 || fail "rclone copy thất bại, xem $LOG_FILE"

if [[ "$GOOGLE_DRIVE_PUBLIC_LINK" == "1" ]]; then
  write_status "linking" "Đang tạo link Google Drive công khai" "" "$remote_file"
else
  write_status "linking" "Đang tạo link Google Drive" "" "$remote_file"
fi
link="$({ "$RCLONE_BIN" link "$remote_file" 2>>"$LOG_FILE" || true; } | tail -n 1 | tr -d '\r')"
[[ -n "$link" ]] || fail "rclone link không trả link, xem $LOG_FILE"
printf '%s\n' "$link" > "$LINK_FILE"
write_status "done" "Upload Google Drive hoàn tất" "$link" "$remote_file"
echo "$link"
