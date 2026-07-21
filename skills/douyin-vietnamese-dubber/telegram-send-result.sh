#!/usr/bin/env bash
set -Eeuo pipefail

RESULT_DIR="${1:-}"
CHAT_ID="${TELEGRAM_CHAT_ID:-}"
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
MESSAGE_THREAD_ID="${TELEGRAM_MESSAGE_THREAD_ID:-}"
TELEGRAM_CONFIG="${TELEGRAM_CONFIG:-$HOME/.openclaw/config/channels/telegram.json}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOOGLE_DRIVE_UPLOAD="${GOOGLE_DRIVE_UPLOAD:-1}"
if [[ -z "${TELEGRAM_SEND_VIDEO_FILE:-}" ]]; then
  if [[ "$GOOGLE_DRIVE_UPLOAD" == "0" ]]; then
    TELEGRAM_SEND_VIDEO_FILE="1"
  else
    TELEGRAM_SEND_VIDEO_FILE="0"
  fi
fi
GOOGLE_DRIVE_UPLOAD_SCRIPT="${GOOGLE_DRIVE_UPLOAD_SCRIPT:-$SCRIPT_DIR/google-drive-upload-result.sh}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

load_telegram_config() {
  if [[ -n "$BOT_TOKEN" && -n "$CHAT_ID" && -n "$MESSAGE_THREAD_ID" ]]; then
    return 0
  fi
  local values
  values="$(python3 - "$TELEGRAM_CONFIG" <<'PY'
import ast, json, os, sys
path = os.path.expanduser(sys.argv[1])
try:
    raw = open(path, 'r', encoding='utf-8').read()
except Exception:
    sys.exit(1)
try:
    data = json.loads(raw)
except Exception:
    data = ast.literal_eval(raw)
telegram = data.get('telegram', data) if isinstance(data, dict) else {}
bots = telegram.get('bots') or []
token = ''
if bots and isinstance(bots[0], dict):
    token = bots[0].get('token') or ''
chat = telegram.get('chatId') or telegram.get('chat_id') or ''
thread = telegram.get('messageThreadId') or telegram.get('message_thread_id') or ''
print(token)
print(chat)
print(thread)
PY
)" || true
  if [[ -z "$BOT_TOKEN" ]]; then
    BOT_TOKEN="$(printf '%s\n' "$values" | sed -n '1p')"
  fi
  if [[ -z "$CHAT_ID" ]]; then
    CHAT_ID="$(printf '%s\n' "$values" | sed -n '2p')"
  fi
  if [[ -z "$MESSAGE_THREAD_ID" ]]; then
    MESSAGE_THREAD_ID="$(printf '%s\n' "$values" | sed -n '3p')"
  fi
}

[[ -n "$RESULT_DIR" ]] || fail "Chưa truyền thư mục kết quả."
[[ -d "$RESULT_DIR" ]] || fail "Thư mục kết quả không tồn tại: $RESULT_DIR"
[[ -f "$RESULT_DIR/final_video_vi.mp4" ]] || fail "Thiếu final_video_vi.mp4 trong $RESULT_DIR"
[[ -f "$RESULT_DIR/vietnamese.srt" ]] || fail "Thiếu vietnamese.srt trong $RESULT_DIR"

load_telegram_config
[[ -n "$BOT_TOKEN" ]] || fail "Thiếu TELEGRAM_BOT_TOKEN và không đọc được token từ $TELEGRAM_CONFIG"
[[ -n "$CHAT_ID" ]] || fail "Thiếu TELEGRAM_CHAT_ID. Hãy export TELEGRAM_CHAT_ID hoặc cấu hình chatId trong $TELEGRAM_CONFIG"

# Group "Group AI" la forum supergroup -> phai gui vao topic cu the
# (message_thread_id) de tranh TOPIC_CLOSED. MESSAGE_THREAD_ID co the rong neu
# chat la private/group thuong (khong forum) -> luc do bo qua field.
thread_args=()
if [[ -n "$MESSAGE_THREAD_ID" ]]; then
  thread_args=(-F "message_thread_id=${MESSAGE_THREAD_ID}")
