#!/usr/bin/env bash
set -Eeuo pipefail

INPUT="${1:-}"
KOKORO_DEFAULT_VOICE="${KOKORO_DEFAULT_VOICE:-mai_linh}"
VOICE_REGISTRY_PY="${VOICE_REGISTRY_PY:-/home/haonguyen/.openclaw/workspace/skills/douyin-vietnamese-dubber/voice_registry.py}"
AI33_MAI_PHUONG_VOICE_ID="${AI33_MAI_PHUONG_VOICE_ID:-vbee_hn_female_maiphuong_vdts_48k-fhg}"
AI33_PHANH_VOICE_ID="${AI33_PHANH_VOICE_ID:-elevenlabs_UuMSQK8FdLwaY2M8ZAnh}"
AI33_DEFAULT_VOICE_ID="${AI33_DEFAULT_VOICE_ID:-$AI33_MAI_PHUONG_VOICE_ID}"
if [[ -f "$VOICE_REGISTRY_PY" ]]; then
  if _voice_registry_default="$(python3 "$VOICE_REGISTRY_PY" default 2>/dev/null)" && [[ -n "$_voice_registry_default" ]]; then
    OPENCLAW_DEFAULT_TTS_VOICE="$_voice_registry_default"
  fi
fi
OPENCLAW_DEFAULT_TTS_VOICE="${OPENCLAW_DEFAULT_TTS_VOICE:-ai33:${AI33_DEFAULT_VOICE_ID}}"
if [[ "$OPENCLAW_DEFAULT_TTS_VOICE" == "ai33:${AI33_PHANH_VOICE_ID}" && "${OPENCLAW_KEEP_LEGACY_PHANH_DEFAULT:-0}" != "1" && ! -f "$VOICE_REGISTRY_PY" ]]; then
  OPENCLAW_DEFAULT_TTS_VOICE="ai33:${AI33_MAI_PHUONG_VOICE_ID}"
fi
VOICE_PRESET="${2:-${EDGE_TTS_VOICE_PRESET:-${DOUYIN_TTS_VOICE_PRESET:-}}}"
LIMIT="${3:-10}"
BASE_ROOT="${BILIBILI_OUTPUT_ROOT:-/mnt/hdd500/video douyin vietsub}"
BILI_BASE="$BASE_ROOT/Bilibili"
CACHE_DIR="$BILI_BASE/source-cache"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDP_HELPER="$SKILL_DIR/scripts/bilibili_cdp.py"
DOUYIN_PIPELINE="${DOUYIN_PIPELINE:-/home/haonguyen/.openclaw/workspace/skills/douyin-vietnamese-dubber/run.sh}"
CDP_URL="${BILIBILI_CDP_URL:-http://127.0.0.1:9222}"
LATEST_OUTPUT="$BILI_BASE/LATEST_OUTPUT_DIR.txt"
LATEST_SOURCE="$BILI_BASE/LATEST_SOURCE_URL.txt"
BILIBILI_BRANDING="${BILIBILI_BRANDING:-0}"
BILIBILI_BRAND_INCLUDE_INTRO="${BILIBILI_BRAND_INCLUDE_INTRO:-0}"
BILIBILI_BRAND_INCLUDE_OUTRO="${BILIBILI_BRAND_INCLUDE_OUTRO:-0}"
SINGLE_JOB_BRAND_SCRIPT="${SINGLE_JOB_BRAND_SCRIPT:-/home/haonguyen/.openclaw/workspace/skills/series-compilation-orchestrator/scripts/single_job_brand.py}"
BRAND_ASSETS_JSON="${BRAND_ASSETS_JSON:-/home/haonguyen/.openclaw/workspace/skills/series-compilation-orchestrator/assets/brand-assets.json}"

