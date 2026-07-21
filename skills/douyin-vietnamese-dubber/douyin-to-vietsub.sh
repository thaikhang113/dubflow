#!/usr/bin/env bash
set -Eeuo pipefail

QUERY_OR_URL="${1:-}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="${DOUYIN_VIDEOS_DIR:-$HOME/video douyin vietsub}"
OPENCLAW_CONTAINER="${OPENCLAW_CONTAINER:-}"
DOUYIN_STEALTH_LOCAL_PATH="${DOUYIN_STEALTH_LOCAL_PATH:-$HOME/.openclaw/workspace/skills/douyin-stealth/scripts/fetch_douyin_v2.py}"
DOUYIN_STEALTH_CONTAINER_PATH="${DOUYIN_STEALTH_CONTAINER_PATH:-/home/node/.openclaw/workspace/skills/douyin-stealth/scripts/fetch_douyin_v2.py}"
SEARCH_TIMEOUT_SECONDS="${DOUYIN_SEARCH_TIMEOUT_SECONDS:-180}"
LOG_DIR="$BASE_DIR/douyin-fetch"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/douyin-fetch-$(date +%Y%m%d-%H%M%S).log"

exec > >(tee -a "$LOG") 2>&1

fail() {
  echo "ERROR: $*" >&2
  echo "Log: $LOG" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Thiếu lệnh '$1'"
}

extract_first_link() {
  python3 - <<'PY'
import re, sys
text = sys.stdin.read()
links = re.findall(r'https?://[^\s|]+', text)
for link in links:
    if 'douyin.com' in link or 'iesdouyin.com' in link:
        print(link.strip(), end='')
        sys.exit(0)
sys.exit(1)
PY
}

classify_search_failure() {
  local search_output="$1"
  if grep -q 'CAPTCHA_WAIT\|QR_LOGIN\|NOT_LOGGED_IN\|CDP_OFFLINE' "$search_output" 2>/dev/null; then
    fail "Douyin đang yêu cầu login/captcha/chrome handoff hoặc chưa sẵn sàng. Xem $search_output để xử lý thủ công."
  fi
  if grep -q 'EXTRACTOR_CARD_FOUND_URL_FAILED\|EXTRACTOR_FAILED' "$search_output" 2>/dev/null; then
    fail "douyin-stealth đã vào được Douyin nhưng chưa trích xuất được link video từ giao diện hiện tại. Xem $search_output"
  fi
  if grep -q 'SEARCH_TIMEOUT' "$search_output" 2>/dev/null; then
    fail "douyin-stealth tìm kiếm quá lâu và đã timeout an toàn. Xem $search_output"
  fi
  fail "douyin-stealth tìm kiếm thất bại. Xem $search_output"
}

run_local_search() {
  local keyword="$1"
  local search_output="$2"
  [[ -f "$DOUYIN_STEALTH_LOCAL_PATH" ]] || return 127
  echo "Đang dùng douyin-stealth local path: $DOUYIN_STEALTH_LOCAL_PATH"
  timeout "$SEARCH_TIMEOUT_SECONDS" python3 "$DOUYIN_STEALTH_LOCAL_PATH" search "$keyword" | tee "$search_output"
}

run_docker_search() {
  local keyword="$1"
  local search_output="$2"
  command -v docker >/dev/null 2>&1 || return 127
  if [[ -z "$OPENCLAW_CONTAINER" ]]; then
    OPENCLAW_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^openclaw.*gateway|gateway.*openclaw' | head -n 1 || true)"
  fi
  [[ -n "$OPENCLAW_CONTAINER" ]] || return 127
  echo "Đang fallback sang douyin-stealth trong container: $OPENCLAW_CONTAINER"
  timeout "$SEARCH_TIMEOUT_SECONDS" docker exec "$OPENCLAW_CONTAINER" python3 "$DOUYIN_STEALTH_CONTAINER_PATH" search "$keyword" | tee "$search_output"
}

[[ -n "$QUERY_OR_URL" ]] || fail "Chưa truyền link Douyin hoặc chủ đề tìm kiếm."
need_cmd python3
need_cmd yt-dlp
need_cmd timeout

if [[ "$QUERY_OR_URL" =~ ^https?:// ]]; then
  VIDEO_URL="$QUERY_OR_URL"
  echo "Đã nhận link Douyin trực tiếp: $VIDEO_URL"
else
  SEARCH_OUTPUT="$LOG_DIR/search-$(date +%Y%m%d-%H%M%S).txt"
  SEARCH_OK=0

  set +e
  run_local_search "$QUERY_OR_URL" "$SEARCH_OUTPUT"
  local_status=$?
  set -e
  if [[ "$local_status" -eq 0 ]]; then
    SEARCH_OK=1
    echo "Search flow hiện tại: local path"
  elif [[ "$local_status" -eq 124 ]]; then
    fail "douyin-stealth local path quá ${SEARCH_TIMEOUT_SECONDS}s không trả kết quả; dừng an toàn. Có thể Chrome handoff/CDP đang treo hoặc Douyin chặn. Xem $SEARCH_OUTPUT"
  elif [[ "$local_status" -ne 127 ]]; then
    classify_search_failure "$SEARCH_OUTPUT"
  fi

  if [[ "$SEARCH_OK" -eq 0 ]]; then
    set +e
    run_docker_search "$QUERY_OR_URL" "$SEARCH_OUTPUT"
    docker_status=$?
    set -e
    if [[ "$docker_status" -eq 0 ]]; then
      SEARCH_OK=1
      echo "Search flow hiện tại: docker fallback"
    elif [[ "$docker_status" -eq 124 ]]; then
      fail "douyin-stealth docker fallback quá ${SEARCH_TIMEOUT_SECONDS}s không trả kết quả; dừng an toàn. Có thể Chrome handoff/CDP đang treo hoặc Douyin chặn. Xem $SEARCH_OUTPUT"
    elif [[ "$docker_status" -ne 127 ]]; then
      classify_search_failure "$SEARCH_OUTPUT"
    fi
  fi

  [[ "$SEARCH_OK" -eq 1 ]] || fail "Keyword search chưa có backend phù hợp: local path không khả dụng và Docker fallback cũng không khả dụng. Hãy kiểm tra douyin-stealth runtime hoặc dùng link Douyin trực tiếp."
  VIDEO_URL="$(extract_first_link < "$SEARCH_OUTPUT")" || fail "Không tìm thấy link Douyin trong kết quả douyin-stealth. Xem $SEARCH_OUTPUT"
  echo "Chọn video đầu tiên: $VIDEO_URL"
fi

DOWNLOAD_DIR="$LOG_DIR/download-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DOWNLOAD_DIR"
VIDEO_FILE="$DOWNLOAD_DIR/input.%(ext)s"

echo "Đang tải video Douyin bằng yt-dlp..."
if ! yt-dlp -f 'bv*+ba/best' --merge-output-format mp4 --no-playlist -o "$VIDEO_FILE" "$VIDEO_URL"; then
  fail "Không tải được video Douyin. Có thể Douyin đang chặn IP/cookie/captcha; script đã dừng an toàn."
fi

DOWNLOADED="$(find "$DOWNLOAD_DIR" -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.mkv' -o -name '*.webm' \) | head -n 1)"
[[ -n "$DOWNLOADED" && -s "$DOWNLOADED" ]] || fail "yt-dlp chạy xong nhưng không thấy file video tải về."

echo "Đã tải video: $DOWNLOADED"
echo "Đang chạy pipeline vietsub/lồng tiếng..."
bash "$SKILL_DIR/run.sh" "$DOWNLOADED"