fi
thread_msg_args=()
if [[ -n "$MESSAGE_THREAD_ID" ]]; then
  thread_msg_args=(-d "message_thread_id=${MESSAGE_THREAD_ID}")
fi

send_file() {
  local endpoint="$1"
  local field="$2"
  local file="$3"
  local caption="$4"
  curl -fsS -X POST "https://api.telegram.org/bot${BOT_TOKEN}/${endpoint}" \
    -F "chat_id=${CHAT_ID}" \
    "${thread_args[@]}" \
    -F "caption=${caption}" \
    -F "${field}=@${file}"
}

send_message() {
  local text="$1"
  curl -fsS -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${CHAT_ID}" \
    "${thread_msg_args[@]}" \
    --data-urlencode "text=${text}" \
    -d "disable_web_page_preview=false"
}

human_size() {
  python3 - "$1" <<'PY'
import os, sys
size = os.path.getsize(sys.argv[1])
units = ['B', 'KB', 'MB', 'GB']
value = float(size)
for unit in units:
    if value < 1024 or unit == units[-1]:
        print(f"{value:.1f} {unit}" if unit != 'B' else f"{int(value)} B")
        break
    value /= 1024
PY
}

video_file="$RESULT_DIR/final_video_vi.mp4"
video_size="$(human_size "$video_file")"
drive_link=""
drive_fail=""
if [[ "$GOOGLE_DRIVE_UPLOAD" != "0" ]]; then
  if [[ ! -x "$GOOGLE_DRIVE_UPLOAD_SCRIPT" ]]; then
    drive_fail="Bật GOOGLE_DRIVE_UPLOAD nhưng thiếu script: $GOOGLE_DRIVE_UPLOAD_SCRIPT"
  else
    echo "Đang upload final_video_vi.mp4 lên Google Drive để gửi link qua Telegram..."
    if ! drive_link="$($GOOGLE_DRIVE_UPLOAD_SCRIPT "$RESULT_DIR")"; then
      drive_fail="Upload Google Drive thất bại (script exit nonzero)"
    elif [[ -z "$drive_link" ]]; then
      drive_fail="Google Drive upload không trả link"
    fi
  fi
  job_name="$(basename "$RESULT_DIR")"
  if [[ -z "$drive_fail" ]]; then
    send_message "✅ Video đã lồng tiếng Việt xong

Job: ${job_name}
Dung lượng: ${video_size}
Google Drive: ${drive_link}

Local path: ${RESULT_DIR}" >/dev/null
  else
    # Drive fail: vẫn báo user qua Telegram (nếu có thể gửi text) thay vì fail
    # im lang truoc khi user kip biet. Sau do moi exit nonzero de pipeline thay
    # trang thai that bai upload.
    echo "WARN: ${drive_fail}" >&2
    send_message "⚠️ Video đã lồng tiếng Việt xong NHƯNG upload Google Drive LỖI

Job: ${job_name}
Dung lượng: ${video_size}
Lỗi upload: ${drive_fail}
Local path: ${RESULT_DIR}

Vào ${RESULT_DIR} lấy final_video_vi.mp4 thủ công." >/dev/null || true
    fail "${drive_fail}"
  fi
else
  echo "Bỏ qua Google Drive vì GOOGLE_DRIVE_UPLOAD=0"
fi

if [[ "$TELEGRAM_SEND_VIDEO_FILE" == "1" || ( "$GOOGLE_DRIVE_UPLOAD" == "0" && "$TELEGRAM_SEND_VIDEO_FILE" != "0" ) ]]; then
  echo "Đang gửi final_video_vi.mp4 trực tiếp về Telegram chat $CHAT_ID..."
  send_file sendVideo video "$video_file" "Video đã lồng tiếng Việt" >/dev/null
else
  echo "Không gửi MP4 trực tiếp qua Telegram (TELEGRAM_SEND_VIDEO_FILE=${TELEGRAM_SEND_VIDEO_FILE}); đã gửi link Drive nếu upload bật."
fi

echo "Đang gửi vietnamese.srt về Telegram chat $CHAT_ID..."
send_file sendDocument document "$RESULT_DIR/vietnamese.srt" "File phụ đề tiếng Việt SRT" >/dev/null

echo "HOÀN TẤT gửi Telegram"