fail() { echo "ERROR: $*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || fail "Thiếu lệnh: $1"; }

emit_latest_job_failure() {
  local exit_code="$1"
  local output_dir status_file
  [[ -s "$LATEST_OUTPUT" ]] || return 0
  output_dir="$(head -n 1 "$LATEST_OUTPUT" 2>/dev/null || true)"
  status_file="$output_dir/job_status.json"
  [[ -s "$status_file" ]] || return 0
  python3 - "$status_file" "$output_dir" "$exit_code" <<'PY' >&2 || true
import json, sys
from pathlib import Path

try:
    status = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    status = {}
allowed = (
    "state", "phase", "progress_percent", "label", "error_code",
    "error_message", "reason", "retry_action", "artifacts",
)
payload = {key: status[key] for key in allowed if key in status}
payload["output_dir"] = sys.argv[2]
payload["exit_code"] = int(sys.argv[3])
print("OPENCLAW_JOB_STATUS_JSON=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
PY
}

validate_branding_flags() {
  case "$BILIBILI_BRANDING" in 0|1) ;; *) fail "BILIBILI_BRANDING chỉ nhận 0 hoặc 1" ;; esac
  case "$BILIBILI_BRAND_INCLUDE_INTRO" in 0|1) ;; *) fail "BILIBILI_BRAND_INCLUDE_INTRO chỉ nhận 0 hoặc 1" ;; esac
  case "$BILIBILI_BRAND_INCLUDE_OUTRO" in 0|1) ;; *) fail "BILIBILI_BRAND_INCLUDE_OUTRO chỉ nhận 0 hoặc 1" ;; esac
  if [[ "$BILIBILI_BRANDING" != "1" && ( "$BILIBILI_BRAND_INCLUDE_INTRO" == "1" || "$BILIBILI_BRAND_INCLUDE_OUTRO" == "1" ) ]]; then
    fail "intro/outro chỉ dùng cùng BILIBILI_BRANDING=1"
  fi
}

# edge-tts (pip --user) nằm ở ~/.local/bin. Đảm bảo wrapper host-runner và
# pipeline con (douyin-vietnamese-dubber) đều thấy được edge-tts kể cả khi env
# gọi tới wrapper này không có ~/.local/bin trong PATH (vd. resume dashboard).
if [[ -d "$HOME/.local/bin" && ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  export PATH="$HOME/.local/bin:$PATH"
fi
EDGE_TTS_BIN="${EDGE_TTS_BIN:-}"
if [[ -z "$EDGE_TTS_BIN" ]]; then
  if command -v edge-tts >/dev/null 2>&1; then
    EDGE_TTS_BIN="$(command -v edge-tts)"
  elif [[ -x "$HOME/.local/bin/edge-tts" ]]; then
    EDGE_TTS_BIN="$HOME/.local/bin/edge-tts"
  fi
fi
export EDGE_TTS_BIN

ensure_hdd() {
  if ! findmnt -rn /mnt/hdd500 >/dev/null 2>&1; then
    fail "/mnt/hdd500 chưa mount HDD thật. Chạy: sudo /home/haonguyen/mount-hdd500.sh"
  fi
  [[ -d "$BASE_ROOT" ]] || fail "Thiếu thư mục output HDD: $BASE_ROOT"
  [[ -w "$BASE_ROOT" ]] || fail "Không có quyền ghi HDD: $BASE_ROOT"
  mkdir -p "$BILI_BASE" "$CACHE_DIR"
}

normalize_voice() {
  local raw="${1:-}"
  local normalized
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    "") printf '%s' "$OPENCLAW_DEFAULT_TTS_VOICE" ;;
    resona) printf '%s' "resona:${RESONA_DEFAULT_VOICE_ID:-ZJEpWoOyElCKuEljNTkm}" ;;
    resona:*) printf '%s' "$1" ;;
    ai33|vbee|vbee-maiphuong|vbee-mai-phuong|maiphuong|mai-phuong|mai_phuong|ngoc\ huyen|ngọc\ huyền|ngochuyen|vbee-ngochuyen|elevenlabs|elevenlabs-phanh|eleven-phanh|phanh|phan|ai33:*|elevenlabs_*|vbee_*)
      if [[ -f "$VOICE_REGISTRY_PY" ]] && normalized="$(python3 "$VOICE_REGISTRY_PY" normalize-ai33 "$raw" 2>/dev/null)"; then
        printf '%s' "$normalized"
      else
        fail "VoiceInvalid: AI33 voice không nằm trong registry: $raw"
      fi
      ;;
    kokoro) printf '%s' "kokoro:${KOKORO_DEFAULT_VOICE:-mai_linh}" ;;
    kokoro:*) printf '%s' "$1" ;;
    diem_trinh|duc_an|duc_duy|hung_thinh|mai_linh|mai_loan|manh_dung|my_yen|ngoc_huyen|phat_tai|storyvert|thanh_dat|thuc_trinh|tuan_ngoc) printf '%s' "kokoro:$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" ;;
    nu|nữ|female|woman|giong-nu|giọng-nữ) printf '%s' "nu" ;;
    nam|male|man|giong-nam|giọng-nam) printf '%s' "nam" ;;
    capcut:*) fail "CapCut TTS đã tắt khỏi pipeline. Dùng kokoro:<voice>, AI33 registry, resona, nam, nu hoặc vi-vn-*." ;;
    vi-vn-*) printf '%s' "$1" ;;
    *) fail "VoiceInvalid: preset giọng không hỗ trợ: $1. Dùng kokoro:<voice>, AI33 registry, resona, nam, nu hoặc vi-vn-*." ;;
  esac
}

slugify() {
  python3 - "$1" <<'PY'
import re, sys, unicodedata
s=sys.argv[1] or 'bilibili-video'
s=unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode('ascii')
s=re.sub(r'[^A-Za-z0-9]+','-',s).strip('-').lower()
print((s or 'bilibili-video')[:80])
PY
}

show_doctor() {
  echo "bilibili-vietnamese-dubber doctor"
  for cmd in python3 yt-dlp ffmpeg findmnt; do
    if command -v "$cmd" >/dev/null 2>&1; then echo "OK $cmd=$(command -v "$cmd")"; else echo "FAIL thiếu $cmd"; fi
  done
  # edge-tts: pipeline con (douyin-vietnamese-dubber) cần khi voice là Edge.
  if command -v edge-tts >/dev/null 2>&1; then
    echo "OK edge-tts=$(command -v edge-tts)"
  elif [[ -n "$EDGE_TTS_BIN" && -x "$EDGE_TTS_BIN" ]]; then
    echo "OK edge-tts=$EDGE_TTS_BIN (ngoài PATH; fallback EDGE_TTS_BIN)"
  else
    echo "FAIL thiếu edge-tts (CapCut đã tắt; cần edge-tts cho TTS hiện tại)"
  fi
  [[ -x "$CDP_HELPER" ]] && echo "OK cdp_helper=$CDP_HELPER" || echo "FAIL cdp_helper=$CDP_HELPER"
  [[ -x "$DOUYIN_PIPELINE" ]] && echo "OK pipeline=$DOUYIN_PIPELINE" || echo "FAIL pipeline=$DOUYIN_PIPELINE"
  if curl -fsS --max-time 3 "$CDP_URL/json/version" >/dev/null 2>&1; then echo "OK CDP reachable $CDP_URL"; else echo "WARN CDP chưa reachable $CDP_URL"; fi
}

resolve_translation_memory_from_series_state() {
  if [[ -n "${TRANSLATION_SERIES_ID:-}" || -n "${TRANSLATION_GENRE_TAGS:-}" ]]; then
    return 0
  fi
  local state_dir="${OPENCLAW_SERIES_STATE_DIR:-$HOME/.openclaw-series}"
  local state_file="${OPENCLAW_SERIES_STATE_FILE:-$state_dir/series.json}"
  [[ -f "$state_file" ]] || return 0

  local resolved resolved_id resolved_tags
  set +e
  resolved="$(python3 - "$state_file" "$INPUT" <<'PY'
import json, sys
from pathlib import Path

state_file = Path(sys.argv[1])
url = sys.argv[2]
try:
    data = json.loads(state_file.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)

for series in data.get("series", []):
    if series.get("source_url") == url:
        print(f"{series.get('series_id') or ''}\t{','.join(series.get('genre_tags') or [])}")
        break
    for ep in series.get("episodes", []):
        if ep.get("url") == url:
            print(f"{series.get('series_id') or ''}\t{','.join(series.get('genre_tags') or [])}")
            raise SystemExit(0)
PY
)"
  local resolve_status=$?
  set -e
  [[ "$resolve_status" -eq 0 && -n "$resolved" ]] || return 0
  IFS=$'\t' read -r resolved_id resolved_tags <<< "$resolved"
  TRANSLATION_SERIES_ID="${TRANSLATION_SERIES_ID:-$resolved_id}"
  TRANSLATION_GENRE_TAGS="${TRANSLATION_GENRE_TAGS:-$resolved_tags}"
}

if [[ "$INPUT" == "--doctor" || "$INPUT" == "doctor" ]]; then
  show_doctor
  exit 0
fi

if [[ "$INPUT" == "--find" || "$INPUT" == "find" || "$INPUT" == "search" || "$INPUT" == "bilibili-find" ]]; then
  KEYWORD="${2:-}"
  LIMIT="${3:-10}"
  [[ -n "$KEYWORD" ]] || fail "Thiếu từ khóa tìm Bilibili."
  need_cmd python3
  "$CDP_HELPER" --cdp "$CDP_URL" search "$KEYWORD" --limit "$LIMIT"
  exit $?
fi

[[ -n "$INPUT" ]] || fail "Thiếu URL Bilibili hoặc --find."
need_cmd python3
INPUT="$(python3 "$CDP_HELPER" normalize-url "$INPUT")" || fail "Chỉ hỗ trợ URL video Bilibili trực tiếp."
[[ -n "$INPUT" ]] || fail "Chỉ hỗ trợ URL video Bilibili trực tiếp."
ensure_hdd
need_cmd yt-dlp
[[ -x "$DOUYIN_PIPELINE" ]] || fail "Không tìm thấy pipeline vietsub: $DOUYIN_PIPELINE"
VOICE_PRESET="$(normalize_voice "$VOICE_PRESET")"
validate_branding_flags

JOB_CACHE="$CACHE_DIR/bilibili-$RUN_ID-$(slugify "$INPUT")"
mkdir -p "$JOB_CACHE"
META_JSON="$JOB_CACHE/bilibili_meta.json"
COOKIES_TXT="$JOB_CACHE/bilibili_cookies.txt"
VIDEO_FILE="$JOB_CACHE/input.mp4"
COVER_FILE="$JOB_CACHE/thumbnail_reference.jpg"
LOG_FILE="$JOB_CACHE/bilibili_download.log"

echo "Bắt đầu Bilibili downloader"
echo "URL: $INPUT"
echo "Voice preset: $VOICE_PRESET"
echo "Cache: $JOB_CACHE"

set +e
"$CDP_HELPER" --cdp "$CDP_URL" cookies --out "$COOKIES_TXT" --require-login > "$JOB_CACHE/cookies_status.json"
cookie_status=$?
"$CDP_HELPER" --cdp "$CDP_URL" meta "$INPUT" --out "$META_JSON" --require-login > "$JOB_CACHE/meta_status.json"
meta_status=$?
set -e
if [[ "$cookie_status" -ne 0 || "$meta_status" -ne 0 ]]; then
  echo "BilibiliLoginRequired: Chrome CDP chưa sẵn sàng hoặc Bilibili đang yêu cầu login/captcha/verify." >&2
  echo "Hãy mở Chrome thật CDP, đăng nhập/xử lý xác minh Bilibili rồi chạy lại." >&2
  exit 20
fi

TITLE="$(python3 - "$META_JSON" <<'PY'
import json, sys
try:
 d=json.load(open(sys.argv[1], encoding='utf-8'))
 print((d.get('title') or '').replace('_哔哩哔哩_bilibili','').strip())
except Exception: print('')
PY
)"
COVER_URL="$(python3 - "$META_JSON" <<'PY'
import json, sys
try:
 d=json.load(open(sys.argv[1], encoding='utf-8'))
 print(d.get('cover') or '')
except Exception: print('')
PY
)"

if [[ -n "$COVER_URL" ]]; then
  curl -L --max-time 30 -A 'Mozilla/5.0' -o "$COVER_FILE" "$COVER_URL" >/dev/null 2>&1 || true
fi

set +e
yt-dlp --cookies "$COOKIES_TXT" -f 'bv*+ba/best' --merge-output-format mp4 --no-playlist -o "$VIDEO_FILE" "$INPUT" > "$LOG_FILE" 2>&1
dl_status=$?
set -e
if [[ "$dl_status" -ne 0 || ! -s "$VIDEO_FILE" ]]; then
  echo "BilibiliDownloadFailed: yt-dlp tải Bilibili thất bại. Log: $LOG_FILE" >&2
  tail -80 "$LOG_FILE" >&2 || true
  exit 21
fi

export DOUYIN_VIDEOS_DIR="$BILI_BASE"
export EDGE_TTS_VOICE_PRESET="$VOICE_PRESET"
export SOURCE_PLATFORM="bilibili"
export SOURCE_URL_OVERRIDE="$INPUT"
export SOURCE_TITLE="$TITLE"
resolve_translation_memory_from_series_state
export TRANSLATION_SERIES_ID="${TRANSLATION_SERIES_ID:-}"
export TRANSLATION_GENRE_TAGS="${TRANSLATION_GENRE_TAGS:-}"
if [[ -n "$TRANSLATION_SERIES_ID" || -n "$TRANSLATION_GENRE_TAGS" ]]; then
  echo "Translation memory metadata: series=${TRANSLATION_SERIES_ID:-none} genres=${TRANSLATION_GENRE_TAGS:-none}"
fi
if [[ -n "$TITLE" ]]; then export FINAL_VIDEO_TITLE="$TITLE"; fi
if [[ -s "$COVER_FILE" ]]; then export THUMBNAIL_REFERENCE_IMAGE="$COVER_FILE"; fi
export AUTO_THUMBNAIL="${AUTO_THUMBNAIL:-1}"
export GOOGLE_FLOW_THUMBNAIL_SCRIPT="${GOOGLE_FLOW_THUMBNAIL_SCRIPT:-/home/haonguyen/.openclaw/workspace/skills/google-flow-thumbnail/google-flow-thumbnail.sh}"

echo "Đã tải Bilibili xong, chuyển sang pipeline vietsub/lồng tiếng hiện có..."
# Đảm bảo pipeline con thấy ~/.local/bin (edge-tts pip --user) và EDGE_TTS_BIN.
export PATH="$HOME/.local/bin:$PATH"
set +e
if [[ "$BILIBILI_BRANDING" == "1" ]]; then
  [[ -f "$SINGLE_JOB_BRAND_SCRIPT" ]] || fail "Không tìm thấy single-job branding script: $SINGLE_JOB_BRAND_SCRIPT"
  [[ -f "$BRAND_ASSETS_JSON" ]] || fail "Không tìm thấy approved branding assets: $BRAND_ASSETS_JSON"
  # The child must not organize/upload the unbranded video.  This wrapper brands
  # its verified job-local final output, then performs each final hand-off once.
  ORGANIZE_OUTPUT=0 AUTO_TELEGRAM_RESULT=0 bash "$DOUYIN_PIPELINE" "$VIDEO_FILE"
  child_status=$?
else
  bash "$DOUYIN_PIPELINE" "$VIDEO_FILE"
  child_status=$?
fi
set -e
if [[ "$child_status" -ne 0 ]]; then
  emit_latest_job_failure "$child_status"
  exit "$child_status"
fi

if [[ -f "$LATEST_OUTPUT" ]]; then
  OUT_DIR="$(cat "$LATEST_OUTPUT")"
  if [[ "$BILIBILI_BRANDING" == "1" ]]; then
    [[ -s "$OUT_DIR/final_video_vi.mp4" ]] || fail "Bilibili branding cần final_video_vi.mp4 đã qua quality gate"
    cp "$META_JSON" "$OUT_DIR/bilibili_meta.json" 2>/dev/null || true
    rm -f "$OUT_DIR/bilibili_cookies.txt" 2>/dev/null || true
    [[ -s "$COVER_FILE" ]] && cp "$COVER_FILE" "$OUT_DIR/thumbnail_reference_bilibili.jpg" 2>/dev/null || true
    python3 "$SINGLE_JOB_BRAND_SCRIPT" --input "$OUT_DIR/final_video_vi.mp4" --output "$OUT_DIR/final_video_vi.mp4" --assets "$BRAND_ASSETS_JSON" --include-intro "$BILIBILI_BRAND_INCLUDE_INTRO" --include-outro "$BILIBILI_BRAND_INCLUDE_OUTRO" || fail "Bilibili branding thất bại; không organize/upload"
    cp "$OUT_DIR/final_video_vi.mp4" "$BILI_BASE/final_video_vi.mp4"
    ORGANIZE_SCRIPT="${ORGANIZE_OUTPUT_SCRIPT:-$(dirname "$DOUYIN_PIPELINE")/organize_output.py}"
    TELEGRAM_SCRIPT="${TELEGRAM_RESULT_SCRIPT:-$(dirname "$DOUYIN_PIPELINE")/telegram-send-result.sh}"
    [[ -x "$ORGANIZE_SCRIPT" ]] || fail "Không tìm thấy organize output script: $ORGANIZE_SCRIPT"
    python3 "$ORGANIZE_SCRIPT" --job-dir "$OUT_DIR" --base-dir "$BILI_BASE" > "$OUT_DIR/organize_output.log" || fail "Organize branded Bilibili output thất bại; không upload"
    if [[ "${AUTO_TELEGRAM_RESULT:-1}" != "0" && -x "$TELEGRAM_SCRIPT" ]]; then
      timeout "${TELEGRAM_RESULT_TIMEOUT:-300}" "$TELEGRAM_SCRIPT" "$OUT_DIR" || echo "WARN: Telegram/Drive branded result failed; video branded vẫn giữ trong job dir."
    fi
  else
    cp "$META_JSON" "$OUT_DIR/bilibili_meta.json" 2>/dev/null || true
    # Hardening: cookies stay only in JOB_CACHE for yt-dlp; never copy into job output.
    # Scrub residual from older runs that may still have bilibili_cookies.txt in OUT_DIR.
    rm -f "$OUT_DIR/bilibili_cookies.txt" 2>/dev/null || true
    [[ -s "$COVER_FILE" ]] && cp "$COVER_FILE" "$OUT_DIR/thumbnail_reference_bilibili.jpg" 2>/dev/null || true
  fi
  printf '%s\n' "$INPUT" > "$LATEST_SOURCE"
  echo "bilibili_output_dir: $OUT_DIR"
fi
