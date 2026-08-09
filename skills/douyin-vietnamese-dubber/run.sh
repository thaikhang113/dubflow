#!/usr/bin/env bash
set -Eeuo pipefail

INPUT="${1:-}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DOUYIN_DUBBER_SKILL_DIR="$SKILL_DIR"
VOICE_REGISTRY_PY="${VOICE_REGISTRY_PY:-$SKILL_DIR/voice_registry.py}"
OPENCLAW_VOICE_REGISTRY_JSON="${OPENCLAW_VOICE_REGISTRY_JSON:-$HOME/.openclaw/config/voice_registry.json}"
BASE_DIR="${DOUYIN_VIDEOS_DIR:-$HOME/video douyin vietsub}"
WHISPER_DIR="${WHISPER_DIR:-$HOME/whisper.cpp}"
WHISPER_BIN="${WHISPER_BIN:-$WHISPER_DIR/build/bin/whisper-cli}"
WHISPER_MODEL="${WHISPER_MODEL:-$WHISPER_DIR/models/ggml-small.bin}"
OPENCLAW_RUNTIME_PROFILE="${OPENCLAW_RUNTIME_PROFILE:-standard}"
if [[ "${OPENCLAW_RUNTIME_PROFILE,,}" == "free_low_gpu" ]]; then
  OPENCLAW_AI_PROVIDER="${OPENCLAW_AI_PROVIDER:-ollama}"
OLLAMA_MODEL="${OLLAMA_MODEL:-translategemma:4b}"
  if [[ -z "${EDGE_TTS_VOICE:-}" && -z "${EDGE_TTS_VOICE_PRESET:-}" && -z "${DOUYIN_TTS_VOICE_PRESET:-}" && -z "${OPENCLAW_DEFAULT_TTS_VOICE:-}" ]]; then
    EDGE_TTS_VOICE="${EDGE_TTS_VOICE:-vi-VN-HoaiMyNeural}"
  fi
  SUBTITLE_OCR_ENGINE="${SUBTITLE_OCR_ENGINE:-paddleocr}"
  SUBTITLE_BAND_DETECT_ENGINE="${SUBTITLE_BAND_DETECT_ENGINE:-cv}"
  BGM_MODE="${BGM_MODE:-none}"
  SPEECH_ONLY_PREPROCESS="${SPEECH_ONLY_PREPROCESS:-0}"
  AI33_TTS_WORKERS="${AI33_TTS_WORKERS:-1}"
  TTS_VOICE_QA_ENABLED="${TTS_VOICE_QA_ENABLED:-0}"
fi
if [[ -z "${VK_ICD_FILENAMES:-}" && -f /usr/share/vulkan/icd.d/radeon_icd.json ]]; then
  export VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/radeon_icd.json"
fi
# edge-tts (pip --user) thường cài vào ~/.local/bin. Khi resume từ dashboard,
# env có thể không chứa ~/.local/bin nên command -v edge-tts fail dù binary có thật.
# Đưa ~/.local/bin lên đầu PATH để mọi command -v/subprocess đều tìm thấy.
if [[ -d "$HOME/.local/bin" && ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  export PATH="$HOME/.local/bin:$PATH"
fi
# EDGE_TTS_BIN: cho phép override binary edge-tts. Mặc định resolve qua PATH,
# fallback sang ~/.local/bin/edge-tts khi command -v edge-tts không thấy.
EDGE_TTS_BIN="${EDGE_TTS_BIN:-}"
if [[ -z "$EDGE_TTS_BIN" ]]; then
  if command -v edge-tts >/dev/null 2>&1; then
    EDGE_TTS_BIN="$(command -v edge-tts)"
  elif [[ -x "$HOME/.local/bin/edge-tts" ]]; then
    EDGE_TTS_BIN="$HOME/.local/bin/edge-tts"
  fi
fi
export EDGE_TTS_BIN
# Translation routing is deliberately isolated from host-wide OpenClaw provider
# settings.  See translation_route.sh for validation and the Ollama fallback.
source "$SKILL_DIR/translation_route.sh"
export OPENCLAW_AI_PROVIDER
NINEROUTER_MODEL="${NINEROUTER_MODEL:-}"
KOKORO_DEFAULT_VOICE="${KOKORO_DEFAULT_VOICE:-mai_linh}"
AI33_MAI_PHUONG_VOICE_ID="${AI33_MAI_PHUONG_VOICE_ID:-vbee_hn_female_maiphuong_vdts_48k-fhg}"
AI33_PHANH_VOICE_ID="${AI33_PHANH_VOICE_ID:-elevenlabs_UuMSQK8FdLwaY2M8ZAnh}"
AI33_DEFAULT_VOICE_ID="${AI33_DEFAULT_VOICE_ID:-$AI33_MAI_PHUONG_VOICE_ID}"
if [[ -z "${OPENCLAW_DEFAULT_TTS_VOICE:-}" && -f "$VOICE_REGISTRY_PY" ]]; then
  if _voice_registry_default="$(python3 "$VOICE_REGISTRY_PY" default 2>/dev/null)" && [[ -n "$_voice_registry_default" ]]; then
    OPENCLAW_DEFAULT_TTS_VOICE="$_voice_registry_default"
  fi
fi
OPENCLAW_DEFAULT_TTS_VOICE="${OPENCLAW_DEFAULT_TTS_VOICE:-ai33:${AI33_DEFAULT_VOICE_ID}}"
if [[ "$OPENCLAW_DEFAULT_TTS_VOICE" == "ai33:${AI33_PHANH_VOICE_ID}" && "${OPENCLAW_KEEP_LEGACY_PHANH_DEFAULT:-0}" != "1" && ! -f "$VOICE_REGISTRY_PY" ]]; then
  OPENCLAW_DEFAULT_TTS_VOICE="ai33:${AI33_MAI_PHUONG_VOICE_ID}"
fi
VOICE_PRESET_INPUT="${EDGE_TTS_VOICE_PRESET:-${DOUYIN_TTS_VOICE_PRESET:-}}"
VOICE_SOURCE_HINT="registry"
if [[ -n "$VOICE_PRESET_INPUT" || -n "${EDGE_TTS_VOICE:-}" ]]; then
  VOICE_SOURCE_HINT="explicit"
fi
VOICE_PRESET="$VOICE_PRESET_INPUT"
OPTIMIZER_ENABLED="${VIET_DUB_TIMING_OPTIMIZER:-1}"
TARGET_MAX_SPEED="${TARGET_MAX_SPEED:-1.25}"
SOFT_MAX_SPEED="${SOFT_MAX_SPEED:-1.35}"
HARD_MAX_SPEED="${HARD_MAX_SPEED:-1.50}"
HARD_MAX_DURATION="${HARD_MAX_DURATION:-3.0}"
SYNC_MODE="${SYNC_MODE:-${TTS_SYNC_MODE:-exact_sync}}"
case "${SYNC_MODE,,}" in
  exact|exact_sync)
    SYNC_MODE="exact_sync"
    TTS_SYNC_POLICY="${TTS_SYNC_POLICY:-frame_strict}"
    AI33_MAX_SPEED="${AI33_MAX_SPEED:-1.12}"
    POST_ATEMPO_MAX="${POST_ATEMPO_MAX:-99.0}"
    TOTAL_AUDIO_SPEED_MAX="${TOTAL_AUDIO_SPEED_MAX:-99.0}"
    DEFAULT_MUSIC_BED_VOLUME="${DEFAULT_MUSIC_BED_VOLUME:-0.12}"
    DEFAULT_SUBTITLE_ONLY_RATIO="${DEFAULT_SUBTITLE_ONLY_RATIO:-10.0}"
    ALLOW_AGGRESSIVE_ATEMPO="${ALLOW_AGGRESSIVE_ATEMPO:-1}"
    ALLOW_VIDEO_RETIME="${ALLOW_VIDEO_RETIME:-1}"
    ALLOW_FREEZE_FRAME="${ALLOW_FREEZE_FRAME:-1}"
    LOCAL_RETIME_SCENE_SAFE="${LOCAL_RETIME_SCENE_SAFE:-1}"
    MAX_FREEZE_PER_SEGMENT_MS="${MAX_FREEZE_PER_SEGMENT_MS:-1500}"
    MAX_FREEZE_PER_SCENE_MS="${MAX_FREEZE_PER_SCENE_MS:-1500}"
    FRAME_STRICT_MAX_SEGMENT_DRIFT_MS="${FRAME_STRICT_MAX_SEGMENT_DRIFT_MS:-40}"
    FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS="${FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS:-10}"
    STRICT_QUALITY_GATE="${STRICT_QUALITY_GATE:-1}"
    ;;
  quality|quality_dub)
    SYNC_MODE="quality_dub"
    TTS_SYNC_POLICY="${TTS_SYNC_POLICY:-bounded}"
    AI33_MAX_SPEED="${AI33_MAX_SPEED:-1.08}"
    POST_ATEMPO_MAX="${POST_ATEMPO_MAX:-1.05}"
    TOTAL_AUDIO_SPEED_MAX="${TOTAL_AUDIO_SPEED_MAX:-1.25}"
    DEFAULT_MUSIC_BED_VOLUME="${DEFAULT_MUSIC_BED_VOLUME:-0.10}"
    DEFAULT_SUBTITLE_ONLY_RATIO="${DEFAULT_SUBTITLE_ONLY_RATIO:-2.0}"
    ;;
  strict|strict_timeline)
    SYNC_MODE="strict_timeline"
    TTS_SYNC_POLICY="${TTS_SYNC_POLICY:-bounded}"
    AI33_MAX_SPEED="${AI33_MAX_SPEED:-1.15}"
    POST_ATEMPO_MAX="${POST_ATEMPO_MAX:-1.05}"
    TOTAL_AUDIO_SPEED_MAX="${TOTAL_AUDIO_SPEED_MAX:-1.45}"
    DEFAULT_MUSIC_BED_VOLUME="${DEFAULT_MUSIC_BED_VOLUME:-0.12}"
    DEFAULT_SUBTITLE_ONLY_RATIO="${DEFAULT_SUBTITLE_ONLY_RATIO:-2.0}"
    ;;
  aggressive|aggressive_legacy|frame_strict)
    SYNC_MODE="aggressive_legacy"
    TTS_SYNC_POLICY="${TTS_SYNC_POLICY:-frame_strict}"
    AI33_MAX_SPEED="${AI33_MAX_SPEED:-1.20}"
    POST_ATEMPO_MAX="${POST_ATEMPO_MAX:-99.0}"
    TOTAL_AUDIO_SPEED_MAX="${TOTAL_AUDIO_SPEED_MAX:-99.0}"
    DEFAULT_MUSIC_BED_VOLUME="${DEFAULT_MUSIC_BED_VOLUME:-0.18}"
    DEFAULT_SUBTITLE_ONLY_RATIO="${DEFAULT_SUBTITLE_ONLY_RATIO:-10.0}"
    ALLOW_AGGRESSIVE_ATEMPO="${ALLOW_AGGRESSIVE_ATEMPO:-1}"
    ;;
  balanced|balanced_dub|*)
    SYNC_MODE="balanced_dub"
    TTS_SYNC_POLICY="${TTS_SYNC_POLICY:-bounded}"
    AI33_MAX_SPEED="${AI33_MAX_SPEED:-1.12}"
    POST_ATEMPO_MAX="${POST_ATEMPO_MAX:-1.05}"
    TOTAL_AUDIO_SPEED_MAX="${TOTAL_AUDIO_SPEED_MAX:-1.35}"
    DEFAULT_MUSIC_BED_VOLUME="${DEFAULT_MUSIC_BED_VOLUME:-0.12}"
    DEFAULT_SUBTITLE_ONLY_RATIO="${DEFAULT_SUBTITLE_ONLY_RATIO:-2.0}"
    ;;
esac
export SYNC_MODE TTS_SYNC_POLICY
FRAME_STRICT_MAX_SEGMENT_DRIFT_MS="${FRAME_STRICT_MAX_SEGMENT_DRIFT_MS:-80}"
FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS="${FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS:-5}"
export FRAME_STRICT_MAX_SEGMENT_DRIFT_MS FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS
ALLOW_AGGRESSIVE_ATEMPO="${ALLOW_AGGRESSIVE_ATEMPO:-0}"
MAX_TTS_SPEED="${MAX_TTS_SPEED:-$TOTAL_AUDIO_SPEED_MAX}"
SUBTITLE_ONLY_IF_RATIO_ABOVE="${SUBTITLE_ONLY_IF_RATIO_ABOVE:-$DEFAULT_SUBTITLE_ONLY_RATIO}"
ALLOW_AUDIO_OVERHANG="${ALLOW_AUDIO_OVERHANG:-0.6}"
ALLOW_FINAL_TRIM="${ALLOW_FINAL_TRIM:-0}"
FINAL_VOICE_OVERHANG_TOLERANCE="${FINAL_VOICE_OVERHANG_TOLERANCE:-0.20}"
TTS_MASTER_SAMPLE_RATE="${TTS_MASTER_SAMPLE_RATE:-48000}"
TTS_MASTER_CHANNELS="${TTS_MASTER_CHANNELS:-1}"
FINAL_AUDIO_SAMPLE_RATE="${FINAL_AUDIO_SAMPLE_RATE:-48000}"
FINAL_AUDIO_CHANNELS="${FINAL_AUDIO_CHANNELS:-2}"
FINAL_AUDIO_BITRATE="${FINAL_AUDIO_BITRATE:-192k}"
ALLOW_SLOW_FIT="${ALLOW_SLOW_FIT:-0}"
POST_ATEMPO_MIN="${POST_ATEMPO_MIN:-0.95}"
TTS_ADAPT_ENABLED="${TTS_ADAPT_ENABLED:-1}"
TTS_ADAPT_MAX_ATTEMPTS="${TTS_ADAPT_MAX_ATTEMPTS:-2}"
TTS_RESTORE_IF_SLOT_RATIO_BELOW="${TTS_RESTORE_IF_SLOT_RATIO_BELOW:-0.72}"
# exact_sync enables a bounded tail freeze; other modes stay opt-in.
# ponytail: per-cue scene retime waits for real-video evidence; upgrade with a
# scene-cut-aware setpts planner if semantic fit + pitch-preserving atempo sounds poor.
FINAL_VIDEO_FIT_MODE="${FINAL_VIDEO_FIT_MODE:-none}"
STRICT_QUALITY_GATE="${STRICT_QUALITY_GATE:-0}"
# Short natural AI33 speech is not a render blocker in balanced/quality mode.  These
# thresholds apply only to synthetic silence appended inside spoken cue slots; they
# deliberately exclude source timeline gaps and final tail silence.
VOICE_SYNC_PADDING_WARN_RATIO="${VOICE_SYNC_PADDING_WARN_RATIO:-0.20}"
VOICE_SYNC_PADDING_FAIL_RATIO="${VOICE_SYNC_PADDING_FAIL_RATIO:-0.30}"
VOICE_SYNC_MIN_MEDIAN_FILL_RATIO="${VOICE_SYNC_MIN_MEDIAN_FILL_RATIO:-0.55}"
VOICE_SYNC_LONG_PADDING_WARN_MS="${VOICE_SYNC_LONG_PADDING_WARN_MS:-1500}"
VOICE_SYNC_LONG_PADDING_FAIL_MS="${VOICE_SYNC_LONG_PADDING_FAIL_MS:-2500}"
VOICE_SYNC_MAX_UNRESOLVED_CONTIGUOUS_OVERHANG_MS="${VOICE_SYNC_MAX_UNRESOLVED_CONTIGUOUS_OVERHANG_MS:-120}"
export VOICE_SYNC_MAX_UNRESOLVED_CONTIGUOUS_OVERHANG_MS
ALLOW_VIDEO_RETIME="${ALLOW_VIDEO_RETIME:-0}"
ALLOW_FREEZE_FRAME="${ALLOW_FREEZE_FRAME:-0}"
LOCAL_RETIME_SCENE_SAFE="${LOCAL_RETIME_SCENE_SAFE:-0}"
MAX_FREEZE_PER_SEGMENT_MS="${MAX_FREEZE_PER_SEGMENT_MS:-500}"
MAX_FREEZE_PER_SCENE_MS="${MAX_FREEZE_PER_SCENE_MS:-1200}"
MAX_OUTPUT_DURATION_INCREASE="${MAX_OUTPUT_DURATION_INCREASE:-10}"
FINAL_LOUDNESS_TARGET="${FINAL_LOUDNESS_TARGET:--18}"
FINAL_TRUE_PEAK_LIMIT="${FINAL_TRUE_PEAK_LIMIT:--1.5}"
ENABLE_FINAL_LOUDNESS_NORMALIZATION="${ENABLE_FINAL_LOUDNESS_NORMALIZATION:-1}"
VOICE_VOLUME="${VOICE_VOLUME:-1.25}"
BURN_VIET_SUBTITLE="${BURN_VIET_SUBTITLE:-1}"
MASK_ORIGINAL_SUBTITLE="${MASK_ORIGINAL_SUBTITLE:-1}"
SUBTITLE_MASK_STYLE="${SUBTITLE_MASK_STYLE:-localized_blur}"
SUBTITLE_BAND_SAMPLE_COUNT="${SUBTITLE_BAND_SAMPLE_COUNT:-24}"
SUBTITLE_BAND_REGION_TOP_RATIO="${SUBTITLE_BAND_REGION_TOP_RATIO:-0.55}"
SUBTITLE_BAND_REGION_BOTTOM_RATIO="${SUBTITLE_BAND_REGION_BOTTOM_RATIO:-0.98}"
SUBTITLE_BAND_HEIGHT_RATIO="${SUBTITLE_BAND_HEIGHT_RATIO:-0.10}"
SUBTITLE_BAND_MIN_HEIGHT="${SUBTITLE_BAND_MIN_HEIGHT:-64}"
SUBTITLE_REGION_REBUILD="${SUBTITLE_REGION_REBUILD:-0}"
SUBTITLE_BAND_BLUR="${SUBTITLE_BAND_BLUR:-18}"
SUBTITLE_BAND_TINT_OPACITY="${SUBTITLE_BAND_TINT_OPACITY:-0.18}"
# Mask band detect: AI vision (MiniMax M3) gate + CV bbox + blur_band fallback.
SUBTITLE_BAND_DETECT_ENGINE="${SUBTITLE_BAND_DETECT_ENGINE:-9router_vision}"
SUBTITLE_BAND_VISION_TIMEOUT="${SUBTITLE_BAND_VISION_TIMEOUT:-60}"
SUBTITLE_TEXT_COLOR="${SUBTITLE_TEXT_COLOR:-yellow}"
# Subtitle Việt: kiểm soát wrap/font để chữ to, dễ đọc trên mobile.
VI_SUBTITLE_MIN_FONT_SIZE="${VI_SUBTITLE_MIN_FONT_SIZE:-48}"
VI_SUBTITLE_MAX_LINES="${VI_SUBTITLE_MAX_LINES:-${SUBTITLE_MAX_LINES:-2}}"
VI_SUBTITLE_WRAP_CHARS="${VI_SUBTITLE_WRAP_CHARS:-${SUBTITLE_MAX_CHARS_PER_LINE:-28}}"
VI_SUBTITLE_BOTTOM_MARGIN_RATIO="${VI_SUBTITLE_BOTTOM_MARGIN_RATIO:-${SUBTITLE_BOTTOM_MARGIN_RATIO:-0.035}}"
VI_SUBTITLE_VERTICAL_OFFSET_RATIO="${VI_SUBTITLE_VERTICAL_OFFSET_RATIO:-${SUBTITLE_BOX_VERTICAL_OFFSET_RATIO:-0.02}}"
# Font Việt + per-cue fitted layout + readability gate.
VI_SUBTITLE_FONT_FILE="${VI_SUBTITLE_FONT_FILE:-}"
VI_SUBTITLE_FONT_NAME="${VI_SUBTITLE_FONT_NAME:-}"
VI_SUBTITLE_FONT_PRESET="${VI_SUBTITLE_FONT_PRESET:-}"
VI_SUBTITLE_FONT_DIR="${VI_SUBTITLE_FONT_DIR:-/home/haonguyen/.openclaw/assets/fonts}"
VI_SUBTITLE_MAX_FONT_SIZE="${VI_SUBTITLE_MAX_FONT_SIZE:-56}"
VI_SUBTITLE_TARGET_BAND_FILL="${VI_SUBTITLE_TARGET_BAND_FILL:-0.70}"
VI_SUBTITLE_SAFE_WIDTH_RATIO="${VI_SUBTITLE_SAFE_WIDTH_RATIO:-0.88}"
VI_SUBTITLE_SAFE_HEIGHT_RATIO="${VI_SUBTITLE_SAFE_HEIGHT_RATIO:-1.0}"
VI_SUBTITLE_MIN_BAND_FILL_WARN="${VI_SUBTITLE_MIN_BAND_FILL_WARN:-0.32}"
VI_SUBTITLE_MAX_SMALL_CUE_RATIO="${VI_SUBTITLE_MAX_SMALL_CUE_RATIO:-0.25}"
VI_SUBTITLE_LAYOUT_GATE="${VI_SUBTITLE_LAYOUT_GATE:-fail}"
VI_SUBTITLE_MIN_FONT_SIZE_GATE="${VI_SUBTITLE_MIN_FONT_SIZE_GATE:-48}"
# Band detection outlier filter: reject bbox giữa màn hình + MAD outlier trên center_y.
SUBTITLE_BAND_MIN_CENTER_Y_RATIO="${SUBTITLE_BAND_MIN_CENTER_Y_RATIO:-0.72}"
SUBTITLE_BAND_OUTLIER_CONSISTENCY="${SUBTITLE_BAND_OUTLIER_CONSISTENCY:-5}"
SUBTITLE_BAND_OUTLIER_MAD_K="${SUBTITLE_BAND_OUTLIER_MAD_K:-3.0}"
SUBTITLE_RENDER_FAILURE_POLICY="${SUBTITLE_RENDER_FAILURE_POLICY:-fail}"
SUBTITLE_TEXT_ALIGN="${SUBTITLE_TEXT_ALIGN:-band_center}"
SUBTITLE_MASK_OPACITY="${SUBTITLE_MASK_OPACITY:-0.95}"
SUBTITLE_MASK_HEIGHT_RATIO="${SUBTITLE_MASK_HEIGHT_RATIO:-0.08}"
SUBTITLE_BOTTOM_MARGIN_RATIO="${SUBTITLE_BOTTOM_MARGIN_RATIO:-0.035}"
SUBTITLE_FONT="${SUBTITLE_FONT:-/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf}"
SUBTITLE_FONT_SIZE_RATIO="${SUBTITLE_FONT_SIZE_RATIO:-0.030}"
SUBTITLE_OUTLINE="${SUBTITLE_OUTLINE:-1}"
SUBTITLE_MAX_LINES="${SUBTITLE_MAX_LINES:-2}"
SUBTITLE_MAX_CHARS_PER_LINE="${SUBTITLE_MAX_CHARS_PER_LINE:-28}"
SUBTITLE_BOX_MODE="${SUBTITLE_BOX_MODE:-compact}"
SUBTITLE_BOX_OPACITY="${SUBTITLE_BOX_OPACITY:-0.92}"
SUBTITLE_BOX_MARGIN_X="${SUBTITLE_BOX_MARGIN_X:-6}"
SUBTITLE_BOX_MARGIN_Y="${SUBTITLE_BOX_MARGIN_Y:-2}"
SUBTITLE_BOX_VERTICAL_OFFSET_RATIO="${SUBTITLE_BOX_VERTICAL_OFFSET_RATIO:-0.02}"
SUBTITLE_DYNAMIC_MASK="${SUBTITLE_DYNAMIC_MASK:-1}"
SUBTITLE_DYNAMIC_MASK_MODE="${SUBTITLE_DYNAMIC_MASK_MODE:-connected_components}"
SUBTITLE_DETECT_REGION_TOP_RATIO="${SUBTITLE_DETECT_REGION_TOP_RATIO:-0.82}"
SUBTITLE_DETECT_REGION_BOTTOM_RATIO="${SUBTITLE_DETECT_REGION_BOTTOM_RATIO:-0.96}"
SUBTITLE_DETECT_LUMA_THRESHOLD="${SUBTITLE_DETECT_LUMA_THRESHOLD:-185}"
SUBTITLE_DETECT_MAX_RGB_SPREAD="${SUBTITLE_DETECT_MAX_RGB_SPREAD:-62}"
SUBTITLE_DYNAMIC_MASK_PAD_X_RATIO="${SUBTITLE_DYNAMIC_MASK_PAD_X_RATIO:-0.010}"
SUBTITLE_DYNAMIC_MASK_PAD_Y_RATIO="${SUBTITLE_DYNAMIC_MASK_PAD_Y_RATIO:-0.006}"
SUBTITLE_DYNAMIC_MASK_MIN_WIDTH_RATIO="${SUBTITLE_DYNAMIC_MASK_MIN_WIDTH_RATIO:-0.12}"
SUBTITLE_DETECT_MAX_WIDTH_RATIO="${SUBTITLE_DETECT_MAX_WIDTH_RATIO:-0.78}"
SUBTITLE_DYNAMIC_MASK_DEBUG="${SUBTITLE_DYNAMIC_MASK_DEBUG:-1}"
SUBTITLE_FALLBACK_MASK_HEIGHT_RATIO="${SUBTITLE_FALLBACK_MASK_HEIGHT_RATIO:-0.08}"
SUBTITLE_FALLBACK_MASK_MAX_WIDTH_RATIO="${SUBTITLE_FALLBACK_MASK_MAX_WIDTH_RATIO:-0.50}"
SUBTITLE_SOURCE_TRACK="${SUBTITLE_SOURCE_TRACK:-1}"
SUBTITLE_RENDER_MASK_FROM_SOURCE="${SUBTITLE_RENDER_MASK_FROM_SOURCE:-1}"
SUBTITLE_SOURCE_DETECT_FPS="${SUBTITLE_SOURCE_DETECT_FPS:-8}"
SUBTITLE_SOURCE_TRACK_REBUILD="${SUBTITLE_SOURCE_TRACK_REBUILD:-0}"
SUBTITLE_SOURCE_TRACK_MIN_CONFIDENCE="${SUBTITLE_SOURCE_TRACK_MIN_CONFIDENCE:-0.45}"
SUBTITLE_SOURCE_MERGE_GAP_SEC="${SUBTITLE_SOURCE_MERGE_GAP_SEC:-0.22}"
SUBTITLE_SOURCE_HOLD_OUT_SEC="${SUBTITLE_SOURCE_HOLD_OUT_SEC:-0.16}"
SUBTITLE_SOURCE_LEAD_IN_SEC="${SUBTITLE_SOURCE_LEAD_IN_SEC:-0.08}"
SUBTITLE_SOURCE_BBOX_SMOOTH_WINDOW="${SUBTITLE_SOURCE_BBOX_SMOOTH_WINDOW:-3}"
SUBTITLE_SOURCE_PAD_X="${SUBTITLE_SOURCE_PAD_X:-64}"
SUBTITLE_SOURCE_PAD_Y="${SUBTITLE_SOURCE_PAD_Y:-28}"
SUBTITLE_SOURCE_WIDE_WIDTH_RATIO="${SUBTITLE_SOURCE_WIDE_WIDTH_RATIO:-0.55}"
SUBTITLE_SOURCE_TRACK_DEBUG="${SUBTITLE_SOURCE_TRACK_DEBUG:-1}"
SUBTITLE_SOURCE_DETECT_MODE="${SUBTITLE_SOURCE_DETECT_MODE:-auto}"
SUBTITLE_OCR_FALLBACK="${SUBTITLE_OCR_FALLBACK:-1}"
# OCR transcript: 9router_vision (AI MiniMax M3) làm mặc định, fallback PaddleOCR nếu lỗi/empty.
SUBTITLE_OCR_ENGINE="${SUBTITLE_OCR_ENGINE:-9router_vision}"
SUBTITLE_OCR_LANG="${SUBTITLE_OCR_LANG:-ch}"
SUBTITLE_OCR_FPS="${SUBTITLE_OCR_FPS:-2}"
SUBTITLE_OCR_ROI_ONLY="${SUBTITLE_OCR_ROI_ONLY:-1}"
SUBTITLE_OCR_BATCH_SIZE="${SUBTITLE_OCR_BATCH_SIZE:-1}"
SUBTITLE_OCR_MIN_CONFIDENCE="${SUBTITLE_OCR_MIN_CONFIDENCE:-0.45}"
SUBTITLE_OCR_REBUILD="${SUBTITLE_OCR_REBUILD:-0}"
# Vision OCR engine config. Keep this independent from NINEROUTER_MODEL: host
# runners may deliberately set that to a text-only translation/chat route.
# OCR_VISION_MODEL is the most specific override, followed by dedicated shared
# vision settings; the final default is the known vision-capable MiniMax route.
# OCR routing is deliberately independent from translation routing.
OCR_VISION_PROVIDER="${OCR_VISION_PROVIDER:-ninerouter}"
case "${OCR_VISION_PROVIDER,,}" in
  ollama)
    OCR_VISION_PROVIDER="ollama"
    OCR_VISION_MODEL="${OCR_VISION_MODEL:-${OLLAMA_VISION_MODEL:-${OLLAMA_MODEL:-ollama/minimax-m3:cloud}}}"
    OCR_VISION_API_BASE="${OCR_VISION_API_BASE:-${OLLAMA_API_BASE:-http://127.0.0.1:11434}}"
    OCR_VISION_API_KEY=""
    ;;
  local|paddleocr|cv)
    OCR_VISION_PROVIDER="local"
    OCR_VISION_API_KEY=""
    ;;
  *)
    OCR_VISION_PROVIDER="ninerouter"
    OCR_VISION_MODEL="${OCR_VISION_MODEL:-${NINEROUTER_VISION_MODEL:-${OPENCLAW_VISION_MODEL:-ollama/minimax-m3:cloud}}}"
    OCR_VISION_API_BASE="${OCR_VISION_API_BASE:-${NINEROUTER_API_BASE:-$API_BASE}}"
    OCR_VISION_API_KEY="${OCR_VISION_API_KEY:-${NINEROUTER_API_KEY:-}}"
    ;;
esac
OCR_VISION_MIN_CONFIDENCE="${OCR_VISION_MIN_CONFIDENCE:-0.45}"
OCR_VISION_DEDUP_THRESHOLD="${OCR_VISION_DEDUP_THRESHOLD:-0.97}"
# Bounded fast mode: giới hạn OCR transcript để không quét mù toàn video tới timeout 900s.
# - SUBTITLE_OCR_TRANSCRIPT_FPS: sample thưa hơn (mặc định 1fps cho transcript, 2fps cho mask).
# - OCR_TRANSCRIPT_FRAME_STRIDE: bỏ frame giữa (3 = xử lý 1/3 frame).
# - OCR_TRANSCRIPT_MAX_FRAMES: cứng số frame tối đa (0 = tự do).
# - OCR_TRANSCRIPT_VISION_TIMEOUT_SECONDS: timeout per-call vision API.
# - OCR_TRANSCRIPT_TOTAL_TIMEOUT_SECONDS: budget nội bộ (SIGALRM), < shell timeout để kịp partial.
# - OCR_TRANSCRIPT_DISABLE_PADDLE_FALLBACK: bỏ fallback Paddle khi engine=vision (tránh init nặng).
SUBTITLE_OCR_TRANSCRIPT_FPS="${SUBTITLE_OCR_TRANSCRIPT_FPS:-1}"
OCR_TRANSCRIPT_FRAME_STRIDE="${OCR_TRANSCRIPT_FRAME_STRIDE:-3}"
OCR_TRANSCRIPT_MAX_FRAMES="${OCR_TRANSCRIPT_MAX_FRAMES:-0}"
OCR_TRANSCRIPT_VISION_TIMEOUT_SECONDS="${OCR_TRANSCRIPT_VISION_TIMEOUT_SECONDS:-30}"
OCR_TRANSCRIPT_TOTAL_TIMEOUT_SECONDS="${OCR_TRANSCRIPT_TOTAL_TIMEOUT_SECONDS:-720}"
OCR_TRANSCRIPT_DISABLE_PADDLE_FALLBACK="${OCR_TRANSCRIPT_DISABLE_PADDLE_FALLBACK:-1}"
SUBTITLE_MASK_ROUNDED="${SUBTITLE_MASK_ROUNDED:-1}"
SUBTITLE_MASK_RADIUS="${SUBTITLE_MASK_RADIUS:-18}"
SUBTITLE_MASK_ALPHA="${SUBTITLE_MASK_ALPHA:-0.82}"
OPTIMIZER_TIMEOUT_SECONDS="${OPTIMIZER_TIMEOUT_SECONDS:-7200}"
SPEECH_ONLY_PREPROCESS_ENABLED="${SPEECH_ONLY_PREPROCESS:-1}"
SPEECH_ONLY_TIMEOUT_SECONDS="${SPEECH_ONLY_TIMEOUT_SECONDS:-10800}"
MUSIC_BED_VOLUME="${MUSIC_BED_VOLUME:-$DEFAULT_MUSIC_BED_VOLUME}"
ENABLE_BGM_DUCKING="${ENABLE_BGM_DUCKING:-1}"
BGM_DUCK_AMOUNT="${BGM_DUCK_AMOUNT:-2.0}"
BGM_MODE="${BGM_MODE:-auto}"
BGM_MODE_FALLBACK="${BGM_MODE_FALLBACK:-none}"
ASR_SPLIT_LONG_SEGMENTS="${ASR_SPLIT_LONG_SEGMENTS:-1}"
ASR_SPLIT_MAX_SECONDS="${ASR_SPLIT_MAX_SECONDS:-10}"
ASR_SPLIT_MAX_CHARS="${ASR_SPLIT_MAX_CHARS:-120}"
AI33_TTS_WORKERS="${AI33_TTS_WORKERS:-3}"
TTS_VOICE_QA_ENABLED="${TTS_VOICE_QA_ENABLED:-1}"
TTS_VOICE_QA_RETRY_MAX="${TTS_VOICE_QA_RETRY_MAX:-1}"

resolve_voice() {
  local preset="${1:-}"
  local explicit_voice="${EDGE_TTS_VOICE:-}"
  local normalized
  if [[ -n "$explicit_voice" ]]; then
    case "$(printf '%s' "$explicit_voice" | tr '[:upper:]' '[:lower:]')" in
      ai33|ai33:*|elevenlabs_*|vbee_*|vbee|vbee-maiphuong|vbee-mai-phuong|maiphuong|mai-phuong|mai_phuong|elevenlabs|elevenlabs-phanh|eleven-phanh|phanh|phan)
        if [[ -f "$VOICE_REGISTRY_PY" ]] && normalized="$(python3 "$VOICE_REGISTRY_PY" normalize-ai33 "$explicit_voice" 2>/dev/null)"; then
          printf '%s' "$normalized"
          return 0
        fi
        echo "VoiceInvalid: AI33 voice explicit không nằm trong registry: $explicit_voice" >&2
        return 64
        ;;
    esac
    printf '%s' "$explicit_voice"
    return 0
  fi

  case "$(printf '%s' "$preset" | tr '[:upper:]' '[:lower:]')" in
    nam|male|man|giọng-nam|giong-nam)
      printf '%s' "vi-VN-NamMinhNeural"
      ;;
    "")
      printf '%s' "$OPENCLAW_DEFAULT_TTS_VOICE"
      ;;
    nu|nữ|female|woman|giọng-nữ|giong-nu|hoaimy|hoai-my)
      printf '%s' "vi-VN-HoaiMyNeural"
      ;;
    resona)
      printf '%s' "resona:${RESONA_DEFAULT_VOICE_ID:-ZJEpWoOyElCKuEljNTkm}"
      ;;
    resona:*)
      printf '%s' "$preset"
      ;;
    ai33|vbee|vbee-maiphuong|vbee-mai-phuong|maiphuong|mai-phuong|mai_phuong|elevenlabs|elevenlabs-phanh|eleven-phanh|phanh|phan|ai33:*|elevenlabs_*|vbee_*)
      if [[ -f "$VOICE_REGISTRY_PY" ]] && normalized="$(python3 "$VOICE_REGISTRY_PY" normalize-ai33 "$preset" 2>/dev/null)"; then
        printf '%s' "$normalized"
        return 0
      fi
      echo "VoiceInvalid: AI33 voice không nằm trong registry: $preset" >&2
      return 64
      ;;
    kokoro)
      printf '%s' "kokoro:${KOKORO_DEFAULT_VOICE:-mai_linh}"
      ;;
    kokoro:*)
      printf '%s' "$preset"
      ;;
    diem_trinh|duc_an|duc_duy|hung_thinh|mai_linh|mai_loan|manh_dung|my_yen|ngoc_huyen|phat_tai|storyvert|thanh_dat|thuc_trinh|tuan_ngoc)
      printf '%s' "kokoro:$(printf '%s' "$preset" | tr '[:upper:]' '[:lower:]')"
      ;;
    capcut:*)
      echo "VoiceInvalid: CapCut TTS đã tắt khỏi pipeline. Dùng kokoro:<voice>, AI33 registry, resona, nam, nu hoặc vi-vn-*." >&2
      return 64
      ;;
    vi-vn-*)
      printf '%s' "$preset"
      ;;
    *)
      echo "VoiceInvalid: preset giọng không hỗ trợ: $preset" >&2
      return 64
      ;;
  esac
}

VOICE="$(resolve_voice "$VOICE_PRESET")" || exit $?
DOUYIN_STEALTH_PATH="${DOUYIN_STEALTH_PATH:-$HOME/.openclaw/workspace/skills/douyin-stealth/scripts/fetch_douyin_v2.py}"
DOUYIN_CLEAN_MEDIA_RESOLVER="${DOUYIN_CLEAN_MEDIA_RESOLVER:-1}"
DOUYIN_CLEAN_ONLY_DEFAULT="${DOUYIN_CLEAN_ONLY_DEFAULT:-0}"
DOUYIN_ALLOW_WATERMARKED_FALLBACK="${DOUYIN_ALLOW_WATERMARKED_FALLBACK:-1}"
CAPCUT_TTS_WRAPPER="${CAPCUT_TTS_WRAPPER:-$SKILL_DIR/capcut_tts_synthesize.py}"
CAPCUT_TTS_VOICES_JSON="${CAPCUT_TTS_VOICES_JSON:-$SKILL_DIR/capcut_voices.json}"
CAPCUT_TTS_EDGE_FALLBACK_VOICE="${CAPCUT_TTS_EDGE_FALLBACK_VOICE:-vi-VN-HoaiMyNeural}"
RESONA_TTS_WRAPPER="${RESONA_TTS_WRAPPER:-$SKILL_DIR/resona_tts_synthesize.py}"
RESONA_API_BASE="${RESONA_API_BASE:-https://resona.live}"
RESONA_DEFAULT_VOICE_ID="${RESONA_DEFAULT_VOICE_ID:-ZJEpWoOyElCKuEljNTkm}"
RESONA_TUE_AN_VOICE_ID="${RESONA_TUE_AN_VOICE_ID:-0phiCO46biYtwYYP0DIR}"
AI33_TTS_WRAPPER="${AI33_TTS_WRAPPER:-$SKILL_DIR/ai33_tts_synthesize.py}"
AI33_API_BASE="${AI33_API_BASE:-https://api.ai33.pro}"
KOKORO_VOICES_JSON="${KOKORO_VOICES_JSON:-$SKILL_DIR/kokoro_voices.json}"
KOKORO_TTS_PYTHON="${KOKORO_TTS_PYTHON:-$HOME/.local/share/openclaw-kokoro-venv/bin/python}"
KOKORO_TTS_DEVICE="${KOKORO_TTS_DEVICE:-cpu}"
KOKORO_TTS_SPEED="${KOKORO_TTS_SPEED:-1.0}"
KOKORO_TTS_CROSSFADE_MS="${KOKORO_TTS_CROSSFADE_MS:-50}"
KOKORO_TTS_NORMALIZE_PEAK="${KOKORO_TTS_NORMALIZE_PEAK:-}"
KOKORO_TTS_REPO_ID="${KOKORO_TTS_REPO_ID:-contextboxai/Kokoro-Vietnamese}"
KOKORO_TTS_MODEL="${KOKORO_TTS_MODEL:-}"
KOKORO_TTS_CONFIG="${KOKORO_TTS_CONFIG:-}"
KOKORO_TTS_VOICEPACK="${KOKORO_TTS_VOICEPACK:-}"
# Comma-separated Resona voice IDs to try if the primary voice fails the pre-TTS probe.
# Empty = single voice (fail loud on probe fail). No silent Edge fallback.
RESONA_FALLBACK_VOICE_IDS="${RESONA_FALLBACK_VOICE_IDS:-}"
: "${RESONA_API_TOKEN:=${RESONA_ACCESS_TOKEN:-}}"
RESONA_MIN_CHARS="${RESONA_MIN_CHARS:-50}"
RESONA_MAX_CHARS="${RESONA_MAX_CHARS:-2000}"
RESONA_SHORT_TEXT_POLICY="${RESONA_SHORT_TEXT_POLICY:-group_or_fail}"
RESONA_SHORT_GROUP_ENABLED="${RESONA_SHORT_GROUP_ENABLED:-1}"
RESONA_SHORT_GROUP_MAX_CUES="${RESONA_SHORT_GROUP_MAX_CUES:-8}"
RESONA_SHORT_GROUP_SOFT_MAX_DURATION_SECONDS="${RESONA_SHORT_GROUP_SOFT_MAX_DURATION_SECONDS:-12}"
RESONA_SHORT_GROUP_HARD_MAX_DURATION_SECONDS="${RESONA_SHORT_GROUP_HARD_MAX_DURATION_SECONDS:-18}"
RESONA_SHORT_GROUP_MAX_INTERNAL_GAP_MS="${RESONA_SHORT_GROUP_MAX_INTERNAL_GAP_MS:-2500}"
RESONA_SHORT_GROUP_MAX_DURATION_SECONDS="${RESONA_SHORT_GROUP_MAX_DURATION_SECONDS:-12}"
RESONA_POLL_INTERVAL_SECONDS="${RESONA_POLL_INTERVAL_SECONDS:-2}"
RESONA_TIMEOUT_SECONDS="${RESONA_TIMEOUT_SECONDS:-180}"
: "${AI33_API_KEY:=${AI33_ACCESS_TOKEN:-}}"
AI33_TTS_SPEED="${AI33_TTS_SPEED:-1.0}"
AI33_WITH_TRANSCRIPT="${AI33_WITH_TRANSCRIPT:-false}"
AI33_CONTEXT_CHAINING="${AI33_CONTEXT_CHAINING:-false}"
AI33_PRONUNCIATION_DICTIONARY_ID="${AI33_PRONUNCIATION_DICTIONARY_ID:-}"
AI33_POLL_INTERVAL_SECONDS="${AI33_POLL_INTERVAL_SECONDS:-2}"
AI33_TIMEOUT_SECONDS="${AI33_TIMEOUT_SECONDS:-180}"
AI33_CIRCUIT_BREAKER_FAILURES="${AI33_CIRCUIT_BREAKER_FAILURES:-2}"
AI33_CIRCUIT_COOLDOWN_SECONDS="${AI33_CIRCUIT_COOLDOWN_SECONDS:-60}"
if [[ "${VOICE,,}" == resona* && "${RESONA_ALLOW_EDGE_FALLBACK:-0}" != "1" && "${RESONA_SHORT_TEXT_POLICY,,}" == "edge" ]]; then
  echo "WARN: Resona voice requested but RESONA_SHORT_TEXT_POLICY=edge; forcing group_or_fail so failed/short Resona segments do not become Edge fallback."
  RESONA_SHORT_TEXT_POLICY="group_or_fail"
fi
TIMING_OPTIMIZER_SCRIPT="${VIET_DUB_TIMING_OPTIMIZER_SCRIPT:-$SKILL_DIR/viet_dub_timing_optimizer.py}"
TRANSLATION_MEMORY_CONTEXT_SCRIPT="${TRANSLATION_MEMORY_CONTEXT_SCRIPT:-$SKILL_DIR/translation_memory_context.py}"
TRANSLATION_MEMORY_DIR="${TRANSLATION_MEMORY_DIR:-$SKILL_DIR/translation_memory}"
TRANSLATION_MEMORY_MAX_CHARS="${TRANSLATION_MEMORY_MAX_CHARS:-6000}"
TRANSLATION_MEMORY_ENABLED="${TRANSLATION_MEMORY_ENABLED:-1}"
TRANSLATION_SERIES_ID="${TRANSLATION_SERIES_ID:-${SERIES_ID:-}}"
TRANSLATION_GENRE_TAGS="${TRANSLATION_GENRE_TAGS:-}"
SPEECH_ONLY_PREPROCESS_SCRIPT="${SPEECH_ONLY_PREPROCESS_SCRIPT:-$SKILL_DIR/speech_only_preprocess.py}"
ASR_POSTPROCESS_SCRIPT="${ASR_POSTPROCESS_SCRIPT:-$SKILL_DIR/postprocess_asr_srt.py}"
OCR_TRANSCRIPT_SCRIPT="${OCR_TRANSCRIPT_SCRIPT:-$SKILL_DIR/ocr_subtitle_transcript.py}"
TRANSCRIPT_DECISION_SCRIPT="${TRANSCRIPT_DECISION_SCRIPT:-$SKILL_DIR/choose_transcript_source.py}"
ORGANIZE_OUTPUT_SCRIPT="${ORGANIZE_OUTPUT_SCRIPT:-$SKILL_DIR/organize_output.py}"
SUBTITLE_MASK_RENDER_SCRIPT="${SUBTITLE_MASK_RENDER_SCRIPT:-$SKILL_DIR/subtitle_mask_render.py}"
TTS_VOICE_QUALITY_SCRIPT="${TTS_VOICE_QUALITY_SCRIPT:-$SKILL_DIR/tts_voice_quality.py}"
SUBTITLE_MASK_RENDER_PYTHON="${SUBTITLE_MASK_RENDER_PYTHON:-/home/haonguyen/.venvs/openclaw-paddleocr/bin/python}"
if [[ ! -x "$SUBTITLE_MASK_RENDER_PYTHON" ]]; then
  SUBTITLE_MASK_RENDER_PYTHON="$(command -v python3)"
fi
TELEGRAM_RESULT_SCRIPT="${TELEGRAM_RESULT_SCRIPT:-$SKILL_DIR/telegram-send-result.sh}"
TELEGRAM_RESULT_TIMEOUT="${TELEGRAM_RESULT_TIMEOUT:-600}"
AUTO_TELEGRAM_RESULT="${AUTO_TELEGRAM_RESULT:-1}"
SUBTITLE_TRANSCRIPT_SOURCE="${SUBTITLE_TRANSCRIPT_SOURCE:-auto}"
OCR_TRANSCRIPT_REBUILD="${OCR_TRANSCRIPT_REBUILD:-0}"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
RESUME_JOB_DIR="${OPENCLAW_RESUME_JOB_DIR:-${DOUYIN_RESUME_JOB_DIR:-}}"
DOCTOR_MODE=0

if [[ "${INPUT:-}" == "--doctor" || "${INPUT:-}" == "doctor" ]]; then
  DOCTOR_MODE=1
fi

slugify_name() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$1" <<'PY'
import os, re, sys, unicodedata
name = sys.argv[1].strip() or 'video'
name = os.path.splitext(os.path.basename(name))[0]
name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
name = re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-._').lower()
print(name or 'video', end='')
PY
    return 0
  fi

  local name="${1##*/}"
  name="${name%.*}"
  name="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g; s/--*/-/g; s/^[._-]*//; s/[._-]*$//')"
  printf '%s' "${name:-video}"
}

SOURCE_NAME="$INPUT"
if [[ "$INPUT" =~ ^https?:// ]]; then
  SOURCE_NAME="video-$RUN_ID"
fi
OUT_DIR="$BASE_DIR/$(slugify_name "$SOURCE_NAME")-$RUN_ID"
if [[ -n "$RESUME_JOB_DIR" ]]; then
  OUT_DIR="$RESUME_JOB_DIR"
fi
LOG="$OUT_DIR/log.txt"
SOURCE_INPUT_TXT="$OUT_DIR/source_input.txt"
LATEST_SOURCE_TXT="$BASE_DIR/LATEST_SOURCE_URL.txt"
LATEST_OUTPUT_TXT="$BASE_DIR/LATEST_OUTPUT_DIR.txt"
THUMBNAIL_SCRIPT="${YOUTUBE_THUMBNAIL_SCRIPT:-${GOOGLE_FLOW_THUMBNAIL_SCRIPT:-/home/haonguyen/.openclaw/workspace/skills/google-flow-thumbnail/google-flow-thumbnail.sh}}"
THUMBNAIL_FILE="$OUT_DIR/thumbnail.jpg"
FINAL_METADATA_JSON="$OUT_DIR/final_metadata.json"
STATUS_WRITER="${OPENCLAW_STATUS_WRITER:-/app/tools/status_writer.py}"
STATUS_WRITER_TIMEOUT_SECONDS="${OPENCLAW_STATUS_WRITER_TIMEOUT_SECONDS:-5}"
if ! [[ "$STATUS_WRITER_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || [[ "$STATUS_WRITER_TIMEOUT_SECONDS" -lt 1 ]]; then
  STATUS_WRITER_TIMEOUT_SECONDS=5
fi
TIMEOUT_STATUS_WRITER_TIMEOUT_SECONDS="${OPENCLAW_TIMEOUT_STATUS_WRITER_TIMEOUT_SECONDS:-1}"
if ! [[ "$TIMEOUT_STATUS_WRITER_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || [[ "$TIMEOUT_STATUS_WRITER_TIMEOUT_SECONDS" -lt 1 ]]; then
  TIMEOUT_STATUS_WRITER_TIMEOUT_SECONDS=1
fi
GUARDED_TERMINATION_GRACE_SECONDS="${OPENCLAW_GUARDED_TERMINATION_GRACE_SECONDS:-1}"
if ! [[ "$GUARDED_TERMINATION_GRACE_SECONDS" =~ ^[0-9]+$ ]] || [[ "$GUARDED_TERMINATION_GRACE_SECONDS" -lt 1 ]]; then
  GUARDED_TERMINATION_GRACE_SECONDS=1
fi
STATUS_FILE="$OUT_DIR/job_status.json"

status_update() {
  local phase="$1"
  local progress="$2"
  local label="$3"
  local api_expected="${4:-0}"
  local error_code="${5:-}"
  local error_message="${6:-}"
  if [[ -x "$STATUS_WRITER" && -d "${OUT_DIR:-}" ]]; then
    timeout --kill-after=1 "$STATUS_WRITER_TIMEOUT_SECONDS" "$STATUS_WRITER" "$OUT_DIR" "$phase" "$progress" "$label" "$api_expected" "$error_code" "$error_message" >/dev/null 2>&1 || true
  fi
}

status_add_failure_context() {
  local reason="$1"
  local retry_action="$2"
  shift 2
  [[ -s "$STATUS_FILE" ]] || return 0
  python3 - "$STATUS_FILE" "$reason" "$retry_action" "$@" <<'PY' || true
import json, os, sys
from pathlib import Path

status_path = Path(sys.argv[1])
try:
    status = json.loads(status_path.read_text(encoding="utf-8"))
except Exception:
    status = {}
artifacts = {}
for raw in sys.argv[4:]:
    path = Path(raw)
    if path.is_file():
        artifacts[path.name] = str(path)
status["reason"] = sys.argv[2]
status["retry_action"] = sys.argv[3]
status["artifacts"] = artifacts
tmp = status_path.with_name(status_path.name + ".tmp")
tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, status_path)
PY
}

run_with_status_heartbeat() {
  local phase="$1"
  local progress="$2"
  local label="$3"
  local timeout_seconds="$4"
  local interval_seconds="${5:-30}"
  shift 5
  local started_at child_pid heartbeat_pid exit_status elapsed
  started_at="$(date +%s)"
  "$@" &
  child_pid=$!
  (
    while kill -0 "$child_pid" >/dev/null 2>&1; do
      sleep "$interval_seconds" || true
      if kill -0 "$child_pid" >/dev/null 2>&1; then
        elapsed=$(( $(date +%s) - started_at ))
        status_update "$phase" "$progress" "$label (${elapsed}s/${timeout_seconds}s)" "0"
      fi
    done
  ) &
  heartbeat_pid=$!
  wait "$child_pid"
  exit_status=$?
  kill "$heartbeat_pid" >/dev/null 2>&1 || true
  wait "$heartbeat_pid" 2>/dev/null || true
  return "$exit_status"
}

process_group_id() {
  ps -o pgid= -p "$1" 2>/dev/null | tr -d ' '
}

terminate_process_tree() {
  local root_pid="$1"
  local signal_name="$2"
  local pending="$root_pid"
  local targets="$root_pid"
  local current_pid children child_pid
  while [[ -n "$pending" ]]; do
    current_pid="${pending%% *}"
    pending="${pending#* }"
    [[ "$pending" == "$current_pid" ]] && pending=""
    children="$(pgrep -P "$current_pid" 2>/dev/null || true)"
    for child_pid in $children; do
      targets+=" $child_pid"
      pending+=" $child_pid"
    done
  done
  # Only explicit PIDs are ever signalled, so this cannot reach the parent
  # shell's process group.
  for current_pid in $targets; do
    [[ "$current_pid" == "$$" ]] || kill "-$signal_name" "$current_pid" >/dev/null 2>&1 || true
  done
}

run_with_status_heartbeat_guarded() {
  local phase="$1"
  local progress="$2"
  local label="$3"
  local timeout_seconds="$4"
  local interval_seconds="${5:-30}"
  shift 5
  local started_at child_pid child_pgid shell_pgid exit_status elapsed sleep_seconds remaining_seconds timed_out=0 monitor_was_enabled=0
  local timeout_status_writer_timeout_seconds="${TIMEOUT_STATUS_WRITER_TIMEOUT_SECONDS:-1}"
  local termination_grace_seconds="${GUARDED_TERMINATION_GRACE_SECONDS:-1}"
  started_at="$(date +%s)"
  case "$-" in
    *m*) monitor_was_enabled=1 ;;
  esac
  # Bash job control gives this subshell its own process group while retaining
  # access to shell functions passed by the TTS caller.
  set -m
  ( "$@" ) &
  child_pid=$!
  child_pgid="$(process_group_id "$child_pid" || true)"
  shell_pgid="$(process_group_id "$$" || true)"
  [[ "$monitor_was_enabled" -eq 1 ]] || set +m
  # A short-lived shell function may already be complete before `ps` observes
  # it. Its exit is safe to propagate directly; there is no running command to
  # isolate or terminate.
  if ! jobs -pr | grep -qx "$child_pid"; then
    wait "$child_pid"
    return $?
  fi
  if [[ -z "$child_pgid" || "$child_pgid" == "$shell_pgid" ]]; then
    # Without a verified distinct PGID we must not risk a group signal. Stop
    # the child tree immediately and report a distinct internal failure.
    terminate_process_tree "$child_pid" TERM
    STATUS_WRITER_TIMEOUT_SECONDS="$timeout_status_writer_timeout_seconds" status_update "$phase" "$progress" "$label process-group setup failed" "0" "GuardedProcessGroupUnavailable" "cannot verify isolated child process group"
    sleep "$termination_grace_seconds" || true
    terminate_process_tree "$child_pid" KILL
    wait "$child_pid" 2>/dev/null || true
    return 125
  fi
  while kill -0 "$child_pid" >/dev/null 2>&1; do
    elapsed=$(( $(date +%s) - started_at ))
    sleep_seconds="$interval_seconds"
    if [[ "$timeout_seconds" =~ ^[0-9]+$ && "$timeout_seconds" -gt 0 ]]; then
      remaining_seconds=$(( timeout_seconds - elapsed ))
      if [[ "$remaining_seconds" -lt "$sleep_seconds" ]]; then
        sleep_seconds="$remaining_seconds"
      fi
    fi
    sleep "$sleep_seconds" || true
    if ! kill -0 "$child_pid" >/dev/null 2>&1; then
      break
    fi
    elapsed=$(( $(date +%s) - started_at ))
    if [[ "$timeout_seconds" =~ ^[0-9]+$ && "$timeout_seconds" -gt 0 && "$elapsed" -ge "$timeout_seconds" ]]; then
      kill -TERM -- "-$child_pgid" >/dev/null 2>&1 || true
      STATUS_WRITER_TIMEOUT_SECONDS="$timeout_status_writer_timeout_seconds" status_update "$phase" "$progress" "$label timeout (${elapsed}s/${timeout_seconds}s)" "0" "StepTimeout" "$phase exceeded ${timeout_seconds}s"
      sleep "$termination_grace_seconds" || true
      if kill -0 "$child_pid" >/dev/null 2>&1; then
        kill -KILL -- "-$child_pgid" >/dev/null 2>&1 || true
      fi
      timed_out=1
      break
    fi
    status_update "$phase" "$progress" "$label (${elapsed}s/${timeout_seconds}s)" "0"
  done
  wait "$child_pid"
  exit_status=$?
  if [[ "$timed_out" -eq 1 ]]; then
    return 124
  fi
  return "$exit_status"
}

fail() {
  echo "ERROR: $*" >&2
  status_update "error" "0" "Lỗi pipeline" "0" "PipelineError" "$*"
  if [[ -n "${OUT_DIR:-}" ]]; then
    echo "Output giữ lại tại: $OUT_DIR" >&2
  fi
  exit 1
}

append_tts_audio_stage_report() {
  local report_path="$1" stage="$2" audio_path="$3" expected_sample_rate="${4:-48000}"
  python3 - "$report_path" "$stage" "$audio_path" "$expected_sample_rate" <<'PY'
import json, subprocess, sys
from pathlib import Path

report_path, audio_path = map(Path, (sys.argv[1], sys.argv[3]))
stage = sys.argv[2]
expected_sample_rate = int(sys.argv[4])
try:
    raw = subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=sample_rate,channels,codec_name:format=duration',
        '-of', 'json', str(audio_path),
    ], text=True)
    probe = json.loads(raw)
    stream = (probe.get('streams') or [{}])[0]
    item = {
        'stage': str(stage), 'file_path': str(audio_path),
        'sample_rate': int(stream.get('sample_rate') or 0),
        'channels': int(stream.get('channels') or 0),
        'codec': stream.get('codec_name') or '',
        'duration_ms': int(round(float((probe.get('format') or {}).get('duration') or 0) * 1000)),
    }
    try:
        report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    except Exception:
        report = {}
    stages = report.get('stages') if isinstance(report.get('stages'), list) else []
    warnings = report.get('warnings') if isinstance(report.get('warnings'), list) else []
    stages.append(item)
    sample_rate_error = None
    if str(stage).startswith(('tts_', 'voice_', 'final_')) and item['sample_rate'] != expected_sample_rate:
        sample_rate_error = (
            f"TTS_CANONICAL_SAMPLE_RATE_MISMATCH stage={stage} "
            f"expected={expected_sample_rate} actual={item['sample_rate']}"
        )
        if item['sample_rate'] == 16000 and 'TTS_MASTER_DOWNGRADED_TO_ASR_FORMAT' not in warnings:
            warnings.append('TTS_MASTER_DOWNGRADED_TO_ASR_FORMAT')
        if sample_rate_error not in warnings:
            warnings.append(sample_rate_error)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({'stages': stages, 'warnings': warnings}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if sample_rate_error:
        raise SystemExit(sample_rate_error)
except Exception as exc:
    raise SystemExit(f'TTS_AUDIO_STAGE_REPORT_FAILED stage={stage}: {exc}')
PY
}

on_pipeline_exit() {
  local code=$?
  trap - EXIT
  if [[ "$code" -ne 0 && -n "${OUT_DIR:-}" && -d "${OUT_DIR:-}" ]]; then
    local state_phase current_state current_phase current_progress
    state_phase="$(python3 - "$STATUS_FILE" <<'PY' 2>/dev/null || true
import json, sys
path = sys.argv[1]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    data = {}
print("{}\t{}\t{}".format(
    data.get("state") or "",
    data.get("phase") or "",
    data.get("progress_percent") or "0",
))
PY
)"
    IFS=$'\t' read -r current_state current_phase current_progress <<< "$state_phase"
    if [[ -z "$current_state" || "$current_state" == "running" || "$current_state" == "queued" || "$current_state" == "warning" ]]; then
      status_update "error" "${current_progress:-0}" "Pipeline dừng bất thường" "0" "PipelineError" "Pipeline exited unexpectedly with code $code during ${current_phase:-unknown}; finalized stale running status."
    fi
  fi
  exit "$code"
}
trap on_pipeline_exit EXIT

get_ninerouter_api_key() {
  if [[ -n "${NINEROUTER_API_KEY:-}" ]]; then
    printf '%s' "$NINEROUTER_API_KEY"
    return 0
  fi
  python3 - <<'PY'
import json, os, sys
candidates = []
if os.environ.get('NINEROUTER_DB_PATH'):
    candidates.append(os.environ['NINEROUTER_DB_PATH'])
for raw in ('~/.9router/db.json', '/app/data/db.json'):
    candidates.append(os.path.expanduser(raw))
seen = set()
for path in candidates:
    if not path or path in seen:
        continue
    seen.add(path)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            db = json.load(f)
    except Exception:
        continue
    for item in db.get('apiKeys') or []:
        key = item.get('key') if isinstance(item, dict) else None
        if key:
            print(key, end='')
            sys.exit(0)

# OpenClaw container fallback: reuse configured OpenAI-compatible provider key.
for raw in ('~/.openclaw/openclaw.json', '~/.openclaw/agents/main/agent/models.json'):
    path = os.path.expanduser(raw)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        continue
    providers = ((cfg.get('models') or {}).get('providers') or cfg.get('providers') or {})
    preferred = ['combo3in1', 'combo_gemini', 'combo_openrouter', 'combo_kyma', 'chattool']
    for name in preferred + list(providers.keys()):
        provider = providers.get(name) if isinstance(providers, dict) else None
        if not isinstance(provider, dict):
            continue
        key = provider.get('apiKey')
        base_url = str(provider.get('baseUrl') or '')
        if key and ('20128' in base_url or name in preferred):
            print(key, end='')
            sys.exit(0)
sys.exit(1)
PY
}

get_api_key() {
  if [[ "${OPENCLAW_AI_PROVIDER:-ninerouter}" == "ollama" ]]; then
    return 0
  fi
  get_ninerouter_api_key
}

check_api_base() {
  local api_key="${1:-}"
  if [[ "${OPENCLAW_AI_PROVIDER:-ninerouter}" == "ollama" ]]; then
    python3 - "$API_BASE" <<'PY'
import json, sys, urllib.request
api_base = sys.argv[1]
url = api_base.rstrip('/') + '/api/tags'
try:
    with urllib.request.urlopen(url, timeout=5) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    models = [str(item.get('model') or item.get('name') or '') for item in data.get('models') or []]
    if models:
        sys.exit(0)
except Exception:
    pass
sys.exit(1)
PY
    return $?
  fi
  python3 - "$API_BASE" "$api_key" <<'PY'
import json, sys, urllib.request, urllib.error
api_base, api_key = sys.argv[1:]
url = api_base.rstrip('/') + '/models'
headers = {}
if api_key:
    headers['Authorization'] = 'Bearer ' + api_key
req = urllib.request.Request(url, headers=headers, method='GET')
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        if 200 <= resp.status < 500:
            sys.exit(0)
except urllib.error.HTTPError as e:
    if e.code in (401, 403, 404):
        sys.exit(0)
except Exception:
    pass
sys.exit(1)
PY
}

print_check() {
  local name="$1"
  local status="$2"
  local detail="${3:-}"
  if [[ "$status" == "OK" ]]; then
    printf 'OK   %-24s %s\n' "$name" "$detail"
  elif [[ "$status" == "WARN" ]]; then
    printf 'WARN %-24s %s\n' "$name" "$detail"
  else
    printf 'FAIL %-24s %s\n' "$name" "$detail"
  fi
}

run_doctor() {
  local failures=0
  local api_key=""
  echo "douyin-vietnamese-dubber doctor"
  echo "Runtime HOME=$HOME"
  echo "BASE_DIR=$BASE_DIR"
  echo "WHISPER_BIN=$WHISPER_BIN"
  echo "WHISPER_MODEL=$WHISPER_MODEL"
  echo "AI_PROVIDER=$OPENCLAW_AI_PROVIDER"
  echo "AI_MODEL=$MODEL"
  echo "AI_API_BASE=$API_BASE"

  for cmd in ffmpeg python3 curl yt-dlp; do
    if command -v "$cmd" >/dev/null 2>&1; then
      print_check "$cmd" OK "$(command -v "$cmd")"
    else
      print_check "$cmd" FAIL "not found in PATH"
      failures=$((failures + 1))
    fi
  done

  local voice_lower
  voice_lower="$(printf '%s' "${VOICE:-}" | tr '[:upper:]' '[:lower:]')"
  if [[ "$voice_lower" == kokoro:* ]]; then
    if [[ -x "$KOKORO_TTS_PYTHON" ]] && "$KOKORO_TTS_PYTHON" - <<'PY' >/dev/null 2>&1
from kokoro_vietnamese import KokoroVietnamese, SAMPLE_RATE
PY
    then
      print_check "Kokoro runtime" OK "$KOKORO_TTS_PYTHON voice=${voice_lower#kokoro:} device=$KOKORO_TTS_DEVICE"
    else
      print_check "Kokoro runtime" FAIL "không import được kokoro_vietnamese từ $KOKORO_TTS_PYTHON"
      failures=$((failures + 1))
    fi
  elif [[ "$voice_lower" == ai33:* ]]; then
    print_check "edge-tts" WARN "not needed for AI33 voice"
  elif [[ "$voice_lower" == resona:* ]]; then
    print_check "edge-tts" WARN "not needed for Resona voice"
  else
    if command -v edge-tts >/dev/null 2>&1; then
      print_check "edge-tts" OK "$(command -v edge-tts)"
    elif [[ -n "$EDGE_TTS_BIN" && -x "$EDGE_TTS_BIN" ]]; then
      print_check "edge-tts" OK "$EDGE_TTS_BIN (ngoài PATH; fallback EDGE_TTS_BIN)"
    else
      print_check "edge-tts" FAIL "not found in PATH"
      failures=$((failures + 1))
    fi
  fi

  if command -v demucs >/dev/null 2>&1; then
    print_check "demucs" OK "$(command -v demucs)"
  else
    print_check "demucs" WARN "not found; speech-only preprocess sẽ fallback sang audio gốc/vocals fallback"
  fi

  if python3 - <<'PY' >/dev/null 2>&1
import inaSpeechSegmenter
PY
  then
    print_check "inaSpeechSegmenter" OK "available"
  else
    print_check "inaSpeechSegmenter" WARN "not found; speech-only preprocess sẽ dùng energy VAD fallback"
  fi

  if [[ -x "$WHISPER_BIN" ]]; then
    print_check "WHISPER_BIN" OK "$WHISPER_BIN"
  else
    print_check "WHISPER_BIN" FAIL "missing or not executable"
    failures=$((failures + 1))
  fi

  if [[ -f "$WHISPER_MODEL" ]]; then
    print_check "WHISPER_MODEL" OK "$WHISPER_MODEL"
  else
    print_check "WHISPER_MODEL" FAIL "missing model file"
    failures=$((failures + 1))
  fi

  if command -v vulkaninfo >/dev/null 2>&1; then
    if vulkaninfo --summary 2>/dev/null | grep -q "AMD Radeon RX 6600"; then
      print_check "VULKAN_GPU" OK "AMD Radeon RX 6600 visible"
    else
      print_check "VULKAN_GPU" WARN "vulkaninfo chạy được nhưng chưa thấy AMD Radeon RX 6600"
    fi
  else
    print_check "vulkaninfo" WARN "not found; cài vulkan-tools nếu cần debug GPU"
  fi

  if [[ -e /dev/dri/renderD128 ]]; then
    if [[ -r /dev/dri/renderD128 && -w /dev/dri/renderD128 ]]; then
      print_check "DRI_RENDER" OK "/dev/dri/renderD128 writable"
    else
      print_check "DRI_RENDER" WARN "/dev/dri/renderD128 tồn tại nhưng user hiện tại chưa có quyền; chạy: sudo usermod -aG render,video haonguyen rồi logout/login hoặc reboot"
    fi
  else
    print_check "DRI_RENDER" WARN "không thấy /dev/dri/renderD128 trong runtime này"
  fi

  if api_key="$(get_api_key)"; then
    if [[ "$OPENCLAW_AI_PROVIDER" == "ollama" ]]; then
      print_check "AI auth" OK "Ollama local session"
    else
      print_check "API key" OK "available (value hidden)"
    fi
  else
    print_check "API key" FAIL "set NINEROUTER_API_KEY or NINEROUTER_DB_PATH"
    failures=$((failures + 1))
  fi

  if check_api_base "$api_key"; then
    print_check "AI_API_BASE" OK "$API_BASE"
  else
    print_check "AI_API_BASE" FAIL "cannot connect to $API_BASE"
    failures=$((failures + 1))
  fi

  # Vision OCR engine (9router MiniMax M3 multimodal) cho subtitle gốc.
  echo "OCR_ENGINE=$SUBTITLE_OCR_ENGINE MASK_DETECT_ENGINE=$SUBTITLE_BAND_DETECT_ENGINE VISION_MODEL=$OCR_VISION_MODEL"
  if [[ "$SUBTITLE_OCR_ENGINE" == "9router_vision" || "$SUBTITLE_BAND_DETECT_ENGINE" == "9router_vision" ]]; then
    if "$SUBTITLE_MASK_RENDER_PYTHON" -c "import nine_router_vision" >/dev/null 2>&1; then
      print_check "Vision module" OK "nine_router_vision import OK"
    else
      print_check "Vision module" FAIL "nine_router_vision.py không import được (PYTHONPATH phải chứa skill dir)"
      failures=$((failures + 1))
    fi
    if python3 - "$API_BASE" "$api_key" "$OCR_VISION_MODEL" >/dev/null 2>&1 <<'PY'
import json, sys, urllib.request
api_base, api_key, model = sys.argv[1:4]
url = api_base.rstrip("/") + "/chat/completions"
payload = {"model": model, "messages": [{"role": "user", "content": "Reply only the word OK"}], "stream": False, "think": False, "max_tokens": 64}
headers = {"Content-Type": "application/json"}
if api_key:
    headers["Authorization"] = "Bearer " + api_key
req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
with urllib.request.urlopen(req, timeout=20) as resp:
    d = json.loads(resp.read().decode("utf-8", "replace"))
content = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
sys.exit(0 if content else 1)
PY
    then
      print_check "Vision model" OK "$OCR_VISION_MODEL responds"
    else
      print_check "Vision model" WARN "$OCR_VISION_MODEL không respond; OCR/mask sẽ fallback PaddleOCR/CV/blur_band"
    fi
  fi

  if mkdir -p "$BASE_DIR" "$BASE_DIR/translated" "$BASE_DIR/temp" 2>/dev/null && [[ -w "$BASE_DIR" ]]; then
    print_check "output dir" OK "$BASE_DIR writable"
  else
    print_check "output dir" FAIL "$BASE_DIR not writable"
    failures=$((failures + 1))
  fi

  # AI33 TTS doctor (không print key bao giờ).
  local ai33_voice_lower
  ai33_voice_lower="$(printf '%s' "${VOICE:-${VOICE_PRESET:-}}" | tr '[:upper:]' '[:lower:]')"
  local ai33_is_default=0
  case "$ai33_voice_lower" in
    ai33|ai33:*|vbee|vbee-*|vbee_*|maiphuong|mai-phuong|mai_phuong|elevenlabs|elevenlabs-*|elevenlabs_*|phanh|phan) ai33_is_default=1 ;;
  esac
  if [[ -f "$AI33_TTS_WRAPPER" ]]; then
    print_check "ai33 adapter" OK "$AI33_TTS_WRAPPER"
  elif [[ "$ai33_is_default" -eq 1 ]]; then
    print_check "ai33 adapter" FAIL "Thiếu $AI33_TTS_WRAPPER"
    failures=$((failures + 1))
  else
    print_check "ai33 adapter" WARN "Thiếu $AI33_TTS_WRAPPER (không dùng AI33 cho job này, bỏ qua)"
  fi
  if [[ -n "$AI33_API_KEY" ]]; then
    print_check "ai33 key" OK "env AI33_API_KEY set (không print giá trị)"
  else
    if [[ "$ai33_is_default" -eq 1 ]]; then
      print_check "ai33 key" FAIL "Thiếu AI33_API_KEY/AI33_ACCESS_TOKEN (AI33 là giọng được chọn)"
      failures=$((failures + 1))
    else
      print_check "ai33 key" WARN "Thiếu AI33_API_KEY (không dùng AI33 cho job này, bỏ qua)"
    fi
  fi
  print_check "ai33 voice" OK "selected=${VOICE:-} registry=${OPENCLAW_DEFAULT_TTS_VOICE} maiphuong=${AI33_MAI_PHUONG_VOICE_ID} phanh=${AI33_PHANH_VOICE_ID}"
  if [[ -n "$AI33_API_KEY" && "${OPENCLAW_DOCTOR_ONLINE:-0}" == "1" ]]; then
    if python3 - "$AI33_API_BASE" "$AI33_API_KEY" >/dev/null 2>&1 <<'PY'
import sys, urllib.request, urllib.error
api_base, api_key = sys.argv[1:3]
url = api_base.rstrip('/') + '/v1/credits'
headers = {'xi-api-key': api_key, 'Accept': 'application/json'}
try:
    req = urllib.request.Request(url, headers=headers, method='GET')
    urllib.request.urlopen(req, timeout=8)
    sys.exit(0)
except urllib.error.HTTPError as e:
    sys.exit(0 if e.code in (401, 403, 404) else 1)
except Exception:
    sys.exit(1)
PY
    then
      print_check "ai33 api" OK "$AI33_API_BASE reachable"
    else
      print_check "ai33 api" WARN "$AI33_API_BASE không reach được (kiểm tra mạng/proxy)"
    fi
  fi

  # Resona TTS doctor (không print token bao giờ).
  local resona_voice_lower
  resona_voice_lower="$(printf '%s' "${VOICE:-${VOICE_PRESET:-}}" | tr '[:upper:]' '[:lower:]')"
  local resona_is_default=0
  case "$resona_voice_lower" in
    resona|resona:*) resona_is_default=1 ;;
  esac
  if [[ -f "$RESONA_TTS_WRAPPER" ]]; then
    print_check "resona adapter" OK "$RESONA_TTS_WRAPPER"
  elif [[ "$resona_is_default" -eq 1 ]]; then
    print_check "resona adapter" FAIL "Thiếu $RESONA_TTS_WRAPPER"
    failures=$((failures + 1))
  else
    print_check "resona adapter" WARN "Thiếu $RESONA_TTS_WRAPPER (không dùng Resona cho job này, bỏ qua)"
  fi
  if [[ -n "$RESONA_API_TOKEN" ]]; then
    print_check "resona token" OK "env RESONA_API_TOKEN set (không print giá trị)"
  else
    if [[ "$resona_is_default" -eq 1 ]]; then
      print_check "resona token" FAIL "Thiếu RESONA_API_TOKEN/RESONA_ACCESS_TOKEN (Resona là giọng mặc định)"
      failures=$((failures + 1))
    else
      print_check "resona token" WARN "Thiếu RESONA_API_TOKEN (không dùng Resona cho job này, bỏ qua)"
    fi
  fi
  print_check "resona voice" OK "default=${RESONA_DEFAULT_VOICE_ID}"
  # Online check chỉ khi user cho phép (env OPENCLAW_DOCTOR_ONLINE=1) + có token.
  if [[ -n "$RESONA_API_TOKEN" && "${OPENCLAW_DOCTOR_ONLINE:-0}" == "1" ]]; then
    if python3 - "$RESONA_API_BASE" >/dev/null 2>&1 <<'PY'
import sys, urllib.request, urllib.error
url = sys.argv[1].rstrip('/') + '/api/v1/generate-speech'
try:
    req = urllib.request.Request(url, method='GET')
    urllib.request.urlopen(req, timeout=5)
    sys.exit(0)
except urllib.error.HTTPError as e:
    sys.exit(0 if e.code in (401, 403, 404, 405, 400) else 1)
except Exception:
    sys.exit(1)
PY
    then
      print_check "resona api" OK "$RESONA_API_BASE reachable"
    else
      print_check "resona api" WARN "$RESONA_API_BASE không reach được (kiểm tra mạng/proxy)"
    fi
  fi

  if [[ "$failures" -eq 0 ]]; then
    echo "DOCTOR RESULT: OK"
    return 0
  fi
  echo "DOCTOR RESULT: FAIL ($failures issue(s))"
  return 1
}

if [[ "$DOCTOR_MODE" -eq 1 ]]; then
  run_doctor
  exit $?
fi

need_cmd() {
  local cmd="$1"
  # edge-tts thường ở ~/.local/bin (pip --user) và có thể vắng trong PATH khi
  # resume từ dashboard. Dùng EDGE_TTS_BIN đã resolve ở đầu script thay vì
  # chỉ tin command -v.
  if [[ "$cmd" == "edge-tts" ]]; then
    if [[ -n "$EDGE_TTS_BIN" && -x "$EDGE_TTS_BIN" ]]; then
      return 0
    fi
    if command -v edge-tts >/dev/null 2>&1; then
      [[ -z "$EDGE_TTS_BIN" ]] && export EDGE_TTS_BIN="$(command -v edge-tts)"
      return 0
    fi
    [[ -x "$HOME/.local/bin/edge-tts" ]] && { export EDGE_TTS_BIN="$HOME/.local/bin/edge-tts"; return 0; }
    fail "Thiếu lệnh 'edge-tts'. Cài: pip install --user edge-tts, hoặc đặt EDGE_TTS_BIN. Chạy: bash run.sh --doctor"
  fi
  command -v "$cmd" >/dev/null 2>&1 || fail "Thiếu lệnh '$cmd'. Chạy: bash run.sh --doctor"
}

translate_srt() {
  local source_srt="$1"
  local target_srt="$2"
  local api_key="$3"
  python3 - "$source_srt" "$target_srt" "$api_key" "$API_BASE" "$MODEL" "$OPENCLAW_AI_PROVIDER" <<'PY'
import json, sys, urllib.request, urllib.error
source_srt, target_srt, api_key, api_base, model, provider = sys.argv[1:]
with open(source_srt, 'r', encoding='utf-8', errors='replace') as f:
    srt = f.read().strip()
if not srt:
    srt = "1\n00:00:00,000 --> 00:00:01,000\n[Không nhận diện được lời nói rõ ràng]"
prompt = """Bạn là biên dịch phụ đề chuyên nghiệp. Dịch file SRT sau từ tiếng Trung sang tiếng Việt tự nhiên.
Giữ nguyên số thứ tự và timestamp SRT. Chỉ dịch nội dung thoại. Không thêm giải thích.

SRT:
""" + srt
payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": "Bạn dịch phụ đề SRT sang tiếng Việt, giữ nguyên định dạng SRT."},
        {"role": "user", "content": prompt},
    ],
    "temperature": 0.2,
    "stream": False,
}
if provider == 'ollama':
    payload['think'] = False
        payload['options'] = {
            'temperature': 0.2,
            'num_ctx': int(float(__import__('os').environ.get('OLLAMA_NUM_CTX', '2048'))),
            'num_predict': int(float(__import__('os').environ.get('OLLAMA_NUM_PREDICT', '1024'))),
        }
    url = api_base.rstrip('/') + '/api/chat'
    headers = {'Content-Type': 'application/json'}
else:
    payload['think'] = False
    url = api_base.rstrip('/') + '/chat/completions'
    headers = {'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'}
req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8', errors='replace')
    raise SystemExit(f'LLM HTTP {e.code}: {body[:1000]}')
if provider == 'ollama':
    content = data.get('message', {}).get('content', '').strip()
else:
    content = data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
if not content:
    raise SystemExit('LLM không trả nội dung dịch')
with open(target_srt, 'w', encoding='utf-8') as f:
    f.write(content.rstrip() + '\n')
PY
}

build_translation_memory_context() {
  local out_file="$1"
  : > "$out_file"
  [[ "${TRANSLATION_MEMORY_ENABLED:-1}" != "0" ]] || return 0
  [[ -f "$TRANSLATION_MEMORY_CONTEXT_SCRIPT" ]] || {
    echo "WARN: Translation memory helper missing: $TRANSLATION_MEMORY_CONTEXT_SCRIPT" >&2
    return 0
  }
  [[ -d "$TRANSLATION_MEMORY_DIR" ]] || return 0
  [[ -n "${TRANSLATION_SERIES_ID:-}${TRANSLATION_GENRE_TAGS:-}" ]] || return 0

  set +e
  python3 "$TRANSLATION_MEMORY_CONTEXT_SCRIPT" \
    --memory-dir "$TRANSLATION_MEMORY_DIR" \
    --genre-tags "${TRANSLATION_GENRE_TAGS:-}" \
    --series-id "${TRANSLATION_SERIES_ID:-}" \
    --max-chars "${TRANSLATION_MEMORY_MAX_CHARS:-6000}" \
    --out "$out_file"
  local memory_status=$?
  set -e
  if [[ "$memory_status" -ne 0 ]]; then
    echo "WARN: Translation memory context build failed exit=$memory_status; continuing without memory." >&2
    : > "$out_file"
    return 0
  fi
  if [[ -s "$out_file" ]]; then
    echo "Translation memory: series=${TRANSLATION_SERIES_ID:-none} genres=${TRANSLATION_GENRE_TAGS:-none} chars=$(wc -c < "$out_file" | tr -d ' ')"
  fi
}

optimize_vietnamese_dub_timing() {
  local original_srt="$1"
  local vietnamese_srt="$2"
  local dub_srt="$3"
  local segments_json="$4"
  local report_json="$5"
  local api_key="$6"
  local tmp_dir="$7"

  [[ "${OPTIMIZER_ENABLED:-1}" != "0" ]] || return 2
  [[ -x "$TIMING_OPTIMIZER_SCRIPT" ]] || return 3

  # progress file để dashboard/tool ngoài theo dõi optimizer (phase + group index).
  local progress_file="${OUT_DIR:-}/optimizer_progress.json"
  local translation_memory_context_file="$tmp_dir/translation_memory_context.txt"
  build_translation_memory_context "$translation_memory_context_file"

  # Bọc bằng heartbeat để job_status.json update đều trong phase optimizer,
  # tránh dashboard báo StuckHeartbeat giả khi optimizer chạy lâu (chat API/TTS probe).
  run_with_status_heartbeat_guarded "optimizer" "58" "Đang dịch/tối ưu timing qua ${OPENCLAW_AI_PROVIDER}" \
    "$OPTIMIZER_TIMEOUT_SECONDS" "${OPENCLAW_LONG_STEP_HEARTBEAT_SECONDS:-30}" \
    env \
    DOUYIN_DUBBER_SKILL_DIR="$SKILL_DIR" \
    CAPCUT_TTS_WRAPPER="$CAPCUT_TTS_WRAPPER" \
    CAPCUT_TTS_VOICES_JSON="$CAPCUT_TTS_VOICES_JSON" \
    CAPCUT_TTS_EDGE_FALLBACK_VOICE="$CAPCUT_TTS_EDGE_FALLBACK_VOICE" \
    RESONA_DEFAULT_VOICE_ID="$RESONA_DEFAULT_VOICE_ID" \
    RESONA_MIN_CHARS="$RESONA_MIN_CHARS" \
    RESONA_MAX_CHARS="$RESONA_MAX_CHARS" \
    OPTIMIZER_CHAT_TIMEOUT_SECONDS="${OPTIMIZER_CHAT_TIMEOUT_SECONDS:-90}" \
    OPTIMIZER_BATCH_TIMEOUT_SECONDS="${OPTIMIZER_BATCH_TIMEOUT_SECONDS:-180}" \
    TRANSLATION_MEMORY_MAX_CHARS="${TRANSLATION_MEMORY_MAX_CHARS:-6000}" \
    EDGE_TTS_TIMEOUT_SECONDS="${EDGE_TTS_TIMEOUT_SECONDS:-20}" \
    SYNC_MODE="$SYNC_MODE" \
    TTS_SYNC_POLICY="$TTS_SYNC_POLICY" \
    ALLOW_AGGRESSIVE_ATEMPO="$ALLOW_AGGRESSIVE_ATEMPO" \
    MAX_TTS_SPEED="$MAX_TTS_SPEED" \
    POST_ATEMPO_MAX="$POST_ATEMPO_MAX" \
    TOTAL_AUDIO_SPEED_MAX="$TOTAL_AUDIO_SPEED_MAX" \
    SUBTITLE_ONLY_IF_RATIO_ABOVE="$SUBTITLE_ONLY_IF_RATIO_ABOVE" \
    python3 "$TIMING_OPTIMIZER_SCRIPT" \
    --original-srt "$original_srt" \
    --vietnamese-srt "$vietnamese_srt" \
    --dub-srt "$dub_srt" \
    --segments-json "$segments_json" \
    --report-json "$report_json" \
    --api-base "$API_BASE" \
    --api-key "$api_key" \
    --api-provider "$OPENCLAW_AI_PROVIDER" \
    --model "$MODEL" \
    --voice "$VOICE" \
    --work-dir "$tmp_dir" \
    --progress-file "$progress_file" \
    --translation-memory-context "$translation_memory_context_file"
}

try_translate_srt() {
  set +e
  translate_srt "$ORIGINAL_SRT" "$VIETNAMESE_SRT" "$API_KEY"
  local translate_status=$?
  set -e
  if [[ "$translate_status" -ne 0 || ! -s "$VIETNAMESE_SRT" ]]; then
    echo "WARN: Dịch tự động lỗi exit=$translate_status; chuyển sang manual translate fallback."
    rm -f "$VIETNAMESE_SRT" "$DUB_SRT"
    return 1
  fi
  cp "$VIETNAMESE_SRT" "$DUB_SRT"
  return 0
}

write_transcript_json() {
  local srt_path="$1"
  local json_path="$2"
  local kind="$3"
  [[ -s "$srt_path" ]] || return 0
  python3 - "$srt_path" "$json_path" "$kind" <<'PY'
import json, re, sys
from pathlib import Path
srt_path, json_path, kind = sys.argv[1:]
text = Path(srt_path).read_text(encoding='utf-8', errors='replace')
blocks = re.split(r'\n\s*\n', text.strip()) if text.strip() else []
items = []
for block in blocks:
    lines = [line.strip('\ufeff') for line in block.splitlines() if line.strip()]
    if not lines: continue
    idx = lines[0] if lines[0].isdigit() else str(len(items) + 1)
    time_i = 1 if lines[0].isdigit() else 0
    if time_i >= len(lines) or '-->' not in lines[time_i]: continue
    start, end = [part.strip() for part in lines[time_i].split('-->', 1)]
    body = ' '.join(lines[time_i + 1:]).strip()
    items.append({'index': int(idx) if str(idx).isdigit() else len(items) + 1, 'start': start, 'end': end, 'text': body})
Path(json_path).write_text(json.dumps({'kind': kind, 'source_srt': str(srt_path), 'segments': items}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
PY
}

split_long_asr_segments() {
  local in_srt="$1"
  local out_srt="$2"
  [[ "${ASR_SPLIT_LONG_SEGMENTS:-1}" != "0" ]] || { cp "$in_srt" "$out_srt"; return 0; }
  python3 - "$in_srt" "$out_srt" "${ASR_SPLIT_MAX_SECONDS:-10}" "${ASR_SPLIT_MAX_CHARS:-120}" <<'PY'
import math, re, sys
from pathlib import Path
in_srt, out_srt, max_seconds_raw, max_chars_raw = sys.argv[1:]
max_seconds = max(1.0, float(max_seconds_raw)); max_chars = max(20, int(max_chars_raw))
def parse_ts(ts):
    h, m, rest = ts.replace(',', '.').split(':'); return int(h)*3600 + int(m)*60 + float(rest)
def fmt_ts(sec):
    ms = int(round(max(0.0, sec) * 1000)); h, rem = divmod(ms, 3600000); m, rem = divmod(rem, 60000); s, ms = divmod(rem, 1000); return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
def split_text(text, parts):
    if parts <= 1: return [text]
    chunks = re.split(r'(?<=[.!?。！？;；,，])\s+', text)
    if len(chunks) <= 1:
        words = text.split(); size = max(1, math.ceil(len(words) / parts)); return [' '.join(words[i:i+size]).strip() for i in range(0, len(words), size) if words[i:i+size]] or [text]
    groups = [''] * parts
    for chunk in chunks:
        target = min(range(parts), key=lambda i: len(groups[i])); groups[target] = (groups[target] + ' ' + chunk).strip()
    return [g for g in groups if g]
text = Path(in_srt).read_text(encoding='utf-8', errors='replace')
blocks = re.split(r'\n\s*\n', text.strip()) if text.strip() else []
out = []
for block in blocks:
    lines = [line for line in block.splitlines() if line.strip()]
    time_i = 1 if lines and lines[0].strip().isdigit() else 0
    if time_i >= len(lines) or '-->' not in lines[time_i]: continue
    start_s, end_s = [p.strip() for p in lines[time_i].split('-->', 1)]
    body = ' '.join(line.strip() for line in lines[time_i + 1:]).strip()
    start, end = parse_ts(start_s), parse_ts(end_s); duration = max(0.01, end - start)
    parts = max(1, math.ceil(duration / max_seconds), math.ceil(len(body) / max_chars)); pieces = split_text(body, parts)
    if len(pieces) <= 1: out.append((start, end, body)); continue
    cursor = start; total_len = sum(max(1, len(piece)) for piece in pieces)
    for i, piece in enumerate(pieces):
        piece_end = end if i == len(pieces) - 1 else min(end, cursor + duration * max(1, len(piece)) / total_len)
        out.append((cursor, piece_end, piece)); cursor = piece_end
lines = []
for i, (start, end, body) in enumerate(out, 1): lines.extend([str(i), f'{fmt_ts(start)} --> {fmt_ts(end)}', body, ''])
Path(out_srt).write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
print(f'ASR split: {len(blocks)} -> {len(out)} segments')
PY
}

create_translate_pending() {
  local reason="$1"
  local pending_json="$OUT_DIR/translate_pending_input.json"
  write_transcript_json "$ORIGINAL_SRT" "$pending_json" "manual_translate_input"
  cat > "$OUT_DIR/TRANSLATE_PENDING.txt" <<'TRANSLATE_EOF'
Pipeline đang chờ bản dịch thủ công vì bước dịch tự động lỗi.

Cách xử lý:
1. Mở file translate_pending_input.json trong thư mục job này.
2. Dịch từng segments[].text sang tiếng Việt.
3. Lưu kết quả thành transcript_vi.json cùng thư mục, giữ start/end/index.
4. Bấm nút "Chạy tiếp sau khi đã dán bản dịch" trên dashboard.
TRANSLATE_EOF
  printf '\nLý do: %s\n' "$reason" >> "$OUT_DIR/TRANSLATE_PENDING.txt"
}

load_manual_translation_if_available() {
  local manual_json="$OUT_DIR/transcript_vi.json"
  [[ -s "$manual_json" ]] || return 1
  python3 - "$manual_json" "$ORIGINAL_SRT" "$VIETNAMESE_SRT" "$DUB_SRT" <<'PY'
import json, re, sys
from pathlib import Path
json_path, original_srt, vi_srt, dub_srt = sys.argv[1:]
data = json.loads(Path(json_path).read_text(encoding='utf-8'))
segments = data.get('segments') if isinstance(data, dict) else data
original_text = Path(original_srt).read_text(encoding='utf-8', errors='replace')
original_count = sum(
    1 for block in re.split(r'\n\s*\n', original_text.strip())
    if '-->' in block
)
if len(segments) != original_count:
    raise SystemExit(
        f'transcript_vi.json incomplete: segments={len(segments)}/{original_count}'
    )
if not isinstance(segments, list) or not segments: raise SystemExit('transcript_vi.json không có segments hợp lệ')
lines = []
for i, seg in enumerate(segments, 1):
    start = str(seg.get('start') or '').strip(); end = str(seg.get('end') or '').strip(); text = str(seg.get('text') or seg.get('vi_text') or seg.get('translation') or '').strip()
    if start and end and text: lines.extend([str(i), f'{start} --> {end}', text, ''])
if not lines: raise SystemExit('transcript_vi.json không có text dịch hợp lệ')
out = '\n'.join(lines).rstrip() + '\n'; Path(vi_srt).write_text(out, encoding='utf-8'); Path(dub_srt).write_text(out, encoding='utf-8')
print(f'Loaded manual translation: {len(lines)//4} segments')
PY
}

select_bgm_source() {
  local mode="$(printf '%s' "${BGM_MODE:-auto}" | tr '[:upper:]' '[:lower:]')"
  SELECTED_BGM_MODE="$mode"; SELECTED_BGM_SOURCE=""
  case "$mode" in
    auto|demucs)
      if background_separation_ready; then
        SELECTED_BGM_SOURCE="$NO_VOCALS_WAV"; SELECTED_BGM_MODE="demucs"
      else
        SELECTED_BGM_MODE="error"
      fi ;;
    duck) SELECTED_BGM_MODE="duck"; SELECTED_BGM_SOURCE="$VIDEO" ;;
    none|off|tat|tắt) SELECTED_BGM_MODE="none" ;;
    *) echo "WARN: BGM_MODE=$BGM_MODE không hợp lệ; dùng auto."; BGM_MODE="auto"; select_bgm_source ;;
  esac
}

background_separation_ready() {
  [[ -s "$NO_VOCALS_WAV" && -s "$SPEECH_PREPROCESS_REPORT_JSON" ]] || return 1
  python3 - "$SPEECH_PREPROCESS_REPORT_JSON" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if data.get("demucs", {}).get("used") is True else 1)
PY
}

write_fit_adjustments_report() {
  local report_path="$OUT_DIR/fit_adjustments.json"
  python3 - "$TTS_STATS_JSON" "$DUBBING_REPORT_JSON" "$report_path" "$SELECTED_BGM_MODE" "$BGM_MODE" "$BGM_MODE_FALLBACK" <<'PY'
import json, sys
from pathlib import Path
tts_path, dubbing_path, report_path, selected_bgm, requested_bgm, fallback = sys.argv[1:]
report = {'bgm_mode_requested': requested_bgm, 'bgm_mode_selected': selected_bgm, 'bgm_mode_fallback': fallback, 'segments_adjusted': 0, 'overflow_segments': 0, 'adjustments': []}
if Path(tts_path).exists():
    try:
        stats = json.loads(Path(tts_path).read_text(encoding='utf-8'))
        for item in (stats.get('segments') or stats.get('segment_stats') or []):
            speed = float(item.get('speed_ratio') or item.get('speed') or 1.0); overflow = bool(item.get('overflow') or item.get('overhang_ms', 0))
            if speed > 1.01 or overflow:
                report['segments_adjusted'] += 1 if speed > 1.01 else 0; report['overflow_segments'] += 1 if overflow else 0; report['adjustments'].append(item)
    except Exception as exc: report['tts_stats_error'] = str(exc)
if Path(dubbing_path).exists(): report['dubbing_report'] = str(dubbing_path)
Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f"Fit adjustments: adjusted={report['segments_adjusted']} overflow={report['overflow_segments']} bgm={selected_bgm}")
PY
}

speech_only_preprocess() {
  local input_video="$1"
  local audio_wav="$2"
  local asr_audio_wav="$3"
  local vocals_wav="$4"
  local no_vocals_wav="$5"
  local speech_regions_json="$6"
  local preprocess_report_json="$7"
  local tmp_dir="$8"

  [[ "${SPEECH_ONLY_PREPROCESS_ENABLED:-1}" != "0" ]] || return 2
  [[ -x "$SPEECH_ONLY_PREPROCESS_SCRIPT" ]] || return 3

  timeout --foreground "$SPEECH_ONLY_TIMEOUT_SECONDS" python3 "$SPEECH_ONLY_PREPROCESS_SCRIPT" \
    --input-video "$input_video" \
    --work-dir "$tmp_dir" \
    --audio-wav "$audio_wav" \
    --asr-audio-wav "$asr_audio_wav" \
    --vocals-wav "$vocals_wav" \
    --no-vocals-wav "$no_vocals_wav" \
    --speech-regions-json "$speech_regions_json" \
    --report-json "$preprocess_report_json"
}

generate_vietnamese_voice() {
  local source_srt="$1"
  local voice_wav="$2"
  local voice_name="$3"
  local tmp_dir="$4"
  local target_duration_seconds="${5:-0}"
  local tts_timeout_seconds="${EDGE_TTS_TIMEOUT_SECONDS:-20}"
  local tts_circuit_breaker="${EDGE_TTS_CIRCUIT_BREAKER_FAILURES:-5}"
  local max_tts_speed="${MAX_TTS_SPEED:-1.5}"
  local allow_audio_overhang="${ALLOW_AUDIO_OVERHANG:-0.6}"
  local tts_audio_stage_report_json="${TTS_AUDIO_STAGE_REPORT_JSON:-$OUT_DIR/tts_audio_stage_report.json}"
  local tts_python_bin="python3"
  if [[ "${voice_name,,}" == kokoro* ]]; then
    [[ -x "$KOKORO_TTS_PYTHON" ]] || fail "Kokoro TTS runtime chưa sẵn sàng: không thấy executable $KOKORO_TTS_PYTHON"
    tts_python_bin="$KOKORO_TTS_PYTHON"
  fi
  DOUYIN_DUBBER_SKILL_DIR="$SKILL_DIR" CAPCUT_TTS_WRAPPER="$CAPCUT_TTS_WRAPPER" CAPCUT_TTS_VOICES_JSON="$CAPCUT_TTS_VOICES_JSON" CAPCUT_TTS_EDGE_FALLBACK_VOICE="$CAPCUT_TTS_EDGE_FALLBACK_VOICE" \
  RESONA_TTS_WRAPPER="$RESONA_TTS_WRAPPER" RESONA_API_BASE="$RESONA_API_BASE" RESONA_DEFAULT_VOICE_ID="$RESONA_DEFAULT_VOICE_ID" \
  RESONA_API_TOKEN="$RESONA_API_TOKEN" \
  RESONA_SHORT_TEXT_POLICY="$RESONA_SHORT_TEXT_POLICY" RESONA_SHORT_GROUP_ENABLED="$RESONA_SHORT_GROUP_ENABLED" \
  RESONA_SHORT_GROUP_MAX_CUES="$RESONA_SHORT_GROUP_MAX_CUES" RESONA_SHORT_GROUP_MAX_DURATION_SECONDS="$RESONA_SHORT_GROUP_MAX_DURATION_SECONDS" \
  RESONA_SHORT_GROUP_SOFT_MAX_DURATION_SECONDS="$RESONA_SHORT_GROUP_SOFT_MAX_DURATION_SECONDS" \
  RESONA_SHORT_GROUP_HARD_MAX_DURATION_SECONDS="$RESONA_SHORT_GROUP_HARD_MAX_DURATION_SECONDS" \
  RESONA_SHORT_GROUP_MAX_INTERNAL_GAP_MS="$RESONA_SHORT_GROUP_MAX_INTERNAL_GAP_MS" \
  RESONA_POLL_INTERVAL_SECONDS="$RESONA_POLL_INTERVAL_SECONDS" RESONA_TIMEOUT_SECONDS="$RESONA_TIMEOUT_SECONDS" \
  RESONA_FALLBACK_VOICE_IDS="${RESONA_FALLBACK_VOICE_IDS:-}" \
  AI33_TTS_WRAPPER="$AI33_TTS_WRAPPER" AI33_API_BASE="$AI33_API_BASE" AI33_API_KEY="$AI33_API_KEY" \
  AI33_TTS_WORKERS="$AI33_TTS_WORKERS" \
  AI33_MAI_PHUONG_VOICE_ID="$AI33_MAI_PHUONG_VOICE_ID" AI33_PHANH_VOICE_ID="$AI33_PHANH_VOICE_ID" AI33_DEFAULT_VOICE_ID="$AI33_DEFAULT_VOICE_ID" \
  VOICE_REGISTRY_PY="$VOICE_REGISTRY_PY" VOICE_SOURCE_HINT="$VOICE_SOURCE_HINT" OPENCLAW_VOICE_REGISTRY_JSON="${OPENCLAW_VOICE_REGISTRY_JSON:-}" \
  AI33_TTS_SPEED="$AI33_TTS_SPEED" AI33_WITH_TRANSCRIPT="$AI33_WITH_TRANSCRIPT" \
  AI33_PRONUNCIATION_DICTIONARY_ID="$AI33_PRONUNCIATION_DICTIONARY_ID" \
  TTS_FORCE_CUE_IDS="${TTS_FORCE_CUE_IDS:-}" TTS_SPOKEN_TEXT_OVERRIDES_JSON="${TTS_SPOKEN_TEXT_OVERRIDES_JSON:-}" \
  TTS_MASTER_SAMPLE_RATE="$TTS_MASTER_SAMPLE_RATE" TTS_MASTER_CHANNELS="$TTS_MASTER_CHANNELS" \
  TTS_AUDIO_STAGE_REPORT_JSON="$tts_audio_stage_report_json" \
  AI33_MAX_SPEED="$AI33_MAX_SPEED" POST_ATEMPO_MAX="$POST_ATEMPO_MAX" \
  POST_ATEMPO_MIN="$POST_ATEMPO_MIN" ALLOW_SLOW_FIT="$ALLOW_SLOW_FIT" \
  TTS_ADAPT_ENABLED="$TTS_ADAPT_ENABLED" TTS_ADAPT_MAX_ATTEMPTS="$TTS_ADAPT_MAX_ATTEMPTS" \
  TTS_RESTORE_IF_SLOT_RATIO_BELOW="$TTS_RESTORE_IF_SLOT_RATIO_BELOW" \
  TOTAL_AUDIO_SPEED_MAX="$TOTAL_AUDIO_SPEED_MAX" ALLOW_AGGRESSIVE_ATEMPO="$ALLOW_AGGRESSIVE_ATEMPO" \
  SOURCE_SPEECH_REGIONS_JSON="${SPEECH_REGIONS_JSON:-}" \
  SYNC_MODE="$SYNC_MODE" STRICT_QUALITY_GATE="$STRICT_QUALITY_GATE" \
  VOICE_SYNC_PADDING_WARN_RATIO="$VOICE_SYNC_PADDING_WARN_RATIO" VOICE_SYNC_PADDING_FAIL_RATIO="$VOICE_SYNC_PADDING_FAIL_RATIO" \
  VOICE_SYNC_MIN_MEDIAN_FILL_RATIO="$VOICE_SYNC_MIN_MEDIAN_FILL_RATIO" \
  VOICE_SYNC_LONG_PADDING_WARN_MS="$VOICE_SYNC_LONG_PADDING_WARN_MS" VOICE_SYNC_LONG_PADDING_FAIL_MS="$VOICE_SYNC_LONG_PADDING_FAIL_MS" \
  AI33_CONTEXT_CHAINING="$AI33_CONTEXT_CHAINING" AI33_POLL_INTERVAL_SECONDS="$AI33_POLL_INTERVAL_SECONDS" \
  AI33_TIMEOUT_SECONDS="$AI33_TIMEOUT_SECONDS" AI33_CIRCUIT_BREAKER_FAILURES="$AI33_CIRCUIT_BREAKER_FAILURES" AI33_CIRCUIT_COOLDOWN_SECONDS="$AI33_CIRCUIT_COOLDOWN_SECONDS" \
  KOKORO_VOICES_JSON="$KOKORO_VOICES_JSON" KOKORO_DEFAULT_VOICE="$KOKORO_DEFAULT_VOICE" \
  KOKORO_TTS_DEVICE="$KOKORO_TTS_DEVICE" KOKORO_TTS_SPEED="$KOKORO_TTS_SPEED" \
  KOKORO_TTS_CROSSFADE_MS="$KOKORO_TTS_CROSSFADE_MS" KOKORO_TTS_NORMALIZE_PEAK="$KOKORO_TTS_NORMALIZE_PEAK" \
  KOKORO_TTS_REPO_ID="$KOKORO_TTS_REPO_ID" KOKORO_TTS_MODEL="$KOKORO_TTS_MODEL" \
  KOKORO_TTS_CONFIG="$KOKORO_TTS_CONFIG" KOKORO_TTS_VOICEPACK="$KOKORO_TTS_VOICEPACK" \
  TRANSCRIPT_DECISION_JSON="${TRANSCRIPT_DECISION_JSON:-}" VOICE_SYNC_REPORT_JSON="${VOICE_SYNC_REPORT_JSON:-}" \
  TTS_SYNC_POLICY="$TTS_SYNC_POLICY" \
  FRAME_STRICT_MAX_SEGMENT_DRIFT_MS="${FRAME_STRICT_MAX_SEGMENT_DRIFT_MS:-80}" \
  FRAME_STRICT_MAX_TOTAL_DRIFT_MS="${FRAME_STRICT_MAX_TOTAL_DRIFT_MS:-200}" \
  FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS="${FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS:-5}" \
  "$tts_python_bin" - "$source_srt" "$voice_wav" "$voice_name" "$tmp_dir" "$target_duration_seconds" "$tts_timeout_seconds" "$tts_circuit_breaker" "$max_tts_speed" "$allow_audio_overhang" <<'PY'
import hashlib, importlib.util, json, os, re, shutil, subprocess, sys, time, urllib.request, urllib.error, wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
source_srt, voice_wav, voice_name, tmp_dir, target_duration_raw, timeout_raw, breaker_raw, max_speed_raw, overhang_raw = sys.argv[1:]
root = Path(tmp_dir)
skill_dir = Path(os.environ.get('DOUYIN_DUBBER_SKILL_DIR', Path.cwd()))
sys.path.insert(0, str(skill_dir))
from dialogue_boundary import boundary_after
from voice_sync_overhang import unresolved_overhang_event
from resona_grouping import ordered_source_cue_ids
tts_checkpoint_spec = importlib.util.spec_from_file_location('openclaw_tts_checkpoint', skill_dir / 'tts_checkpoint.py')
if not tts_checkpoint_spec or not tts_checkpoint_spec.loader:
    raise RuntimeError(f"TTSCheckpointMissing: {skill_dir / 'tts_checkpoint.py'}")
tts_checkpoint = importlib.util.module_from_spec(tts_checkpoint_spec)
tts_checkpoint_spec.loader.exec_module(tts_checkpoint)
structured_json_py = skill_dir / 'structured_json.py'
structured_json_spec = importlib.util.spec_from_file_location('openclaw_structured_json', structured_json_py)
if not structured_json_spec or not structured_json_spec.loader:
    raise RuntimeError(f"StructuredJsonHelperMissing: {structured_json_py}")
structured_json = importlib.util.module_from_spec(structured_json_spec)
structured_json_spec.loader.exec_module(structured_json)
extract_first_json_object = structured_json.extract_first_json_object
voice_registry_py = Path(os.environ.get('VOICE_REGISTRY_PY') or (skill_dir / 'voice_registry.py'))
voice_registry = None
if voice_registry_py.exists():
    try:
        spec = importlib.util.spec_from_file_location('openclaw_voice_registry', voice_registry_py)
        if spec and spec.loader:
            voice_registry = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(voice_registry)
    except Exception as exc:
        print(f"WARN: VoiceRegistryInvalid: không load được {voice_registry_py}: {exc}", flush=True)
speed_contract_py = skill_dir / 'tts_speed_contract.py'
speed_contract_spec = importlib.util.spec_from_file_location('openclaw_tts_speed_contract', speed_contract_py)
if not speed_contract_spec or not speed_contract_spec.loader:
    raise RuntimeError(f"TTSSpeedContractMissing: {speed_contract_py}")
speed_contract = importlib.util.module_from_spec(speed_contract_spec)
speed_contract_spec.loader.exec_module(speed_contract)
final_mix_quality_py = skill_dir / 'final_mix_quality.py'
final_mix_quality_spec = importlib.util.spec_from_file_location('openclaw_final_mix_quality', final_mix_quality_py)
if not final_mix_quality_spec or not final_mix_quality_spec.loader:
    raise RuntimeError(f"FinalMixQualityMissing: {final_mix_quality_py}")
final_mix_quality = importlib.util.module_from_spec(final_mix_quality_spec)
final_mix_quality_spec.loader.exec_module(final_mix_quality)
segments_dir = root / 'tts_segments'
segments_dir.mkdir(parents=True, exist_ok=True)
concat_list = root / 'tts_concat.txt'
stats_path = root / 'tts_stats.json'
ai33_checkpoint_path = root / 'tts_checkpoint.json'
ai33_provider_state_path = root / 'ai33_provider_state.json'
alignment_report_path = root / 'tts_alignment_report.json'
speed_report_path = root / 'speed_report.csv'
job_status_path = root.parent / 'job_status.json'
# Replaced after parsing with the authoritative final cue timing topology.
# Individual dub text is fingerprinted per cue by tts_checkpoint.py.
source_fingerprint = ''
source_speech_regions = []
speech_timing_source = ''
display_subtitle_timing = ''
dub_tts_timing = ''
try:
    transcript_decision_path = Path(os.environ.get('TRANSCRIPT_DECISION_JSON') or '')
    transcript_decision = json.loads(transcript_decision_path.read_text(encoding='utf-8'))
    speech_timing_source = str(transcript_decision.get('speech_timing_source') or '')
    display_subtitle_timing = str(transcript_decision.get('display_subtitle_timing') or '')
    dub_tts_timing = str(transcript_decision.get('dub_tts_timing') or '')
except Exception:
    pass
# Exact backend labels emitted by speech_only_preprocess.py that classify speech
# rather than merely detecting audio energy. Unknown/missing backends must stay
# available for diagnostics, but cannot turn a synthetic silence into proof.
SPEECH_AWARE_BACKENDS = frozenset({"inaSpeechSegmenter"})
try:
    source_speech_regions_raw = json.loads(
        Path(os.environ.get('SOURCE_SPEECH_REGIONS_JSON') or '').read_text(encoding='utf-8')
    )
    if isinstance(source_speech_regions_raw, list):
        source_speech_regions = sorted(
            (
                {
                    'start_ms': int(float(region.get('start', 0)) * 1000),
                    'end_ms': int(float(region.get('end', 0)) * 1000),
                    'backend': region.get('backend'),
                }
                for region in source_speech_regions_raw
                if isinstance(region, dict) and region.get('kind') == 'speech'
                and float(region.get('end', 0)) > float(region.get('start', 0))
            ),
            key=lambda region: region['start_ms']
        )
except Exception:
    source_speech_regions = []

def max_source_speech_overlap_ms(start_ms, end_ms):
    """Return overlap proven by a speech-aware backend, never energy VAD."""
    return max((max(0, min(end_ms, region['end_ms']) - max(start_ms, region['start_ms']))
                for region in source_speech_regions
                if region.get('backend') in SPEECH_AWARE_BACKENDS), default=0)
try:
    tts_master_sample_rate = max(8000, int(float(os.environ.get("TTS_MASTER_SAMPLE_RATE", "48000") or "48000")))
except Exception:
    tts_master_sample_rate = 48000
try:
    tts_master_channels = max(1, min(2, int(float(os.environ.get("TTS_MASTER_CHANNELS", "1") or "1"))))
except Exception:
    tts_master_channels = 1
tts_audio_stage_report_path = Path(os.environ.get("TTS_AUDIO_STAGE_REPORT_JSON") or (root / "tts_audio_stage_report.json"))
adaptation_module = None
adaptation_path = skill_dir / 'dub_text_adaptation.py'
try:
    spec = importlib.util.spec_from_file_location('openclaw_dub_text_adaptation', adaptation_path)
    if spec and spec.loader:
        adaptation_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adaptation_module)
except Exception as exc:
    print(f"WARN: cannot load dub-text adaptation policy: {exc}", flush=True)

def record_audio_stage(stage: str, path: Path):
    """Append inspectable TTS audio metadata without exposing API data or audio payloads."""
    try:
        proc = subprocess.run([
            'ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=sample_rate,channels,codec_name:format=duration',
            '-of', 'json', str(path),
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
        probe = json.loads(proc.stdout or '{}')
        stream = (probe.get('streams') or [{}])[0]
        item = {
            'stage': stage,
            'file_path': str(path),
            'sample_rate': int(stream.get('sample_rate') or 0),
            'channels': int(stream.get('channels') or 0),
            'codec': stream.get('codec_name') or '',
            'duration_ms': int(round(float((probe.get('format') or {}).get('duration') or 0) * 1000)),
        }
        try:
            report = json.loads(tts_audio_stage_report_path.read_text(encoding='utf-8')) if tts_audio_stage_report_path.exists() else {}
        except Exception:
            report = {}
        stages = report.get('stages') if isinstance(report.get('stages'), list) else []
        warnings = report.get('warnings') if isinstance(report.get('warnings'), list) else []
        stages.append(item)
        sample_rate_error = final_mix_quality.canonical_sample_rate_error(
            stage, item['sample_rate'], tts_master_sample_rate,
        )
        if item['sample_rate'] == 16000 and 'TTS_MASTER_DOWNGRADED_TO_ASR_FORMAT' not in warnings:
            warnings.append('TTS_MASTER_DOWNGRADED_TO_ASR_FORMAT')
        if sample_rate_error and sample_rate_error not in warnings:
            warnings.append(sample_rate_error)
        tts_audio_stage_report_path.parent.mkdir(parents=True, exist_ok=True)
        tts_audio_stage_report_path.write_text(json.dumps({'stages': stages, 'warnings': warnings}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if sample_rate_error:
            raise RuntimeError(sample_rate_error)
    except RuntimeError as exc:
        if str(exc).startswith('TTS_CANONICAL_SAMPLE_RATE_MISMATCH'):
            raise
        print(f'WARN: audio stage report failed stage={stage}: {exc}', flush=True)
    except Exception as exc:
        print(f'WARN: audio stage report failed stage={stage}: {exc}', flush=True)

def _safe_error_text(exc):
    return re.sub(r'https?://[^\s"\']+', '<redacted-url>', str(exc)).replace('\n', ' ')[:500]


def _classify_tts_exception(exc):
    msg = _safe_error_text(exc)
    if 'VoiceInvalid' in msg:
        return 'VoiceInvalid'
    if 'AI33AuthMissing' in msg:
        return 'AI33AuthMissing'
    if 'AI33AuthFailed' in msg:
        return 'AI33AuthFailed'
    if 'AI33QuotaFailed' in msg:
        return 'AI33QuotaFailed'
    if 'AI33Timeout' in msg:
        return 'AI33Timeout'
    if 'AI33NoAudioUrl' in msg:
        return 'AI33NoAudioUrl'
    if 'No such file or directory' in msg:
        return 'TTSDependencyMissing'
    if exc.__class__.__name__ == 'CalledProcessError':
        return 'TTSFfmpegFailed'
    return 'TTSGenerationFailed'


def _early_voice_report_fields():
    raw_voice = (voice_name or '').strip()
    lower = raw_voice.lower()
    fields = {
        "voice_name": raw_voice,
        "tts_engine_requested": "ai33" if lower.startswith("ai33") else ("kokoro" if lower.startswith("kokoro") else ("resona" if lower.startswith("resona") else ("capcut" if lower.startswith("capcut:") else "edge-tts"))),
    }
    if lower.startswith("ai33"):
        voice_id = raw_voice.split(":", 1)[1].strip() if ":" in raw_voice else raw_voice
        fields.update({
            "voice_id": voice_id,
            "canonical_voice": f"ai33:{voice_id}",
            "ai33_voice_used": voice_id,
        })
    return fields


def _write_tts_early_failure_report(exc, error_code=None):
    error_code = error_code or _classify_tts_exception(exc)
    msg = _safe_error_text(exc)
    voice_fields = _early_voice_report_fields()
    report = {
        "status": "fail",
        "phase": "tts_generation",
        "error_code": error_code,
        "error_message": msg,
        "fail_reasons": [f"{error_code}: {msg}"],
        "ai33_failed_segments": 1 if error_code.startswith("AI33") else 0,
        "ai33_fail_error_codes": [error_code] if error_code.startswith("AI33") else [],
        "tts_checkpoint_schema": 1,
        "tts_checkpoint_path": ai33_checkpoint_path.name,
        "tts_cues_completed": 0,
        "tts_cues_total": 0,
        "tts_cues_reused": 0,
        "failed_cue": 0,
        "failed_stage": "provider" if error_code.startswith("AI33") else "",
        "failed_code": error_code,
        "failed_attempts": 0,
        "resume_from_cue": 1,
        **voice_fields,
    }
    stats = {
        "entries": 0,
        "source_entries": 0,
        "tts_silence_fallback_segments": 0,
        "tts_circuit_breaker_segments": 0,
        "error_code": error_code,
        "error_message": msg,
        "tts_checkpoint_schema": 1,
        "tts_checkpoint_path": ai33_checkpoint_path.name,
        "tts_cues_completed": 0,
        "tts_cues_total": 0,
        "tts_cues_reused": 0,
        "tts_failed_cue": 0,
        "tts_failed_stage": "provider" if error_code.startswith("AI33") else "",
        "tts_failed_code": error_code,
        "tts_failed_attempts": 0,
        "tts_resume_from_cue": 1,
        **voice_fields,
    }
    try:
        if stats_path.exists():
            existing = json.loads(stats_path.read_text(encoding='utf-8'))
            if isinstance(existing, dict):
                existing.update(stats)
                stats = existing
        stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
    except Exception:
        pass
    try:
        report_path = os.environ.get('VOICE_SYNC_REPORT_JSON') or str(root / 'voice_sync_quality_report.json')
        if report_path:
            p = Path(report_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
    except Exception:
        pass
    return error_code, msg


def _write_tts_error_status(exc, error_code='TTSGenerationFailed'):
    try:
        existing = {}
        if job_status_path.exists():
            existing = json.loads(job_status_path.read_text(encoding='utf-8'))
        if not isinstance(existing, dict):
            existing = {}
        msg = _safe_error_text(exc)
        now = time.time()
        existing.update({
            "status_schema": existing.get("status_schema", 1),
            "phase": "error",
            "phase_label_vi": "Lỗi TTS",
            "progress_percent": existing.get("progress_percent", 66),
            "last_heartbeat_at": time.strftime('%Y-%m-%d %H:%M:%S %z'),
            "last_log_line": f"TTS failed: {msg}",
            "api_expected": False,
            "error_code": error_code,
            "error_message": msg,
            "updated_at_epoch": now,
            "state": "error",
        })
        job_status_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass

def _tts_excepthook(exc_type, exc, tb):
    error_code, _ = _write_tts_early_failure_report(exc)
    _write_tts_error_status(exc, error_code)
    sys.__excepthook__(exc_type, exc, tb)

sys.excepthook = _tts_excepthook
try:
    tts_timeout = max(5, int(float(timeout_raw)))
except Exception:
    tts_timeout = 20
try:
    circuit_breaker_failures = max(1, int(float(breaker_raw)))
except Exception:
    circuit_breaker_failures = 5
try:
    max_tts_speed = max(1.0, float(max_speed_raw))
except Exception:
    max_tts_speed = 1.2
# Mọi mode đều ưu tiên rewrite + native speed; exact/aggressive mới mở residual atempo rộng.
sync_mode = (os.environ.get("SYNC_MODE", "exact_sync") or "exact_sync").strip().lower()
sync_policy_default = "frame_strict" if sync_mode == "exact_sync" else "bounded"
sync_policy = (os.environ.get("TTS_SYNC_POLICY", sync_policy_default) or sync_policy_default).strip().lower()
frame_strict = (sync_policy == "frame_strict")
exact_sync = (sync_mode == "exact_sync")
allow_aggressive_atempo = (os.environ.get("ALLOW_AGGRESSIVE_ATEMPO", "0") or "0").strip().lower() in ("1", "true", "yes", "on")
try:
    post_atempo_max = max(1.0, float(os.environ.get("POST_ATEMPO_MAX", str(max_tts_speed)) or str(max_tts_speed)))
except Exception:
    post_atempo_max = max_tts_speed
try:
    total_audio_speed_max = max(1.0, float(os.environ.get("TOTAL_AUDIO_SPEED_MAX", str(max_tts_speed)) or str(max_tts_speed)))
except Exception:
    total_audio_speed_max = max_tts_speed
if frame_strict and allow_aggressive_atempo:
    max_tts_speed = 99.0  # atempo chain (build_atempo_filters) xử lý ratio bất kỳ
    post_atempo_max = max(post_atempo_max, max_tts_speed)
    total_audio_speed_max = max(total_audio_speed_max, max_tts_speed)
else:
    max_tts_speed = min(max_tts_speed, total_audio_speed_max)
    post_atempo_max = min(post_atempo_max, max_tts_speed, total_audio_speed_max)
allow_slow_fit = (os.environ.get("ALLOW_SLOW_FIT", "0") or "0").strip().lower() in ("1", "true", "yes", "on")
try:
    post_atempo_min = max(0.5, min(1.0, float(os.environ.get("POST_ATEMPO_MIN", "0.95") or "0.95")))
except Exception:
    post_atempo_min = 0.95
slow_fit_min_default = "1.0"
try:
    min_slow_ratio = float(os.environ.get("TTS_SLOW_FIT_MIN", slow_fit_min_default))
except Exception:
    min_slow_ratio = float(slow_fit_min_default)
if frame_strict or not allow_slow_fit:
    min_slow_ratio = max(1.0, min_slow_ratio)
else:
    # Bounded mode chỉ cho phép opt-in slow nhẹ 0.95–0.99; mặc định pad silence.
    min_slow_ratio = min(0.99, max(post_atempo_min, min_slow_ratio))
frame_strict_max_segment_drift = max(0, int(float(os.environ.get("FRAME_STRICT_MAX_SEGMENT_DRIFT_MS", "80"))))
frame_strict_base_total_drift = max(0, int(float(os.environ.get("FRAME_STRICT_MAX_TOTAL_DRIFT_MS", "200"))))
frame_strict_total_drift_per_segment = max(0, int(float(os.environ.get("FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS", "5"))))
frame_strict_max_total_drift = frame_strict_base_total_drift
try:
    fit_tolerance_ms = max(0, int(float(os.environ.get('TTS_FIT_TOLERANCE_MS', '20'))))
except Exception:
    fit_tolerance_ms = 20
try:
    target_video_ms = max(0, int(float(target_duration_raw) * 1000))
except Exception:
    target_video_ms = 0
try:
    allow_overhang_ms = max(0, int(float(overhang_raw) * 1000))
except Exception:
    allow_overhang_ms = 600

skill_dir = Path(os.environ.get('DOUYIN_DUBBER_SKILL_DIR') or '.')
capcut_wrapper = Path(os.environ.get('CAPCUT_TTS_WRAPPER') or (skill_dir / 'capcut_tts_synthesize.py'))
capcut_voices_json = Path(os.environ.get('CAPCUT_TTS_VOICES_JSON') or (skill_dir / 'capcut_voices.json'))
capcut_edge_fallback_voice = os.environ.get('CAPCUT_TTS_EDGE_FALLBACK_VOICE', 'vi-VN-HoaiMyNeural')
capcut_disable_edge_fallback = os.environ.get('CAPCUT_TTS_DISABLE_EDGE_FALLBACK', '0') == '1'
capcut_debug_dir = root / 'capcut_tts_debug'
_capcut_voice_cache = None
kokoro_voices_json = Path(os.environ.get('KOKORO_VOICES_JSON') or (skill_dir / 'kokoro_voices.json'))
kokoro_default_voice = os.environ.get('KOKORO_DEFAULT_VOICE', 'mai_linh') or 'mai_linh'
kokoro_tts_device = os.environ.get('KOKORO_TTS_DEVICE', 'cpu') or 'cpu'
kokoro_tts_repo_id = os.environ.get('KOKORO_TTS_REPO_ID', 'contextboxai/Kokoro-Vietnamese') or 'contextboxai/Kokoro-Vietnamese'
kokoro_tts_model = os.environ.get('KOKORO_TTS_MODEL') or None
kokoro_tts_config = os.environ.get('KOKORO_TTS_CONFIG') or None
kokoro_tts_voicepack = os.environ.get('KOKORO_TTS_VOICEPACK') or None
try:
    kokoro_tts_speed = max(0.25, float(os.environ.get('KOKORO_TTS_SPEED', '1.0') or '1.0'))
except Exception:
    kokoro_tts_speed = 1.0
try:
    kokoro_tts_crossfade_ms = max(0, int(float(os.environ.get('KOKORO_TTS_CROSSFADE_MS', '50') or '50')))
except Exception:
    kokoro_tts_crossfade_ms = 50
try:
    _kokoro_normalize_raw = os.environ.get('KOKORO_TTS_NORMALIZE_PEAK', '')
    kokoro_tts_normalize_peak = float(_kokoro_normalize_raw) if _kokoro_normalize_raw else None
    if kokoro_tts_normalize_peak is not None and kokoro_tts_normalize_peak <= 0:
        kokoro_tts_normalize_peak = None
except Exception:
    kokoro_tts_normalize_peak = None
_kokoro_voice_cache = None
_kokoro_models = {}

# --- Resona TTS (engine chính, Edge chỉ là fallback tường minh cho short-text policy) ---
resona_wrapper = Path(os.environ.get('RESONA_TTS_WRAPPER') or (skill_dir / 'resona_tts_synthesize.py'))
resona_api_base = os.environ.get('RESONA_API_BASE', 'https://resona.live')
resona_default_voice_id = os.environ.get('RESONA_DEFAULT_VOICE_ID', 'ZJEpWoOyElCKuEljNTkm')
resona_api_token = os.environ.get('RESONA_API_TOKEN') or os.environ.get('RESONA_ACCESS_TOKEN') or ''
resona_min_chars = max(1, int(os.environ.get('RESONA_MIN_CHARS', '50')))
resona_max_chars = max(resona_min_chars, int(os.environ.get('RESONA_MAX_CHARS', '2000')))
resona_short_text_policy = (os.environ.get('RESONA_SHORT_TEXT_POLICY', 'group_or_fail') or 'group_or_fail').lower()
resona_short_group_enabled = os.environ.get('RESONA_SHORT_GROUP_ENABLED', '1') != '0'
try:
    resona_short_group_max_cues = max(1, int(os.environ.get('RESONA_SHORT_GROUP_MAX_CUES', '8')))
except Exception:
    resona_short_group_max_cues = 8
try:
    resona_short_group_max_duration_ms = max(500, int(float(os.environ.get('RESONA_SHORT_GROUP_MAX_DURATION_SECONDS', '12')) * 1000))
except Exception:
    resona_short_group_max_duration_ms = 12000
try:
    resona_short_group_soft_max_ms = max(500, int(float(os.environ.get('RESONA_SHORT_GROUP_SOFT_MAX_DURATION_SECONDS', '12')) * 1000))
except Exception:
    resona_short_group_soft_max_ms = 12000
try:
    resona_short_group_hard_max_ms = max(resona_short_group_soft_max_ms, int(float(os.environ.get('RESONA_SHORT_GROUP_HARD_MAX_DURATION_SECONDS', '18')) * 1000))
except Exception:
    resona_short_group_hard_max_ms = 18000
try:
    resona_short_group_max_internal_gap_ms = max(0, int(os.environ.get('RESONA_SHORT_GROUP_MAX_INTERNAL_GAP_MS', '2500')))
except Exception:
    resona_short_group_max_internal_gap_ms = 2500
resona_poll_interval = max(1.0, float(os.environ.get('RESONA_POLL_INTERVAL_SECONDS', '2')))
resona_timeout_seconds = max(30, int(os.environ.get('RESONA_TIMEOUT_SECONDS', '180')))
resona_debug_dir = root / 'resona_tts_debug'

# --- AI33 TTS (ElevenLabs provider qua AI33 API) ---
ai33_wrapper = Path(os.environ.get('AI33_TTS_WRAPPER') or (skill_dir / 'ai33_tts_synthesize.py'))
ai33_api_base = os.environ.get('AI33_API_BASE', 'https://api.ai33.pro')
ai33_api_key = os.environ.get('AI33_API_KEY') or os.environ.get('AI33_ACCESS_TOKEN') or ''
ai33_mai_phuong_voice_id = os.environ.get('AI33_MAI_PHUONG_VOICE_ID', 'vbee_hn_female_maiphuong_vdts_48k-fhg')
ai33_phanh_voice_id = os.environ.get('AI33_PHANH_VOICE_ID', 'elevenlabs_UuMSQK8FdLwaY2M8ZAnh')
ai33_default_voice_id = os.environ.get('AI33_DEFAULT_VOICE_ID', ai33_mai_phuong_voice_id)
try:
    ai33_tts_speed = max(0.5, min(1.5, float(os.environ.get('AI33_TTS_SPEED', '1.0') or '1.0')))
except Exception:
    ai33_tts_speed = 1.0
try:
    ai33_max_speed = max(ai33_tts_speed, min(1.5, float(os.environ.get('AI33_MAX_SPEED', '1.12') or '1.12')))
except Exception:
    ai33_max_speed = max(ai33_tts_speed, 1.12)
ai33_with_transcript = (os.environ.get('AI33_WITH_TRANSCRIPT', 'false') or 'false').lower()
ai33_context_chaining = (os.environ.get('AI33_CONTEXT_CHAINING', 'false') or 'false').lower()
ai33_pronunciation_dictionary_id = (os.environ.get('AI33_PRONUNCIATION_DICTIONARY_ID', '') or '').strip()
try:
    ai33_source_quality_retries = max(0, min(2, int(os.environ.get('AI33_SOURCE_QUALITY_RETRIES', '1') or '1')))
except Exception:
    ai33_source_quality_retries = 1
ai33_poll_interval = max(1.0, float(os.environ.get('AI33_POLL_INTERVAL_SECONDS', '2')))
ai33_timeout_seconds = max(30, int(os.environ.get('AI33_TIMEOUT_SECONDS', '180')))
ai33_debug_dir = root / 'ai33_tts_debug'
# Ưu tiên severity cao nhất để TTS_GATE chọn error_code đại diện khi nhiều segment fail.
RESONA_ERROR_SEVERITY = [
    'ResonaAuthMissing', 'ResonaAuthFailed', 'ResonaQuotaFailed',
    'ResonaTimeout', 'ResonaNoAudioUrl', 'ResonaTextTooShortUngroupable',
    'ResonaTextTooShort', 'ResonaCoverageTooLow', 'TTSResonaFailed',
]
AI33_ERROR_SEVERITY = [
    'AI33AuthMissing', 'AI33AuthFailed', 'AI33QuotaFailed',
    'AI33InputEmpty', 'AI33VoiceInvalid', 'AI33WrapperMissing',
    'AI33CreateRateLimited', 'AI33CreateHttp5xx', 'AI33CreateTimeout',
    'AI33PollingBusy', 'AI33PollingRateLimited', 'AI33PollingHttp5xx', 'AI33PollingTimeout', 'AI33TaskFailed',
    'AI33DownloadRateLimited', 'AI33DownloadHttp5xx', 'AI33DownloadHttp4xx', 'AI33DownloadTimeout', 'AI33DownloadNetwork', 'AI33DownloadEmpty', 'AI33DownloadCorrupt',
    'AI33ConvertFailed', 'AI33WavInvalid', 'AI33WavSilent', 'AI33WavDurationInvalid',
    'AI33CircuitOpen',
    'AI33Timeout', 'AI33NoAudioUrl', 'TTSAI33Failed',
]


def resolve_resona_voice_id(voice_spec: str) -> str:
    """resona -> default id; resona:<id> -> id."""
    raw = (voice_spec or '').strip()
    if raw.lower() == 'resona':
        return resona_default_voice_id
    if raw.lower().startswith('resona:'):
        return raw.split(':', 1)[1].strip() or resona_default_voice_id
    return raw or resona_default_voice_id


def resona_credit_chars(text: str) -> int:
    """Resona tinh credit gan dung: bo khoang trang va nhan Speaker N."""
    text = re.sub(r'(?im)^\s*Speaker\s*\d+\s*:\s*', '', text or '')
    text = re.sub(r'\s+', '', text)
    return len(text)


def _legacy_ai33_voice_id(voice_spec: str) -> str:
    raw = (voice_spec or '').strip()
    lower = raw.lower()
    if lower in ('', 'ai33', 'vbee', 'vbee-maiphuong', 'vbee-mai-phuong', 'maiphuong', 'mai-phuong', 'mai_phuong'):
        return ai33_mai_phuong_voice_id or ai33_default_voice_id
    if lower in ('elevenlabs', 'elevenlabs-phanh', 'eleven-phanh', 'phanh', 'phan'):
        return ai33_phanh_voice_id or ai33_default_voice_id
    if lower.startswith('ai33:'):
        return raw.split(':', 1)[1].strip() or ai33_default_voice_id
    if lower.startswith('elevenlabs_') or lower.startswith('vbee_'):
        return raw
    return raw or ai33_default_voice_id


def resolve_ai33_voice_meta(voice_spec: str) -> dict:
    raw = (voice_spec or '').strip()
    source_hint = (os.environ.get('VOICE_SOURCE_HINT') or '').strip().lower()
    if source_hint not in ('registry', 'explicit'):
        source_hint = 'explicit' if raw else 'registry'
    if voice_registry is not None:
        try:
            meta = dict(voice_registry.ai33_metadata(raw or None))
            meta['voice_source'] = source_hint
            return meta
        except Exception as exc:
            lower = raw.lower()
            if lower.startswith('ai33:') or lower.startswith('vbee_') or lower.startswith('elevenlabs_') or lower in {
                'ai33', 'vbee', 'vbee-maiphuong', 'vbee-mai-phuong', 'maiphuong',
                'mai-phuong', 'mai_phuong', 'elevenlabs', 'elevenlabs-phanh',
                'eleven-phanh', 'phanh', 'phan',
            }:
                raise RuntimeError(f"VoiceInvalid: {exc}") from exc
    voice_id = _legacy_ai33_voice_id(raw)
    return {
        "provider": "ai33",
        "voice_id": voice_id,
        "canonical_voice": f"ai33:{voice_id}",
        "label": "AI33 legacy fallback",
        "aliases": [],
        "enabled": True,
        "timing_profile": "ai33_balanced_fast",
        "min_slow_ratio": 0.85,
        "voice_source": "legacy_env",
    }


def resolve_ai33_voice_id(voice_spec: str) -> str:
    return str(resolve_ai33_voice_meta(voice_spec).get("voice_id") or _legacy_ai33_voice_id(voice_spec))


ai33_voice_meta = {}
timing_overrides_applied = {}
dub_text_overrides_applied = {}

def apply_ai33_timing_overrides(meta: dict):
    """Apply only stricter per-voice speed caps; global policy remains authoritative."""
    global ai33_max_speed, post_atempo_max, total_audio_speed_max, max_tts_speed
    overrides = meta.get("timing_overrides") if isinstance(meta, dict) else {}
    if not isinstance(overrides, dict):
        return
    caps = {
        "ai33_max_speed": "ai33_max_speed",
        "post_atempo_max": "post_atempo_max",
        "total_audio_speed_max": "total_audio_speed_max",
    }
    for key, variable in caps.items():
        raw_value = overrides.get(key)
        if raw_value is None:
            continue
        try:
            requested = max(1.0, min(1.5, float(raw_value)))
        except Exception:
            continue
        current = globals()[variable]
        applied = min(current, requested)
        globals()[variable] = applied
        timing_overrides_applied[key] = round(applied, 4)
    max_tts_speed = min(max_tts_speed, total_audio_speed_max)
    post_atempo_max = min(post_atempo_max, max_tts_speed, total_audio_speed_max)

if voice_name.lower().startswith("ai33"):
    ai33_voice_meta = resolve_ai33_voice_meta(voice_name)
    apply_ai33_timing_overrides(ai33_voice_meta)
    if allow_slow_fit and not frame_strict and "TTS_SLOW_FIT_MIN" not in os.environ:
        try:
            min_slow_ratio = min(0.99, max(post_atempo_min, float(ai33_voice_meta.get("min_slow_ratio", min_slow_ratio))))
        except Exception:
            pass


def synthesize_ai33_tts(mp3_path: Path, wav_path: Path, text: str, voice_spec: str, slot_ms: int, speed: float = None, cue_index: int = 0):
    """AI33 adapter with per-cue atomic checkpoint; failures never become renderable silence."""
    text = (text or '').strip()
    voice_id = resolve_ai33_voice_id(voice_spec)
    try:
        speed_value = max(0.5, min(1.5, float(ai33_tts_speed if speed is None else speed)))
    except Exception:
        speed_value = ai33_tts_speed
    # Keep provider-affecting knobs secret-free and bind the native speed used
    # for this cue; a speed retry must never reuse the 1.0x audio by accident.
    cue_settings_fingerprint = hashlib.sha256(json.dumps({
        'speed': speed_value, 'context_chaining': ai33_context_chaining,
        'with_transcript': ai33_with_transcript, 'sample_rate': tts_master_sample_rate,
        'channels': tts_master_channels, 'api_base': ai33_api_base,
        'poll_interval': ai33_poll_interval, 'timeout_total': ai33_timeout_seconds,
        'pronunciation_dictionary_id': ai33_pronunciation_dictionary_id,
    }, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    if not text:
        return {"ok": False, "fallback_silence": False, "engine": "ai33", "ai33_failed": True, "error_code": "AI33InputEmpty", "attempts": 0}
    if not ai33_wrapper.exists():
        return {"ok": False, "fallback_silence": False, "engine": "ai33", "ai33_failed": True, "error_code": "AI33WrapperMissing", "attempts": 0, "error": "ai33_wrapper_missing"}
    ai33_debug_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        'python3', str(ai33_wrapper),
        '--text', text,
        '--voice', voice_id,
        '--output', str(wav_path),
        '--api-base', ai33_api_base,
        '--speed', f'{speed_value:.3f}',
        '--with-transcript', ai33_with_transcript,
        '--context-chaining', ai33_context_chaining,
        '--timeout-total', str(ai33_timeout_seconds),
        '--poll-interval', str(ai33_poll_interval),
        '--debug-dir', str(ai33_debug_dir),
        '--sample-rate', str(tts_master_sample_rate),
        '--channels', str(tts_master_channels),
        '--report-json', str(tts_audio_stage_report_path),
        '--checkpoint', str(ai33_checkpoint_path),
        '--provider-state', str(ai33_provider_state_path),
        '--status-json', str(job_status_path),
        '--breaker-threshold', str(os.environ.get('AI33_CIRCUIT_BREAKER_FAILURES', '2')),
        '--breaker-cooldown-seconds', str(os.environ.get('AI33_CIRCUIT_COOLDOWN_SECONDS', '60')),
        '--cue-index', str(cue_index),
        '--total-cues', str(len(entries)),
        '--source-fingerprint', source_fingerprint,
        '--settings-fingerprint', cue_settings_fingerprint,
    ]
    if ai33_pronunciation_dictionary_id:
        cmd.extend(['--pronunciation-dictionary-id', ai33_pronunciation_dictionary_id])
    if cue_index in forced_cue_ids:
        cmd.append('--force-regenerate')
    proc = None
    source_quality_retry_count = 0
    for source_quality_attempt in range(ai33_source_quality_retries + 1):
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 256:
            try:
                wrapper_result = json.loads((proc.stdout or '').strip().splitlines()[-1])
            except Exception:
                wrapper_result = {}
            return {
                "ok": True, "fallback_silence": False, "engine": "ai33",
                "ai33_failed": False, "attempts": int(wrapper_result.get('attempts') or 1),
                "ai33_voice": voice_id, "ai33_speed": round(speed_value, 4),
                "checkpoint_reused": bool(wrapper_result.get('reused')),
                "source_quality_retries": source_quality_retry_count,
            }
        stderr = (proc.stderr or '')[:500]
        if 'AI33SourceSampleRateLow' not in stderr or source_quality_attempt >= ai33_source_quality_retries:
            break
        source_quality_retry_count += 1
        print(
            f"WARN: AI33 source sample rate below {tts_master_sample_rate}Hz; "
            f"regenerating cue={cue_index} retry={source_quality_retry_count}/{ai33_source_quality_retries}",
            flush=True,
        )
        wav_path.unlink(missing_ok=True)
        if '--force-regenerate' not in cmd:
            cmd.append('--force-regenerate')
    stderr = (proc.stderr or '')[:500]
    error_code = "TTSAI33Failed"
    if 'AI33AuthMissing' in stderr:
        error_code = "AI33AuthMissing"
    elif 'AI33AuthFailed' in stderr:
        error_code = "AI33AuthFailed"
    elif 'AI33QuotaFailed' in stderr:
        error_code = "AI33QuotaFailed"
    elif 'AI33Timeout' in stderr:
        error_code = "AI33Timeout"
    elif 'AI33NoAudioUrl' in stderr or 'No generated' in stderr or 'no generated' in stderr:
        error_code = "AI33NoAudioUrl"
    else:
        for candidate in ('AI33InputEmpty', 'AI33VoiceInvalid', 'AI33CreateRateLimited', 'AI33CreateHttp5xx', 'AI33CreateTimeout', 'AI33PollingBusy', 'AI33PollingRateLimited', 'AI33PollingHttp5xx', 'AI33PollingTimeout', 'AI33TaskFailed', 'AI33DownloadRateLimited', 'AI33DownloadHttp5xx', 'AI33DownloadHttp4xx', 'AI33DownloadTimeout', 'AI33DownloadNetwork', 'AI33DownloadEmpty', 'AI33DownloadCorrupt', 'AI33SourceSampleRateLow', 'AI33ConvertFailed', 'AI33WavInvalid', 'AI33WavSilent', 'AI33WavDurationInvalid', 'AI33CircuitOpen'):
            if candidate in stderr:
                error_code = candidate; break
    print(f"WARN: AI33 TTS fail voice={voice_spec} code={error_code} rc={proc.returncode} stderr={stderr[:200]}", flush=True)
    return {
        "ok": False, "fallback_silence": False, "engine": "ai33",
        "ai33_failed": True, "error_code": error_code,
        # The wrapper writes its classified retry count as ``attempts=N``.
        # Preserve that exact value in the job report/checkpoint handoff rather
        # than turning every provider failure into a misleading single attempt.
        "attempts": int((re.search(r'attempts=(\d+)', stderr) or [None, '0'])[1]), "ai33_stderr": stderr,
        "ai33_stage": (re.search(r'stage=([a-z_]+)', stderr) or [None, 'provider'])[1],
    }


def synthesize_resona_tts(mp3_path: Path, wav_path: Path, text: str, voice_spec: str, slot_ms: int):
    """Gọi Resona adapter. KHÔNG fallback Edge khi API lỗi thật.
    Chỉ fallback Edge khi text quá ngắn (<RESONA_MIN_CHARS) và policy=edge.
    Fail -> write_silence tạm (loop/report không crash) + resona_failed=True + error_code cụ thể.
    """
    text = (text or '').strip()
    voice_id = resolve_resona_voice_id(voice_spec)

    # Text quá ngắn: Resona cần tối thiểu ~50 credit/request.
    if resona_credit_chars(text) < resona_min_chars:
        # policy=group_or_fail (default): build_resona_tts_entries đã cố gom mà vẫn thiếu
        # -> fail rõ, KHÔNG fallback Edge mặc định.
        if resona_short_text_policy in ('fail', 'group_or_fail'):
            write_silence(wav_path, slot_ms)
            return {
                "ok": False, "fallback_silence": True, "engine": "resona",
                "resona_failed": True, "resona_short_text": True,
                "error_code": "ResonaTextTooShortUngroupable", "attempts": 0,
            }
        # policy=edge: fallback Edge tường minh (chỉ khi user bật tường minh).
        edge_result = synthesize_edge_tts(mp3_path, wav_path, text, capcut_edge_fallback_voice or 'vi-VN-HoaiMyNeural')
        edge_result["resona_short_edge_fallback"] = True
        edge_result["resona_short_text"] = True
        return edge_result

    # Text quá dài: truncate an toàn (không fatal).
    if resona_credit_chars(text) > resona_max_chars:
        text = text[:resona_max_chars]

    if not resona_wrapper.exists():
        write_silence(wav_path, slot_ms)
        return {
            "ok": False, "fallback_silence": True, "engine": "resona",
            "resona_failed": True, "error_code": "TTSResonaFailed",
            "attempts": 0, "error": "resona_wrapper_missing",
        }
    if not resona_api_token:
        write_silence(wav_path, slot_ms)
        return {
            "ok": False, "fallback_silence": True, "engine": "resona",
            "resona_failed": True, "error_code": "ResonaAuthMissing",
            "attempts": 0,
        }

    resona_debug_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        'python3', str(resona_wrapper),
        '--text', text,
        '--voice', voice_id,
        '--output', str(wav_path),
        '--sample-rate', str(tts_master_sample_rate),
        '--channels', str(tts_master_channels),
        '--api-base', resona_api_base,
        '--timeout-total', str(resona_timeout_seconds),
        '--poll-interval', str(resona_poll_interval),
        '--debug-dir', str(resona_debug_dir),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 256:
        return {
            "ok": True, "fallback_silence": False, "engine": "resona",
            "resona_failed": False, "attempts": 1,
        }
    # Map exit code -> error_code cụ thể (đọc stderr marker do adapter emit).
    stderr = (proc.stderr or '')[:500]
    error_code = "TTSResonaFailed"
    if 'ResonaAuthMissing' in stderr:
        error_code = "ResonaAuthMissing"
    elif 'ResonaAuthFailed' in stderr:
        error_code = "ResonaAuthFailed"
    elif 'ResonaQuotaFailed' in stderr:
        error_code = "ResonaQuotaFailed"
    elif 'ResonaTimeout' in stderr:
        error_code = "ResonaTimeout"
    elif 'ResonaNoAudioUrl' in stderr or 'No generated' in stderr or 'no generated' in stderr:
        error_code = "ResonaNoAudioUrl"
    print(f"WARN: Resona TTS fail voice={voice_spec} code={error_code} rc={proc.returncode} stderr={stderr[:200]}", flush=True)
    write_silence(wav_path, slot_ms)
    return {
        "ok": False, "fallback_silence": True, "engine": "resona",
        "resona_failed": True, "error_code": error_code,
        "attempts": 1, "resona_stderr": stderr,
    }

# --- Inline rewrite cho TTS quá dài (case Douyin: TTS dài hơn slot -> drift tích lũy) ---
# Khi 1 segment sau speed-fit tới MAX_TTS_SPEED vẫn dài hơn slot, rewrite dub_text ngắn hơn
# rồi re-synthesize + đo lại. Tối đa TTS_REWRITE_MAX_ATTEMPTS. Vẫn quá -> mark fail, gate fail.
# Source_text Trung lấy từ dubbing_segments.json (optimizer ghi, chung output_entries với dub.srt).
# Inline chat()/rewrite_dub() copy y hệt viet_dub_timing_optimizer.py:112 / :621 (canonical).
_rw_api_base = (os.environ.get('DOUYIN_DUBBER_API_BASE') or '').strip()
_rw_api_key = (os.environ.get('DOUYIN_DUBBER_API_KEY') or '').strip()
_rw_model = (os.environ.get('DOUYIN_DUBBER_MODEL') or '').strip()
_rw_api_provider = (os.environ.get('OPENCLAW_AI_PROVIDER') or 'ninerouter').strip()
try:
    rw_max_attempts = max(0, int(os.environ.get('TTS_REWRITE_MAX_ATTEMPTS', '1')))
except Exception:
    rw_max_attempts = 1
try:
    adapt_max_attempts = max(0, int(os.environ.get('TTS_ADAPT_MAX_ATTEMPTS', str(rw_max_attempts))))
except Exception:
    adapt_max_attempts = rw_max_attempts
adapt_enabled = (os.environ.get('TTS_ADAPT_ENABLED', '1') or '1').strip().lower() in ('1', 'true', 'yes', 'on')
try:
    restore_if_slot_ratio_below = min(1.0, max(0.1, float(os.environ.get('TTS_RESTORE_IF_SLOT_RATIO_BELOW', '0.72'))))
except Exception:
    restore_if_slot_ratio_below = 0.72

def apply_ai33_dub_text_overrides(meta: dict):
    """Use a validated per-voice threshold for safe detail restoration only."""
    global restore_if_slot_ratio_below
    overrides = meta.get("dub_text_overrides") if isinstance(meta, dict) else {}
    if not isinstance(overrides, dict):
        return
    raw_value = overrides.get("restore_if_slot_ratio_below")
    if raw_value is None:
        return
    try:
        requested = min(0.95, max(0.5, float(raw_value)))
    except Exception:
        return
    restore_if_slot_ratio_below = requested
    dub_text_overrides_applied["restore_if_slot_ratio_below"] = round(requested, 4)
    print(f"AI33 dub-text profile: restore_if_slot_ratio_below={requested:.2f}", flush=True)

if voice_name.lower().startswith("ai33"):
    apply_ai33_dub_text_overrides(ai33_voice_meta)
if not (_rw_api_base and _rw_model):
    rw_max_attempts = 0
    adapt_max_attempts = 0  # no configured rewrite model: keep natural or mark attention

_seg_source_lookup = {}
_seg_context_lookup = {}
_segs_json_path = os.environ.get('DOUYIN_DUBBER_SEGMENTS_JSON') or ''
if _segs_json_path and Path(_segs_json_path).exists():
    try:
        for _e in json.loads(Path(_segs_json_path).read_text(encoding='utf-8')):
            try:
                _seg_key = (int(_e.get('start_ms')), int(_e.get('end_ms')))
                _seg_source_lookup[_seg_key] = _e.get('source_text') or ''
                _seg_context_lookup[_seg_key] = {
                    'source_text': _e.get('source_text') or '',
                    'subtitle_text': _e.get('subtitle_text') or '',
                    'dub_text': _e.get('dub_text') or '',
                }
            except Exception:
                continue
    except Exception as exc:
        print(f"WARN: load dubbing_segments.json cho rewrite fail: {exc}", flush=True)

_rw_chat_timeout = float(os.environ.get('OPTIMIZER_CHAT_TIMEOUT_SECONDS', '90'))
_rw_max_retries = int(os.environ.get('OPTIMIZER_CHAT_MAX_RETRIES', '3'))
_rw_backoff_base = float(os.environ.get('OPTIMIZER_CHAT_BACKOFF_BASE', '5.0'))

def _rw_chat(messages, temperature=0.2):
    """Copy y hệt viet_dub_timing_optimizer.py:chat (urllib, 429 backoff, ollama vs ninerouter)."""
    api_base, api_key, model, api_provider = _rw_api_base, _rw_api_key, _rw_model, _rw_api_provider
    if not (api_base and model):
        raise RuntimeError('missing API base/model')
    if api_provider == 'ollama':
        payload = {'model': model, 'messages': messages, 'format': 'json', 'temperature': temperature,
                   'stream': False, 'think': False,
                   'options': {'temperature': temperature, 'num_predict': int(os.environ.get('OPTIMIZER_OLLAMA_NUM_PREDICT', '1024'))}}
        url = api_base.rstrip('/') + '/api/chat'
        headers = {'Content-Type': 'application/json'}
        is_ollama = True
    else:
        payload = {'model': model, 'messages': messages, 'temperature': temperature, 'stream': False, 'think': False}
        url = api_base.rstrip('/') + '/chat/completions'
        headers = {'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'} if api_key else {'Content-Type': 'application/json'}
        is_ollama = False
    last_exc = None
    for attempt in range(_rw_max_retries + 1):
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                     headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=_rw_chat_timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            last_exc = exc
            body = ''
            try:
                body = exc.read().decode('utf-8', 'replace')[:200]
            except Exception:
                pass
            if exc.code == 429 and attempt < _rw_max_retries:
                time.sleep(_rw_backoff_base * (2 ** attempt))
                continue
            raise RuntimeError(f'HTTP {exc.code}: {body or exc.reason}')
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < _rw_max_retries:
                time.sleep(_rw_backoff_base * (2 ** attempt))
                continue
            raise RuntimeError(f'network: {exc}')
        if is_ollama:
            content = (data.get('message') or {}).get('content', '').strip()
            if not content:
                # Some Ollama-compatible routes accept format=json but return an
                # empty message. Retry that successful response once without the
                # format constraint; malformed nonempty responses stay with the
                # strict parser and outer bounded adaptation retry.
                compatibility_payload = dict(payload)
                compatibility_payload.pop('format', None)
                print('WARN: Ollama structured response empty; compatibility retry without format', flush=True)
                compatibility_req = urllib.request.Request(
                    url, data=json.dumps(compatibility_payload, ensure_ascii=False).encode('utf-8'),
                    headers=headers, method='POST')
                try:
                    with urllib.request.urlopen(compatibility_req, timeout=_rw_chat_timeout) as compatibility_resp:
                        compatibility_data = json.loads(compatibility_resp.read().decode('utf-8'))
                except urllib.error.HTTPError as exc:
                    raise RuntimeError(f'Ollama compatibility retry HTTP {exc.code}') from exc
                except urllib.error.URLError as exc:
                    raise RuntimeError('Ollama compatibility retry network failure') from exc
                content = (compatibility_data.get('message') or {}).get('content', '').strip()
                if not content:
                    raise RuntimeError('Ollama không trả nội dung')
            return content
        content = (data.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
        if not content:
            raise RuntimeError('9Router không trả nội dung')
        return content
    raise RuntimeError(f'chat exhausted retries: {last_exc}')

def rewrite_dub(vi_text, source_text, duration_s):
    """Rút gọn câu Việt quá dài để đọc vừa slot. Copy y hệt optimizer:rewrite_dub (:621).
    Trả câu ngắn hơn, hoặc 'UNSAFE_TO_REWRITE' nếu không rút gọn an toàn."""
    lock = [source_text.strip()[:120]] if source_text.strip() else []
    prompt = f"""Câu tiếng Việt sau quá dài để lồng tiếng vào video.
Hãy rút gọn câu này để đọc tự nhiên trong {duration_s:.2f} giây.

Yêu cầu bắt buộc:
- Giữ đúng ý chính, không thêm ý mới, không đổi nghĩa.
- Không đổi cảm xúc gốc.
- Không đổi phủ định thành khẳng định hoặc ngược lại.
- Không bỏ tên riêng, số liệu, địa điểm quan trọng.
- Ngắn hơn bản cũ và nghe tự nhiên như người Việt nói.
- Không giải thích. Trả về duy nhất một câu tiếng Việt.
- Nếu không thể rút gọn an toàn, trả về đúng chuỗi: UNSAFE_TO_REWRITE

Các ý bắt buộc phải giữ:
{json.dumps(lock, ensure_ascii=False)}

Câu Trung gốc:
{source_text}

Câu Việt hiện tại:
{vi_text}"""
    return _rw_chat([{'role': 'system', 'content': 'Bạn rút gọn lời thoại Việt an toàn cho lồng tiếng.'},
                     {'role': 'user', 'content': prompt}]).strip().strip('"')

def _rw_json_object(content):
    """Parse the single JSON object required by the adaptation prompt."""
    return extract_first_json_object(content)

def adapt_dub_text(direction, subtitle_text, dub_text, source_text, natural_tts_ms, slot_ms):
    """Ask the model for a bounded, auditable post-probe adaptation candidate."""
    if direction not in ('shorten', 'restore_safe_detail'):
        raise ValueError(f'unsupported adaptation direction: {direction}')
    if direction == 'shorten':
        instruction = (
            'Rút gọn an toàn: chỉ bỏ cảm thán, từ thừa, lặp ý hoặc mô tả phụ. '
            'Không thêm sự kiện; không đổi nhân vật, chủ thể/hành động, nguyên nhân/kết quả, '
            'số liệu, vật phẩm hay cấp bậc.'
        )
    else:
        instruction = (
            'Khôi phục chi tiết an toàn: chỉ lấy lại chi tiết đã có nguyên văn hoặc tương đương '
            'trong subtitle_text/câu gốc. Không sáng tác chi tiết, sự kiện hay lời đệm để lấp thời lượng.'
        )
    prompt = f"""Bạn chỉnh một câu lồng tiếng Việt SAU KHI đã đo AI33 speed 1.0.
Hướng chỉnh: {direction}.
{instruction}

Trả duy nhất JSON hợp lệ, không markdown:
{{"dub_text":"...","kept_meaning":["..."],"dropped_details":["..."],"restored_details":["..."],"meaning_risk":"low|medium|high","fit_decision":"..."}}

Quy tắc bắt buộc:
- meaning_risk=high nếu không chắc giữ đúng nghĩa; khi đó dub_text phải là câu cũ.
- Không dùng câu vô nghĩa để lấp slot.
- Câu mới phải tự nhiên, tiếng Việt, và khác câu cũ theo đúng hướng chỉnh.
- Slot={slot_ms}ms; AI33 natural={natural_tts_ms}ms. Đây chỉ là dữ kiện timing, không được bịa nội dung.

Câu gốc: {source_text}
Subtitle đã dịch: {subtitle_text}
Dub_text hiện tại: {dub_text}"""
    raw = _rw_chat([
        {'role': 'system', 'content': 'Bạn là biên tập viên lồng tiếng Việt, ưu tiên giữ nghĩa và chỉ trả JSON.'},
        {'role': 'user', 'content': prompt},
    ], temperature=0.1)
    return _rw_json_object(raw)

def check_adapted_meaning(source_text, subtitle_text, before_text, candidate_text):
    """Independent semantic gate; a high-risk candidate must never reach final TTS."""
    prompt = f"""So sánh câu lồng tiếng ứng viên với nguồn. Trả duy nhất JSON hợp lệ:
{{"meaning_preserved":true|false,"meaning_risk":"low|medium|high","reason":"..."}}
Đánh giá high nếu ứng viên thêm sự kiện, đổi nhân vật/chủ thể/hành động, nguyên nhân-kết quả,
phủ định, số liệu, vật phẩm/cấp bậc hoặc làm mất ý bắt buộc.

Nguồn: {source_text}
Subtitle: {subtitle_text}
Câu trước: {before_text}
Ứng viên: {candidate_text}"""
    result = _rw_json_object(_rw_chat([
        {'role': 'system', 'content': 'Bạn là kiểm định nghĩa lời thoại. Chỉ trả JSON.'},
        {'role': 'user', 'content': prompt},
    ], temperature=0.0))
    risk = str(result.get('meaning_risk') or 'high').lower()
    result['meaning_risk'] = risk if risk in ('low', 'medium', 'high') else 'high'
    result['meaning_preserved'] = bool(result.get('meaning_preserved'))
    return result

def parse_ms(ts):
    hh, mm, rest = ts.split(':')
    ss, ms = rest.split(',')
    return ((int(hh)*60 + int(mm))*60 + int(ss))*1000 + int(ms)

def measure_wav_ms(path: Path):
    with wave.open(str(path), 'rb') as wav_f:
        return int(wav_f.getnframes() * 1000 / wav_f.getframerate())

def build_atempo_filters(speed_ratio: float):
    ratio = max(0.5, float(speed_ratio))
    filters = []
    while ratio > 2.0:
        filters.append('atempo=2.0')
        ratio /= 2.0
    filters.append(f'atempo={ratio:.5f}')
    return ",".join(filters)

def unique_segment_wav(segment_index: int, label: str, src_path: Path):
    src_resolved = Path(src_path).resolve()
    safe_label = re.sub(r'[^a-zA-Z0-9_-]+', '_', label).strip('_') or 'fit'
    for n in range(1000):
        suffix = safe_label if n == 0 else f'{safe_label}_{n}'
        candidate = segments_dir / f'{segment_index:04d}_{suffix}.wav'
        if candidate.resolve() == src_resolved:
            continue
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot allocate unique TTS segment path segment={segment_index} label={safe_label}")

def apply_atempo_fit(src_path: Path, segment_index: int, ratio: float, label: str):
    src = Path(src_path)
    ratio = float(ratio)
    epsilon = max(0.0, float(os.environ.get('TTS_ATEMPO_EPSILON', '0.005')))
    # Avoid a no-op encode. More importantly, never let ffmpeg read and write the same file.
    if abs(ratio - 1.0) <= epsilon:
        return src, False
    dst = unique_segment_wav(segment_index, label, src)
    cmd = [
        'ffmpeg', '-y', '-i', str(src),
        '-filter:a', build_atempo_filters(ratio),
        '-ac', str(tts_master_channels), '-ar', str(tts_master_sample_rate), '-c:a', 'pcm_s16le',
        str(dst)
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or '').strip().replace('\n', ' ')[:500]
        raise RuntimeError(
            f"ffmpeg atempo failed segment={segment_index} label={label} "
            f"ratio={ratio:.5f} src={src} dst={dst} stderr={stderr}"
        )
    return dst, True

def normalize_wav_for_concat(src_path: Path, segment_index: int, label: str = 'speech_norm'):
    """Normalize speech chunks before concat; copy-concat of mixed WAV params drifts."""
    src = Path(src_path)
    try:
        with wave.open(str(src), 'rb') as wav_f:
            if wav_f.getnchannels() == tts_master_channels and wav_f.getframerate() == tts_master_sample_rate and wav_f.getsampwidth() == 2:
                return src, False
    except Exception:
        pass
    dst = unique_segment_wav(segment_index, label, src)
    cmd = [
        'ffmpeg', '-y', '-i', str(src),
        '-vn', '-ac', str(tts_master_channels), '-ar', str(tts_master_sample_rate), '-c:a', 'pcm_s16le',
        str(dst)
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or '').strip().replace('\n', ' ')[:500]
        raise RuntimeError(
            f"ffmpeg normalize failed segment={segment_index} label={label} "
            f"src={src} dst={dst} stderr={stderr}"
        )
    return dst, True

def normalize_speech_loudness(src_path: Path, segment_index: int):
    """Match spoken cue loudness before concat while preserving canonical WAV format."""
    src = Path(src_path)
    dst = unique_segment_wav(segment_index, 'speech_loudness', src)
    cmd = [
        'ffmpeg', '-y', '-i', str(src), '-vn',
        '-af', 'loudnorm=I=-20:TP=-3:LRA=7,alimiter=limit=0.7079:level=false',
        '-ac', str(tts_master_channels), '-ar', str(tts_master_sample_rate),
        '-c:a', 'pcm_s16le', str(dst),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or '').strip().replace('\n', ' ')[:500]
        raise RuntimeError(
            f"ffmpeg loudness normalize failed segment={segment_index} "
            f"src={src} dst={dst} stderr={stderr}"
        )
    return dst

def choose_ai33_native_speed(required_ratio: float) -> float:
    """Use AI33 native speed lightly before ffmpeg atempo; keep voice close to source."""
    try:
        required = float(required_ratio)
    except Exception:
        required = 1.0
    if required <= 1.04:
        return ai33_tts_speed
    return max(ai33_tts_speed, min(ai33_max_speed, required))

def post_atempo_cap_for(native_speed: float = 1.0) -> float:
    """Cap post-TTS atempo so native AI33 speed + atempo stays within quality budget."""
    if frame_strict and allow_aggressive_atempo and not voice_name.lower().startswith('ai33'):
        return max_tts_speed
    try:
        native = max(1.0, float(native_speed))
    except Exception:
        native = 1.0
    # In balanced_dub, AI33's stated 1.12 ceiling applies to the complete
    # native × post-atempo chain, not just the provider request speed.
    total_limit = min(total_audio_speed_max, ai33_max_speed) if voice_name.lower().startswith('ai33') else total_audio_speed_max
    remaining_total = total_limit / native
    return max(1.0, min(post_atempo_max, max_tts_speed, remaining_total))

def write_silence(path: Path, duration_ms: int):
    subprocess.run([
        'ffmpeg', '-y', '-f', 'lavfi', '-i', f'anullsrc=r={tts_master_sample_rate}:cl={"mono" if tts_master_channels == 1 else "stereo"}',
        '-t', f'{max(1, duration_ms)/1000:.3f}', '-c:a', 'pcm_s16le', str(path)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def normalize_capcut_key(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (value or '').strip().lower())

def load_capcut_voices():
    global _capcut_voice_cache
    if _capcut_voice_cache is not None:
        return _capcut_voice_cache
    try:
        data = json.loads(capcut_voices_json.read_text(encoding='utf-8'))
        _capcut_voice_cache = data if isinstance(data, list) else []
    except Exception as exc:
        print(f"WARN: Không đọc được capcut_voices.json: {exc}", flush=True)
        _capcut_voice_cache = []
    return _capcut_voice_cache

def resolve_capcut_voice(spec: str):
    raw = (spec.split(':', 1)[1] if ':' in spec else spec).strip()
    if not raw:
        return None
    if ':' in raw:
        voice_type, resource_id = [part.strip() for part in raw.split(':', 1)]
        if voice_type and resource_id:
            return {"voice_type": voice_type, "resource_id": resource_id, "display_name": voice_type}
    wanted = normalize_capcut_key(raw)
    for item in load_capcut_voices():
        if not isinstance(item, dict):
            continue
        keys = [
            item.get('voice_type'),
            item.get('display_name'),
            f"{item.get('display_name', '')}-{item.get('voice_type', '')}",
        ]
        if any(normalize_capcut_key(key) == wanted for key in keys):
            voice_type = item.get('voice_type')
            resource_id = item.get('resource_id')
            if voice_type and resource_id:
                return {"voice_type": voice_type, "resource_id": str(resource_id), "display_name": item.get('display_name') or voice_type}
    return None

def convert_mp3_to_wav(mp3_path: Path, wav_path: Path):
    subprocess.run(['ffmpeg', '-y', '-i', str(mp3_path), '-ac', str(tts_master_channels), '-ar', str(tts_master_sample_rate), '-c:a', 'pcm_s16le', str(wav_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wav_path.exists() and wav_path.stat().st_size > 0

def normalize_kokoro_key(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', (value or '').strip().lower()).strip('_')

def load_kokoro_voices():
    global _kokoro_voice_cache
    if _kokoro_voice_cache is not None:
        return _kokoro_voice_cache
    voices = {}
    try:
        data = json.loads(kokoro_voices_json.read_text(encoding='utf-8'))
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                voice_id = str(item.get('id') or '').strip()
                if voice_id:
                    voices[voice_id] = item
    except Exception as exc:
        print(f"WARN: Không đọc được kokoro_voices.json: {exc}", flush=True)
    _kokoro_voice_cache = voices
    return voices

def resolve_kokoro_voice(spec: str) -> str:
    raw = (spec or '').strip()
    lower = raw.lower()
    if lower in ('', 'kokoro', 'kokoro:'):
        return kokoro_default_voice
    if lower.startswith('kokoro:'):
        raw = raw.split(':', 1)[1].strip()
    key = normalize_kokoro_key(raw)
    voices = load_kokoro_voices()
    if key in voices:
        return key
    for voice_id, meta in voices.items():
        candidates = [
            voice_id,
            meta.get('label', ''),
            meta.get('display_name', ''),
        ]
        if any(normalize_kokoro_key(str(candidate)) == key for candidate in candidates):
            return voice_id
    return key or kokoro_default_voice

def get_kokoro_model(voice_id: str):
    if voice_id in _kokoro_models:
        return _kokoro_models[voice_id]
    try:
        from kokoro_vietnamese import KokoroVietnamese, list_voices
    except Exception as exc:
        raise RuntimeError(
            "KokoroTTSUnavailable: không import được kokoro_vietnamese. "
            "Kiểm tra KOKORO_TTS_PYTHON và venv /home/haonguyen/.local/share/openclaw-kokoro-venv."
        ) from exc
    available = set(list_voices())
    if voice_id not in available:
        raise RuntimeError(f"KokoroVoiceInvalid: voice={voice_id!r} không có trong Kokoro ({', '.join(sorted(available))})")
    kwargs = {
        "repo_id": kokoro_tts_repo_id,
        "voice": voice_id,
        "model_path": kokoro_tts_model,
        "voicepack_path": kokoro_tts_voicepack,
        "config_path": kokoro_tts_config,
        "device": kokoro_tts_device,
    }
    model = KokoroVietnamese(**kwargs)
    _kokoro_models[voice_id] = model
    print(f"Kokoro TTS model loaded voice={voice_id} device={model.device}", flush=True)
    return model

def synthesize_kokoro_tts(mp3_path: Path, wav_path: Path, text: str, voice_spec: str):
    voice_id = resolve_kokoro_voice(voice_spec)
    model = get_kokoro_model(voice_id)
    try:
        import soundfile as sf
        from kokoro_vietnamese import SAMPLE_RATE
        audio, _phonemes = model.synthesize(
            text,
            speed=kokoro_tts_speed,
            crossfade_ms=kokoro_tts_crossfade_ms,
            normalize_peak=kokoro_tts_normalize_peak,
        )
        if len(audio) == 0:
            raise RuntimeError("No audio generated")
        raw_wav = wav_path.with_suffix('.kokoro.wav')
        sf.write(raw_wav, audio, SAMPLE_RATE)
        subprocess.run(
            ['ffmpeg', '-y', '-i', str(raw_wav), '-ac', str(tts_master_channels), '-ar', str(tts_master_sample_rate), '-c:a', 'pcm_s16le', str(wav_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        raw_wav.unlink(missing_ok=True)
    except Exception as exc:
        raise RuntimeError(f"KokoroTTSFailed: voice={voice_id} error={str(exc)[:240]}") from exc
    if not wav_path.exists() or wav_path.stat().st_size <= 0:
        raise RuntimeError(f"KokoroTTSFailed: voice={voice_id} output WAV rỗng")
    return {"ok": True, "fallback_silence": False, "attempts": 1, "engine": "kokoro", "kokoro_voice": voice_id}

def synthesize_edge_tts(mp3_path: Path, wav_path: Path, text: str, voice: str, attempts: int = 3):
    # Ưu tiên EDGE_TTS_BIN (resolve ở run.sh, gồm fallback ~/.local/bin/edge-tts)
    # thay vì hardcode 'edge-tts' để pipeline chạy được khi PATH host-runner/resume
    # không chứa ~/.local/bin.
    edge_tts_bin = os.environ.get('EDGE_TTS_BIN') or shutil.which('edge-tts') or 'edge-tts'
    for attempt in range(1, attempts + 1):
        try:
            if mp3_path.exists():
                mp3_path.unlink()
            proc = subprocess.run(
                [edge_tts_bin, '--voice', voice, '--text', text, '--write-media', str(mp3_path)],
                check=False,
                timeout=tts_timeout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.TimeoutExpired:
            proc = None
        if proc is not None and proc.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 0:
            if convert_mp3_to_wav(mp3_path, wav_path):
                return {"ok": True, "fallback_silence": False, "attempts": attempt, "engine": "edge-tts", "skipped_by_circuit_breaker": False}
        time.sleep(0.3 * attempt)
    return {"ok": False, "fallback_silence": False, "attempts": attempts, "engine": "edge-tts", "skipped_by_circuit_breaker": False}

def synthesize_capcut_tts(mp3_path: Path, wav_path: Path, text: str, voice_spec: str):
    resolved = resolve_capcut_voice(voice_spec)
    if not resolved:
        print(f"WARN: Không map được preset CapCut '{voice_spec}' trong capcut_voices.json", flush=True)
        return {"ok": False, "engine": "capcut", "attempts": 0, "error": "voice_not_mapped"}
    if not capcut_wrapper.exists():
        print(f"WARN: Thiếu CapCut wrapper: {capcut_wrapper}", flush=True)
        return {"ok": False, "engine": "capcut", "attempts": 0, "error": "wrapper_missing"}
    capcut_debug_dir.mkdir(parents=True, exist_ok=True)
    attempts = max(1, int(float(os.environ.get('CAPCUT_TTS_ATTEMPTS', '2'))))
    timeout_total = max(10, int(float(os.environ.get('CAPCUT_TTS_TIMEOUT_TOTAL', '45'))))
    command_timeout = max(tts_timeout, timeout_total + 20)
    for attempt in range(1, attempts + 1):
        try:
            if mp3_path.exists():
                mp3_path.unlink()
            proc = subprocess.run(
                [
                    'python3', str(capcut_wrapper),
                    '--text', text,
                    '--voice', resolved['voice_type'],
                    '--resource-id', resolved['resource_id'],
                    '--output', str(mp3_path),
                    '--debug-dir', str(capcut_debug_dir),
                ],
                check=False,
                timeout=command_timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.TimeoutExpired:
            proc = None
        if proc is not None and proc.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 0:
            if convert_mp3_to_wav(mp3_path, wav_path):
                return {"ok": True, "fallback_silence": False, "attempts": attempt, "engine": "capcut", "capcut_voice": resolved}
        err = ((proc.stderr if proc else "timeout") or "").strip().splitlines()[-1:] if proc else ["timeout"]
        print(f"WARN: CapCut TTS fail attempt={attempt}/{attempts} voice={resolved['voice_type']} error={(err[0] if err else '')}", flush=True)
        time.sleep(0.4 * attempt)
    return {"ok": False, "engine": "capcut", "attempts": attempts, "error": "capcut_failed"}

def synthesize_tts(mp3_path: Path, wav_path: Path, text: str, voice: str, slot_ms: int, skip_network: bool = False, ai33_speed: float = None, cue_index: int = 0):
    if skip_network:
        write_silence(wav_path, slot_ms)
        return {"ok": False, "fallback_silence": True, "attempts": 0, "engine": "silence", "skipped_by_circuit_breaker": True}

    if (voice or '').lower().startswith('kokoro'):
        return synthesize_kokoro_tts(mp3_path, wav_path, text, voice)

    if (voice or '').lower().startswith('ai33'):
        # Compatibility dispatch shape: return synthesize_ai33_tts(mp3_path, wav_path, text, voice, slot_ms, ai33_speed)
        return synthesize_ai33_tts(mp3_path, wav_path, text, voice, slot_ms, ai33_speed, cue_index)

    if (voice or '').lower().startswith('capcut:'):
        raise RuntimeError('CapCut TTS disabled in OpenClaw pipeline; choose kokoro:<voice>, ai33/maiphuong/phanh, resona, nam, nu or vi-vn-*.')

    # Resona là engine chính. KHÔNG fallback Edge khi Resona API lỗi thật
    # (chỉ Edge fallback cho short-text policy=edge bên trong synthesize_resona_tts).
    if (voice or '').lower().startswith('resona'):
        return synthesize_resona_tts(mp3_path, wav_path, text, voice, slot_ms)

    edge_result = synthesize_edge_tts(mp3_path, wav_path, text, voice)
    if edge_result.get("ok"):
        return edge_result
    write_silence(wav_path, slot_ms)
    return {"ok": False, "fallback_silence": True, "attempts": edge_result.get("attempts", 3), "engine": "silence", "skipped_by_circuit_breaker": False}


content = Path(source_srt).read_text(encoding='utf-8', errors='replace').strip()
blocks = [b.strip() for b in re.split(r'\n\s*\n', content) if b.strip()]
entries = []
for block in blocks:
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 3 or '-->' not in lines[1]:
        continue
    start_raw, end_raw = [part.strip() for part in lines[1].split('-->')]
    text = re.sub(r'<[^>]+>', '', ' '.join(lines[2:]).strip())
    if text:
        # The ordinal is the source identity: SRT time ranges are not unique.
        source_cue_id = len(entries) + 1
        entries.append((parse_ms(start_raw), parse_ms(end_raw), text, source_cue_id))
if not entries:
    if target_video_ms > 0:
        write_silence(Path(voice_wav), target_video_ms)
        stats_path.write_text(json.dumps({
            "entries": 0,
            "raw_tts_ms": 0,
            "adjusted_tts_ms": target_video_ms,
            "target_end_ms": target_video_ms,
            "final_voice_ms": target_video_ms,
            "subtitle_only_all": True,
            "warning": "TTS source SRT không có thoại; tạo audio im lặng đúng duration video để pipeline vẫn xuất video/phụ đề.",
            "max_tts_speed": max_tts_speed,
            "tts_timeout_seconds": tts_timeout,
            "tts_circuit_breaker_failures": circuit_breaker_failures,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        print('WARN: TTS source SRT không có thoại; tạo audio im lặng vì toàn bộ segment là subtitle-only.', flush=True)
        raise SystemExit(0)
    raise SystemExit('TTS source SRT không có dòng thoại và chưa biết VIDEO_DURATION để tạo silence fallback')

forced_cue_ids = {
    int(value) for value in (os.environ.get('TTS_FORCE_CUE_IDS', '') or '').split(',')
    if value.strip().isdigit() and int(value) > 0
}
spoken_text_overrides = {}
spoken_text_overrides_raw = (os.environ.get('TTS_SPOKEN_TEXT_OVERRIDES_JSON', '') or '').strip()
if spoken_text_overrides_raw:
    spoken_text_overrides_path = Path(spoken_text_overrides_raw)
    try:
        spoken_text_overrides = json.loads(spoken_text_overrides_path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise RuntimeError(f"TTSVoiceQaOverridesInvalid: {exc}") from exc
entries = [
    (start_ms, end_ms, str(spoken_text_overrides.get(str(source_cue_id)) or text).strip(), source_cue_id)
    for start_ms, end_ms, text, source_cue_id in entries
]

# Global identity changes conservatively for timing/topology changes. Text stays
# per-cue so editing cue 50 does not discard 121 valid AI33 checkpoint WAVs.
source_fingerprint = hashlib.sha256(json.dumps(
    [{"start_ms": start, "end_ms": end} for start, end, _text, _source_cue_id in entries],
    sort_keys=True
).encode('utf-8')).hexdigest()

source_entry_count = len(entries)
resona_tts_group_meta = {}


def normalize_resona_join_piece(text: str) -> str:
    text = re.sub(r'\s+', ' ', (text or '').strip())
    if not text:
        return ''
    if not re.search(r'[.!?…。！？]$', text):
        text += '.'
    return text


def build_resona_tts_entries(raw_entries):
    """Gom cue ngắn cho Resona. Mục tiêu: mỗi TTS unit đạt >= RESONA_MIN_CHARS credit.
    - Gom liền kề cho tới khi đủ credit; cho phép vượt soft max nếu chưa đủ, nhưng không vượt hard max.
    - Giới hạn: max_cues, hard_max_duration_ms, max_internal_gap_ms, max_chars.
    - Group cuối nếu thiếu chữ: merge ngược vào group trước nếu không vượt hard max/max chars.
    - Nếu vẫn không đủ: giữ lại unit ngắn (sẽ fail ResonaTextTooShortUngroupable ở synthesize),
      KHÔNG fallback Edge mặc định (policy=group_or_fail).
    vietnamese.srt không đụng (hiển thị per-cue); chỉ TTS units gom.
    """
    if not voice_name.lower().startswith('resona') or not resona_short_group_enabled:
        return [entry[:3] for entry in raw_entries], {}
    grouped_entries = []
    grouped_meta = {}
    i = 0
    while i < len(raw_entries):
        start_ms, end_ms, text, source_cue_id = raw_entries[i]
        # Cue đã đủ credit → giữ nguyên 1 unit.
        if resona_credit_chars(text) >= resona_min_chars:
            grouped_entries.append((start_ms, end_ms, text))
            meta_index = len(grouped_entries)
            grouped_meta[meta_index] = {
                "group_index": meta_index, "source_segment_count": 1,
                "source_cue_ids": [source_cue_id],
            }
            i += 1
            continue
        # Cue ngắn → gom tiến.
        group = [(start_ms, end_ms, text)]
        j = i + 1
        while j < len(raw_entries):
            next_start, next_end, next_text, _next_source_cue_id = raw_entries[j]
            # Gap nội bộ quá lớn → dừng gom (giữ sync).
            internal_gap = next_start - group[-1][1]
            if internal_gap > resona_short_group_max_internal_gap_ms:
                break
            resona_hard_boundary = boundary_after(group[-1][2])
            if resona_hard_boundary:
                break
            if len(group) >= resona_short_group_max_cues:
                break
            if next_end - group[0][0] > resona_short_group_hard_max_ms:
                break
            pieces = [normalize_resona_join_piece(item[2]) for item in group + [raw_entries[j]]]
            joined_preview = ' '.join(piece for piece in pieces if piece)
            if resona_credit_chars(joined_preview) > resona_max_chars:
                break
            group.append(raw_entries[j])
            j += 1
            if resona_credit_chars(joined_preview) >= resona_min_chars:
                break
        # Gom xong: nếu đủ credit → chấp nhận group (cho phép vượt soft max).
        combined_text = ' '.join(
            piece for piece in (normalize_resona_join_piece(item[2]) for item in group) if piece
        )
        if len(group) > 1 and resona_credit_chars(combined_text) >= resona_min_chars:
            grouped_entries.append((group[0][0], group[-1][1], combined_text))
            meta_index = len(grouped_entries)
            source_texts = []
            for source_start, source_end, _source_text, _source_cue_id in group:
                src = _seg_source_lookup.get((source_start, source_end), '')
                if src:
                    source_texts.append(src)
            grouped_meta[meta_index] = {
                "group_index": meta_index,
                "source_segment_count": len(group),
                "source_cue_ids": ordered_source_cue_ids(group),
                "source_start_ms": group[0][0],
                "source_end_ms": group[-1][1],
                "source_chars": sum(resona_credit_chars(item[2]) for item in group),
                "grouped_chars": resona_credit_chars(combined_text),
                "source_text": ' '.join(source_texts),
            }
            i = j
            continue
        # Group cuối/đơn lẻ vẫn thiếu credit → thử merge ngược vào group trước (nếu có).
        if len(grouped_entries) > 0:
            prev_start, prev_end, prev_text = grouped_entries[-1]
            prev_meta = grouped_meta.get(len(grouped_entries))
            prev_source_count = (prev_meta or {}).get("source_segment_count", 1) if prev_meta else 1
            merge_pieces = [normalize_resona_join_piece(p) for p in [prev_text] + [item[2] for item in group]]
            merge_text = ' '.join(p for p in merge_pieces if p)
            new_total_cues = prev_source_count + len(group)
            new_span = group[-1][1] - prev_start
            resona_hard_boundary = boundary_after(prev_text)
            if (not resona_hard_boundary
                    and resona_credit_chars(merge_text) <= resona_max_chars
                    and new_total_cues <= resona_short_group_max_cues
                    and new_span <= resona_short_group_hard_max_ms):
                grouped_entries[-1] = (prev_start, group[-1][1], merge_text)
                source_texts = []
                if prev_meta:
                    source_texts.append(prev_meta.get("source_text") or prev_text)
                for source_start, source_end, _source_text, _source_cue_id in group:
                    src = _seg_source_lookup.get((source_start, source_end), '')
                    if src:
                        source_texts.append(src)
                grouped_meta[len(grouped_entries)] = {
                    "group_index": len(grouped_entries),
                    "source_segment_count": new_total_cues,
                    "source_cue_ids": (prev_meta or {}).get("source_cue_ids", []) + ordered_source_cue_ids(group),
                    "source_start_ms": prev_start,
                    "source_end_ms": group[-1][1],
                    "source_chars": (prev_meta or {}).get("source_chars", resona_credit_chars(prev_text)) + sum(resona_credit_chars(item[2]) for item in group),
                    "grouped_chars": resona_credit_chars(merge_text),
                    "source_text": ' '.join(source_texts),
                }
                i = j
                continue
        # Không gom đủ → giữ từng unit ngắn (sẽ fail ResonaTextTooShortUngroupable khi synthesize).
        for item in group:
            grouped_entries.append(item[:3])
            meta_index = len(grouped_entries)
            grouped_meta[meta_index] = {
                "group_index": meta_index, "source_segment_count": 1,
                "source_cue_ids": [item[3]],
            }
        i = j
    return grouped_entries, grouped_meta


entries, resona_tts_group_meta = build_resona_tts_entries(entries)

# --- Pre-TTS Resona probe (fail-fast trước khi chạy full TTS loop) ---
# Lấy 3-5 grouped entries đại diện, gọi Resona thử với voice đang chọn (và các
# fallback voice nếu có). Nếu đa số mẫu fail với mọi voice -> dừng sớm (exit 9),
# không chạy full TTS, không render. Voice đầu tiên pass majority -> dùng cho full TTS.
# Non-Resona job -> skip (status=skipped), identical to today.
resona_probe_report = {
    "enabled": False,
    "ran": False,
    "samples_planned": 0,
    "samples_tried": 0,
    "samples_passed": 0,
    "voices_tried": [],
    "voice_used": None,
    "primary_voice_id": None,
    "fallback_voice_ids": [],
    "status": "skipped",   # ok | fail | skipped
    "error_code": None,
    "fail_reasons": [],
}

_primary_voice_id = resolve_resona_voice_id(voice_name)
resona_probe_report["primary_voice_id"] = _primary_voice_id
_fb_raw = (os.environ.get('RESONA_FALLBACK_VOICE_IDS') or '').strip()
_fb_ids = [v.strip() for v in _fb_raw.split(',') if v.strip()] if _fb_raw else []
_seen = {_primary_voice_id}
_probe_voice_candidates = []
for _v in _fb_ids:
    if _v not in _seen:
        _probe_voice_candidates.append(_v)
        _seen.add(_v)
resona_probe_report["fallback_voice_ids"] = _probe_voice_candidates

_is_resona_job = voice_name.lower().startswith('resona')
resona_probe_report["enabled"] = _is_resona_job
if _is_resona_job and entries:
    # Chọn mẫu đại diện: ưu tiên entry đủ credit (>=min_chars, <=max_chars), sort
    # ascending theo credit để probe nhanh nhất (text ngắn-nhất đủ credit trước).
    _probe_candidates = []
    for _st, _en, _txt in entries:
        _c = resona_credit_chars(_txt)
        if _c >= resona_min_chars and _c <= resona_max_chars:
            _probe_candidates.append((_c, _txt))
    _probe_candidates.sort(key=lambda t: t[0])
    _probe_samples = [t for _, t in _probe_candidates[:5]]
    if not _probe_samples and entries:
        # Fallback: lấy text dài nhất (cắt theo max_chars) nếu không có entry đủ credit.
        _longest = max(entries, key=lambda e: resona_credit_chars(e[2]))
        _probe_samples = [_longest[2][:resona_max_chars]]
    resona_probe_report["samples_planned"] = len(_probe_samples)

    _probe_debug_dir = resona_debug_dir / 'probe'
    _probe_debug_dir.mkdir(parents=True, exist_ok=True)
    _all_voices = [_primary_voice_id] + _probe_voice_candidates

    def _probe_one_voice(vid, sample_text):
        # Trả (ok: bool, error_code: str|None, stderr: str). Cùng logic map exit/stderr
        # với synthesize_resona_tts (run.sh ~1139-1152).
        _probe_wav = _probe_debug_dir / f'probe_{vid}.wav'
        _cmd = [
            'python3', str(resona_wrapper),
            '--text', sample_text,
            '--voice', vid,
            '--output', str(_probe_wav),
            '--api-base', resona_api_base,
            '--timeout-total', str(resona_timeout_seconds),
            '--poll-interval', str(resona_poll_interval),
            '--debug-dir', str(_probe_debug_dir),
        ]
        try:
            _proc = subprocess.run(_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except Exception as _e:
            return False, "TTSResonaFailed", str(_e)[:200]
        if _proc.returncode == 0 and _probe_wav.exists() and _probe_wav.stat().st_size > 256:
            return True, None, (_proc.stderr or '')[:200]
        _stderr = (_proc.stderr or '')[:500]
        _ec = "TTSResonaFailed"
        if 'ResonaAuthMissing' in _stderr: _ec = "ResonaAuthMissing"
        elif 'ResonaAuthFailed' in _stderr: _ec = "ResonaAuthFailed"
        elif 'ResonaQuotaFailed' in _stderr: _ec = "ResonaQuotaFailed"
        elif 'ResonaTimeout' in _stderr: _ec = "ResonaTimeout"
        elif 'ResonaNoAudioUrl' in _stderr or 'No generated' in _stderr or 'no generated' in _stderr:
            _ec = "ResonaNoAudioUrl"
        return False, _ec, _stderr

    _PROBE_PASS_THRESHOLD = max(1, (len(_probe_samples) + 1) // 2)  # đa số mẫu phải pass
    _chosen_voice_id = None
    _chosen_pass_count = 0
    for _vid in _all_voices:
        _pass = 0
        _fail_codes = []
        _voice_result = {"voice_id": _vid, "samples": [], "passed": False}
        for _s in _probe_samples:
            _ok, _ec, _se = _probe_one_voice(_vid, _s)
            resona_probe_report["samples_tried"] += 1
            _voice_result["samples"].append({"ok": _ok, "error_code": _ec})
            if _ok:
                _pass += 1
            else:
                _fail_codes.append(_ec or "TTSResonaFailed")
        _voice_result["pass_count"] = _pass
        _voice_result["fail_codes"] = _fail_codes
        resona_probe_report["voices_tried"].append(_voice_result)
        if _pass >= _PROBE_PASS_THRESHOLD:
            _chosen_voice_id = _vid
            _chosen_pass_count = _pass
            _voice_result["passed"] = True
            break  # voice đầu tiên pass đa số -> chọn

    resona_probe_report["ran"] = True
    resona_probe_report["samples_passed"] = _chosen_pass_count if _chosen_voice_id else 0
    resona_probe_report["voice_used"] = _chosen_voice_id

    if _chosen_voice_id is None:
        # Tất cả voice fail -> chọn error_code severity cao nhất trong tất cả fail_codes.
        _all_fail = []
        for _vr in resona_probe_report["voices_tried"]:
            _all_fail.extend(_vr.get("fail_codes") or [])
        _chosen_err = next((c for c in RESONA_ERROR_SEVERITY if c in _all_fail), "ResonaProbeFail")
        resona_probe_report["status"] = "fail"
        resona_probe_report["error_code"] = _chosen_err
        resona_probe_report["fail_reasons"] = [
            f"probe failed for all {len(_all_voices)} voice(s); samples={len(_probe_samples)} fail_codes={_all_fail}"
        ]
        print(f"RESONA_PROBE_FAIL: voices={len(_all_voices)} samples={len(_probe_samples)} chosen_err={_chosen_err}", flush=True)
        # Ghi report riêng để dashboard/Telegram đọc được dù stats chưa init.
        (root / 'resona_probe_report.json').write_text(json.dumps(resona_probe_report, ensure_ascii=False, indent=2), encoding='utf-8')
        # Ghi voice_sync_quality_report.json ngay (giống gate fail path) để bash wrapper map error_code.
        try:
            _vsr_path = os.environ.get('VOICE_SYNC_REPORT_JSON') or (root / 'voice_sync_quality_report.json')
            Path(_vsr_path).write_text(json.dumps({
                "status": "fail",
                "error_code": _chosen_err,
                "phase": "resona_probe",
                "resona_probe": resona_probe_report,
                "fail_reasons": resona_probe_report["fail_reasons"],
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        sys.exit(9)   # 9 = probe fail (bash wrapper map riêng, KHÔNG vào TTSAllSilence)
    else:
        resona_probe_report["status"] = "ok"
        # Override voice cho full TTS loop: dùng voice winner. Rewrite voice_name
        # thành 'resona:<chosen>' để resolve_resona_voice_id trả đúng voice_id.
        if _chosen_voice_id != _primary_voice_id:
            voice_name = f'resona:{_chosen_voice_id}'
            print(f"RESONA_PROBE_OK: fallback voice chosen voice_id={_chosen_voice_id} pass={_chosen_pass_count}/{len(_probe_samples)}", flush=True)
        else:
            print(f"RESONA_PROBE_OK: primary voice voice_id={_chosen_voice_id} pass={_chosen_pass_count}/{len(_probe_samples)}", flush=True)

# Ghi probe report ra TMP_DIR (stats sẽ merge sau khi init).
(root / 'resona_probe_report.json').write_text(json.dumps(resona_probe_report, ensure_ascii=False, indent=2), encoding='utf-8')

stats = {
    "entries": len(entries),
    "source_entries": source_entry_count,
    "raw_tts_ms": 0,
    "adjusted_tts_ms": 0,
    "target_end_ms": max(end for _, end, _ in entries),
    "speedup_segments": 0,
    "padded_segments": 0,
    "tts_retry_segments": 0,
    "tts_silence_fallback_segments": 0,
    "tts_circuit_breaker_segments": 0,
    "tts_over_max_speed_segments": 0,
    "tts_clipped_to_slot_segments": 0,
    "tts_overhang_segments": 0,
    "unresolved_contiguous_overhang_events": [],
    "tts_too_long_not_clipped_segments": 0,
    "max_tts_speed": max_tts_speed,
    "allow_overhang_ms": allow_overhang_ms,
    "max_start_drift_ms": 0.0,
    "start_drift_ms_list": [],
    "end_overflow_ms_list": [],
    "final_segment_drift_ms_list": [],
    "total_final_drift_ms": 0,
    "rewritten_segments": 0,
    "rewrite_failed_segments": 0,
    "max_end_overhang": 0.0,
    "tts_timeout_seconds": tts_timeout,
    "tts_circuit_breaker_failures": circuit_breaker_failures,
    "sync_mode": sync_mode,
    "sync_policy": sync_policy,
    "allow_aggressive_atempo": allow_aggressive_atempo,
    "ai33_max_speed": round(ai33_max_speed, 4),
    "post_atempo_max": round(post_atempo_max, 4),
    "post_atempo_min": round(post_atempo_min, 4),
    "allow_slow_fit": allow_slow_fit,
    "tts_master_sample_rate": tts_master_sample_rate,
    "tts_master_channels": tts_master_channels,
    "total_audio_speed_max": round(total_audio_speed_max, 4),
    "tts_engine_requested": "kokoro" if voice_name.lower().startswith("kokoro") else ("ai33" if voice_name.lower().startswith("ai33") else ("resona" if voice_name.lower().startswith("resona") else ("capcut" if voice_name.lower().startswith("capcut:") else "edge-tts"))),
    "tts_engine_used": "",
    "tts_engines_used": [],
    "kokoro_segments": 0,
    "kokoro_voice_used": resolve_kokoro_voice(voice_name) if voice_name.lower().startswith("kokoro") else "",
    "ai33_segments": 0,
    "ai33_native_speed_segments": 0,
    "ai33_native_speed_failed_segments": 0,
    "ai33_max_native_speed_used": 1.0,
    "ai33_failed_segments": 0,
    "ai33_fail_error_codes": [],
    "tts_completed_cues": 0,
    "tts_total_cues": len(entries),
    "tts_reusable_cues": 0,
    "tts_cues_completed": 0,
    "tts_cues_total": len(entries),
    "tts_cues_reused": 0,
    "tts_checkpoint_schema": 1,
    "tts_checkpoint_path": ai33_checkpoint_path.name,
    "tts_resume_from_cue": 1,
    "tts_failed_cue": 0,
    "tts_failed_stage": "",
    "tts_failed_code": "",
    "tts_failed_attempts": 0,
    "ai33_voice_used": resolve_ai33_voice_id(voice_name) if voice_name.lower().startswith("ai33") else "",
    "voice_source": ai33_voice_meta.get("voice_source", "") if voice_name.lower().startswith("ai33") else "",
    "voice_label": ai33_voice_meta.get("label", "") if voice_name.lower().startswith("ai33") else "",
    "voice_id": ai33_voice_meta.get("voice_id", "") if voice_name.lower().startswith("ai33") else "",
    "canonical_voice": ai33_voice_meta.get("canonical_voice", voice_name) if voice_name.lower().startswith("ai33") else voice_name,
    "timing_profile": ai33_voice_meta.get("timing_profile", "") if voice_name.lower().startswith("ai33") else "",
    "timing_overrides_applied": timing_overrides_applied if voice_name.lower().startswith("ai33") else {},
    "dub_text_overrides_applied": dub_text_overrides_applied if voice_name.lower().startswith("ai33") else {},
    "min_slow_ratio": ai33_voice_meta.get("min_slow_ratio", min_slow_ratio) if voice_name.lower().startswith("ai33") else "",
    "capcut_segments": 0,
    "capcut_fallback_edge_segments": 0,
    "capcut_failed_segments": 0,
    "resona_segments": 0,
    "resona_failed_segments": 0,
    "resona_short_text_segments": 0,
    "resona_short_edge_fallback_segments": 0,
    "resona_short_grouped_units": len(resona_tts_group_meta),
    "resona_short_grouped_source_segments": sum(meta.get("source_segment_count", 0) for meta in resona_tts_group_meta.values()),
    "resona_short_group_max_cues": resona_short_group_max_cues,
    "resona_short_group_max_duration_ms": resona_short_group_max_duration_ms,
    "resona_fail_error_codes": [],
    "resona_voice_used": resona_probe_report.get("voice_used") or resolve_resona_voice_id(voice_name),
    "resona_probe": resona_probe_report,
    "edge_segments": 0,
    "edge_fallback_reason": "",
    "semantic_rewrite_schema_version": 2,
    "semantic_rewrite_mode": "post_probe_two_way_adaptation",
    "semantic_rewrite_fields": ["subtitle_text", "dub_text_before", "dub_text_after", "kept_meaning", "dropped_details", "restored_details", "meaning_risk", "adapt_direction", "rewrite_attempts", "fit_decision"],
    "adapt_enabled": adapt_enabled,
    "adapt_max_attempts": adapt_max_attempts,
    "adapt_restore_if_slot_ratio_below": restore_if_slot_ratio_below,
    "adapt_shorten_segments": 0,
    "adapt_restore_segments": 0,
    "restore_safe_detail_attempted_segments": 0,
    "restore_safe_detail_success_segments": 0,
    "adapt_keep_natural_segments": 0,
    "adapt_needs_attention_segments": 0,
    "adapt_native_speed_resolved_segments": 0,
    "low_fill_after_restore_segments": 0,
    "normalized_for_concat_segments": 0,
    "loudness_normalized_segments": 0,
    "expected_final_voice_ms": 0,
    "concat_duration_extra_ms": 0,
    "final_tail_safe_trim_ms": 0,
    # Voice-sync metrics (phát hiện TTS quá ngắn so với slot = padding im lặng nhiều).
    "padding_total_ms": 0,       # speech_padding: im lặng chèn trong vùng thoại
    "speech_padding_ms": 0,      # alias rõ ràng cho speech padding (không tính tail)
    "source_gap_ms": 0,          # khoảng trống có sẵn giữa cue nguồn, không phải padding TTS
    "synthetic_padding_ms": 0,   # silence thêm sau speech trong cue, dùng cho short-audio gate
    "proven_synthetic_padding_ms": 0,  # subset overlapping allowlisted speech-aware evidence
    "proven_synthetic_padding_evidence_backends": [],
    "longest_consecutive_synthetic_padding_ms": 0,
    "longest_proven_synthetic_padding_ms": 0,
    "longest_unproven_synthetic_padding_ms": 0,
    "final_tail_silence_ms": 0,  # im lặng từ câu cuối tới hết video (không phải lỗi sync)
    "slow_fit_segments": 0,
    "slow_fit_min_ratio": round(min_slow_ratio, 4),
    "min_final_speed": 1.0,
    "final_speed_below_1_segments": 0,
    "low_ratio_segments": 0,  # segment có raw/effective_slot < 0.5
    "final_low_ratio_segments": 0,  # segment sau fit vẫn < 0.5 slot
    "raw_slot_ratios": [],    # list raw_duration_ms / effective_slot_ms per segment
    "final_slot_ratios": [],  # list final_duration_ms / effective_slot_ms per segment
}


alignment_rows = []
total_entries = len(entries)
ai33_tts_workers = max(1, min(3, int(os.environ.get("AI33_TTS_WORKERS", "3") or "3")))
prefetched_tts_results = {}
if voice_name.lower().startswith("ai33") and ai33_tts_workers > 1 and entries:
    prefetch_dir = segments_dir / "_ai33_prefetch"
    prefetch_dir.mkdir(parents=True, exist_ok=True)
    ai33_voice_id = resolve_ai33_voice_id(voice_name)
    ai33_prefetch_settings_hash = hashlib.sha256(json.dumps({
        'speed': 1.0, 'context_chaining': ai33_context_chaining,
        'with_transcript': ai33_with_transcript, 'sample_rate': tts_master_sample_rate,
        'channels': tts_master_channels, 'api_base': ai33_api_base,
        'poll_interval': ai33_poll_interval, 'timeout_total': ai33_timeout_seconds,
        'pronunciation_dictionary_id': ai33_pronunciation_dictionary_id,
    }, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    ai33_prefetch_config = tts_checkpoint.CheckpointConfig(
        source_fingerprint, ai33_voice_id,
        {"settings_fingerprint": ai33_prefetch_settings_hash}, total_entries,
        tts_master_sample_rate, tts_master_channels, 1, 1800000,
    )
    reusable_checkpoint_cues = set()
    for entry_index, (_start_ms, _end_ms, _text) in enumerate(entries, 1):
        if entry_index in forced_cue_ids:
            continue
        identity = tts_checkpoint.CueIdentity(
            entry_index - 1, hashlib.sha256(_text.encode("utf-8")).hexdigest(),
            ai33_voice_id, ai33_prefetch_config.settings,
        )
        if tts_checkpoint.reusable_cue(ai33_checkpoint_path, ai33_prefetch_config, identity):
            reusable_checkpoint_cues.add(entry_index)
            _wav = prefetch_dir / f"{entry_index:04d}.wav"
            tts_checkpoint.materialize_cue(ai33_checkpoint_path, ai33_prefetch_config, identity, _wav)
            prefetched_tts_results[entry_index] = (
                {"ok": True, "fallback_silence": False, "engine": "ai33",
                 "ai33_failed": False, "attempts": 0, "ai33_voice": ai33_voice_id,
                 "checkpoint_reused": True},
                prefetch_dir / f"{entry_index:04d}.mp3", _wav,
            )

    def prefetch_ai33(entry_index):
        _start_ms, _end_ms, _text = entries[entry_index - 1]
        _mp3 = prefetch_dir / f"{entry_index:04d}.mp3"
        _wav = prefetch_dir / f"{entry_index:04d}.wav"
        _result = synthesize_tts(
            _mp3, _wav, _text, voice_name, max(1, _end_ms - _start_ms),
            skip_network=False, ai33_speed=1.0, cue_index=entry_index,
        )
        return _result, _mp3, _wav

    pending_entries = [
        entry_index for entry_index in range(1, total_entries + 1)
        if entry_index not in reusable_checkpoint_cues
    ]
    print(
        f"AI33 TTS workers: {ai33_tts_workers}; checkpoint reuse: "
        f"{len(reusable_checkpoint_cues)}/{total_entries}",
        flush=True,
    )
    while pending_entries:
        batch = pending_entries[:ai33_tts_workers]
        del pending_entries[:len(batch)]
        with ThreadPoolExecutor(max_workers=ai33_tts_workers) as executor:
            futures = {
                entry_index: executor.submit(prefetch_ai33, entry_index)
                for entry_index in batch
            }
            batch_results = {
                entry_index: futures[entry_index].result()
                for entry_index in batch
            }
        prefetched_tts_results.update(batch_results)
        if any((result[0] or {}).get("ai33_failed") for result in batch_results.values()):
            print("AI33 prefetch stopped after provider failure", flush=True)
            break

with concat_list.open('w', encoding='utf-8') as manifest:
    current_ms = 0
    segment_index = 0
    consecutive_tts_failures = 0
    consecutive_synthetic_padding_ms = 0
    if resona_tts_group_meta:
        print(
            f"Resona short-cue grouping: {source_entry_count} dub cues -> {total_entries} TTS units "
            f"({len(resona_tts_group_meta)} grouped units, max {resona_short_group_max_cues} cues/{resona_short_group_max_duration_ms/1000:.1f}s)",
            flush=True,
        )
    for entry_index, (start_ms, end_ms, text) in enumerate(entries, 1):
        segment_meta = _seg_context_lookup.get((start_ms, end_ms), {})
        subtitle_text = (resona_tts_group_meta.get(entry_index) or {}).get("subtitle_text") or segment_meta.get("subtitle_text") or text
        source_text = (resona_tts_group_meta.get(entry_index) or {}).get("source_text") or segment_meta.get("source_text") or _seg_source_lookup.get((start_ms, end_ms), "")
        dub_text_before = text
        kept_meaning, dropped_details, restored_details = [], [], []
        meaning_risk = "not_evaluated"
        adapt_direction = "keep_natural"
        fit_decision = "pending_natural_tts"
        adaptation_needs_attention = False
        restore_safe_detail_attempted = False
        restore_safe_detail_success = False
        if entry_index == 1 or entry_index % 10 == 0 or entry_index == total_entries:
            print(f"TTS progress: {entry_index}/{total_entries} segments", flush=True)
        slot_ms = max(1, end_ms - start_ms)
        next_start_ms = entries[entry_index][0] if entry_index < total_entries else (target_video_ms if target_video_ms > 0 else end_ms + allow_overhang_ms)
        safe_until_next_ms = max(end_ms, next_start_ms)
        effective_slot_ms = min(slot_ms + allow_overhang_ms, max(1, safe_until_next_ms - start_ms))
        gap_ms = max(0, start_ms - current_ms)
        if gap_ms > 0:
            stats["source_gap_ms"] += gap_ms
            consecutive_synthetic_padding_ms = 0
            silence_wav = segments_dir / f'{segment_index:04d}_silence.wav'
            write_silence(silence_wav, gap_ms)
            manifest.write(f"file '{silence_wav.as_posix()}'\n")
            segment_index += 1
        # actual_start_ms = cursor sau gap/overrun câu trước. Khi câu trước tràn (current_ms >
        # start_ms), gap_ms=0, không chèn silence -> audio bắt đầu muộn -> drift tích lũy.
        actual_start_ms = current_ms
        start_drift_ms = max(0, actual_start_ms - start_ms)
        stats["start_drift_ms_list"].append(start_drift_ms)
        if start_drift_ms > stats["max_start_drift_ms"]:
            stats["max_start_drift_ms"] = start_drift_ms
        rewrite_attempts_used = 0
        rewritten_text = ""
        mp3_path = segments_dir / f'{segment_index:04d}_speech.mp3'
        wav_path = segments_dir / f'{segment_index:04d}_speech.wav'
        # The generic loop breaker must never manufacture a silent AI33 cue;
        # an AI33 provider failure is checkpointed and fails fast instead.
        skip_network = (not voice_name.lower().startswith('ai33')) and consecutive_tts_failures >= circuit_breaker_failures
        # This first synthesis is the mandatory natural probe. AI33 must not inherit a
        # job-level speed override here; adaptation decisions use the measured 1.0 WAV.
        prefetched = prefetched_tts_results.pop(entry_index, None)
        if prefetched is not None:
            tts_result, mp3_path, wav_path = prefetched
        else:
            tts_result = synthesize_tts(
                mp3_path, wav_path, text, voice_name, slot_ms, skip_network=skip_network,
                ai33_speed=1.0 if voice_name.lower().startswith("ai33") else None,
                cue_index=entry_index,
            )
        engine = tts_result.get("engine") or ("capcut" if voice_name.lower().startswith("capcut:") and tts_result.get("ok") else "edge-tts")
        if engine and engine not in stats["tts_engines_used"]:
            stats["tts_engines_used"].append(engine)
        if engine == "kokoro":
            stats["kokoro_segments"] += 1
            if tts_result.get("kokoro_voice"):
                stats["kokoro_voice_used"] = tts_result.get("kokoro_voice")
        if engine == "ai33" and tts_result.get("ok"):
            stats["ai33_segments"] += 1
            stats["tts_completed_cues"] += 1
            stats["tts_cues_completed"] = stats["tts_completed_cues"]
            if tts_result.get("checkpoint_reused"):
                stats["tts_reusable_cues"] += 1
                stats["tts_cues_reused"] = stats["tts_reusable_cues"]
            if tts_result.get("ai33_voice"):
                stats["ai33_voice_used"] = tts_result.get("ai33_voice")
        if tts_result.get("ai33_failed"):
            stats["tts_failed_cue"] = entry_index
            stats["tts_resume_from_cue"] = entry_index
            stats["tts_failed_code"] = tts_result.get("error_code") or "TTSAI33Failed"
            stats["tts_failed_stage"] = tts_result.get("ai33_stage") or "provider"
            stats["tts_failed_attempts"] = tts_result.get("attempts", 0)
            stats["ai33_failed_segments"] += 1
            ec = tts_result.get("error_code") or "TTSAI33Failed"
            if ec not in stats["ai33_fail_error_codes"]:
                stats["ai33_fail_error_codes"].append(ec)
        if engine == "capcut":
            stats["capcut_segments"] += 1
        if engine.startswith("edge-tts-fallback"):
            stats["capcut_fallback_edge_segments"] += 1
        if tts_result.get("capcut_failed"):
            stats["capcut_failed_segments"] += 1
        # Resona accounting.
        if engine == "resona" and tts_result.get("ok"):
            stats["resona_segments"] += 1
        if tts_result.get("resona_failed"):
            stats["resona_failed_segments"] += 1
            ec = tts_result.get("error_code") or "TTSResonaFailed"
            if ec not in stats["resona_fail_error_codes"]:
                stats["resona_fail_error_codes"].append(ec)
        if tts_result.get("resona_short_text"):
            stats["resona_short_text_segments"] += 1
        if tts_result.get("resona_short_edge_fallback"):
            stats["resona_short_edge_fallback_segments"] += 1
        # Edge accounting (khi Resona requested nhưng fallback Edge do short-text policy=edge).
        if engine and engine.startswith("edge-tts"):
            stats["edge_segments"] = stats.get("edge_segments", 0) + 1
            if tts_result.get("resona_short_edge_fallback") and not stats.get("edge_fallback_reason"):
                stats["edge_fallback_reason"] = "resona_short_text_policy_edge"
        # tts_engine_used: engine thực tế của segment đầu tiên (cho report).
        if not stats["tts_engine_used"]:
            stats["tts_engine_used"] = engine
        if tts_result["attempts"] > 1:
            stats["tts_retry_segments"] += 1
        if tts_result["fallback_silence"]:
            stats["tts_silence_fallback_segments"] += 1
            consecutive_tts_failures += 1
        else:
            consecutive_tts_failures = 0
        if tts_result.get("skipped_by_circuit_breaker"):
            stats["tts_circuit_breaker_segments"] += 1
        # Auth/quota/timeout/no-audio failures are deterministic provider errors,
        # not a per-cue quality problem.  Preserve the first classified failure
        # for the provider gate below instead of producing silence for every cue.
        if tts_result.get("ai33_failed"):
            print(
                f"AI33_PROVIDER_FAIL_FAST: segment={entry_index}/{total_entries} "
                f"code={tts_result.get('error_code') or 'TTSAI33Failed'}; "
                "stop remaining segments for provider gate",
                flush=True,
            )
            break
        duration_ms = measure_wav_ms(wav_path)
        segment_out = wav_path
        raw_duration_ms = duration_ms
        natural_tts_ms = raw_duration_ms
        adapted_natural_tts_ms = raw_duration_ms
        ai33_speed_used = float(tts_result.get("ai33_speed", 1.0) or 1.0)
        speed_intent = {
            "native_speed_mode": "not_applicable",
            "native_speed": ai33_speed_used,
            "post_atempo_max": post_atempo_cap_for(ai33_speed_used),
            "total_speed_factor": ai33_speed_used,
        }
        if not tts_result.get("fallback_silence") and adaptation_module is not None:
            decision = adaptation_module.decide_adaptation(
                natural_tts_ms=natural_tts_ms,
                slot_ms=effective_slot_ms,
                tolerance_ms=fit_tolerance_ms,
                subtitle_text=subtitle_text,
                dub_text=text,
                restore_ratio=restore_if_slot_ratio_below,
            )
            adapt_direction = decision.get("adapt_direction", "keep_natural")
            fit_decision = decision.get("fit_decision", "use_natural")
            meaning_risk = "low" if adapt_direction == "keep_natural" else "not_evaluated"
            restore_safe_detail_attempted = adapt_direction == "restore_safe_detail"
            if restore_safe_detail_attempted:
                stats["restore_safe_detail_attempted_segments"] += 1
            if adapt_direction in ("shorten", "restore_safe_detail"):
                accepted_candidate = False
                if adapt_enabled and adapt_max_attempts > 0:
                    for attempt in range(1, adapt_max_attempts + 1):
                        rewrite_attempts_used += 1
                        try:
                            response = adapt_dub_text(
                                adapt_direction, subtitle_text, text, source_text,
                                natural_tts_ms, effective_slot_ms,
                            )
                            normalized = adaptation_module.normalize_adaptation_response(
                                response, direction=adapt_direction, before_text=text,
                                natural_tts_ms=natural_tts_ms, slot_ms=effective_slot_ms,
                            )
                        except Exception as exc:
                            print(f"WARN: adaptation fail seg {entry_index} attempt {attempt}: {str(exc)[:160]}", flush=True)
                            continue
                        kept_meaning = normalized.get("kept_meaning", [])
                        dropped_details = normalized.get("dropped_details", [])
                        restored_details = normalized.get("restored_details", [])
                        meaning_risk = normalized.get("meaning_risk", "high")
                        fit_decision = normalized.get("fit_decision", "candidate_rejected")
                        if not normalized.get("accepted"):
                            continue
                        candidate = normalized["dub_text"]
                        try:
                            meaning_check = check_adapted_meaning(source_text, subtitle_text, text, candidate)
                        except Exception as exc:
                            print(f"WARN: meaning check fail seg {entry_index} attempt {attempt}: {str(exc)[:160]}", flush=True)
                            meaning_risk = "high"
                            continue
                        meaning_risk = meaning_check.get("meaning_risk", "high")
                        if not meaning_check.get("meaning_preserved") or meaning_risk == "high":
                            fit_decision = "meaning_check_rejected"
                            continue
                        candidate_mp3 = segments_dir / f'{segment_index:04d}_speech_adapt_{attempt}.mp3'
                        candidate_wav = segments_dir / f'{segment_index:04d}_speech_adapt_{attempt}.wav'
                        candidate_tts = synthesize_tts(
                            candidate_mp3, candidate_wav, candidate, voice_name, slot_ms,
                            skip_network=skip_network, ai33_speed=1.0 if engine == "ai33" else None,
                            cue_index=entry_index,
                        )
                        if candidate_tts.get("fallback_silence"):
                            continue
                        candidate_ms = measure_wav_ms(candidate_wav)
                        improves = (
                            (adapt_direction == "shorten" and candidate_ms < raw_duration_ms) or
                            (adapt_direction == "restore_safe_detail" and candidate_ms > raw_duration_ms)
                        )
                        if not improves:
                            continue
                        text = candidate
                        rewritten_text = candidate
                        tts_result = candidate_tts
                        mp3_path, wav_path, segment_out = candidate_mp3, candidate_wav, candidate_wav
                        raw_duration_ms = candidate_ms
                        duration_ms = candidate_ms
                        adapted_natural_tts_ms = candidate_ms
                        ai33_speed_used = float(tts_result.get("ai33_speed", 1.0) or 1.0)
                        accepted_candidate = True
                        stats["rewritten_segments"] += 1
                        if adapt_direction == "shorten":
                            stats["adapt_shorten_segments"] += 1
                        else:
                            stats["adapt_restore_segments"] += 1
                            restore_safe_detail_success = True
                            stats["restore_safe_detail_success_segments"] += 1
                        fit_decision = "candidate_accepted_pending_fit"
                        break
                if not accepted_candidate:
                    adapt_direction = "needs_attention"
                    adaptation_needs_attention = True
                    meaning_risk = "high" if meaning_risk == "not_evaluated" else meaning_risk
                    fit_decision = "no_safe_adaptation_candidate"
                    stats["adapt_needs_attention_segments"] += 1
            else:
                stats["adapt_keep_natural_segments"] += 1
        elif not tts_result.get("fallback_silence"):
            adapt_direction = "needs_attention"
            adaptation_needs_attention = True
            meaning_risk = "high"
            fit_decision = "adaptation_policy_unavailable"
            stats["adapt_needs_attention_segments"] += 1

        # A semantic rewrite rejection must not suppress the bounded, text-preserving
        # native-speed retry.  It is selected from the measured 1.0x WAV and remains
        # inside the per-voice AI33 cap; only a retry that actually fits clears the
        # needs-attention state.
        if (engine == "ai33" and tts_result.get("ok") and not tts_result.get("fallback_silence")
                and raw_duration_ms > effective_slot_ms + fit_tolerance_ms):
            required_before_native = raw_duration_ms / max(1, effective_slot_ms)
            speed_intent = speed_contract.canonical_speed_contract(
                required_before_native, native_max_speed=ai33_max_speed,
                total_max_speed=total_audio_speed_max,
                residual_atempo_max=min(post_atempo_max, max_tts_speed),
            )
            native_speed_mode = speed_intent['native_speed_mode']
            native_speed = speed_intent['native_speed']
            if native_speed > ai33_speed_used + 0.005:
                native_mp3_path = segments_dir / f'{segment_index:04d}_speech_ai33_native.mp3'
                native_wav_path = segments_dir / f'{segment_index:04d}_speech_ai33_native.wav'
                tts_native = synthesize_tts(
                    native_mp3_path, native_wav_path, text, voice_name, slot_ms,
                    skip_network=skip_network, ai33_speed=native_speed, cue_index=entry_index,
                )
                if tts_native.get("ok") and not tts_native.get("fallback_silence"):
                    tts_result = tts_native
                    mp3_path = native_mp3_path
                    wav_path = native_wav_path
                    ai33_speed_used = float(tts_result.get("ai33_speed", native_speed) or native_speed)
                    duration_ms = measure_wav_ms(wav_path)
                    raw_duration_ms = duration_ms
                    segment_out = wav_path
                    if adaptation_needs_attention and raw_duration_ms <= effective_slot_ms + fit_tolerance_ms:
                        adaptation_needs_attention = False
                        adapt_direction = "keep_native_fit"
                        meaning_risk = "low"
                        fit_decision = "native_speed_resolved_after_adaptation_rejected"
                        stats["adapt_needs_attention_segments"] = max(0, stats["adapt_needs_attention_segments"] - 1)
                        stats["adapt_native_speed_resolved_segments"] += 1
                    stats["ai33_native_speed_segments"] += 1
                    stats["ai33_max_native_speed_used"] = max(
                        float(stats.get("ai33_max_native_speed_used", 1.0) or 1.0),
                        ai33_speed_used,
                    )
                    print(
                        f"AI33 native speed segment={entry_index} speed={ai33_speed_used:.3f} "
                        f"required_before={required_before_native:.3f} raw_ms={raw_duration_ms}",
                        flush=True,
                    )
                else:
                    speed_intent = speed_contract.canonical_speed_contract(
                        required_before_native, native_max_speed=ai33_max_speed,
                        total_max_speed=total_audio_speed_max,
                        residual_atempo_max=min(post_atempo_max, max_tts_speed), native_supported=False,
                    )
                    native_speed_mode = speed_intent['native_speed_mode']
                    stats["ai33_native_speed_failed_segments"] += 1
                    print(
                        f"WARN: AI33 native speed retry failed segment={entry_index}; keeping natural-speed audio",
                        flush=True,
                    )
        stats["raw_tts_ms"] += duration_ms
        action_taken = {
            'shorten': 'shorten',
            'restore_safe_detail': 'restore_safe_detail',
            'needs_attention': 'needs_attention',
        }.get(adapt_direction, 'use_natural')
        final_speed = 1.0
        quality_flag = 'NEED_ADAPTATION' if adaptation_needs_attention else 'OK'
        # Theo dõi raw/slot ratio để phát hiện TTS quá ngắn so với slot (padding nhiều).
        slot_ratio = (raw_duration_ms / effective_slot_ms) if effective_slot_ms > 0 else 1.0
        stats["raw_slot_ratios"].append(round(slot_ratio, 4))
        if slot_ratio < 0.5:
            stats["low_ratio_segments"] += 1
        # Giữ natural TTS speed 1.0 và pad silence theo mặc định. Slow-fit chỉ opt-in.
        if (not adaptation_needs_attention and allow_slow_fit and (not tts_result.get("fallback_silence"))
                and raw_duration_ms > 0 and raw_duration_ms < effective_slot_ms):
            needed_slow = raw_duration_ms / effective_slot_ms  # <1.0
            slow_ratio = max(post_atempo_min, min_slow_ratio, needed_slow)
            if post_atempo_min <= slow_ratio < 0.99:
                slow_path, slow_changed = apply_atempo_fit(wav_path, segment_index, slow_ratio, 'speech_slowfit')
                slowed_ms = measure_wav_ms(slow_path)
                # Chỉ nhận slow-fit nếu nó giảm padding (tăng duration) mà không vượt slot.
                if slow_changed and slowed_ms > raw_duration_ms and slowed_ms <= effective_slot_ms + fit_tolerance_ms:
                    segment_out = slow_path
                    duration_ms = slowed_ms
                    stats["slow_fit_segments"] += 1
                    final_speed = slow_ratio
                    action_taken = 'slow_fit'
        speed_fit_decision = 'not_needed'
        if duration_ms > effective_slot_ms + fit_tolerance_ms:
            needed_speed_ratio = duration_ms / (effective_slot_ms + fit_tolerance_ms)
            if engine == "ai33":
                measured_fit = speed_contract.measured_post_atempo_fit(
                    actual_duration_ms=duration_ms,
                    allowed_duration_ms=effective_slot_ms + fit_tolerance_ms,
                    native_speed=ai33_speed_used,
                    total_max_speed=total_audio_speed_max,
                    routine_post_atempo_max=speed_intent['post_atempo_max'],
                    adaptation_needs_attention=adaptation_needs_attention,
                    adaptation_fit_eligible=(fit_decision == "candidate_accepted_pending_fit"),
                    exact_sync=exact_sync,
                )
                speed_ratio = measured_fit['post_atempo_factor']
                post_cap = speed_ratio
                speed_fit_decision = measured_fit['decision']
            else:
                post_cap = post_atempo_cap_for(ai33_speed_used)
                speed_ratio = min(needed_speed_ratio, post_cap)
                speed_fit_decision = 'routine_fit'
            sped_path, speed_changed = apply_atempo_fit(wav_path, segment_index, speed_ratio, 'speech_fit')
            if speed_changed:
                segment_out = sped_path
                duration_ms = measure_wav_ms(segment_out)
                stats["speedup_segments"] += 1
                final_speed = speed_ratio
                action_taken = 'speed_fit'
            if needed_speed_ratio > post_cap:
                stats["tts_over_max_speed_segments"] += 1
                quality_flag = 'TOO_LONG_AFTER_MAX_SPEED'
        normalized_for_concat = False
        segment_out, normalized_for_concat = normalize_wav_for_concat(segment_out, segment_index)
        if normalized_for_concat:
            stats["normalized_for_concat_segments"] += 1
            duration_ms = measure_wav_ms(segment_out)
        if not tts_result.get("fallback_silence"):
            segment_out = normalize_speech_loudness(segment_out, segment_index)
            stats["loudness_normalized_segments"] += 1
            duration_ms = measure_wav_ms(segment_out)
        record_audio_stage('tts_normalized', segment_out)
        # Luôn ghi stage này, kể cả không cần đổi tempo: dễ audit "natural 1.0".
        record_audio_stage('tts_after_tempo', segment_out)
        if duration_ms > effective_slot_ms + fit_tolerance_ms:
            # Vẫn quá slot sau speed-fit + rewrite: KHÔNG clip ngang câu (tránh cụt/kỳ),
            # giữ audio và ghi report. Gate voice-sync sẽ quyết định theo tỷ lệ + drift/trim.
            stats["tts_too_long_not_clipped_segments"] += 1
            stats["rewrite_failed_segments"] += 1
            action_taken = 'kept_unclipped_too_long'
            quality_flag = 'NEED_ADAPTATION' if adaptation_needs_attention else 'NEED_REWRITE'
        final_slot_ratio = (duration_ms / effective_slot_ms) if effective_slot_ms > 0 else 1.0
        stats["final_slot_ratios"].append(round(final_slot_ratio, 4))
        if final_slot_ratio < 0.5:
            stats["final_low_ratio_segments"] += 1
            if restore_safe_detail_success:
                quality_flag = 'LOW_FILL_AFTER_RESTORE'
                stats["low_fill_after_restore_segments"] += 1
        stats["min_final_speed"] = min(float(stats.get("min_final_speed", 1.0) or 1.0), float(final_speed))
        if final_speed < 1.0:
            stats["final_speed_below_1_segments"] = int(stats.get("final_speed_below_1_segments", 0) or 0) + 1
        manifest.write(f"file '{segment_out.as_posix()}'\n")
        current_ms = start_ms + duration_ms
        actual_end_ms = current_ms
        end_overflow_ms = max(0, actual_end_ms - end_ms)
        stats["end_overflow_ms_list"].append(end_overflow_ms)
        # frame_strict metric: độ lệch slot thật sau fit (dùng effective_slot_ms).
        final_segment_drift_ms = max(0, duration_ms - effective_slot_ms)
        stats["final_segment_drift_ms_list"].append(final_segment_drift_ms)
        stats["total_final_drift_ms"] = (stats.get("total_final_drift_ms", 0) or 0) + final_segment_drift_ms
        overhang_ms = end_overflow_ms
        if overhang_ms:
            stats["tts_overhang_segments"] += 1
            stats["max_end_overhang"] = max(stats["max_end_overhang"], overhang_ms / 1000.0)
        next_cue_start_ms = entries[entry_index][0] if entry_index < total_entries else None
        segment_source_cue_ids = (resona_tts_group_meta.get(entry_index) or {}).get(
            "source_cue_ids", [entry_index]
        )
        unresolved_overhang = unresolved_overhang_event(
            entry_index, actual_end_ms, next_cue_start_ms,
            source_cue_ids=segment_source_cue_ids,
        )
        if unresolved_overhang:
            stats["unresolved_contiguous_overhang_events"].append(unresolved_overhang)
        synthetic_padding_for_segment = 0
        proven_synthetic_padding_for_segment = 0
        if current_ms < end_ms:
            tail_ms = end_ms - current_ms
            synthetic_padding_for_segment = tail_ms
            tail_silence = segments_dir / f'{segment_index:04d}_tail_silence.wav'
            write_silence(tail_silence, tail_ms)
            manifest.write(f"file '{tail_silence.as_posix()}'\n")
            current_ms = end_ms
            stats["padded_segments"] += 1
            stats["padding_total_ms"] += tail_ms
            stats["speech_padding_ms"] += tail_ms
            stats["synthetic_padding_ms"] += tail_ms
            # The next cue emits real TTS before any of its tail padding, so this
            # tail is a separate synthetic-silence run rather than an accumulation.
            consecutive_synthetic_padding_ms = synthetic_padding_for_segment
            stats["longest_consecutive_synthetic_padding_ms"] = max(
                stats["longest_consecutive_synthetic_padding_ms"], consecutive_synthetic_padding_ms,
            )
            proven_speech_overlap_ms = max_source_speech_overlap_ms(actual_end_ms, end_ms)
            proven_synthetic_padding_for_segment = proven_speech_overlap_ms
            stats["proven_synthetic_padding_ms"] += proven_speech_overlap_ms
            if proven_speech_overlap_ms and "inaSpeechSegmenter" not in stats["proven_synthetic_padding_evidence_backends"]:
                stats["proven_synthetic_padding_evidence_backends"].append("inaSpeechSegmenter")
            stats["longest_proven_synthetic_padding_ms"] = max(
                stats["longest_proven_synthetic_padding_ms"], proven_speech_overlap_ms,
            )
            if proven_speech_overlap_ms < tail_ms:
                stats["longest_unproven_synthetic_padding_ms"] = max(
                    stats["longest_unproven_synthetic_padding_ms"], tail_ms,
                )
            if adapt_direction == 'keep_natural':
                fit_decision = 'keep_natural_silence'
        else:
            consecutive_synthetic_padding_ms = 0
        stats["adjusted_tts_ms"] = current_ms
        alignment_rows.append({
            "segment_id": entry_index,
            "group_index": (resona_tts_group_meta.get(entry_index) or {}).get("group_index", entry_index),
            "source_segment_count": (resona_tts_group_meta.get(entry_index) or {}).get("source_segment_count", 1),
            "source_cue_ids": segment_source_cue_ids,
            "resona_grouped": bool(resona_tts_group_meta.get(entry_index)),
            "target_start_ms": start_ms,
            "actual_start_ms": actual_start_ms,
            "start_drift_ms": start_drift_ms,
            "orig_start_ms": start_ms,
            "orig_end_ms": end_ms,
            "target_end_ms": end_ms,
            "actual_end_ms": actual_end_ms,
            "end_overflow_ms": end_overflow_ms,
            "slot_duration_ms": slot_ms,
            "slot_ms": slot_ms,
            "effective_slot_ms": effective_slot_ms,
            "source_gap_ms": gap_ms,
            "synthetic_padding_ms": synthetic_padding_for_segment,
            "proven_synthetic_padding_ms": proven_synthetic_padding_for_segment,
            "fill_ratio": round(final_slot_ratio, 4),
            "tts_raw_duration_ms": raw_duration_ms,
            "natural_tts_ms": natural_tts_ms,
            "adapted_natural_tts_ms": adapted_natural_tts_ms,
            "required_speed": round(raw_duration_ms / max(1, effective_slot_ms), 4),
            "ai33_speed": round(ai33_speed_used, 4),
            "native_speed": round(ai33_speed_used, 4),
            "native_speed_mode": speed_intent['native_speed_mode'],
            "measured_duration_ms": raw_duration_ms,
            "post_atempo_speed": round(final_speed, 4),
            "post_atempo": round(final_speed, 4),
            "post_atempo_applied": final_speed != 1.0,
            "total_audio_speed": round(ai33_speed_used * final_speed, 4),
            "total_speed_factor": round(ai33_speed_used * final_speed, 4),
            "speed_fit_decision": speed_fit_decision,
            "final_speed": round(final_speed, 4),
            "final_duration_ms": duration_ms,
            "final_segment_ms": duration_ms,
            "slow_fit_used": action_taken == 'slow_fit',
            "overhang_ms": overhang_ms,
            "rewrite_attempts": rewrite_attempts_used,
            "rewritten_text": rewritten_text,
            "subtitle_text": subtitle_text,
            "dub_text_before": dub_text_before,
            "dub_text_after": text,
            "dub_text": text,
            "kept_meaning": kept_meaning,
            "dropped_details": dropped_details,
            "restored_details": restored_details,
            "meaning_risk": meaning_risk,
            "adapt_direction": adapt_direction,
            "restore_safe_detail_attempted": restore_safe_detail_attempted,
            "restore_safe_detail_success": restore_safe_detail_success,
            "fit_decision": fit_decision,
            "normalized_for_concat": normalized_for_concat,
            "action_taken": action_taken,
            "quality_flag": quality_flag,
            "tts_engine": engine,
            'speech_timing_source': speech_timing_source,
            'display_subtitle_timing': display_subtitle_timing,
            'dub_tts_timing': dub_tts_timing,
            'pitch_preserving_method': 'ffmpeg_atempo' if final_speed != 1.0 else 'none',
            "text": text,
        })
        segment_index += 1
    if target_video_ms > current_ms:
        final_tail = segments_dir / f'{segment_index:04d}_final_tail_silence.wav'
        tail_ms = target_video_ms - current_ms
        write_silence(final_tail, tail_ms)
        manifest.write(f"file '{final_tail.as_posix()}'\n")
        current_ms = target_video_ms
        stats["final_tail_silence_ms"] = tail_ms
        # KHÔNG cộng final_tail_silence vào padding_total_ms: im lặng cuối video không phải
        # voice-sync lỗi (nó chỉ là khoảng trống tự nhiên sau câu cuối). padding_total_ms giờ
        # chỉ tính speech_padding (im lặng chèn trong vùng thoại).
stats["expected_final_voice_ms"] = current_ms
if voice_name.lower().startswith('ai33') and stats["tts_completed_cues"] != stats["tts_total_cues"]:
    # Never concat/render a partially completed AI33 timeline or manufacture silence.
    stats["tts_status"] = "waiting_provider" if stats.get("tts_failed_code", "").endswith(("Http5xx", "RateLimited", "Timeout", "Network")) else "needs_attention"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    raise RuntimeError(
        f"AI33CueCoverageIncomplete completed={stats['tts_completed_cues']}/{stats['tts_total_cues']} "
        f"failed_cue={stats.get('tts_failed_cue', 0)} code={stats.get('tts_failed_code', 'TTSAI33Failed')}"
    )
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_list), '-vn', '-ac', str(tts_master_channels), '-ar', str(tts_master_sample_rate), '-c:a', 'pcm_s16le', str(voice_wav)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
record_audio_stage('voice_concat', Path(voice_wav))
stats["final_voice_ms"] = measure_wav_ms(Path(voice_wav))
stats["concat_duration_extra_ms"] = stats["final_voice_ms"] - stats["expected_final_voice_ms"]

# ffmpeg concat/WAV frame rounding can leave the rendered file a little longer than
# the integer timeline cursor. If that excess is fully inside the explicit final
# tail silence, trim only that silence now. This is not ALLOW_FINAL_TRIM voice
# cutting: the last real speech already ended before the final_tail_silence chunk.
if target_video_ms > 0 and stats["final_voice_ms"] > target_video_ms:
    excess_ms = stats["final_voice_ms"] - target_video_ms
    final_tail_ms = int(stats.get("final_tail_silence_ms", 0) or 0)
    tail_trim_tolerance_ms = max(0, int(float(os.environ.get("TTS_FINAL_TAIL_TRIM_TOLERANCE_MS", "80"))))
    if final_tail_ms > 0 and excess_ms <= final_tail_ms + tail_trim_tolerance_ms:
        tailfit_wav = Path(voice_wav).with_name(Path(voice_wav).stem + "_tailfit.wav")
        subprocess.run([
            'ffmpeg', '-y', '-i', str(voice_wav),
            '-t', f'{target_video_ms/1000:.3f}',
            '-vn', '-ac', str(tts_master_channels), '-ar', str(tts_master_sample_rate), '-c:a', 'pcm_s16le',
            str(tailfit_wav),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.replace(tailfit_wav, voice_wav)
        stats["final_tail_safe_trim_ms"] = excess_ms
        stats["final_tail_silence_ms"] = max(0, final_tail_ms - excess_ms)
        stats["final_voice_ms"] = measure_wav_ms(Path(voice_wav))
# Voice có thể dài hơn video khi nhiều segment tràn (drift tích lũy). Bash trim -t VIDEO_DURATION
# sẽ cắt đuôi -> nghe delay + mất câu cuối. trimmed_ms để gate bắt "voice dài hơn video > 500ms".
stats["final_voice_duration_ms"] = stats["final_voice_ms"]
stats["target_video_ms"] = target_video_ms
stats["trimmed_ms"] = max(0, stats["final_voice_ms"] - target_video_ms) if target_video_ms > 0 else 0
stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
alignment_report_path.write_text(json.dumps({"stats": stats, "segments": alignment_rows}, ensure_ascii=False, indent=2), encoding='utf-8')
with speed_report_path.open('w', encoding='utf-8') as f:
    f.write('segment_id,slot_ms,natural_tts_ms,post_atempo,final_segment_ms,slow_fit_used,orig_start_ms,orig_end_ms,slot_duration_ms,effective_slot_ms,source_gap_ms,synthetic_padding_ms,fill_ratio,tts_raw_duration_ms,measured_duration_ms,required_speed,ai33_speed,native_speed,native_speed_mode,post_atempo_speed,post_atempo_applied,total_audio_speed,total_speed_factor,speed_fit_decision,final_speed,final_duration_ms,overhang_ms,adapt_direction,restore_safe_detail_attempted,restore_safe_detail_success,rewrite_attempts,meaning_risk,fit_decision,action_taken,quality_flag,speech_timing_source,display_subtitle_timing,dub_tts_timing,pitch_preserving_method,subtitle_text,dub_text_before,dub_text_after,kept_meaning,dropped_details,restored_details,text\n')
    for row in alignment_rows:
        def csv_value(value):
            return '"' + str(value).replace('"', '""').replace('\n', ' ') + '"'
        f.write(
            f"{row['segment_id']},{row['slot_ms']},{row['natural_tts_ms']},{row['post_atempo']},{row['final_segment_ms']},{row['slow_fit_used']},{row['orig_start_ms']},{row['orig_end_ms']},{row['slot_duration_ms']},{row['effective_slot_ms']},{row['source_gap_ms']},{row['synthetic_padding_ms']},{row['fill_ratio']},{row['tts_raw_duration_ms']},{row['measured_duration_ms']},{row['required_speed']},{row['ai33_speed']},{row['native_speed']},{row['native_speed_mode']},{row['post_atempo_speed']},{row['post_atempo_applied']},{row['total_audio_speed']},{row['total_speed_factor']},{row['speed_fit_decision']},{row['final_speed']},{row['final_duration_ms']},{row['overhang_ms']},{row['adapt_direction']},{row['restore_safe_detail_attempted']},{row['restore_safe_detail_success']},{row['rewrite_attempts']},{row['meaning_risk']},{csv_value(row['fit_decision'])},{row['action_taken']},{row['quality_flag']},{csv_value(row['speech_timing_source'])},{csv_value(row['display_subtitle_timing'])},{csv_value(row['dub_tts_timing'])},{row['pitch_preserving_method']},{csv_value(row['subtitle_text'])},{csv_value(row['dub_text_before'])},{csv_value(row['dub_text_after'])},{csv_value(json.dumps(row['kept_meaning'], ensure_ascii=False))},{csv_value(json.dumps(row['dropped_details'], ensure_ascii=False))},{csv_value(json.dumps(row['restored_details'], ensure_ascii=False))},{csv_value(row.get('text', ''))}\n"
        )
PY
}

run_tts_voice_qa() {
  local cue_ids="${1:-}"
  local qa_base="$TMP_DIR/tts_voice_qa"
  local qa_srt="${qa_base}.srt"
  rm -f "$qa_srt"
  "$WHISPER_BIN" -m "$WHISPER_MODEL" -f "$VIETNAMESE_VOICE_WAV" -l vi -osrt -of "$qa_base"
  [[ -s "$qa_srt" ]] || return 9
  if [[ -n "$cue_ids" ]]; then
    python3 "$TTS_VOICE_QUALITY_SCRIPT" compare --expected-srt "$TTS_SOURCE_SRT" --observed-srt "$qa_srt" --report "$TTS_VOICE_QUALITY_REPORT_JSON" --cue-ids "$cue_ids"
  else
    python3 "$TTS_VOICE_QUALITY_SCRIPT" compare --expected-srt "$TTS_SOURCE_SRT" --observed-srt "$qa_srt" --report "$TTS_VOICE_QUALITY_REPORT_JSON"
  fi
}

tts_resume_cache_is_complete() {
  python3 - "$1" "$2" "$3" "$4" "$5" "$TTS_MASTER_SAMPLE_RATE" "$TTS_MASTER_CHANNELS" <<'PY'
import hashlib, json, re, subprocess, sys
from pathlib import Path

srt_path, voice_path, stats_path, checkpoint_path, voice, sample_rate, channels = sys.argv[1:]
if not voice.lower().startswith("ai33:"):
    raise SystemExit(1)
try:
    stats = json.loads(Path(stats_path).read_text(encoding="utf-8"))
    checkpoint = json.loads(Path(checkpoint_path).read_text(encoding="utf-8"))
    blocks = re.split(r"\n\s*\n", Path(srt_path).read_text(encoding="utf-8", errors="replace").strip())
    entries = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing = next((line for line in lines if "-->" in line), "")
        start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
        def millis(value):
            match = re.fullmatch(r"(\d+):(\d+):(\d+)[,.](\d+)", value)
            if not match:
                raise ValueError("invalid SRT timestamp")
            hour, minute, second, fraction = match.groups()
            return ((int(hour) * 60 + int(minute)) * 60 + int(second)) * 1000 + int(fraction.ljust(3, "0")[:3])
        entries.append({"start_ms": millis(start_raw), "end_ms": millis(end_raw)})
    source_fingerprint = hashlib.sha256(json.dumps(entries, sort_keys=True).encode("utf-8")).hexdigest()
    expected_voice = voice.split(":", 1)[1]
    cues = checkpoint.get("cues") or {}
    completed = int(stats.get("tts_completed_cues") or 0)
    total = int(stats.get("tts_total_cues") or 0)
    if not (
        entries and completed == total == len(entries)
        and not stats.get("tts_failed_code")
        and stats.get("canonical_voice") == voice
        and checkpoint.get("canonical_voice") == expected_voice
        and checkpoint.get("source_fingerprint") == source_fingerprint
        and int(checkpoint.get("total_cues") or 0) == total
        and len(cues) == total
        and all(item.get("status") == "completed" and Path(item.get("wav_path") or "").is_file() for item in cues.values())
    ):
        raise SystemExit(1)
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels:format=duration",
        "-of", "json", voice_path,
    ], text=True))
    stream = (probe.get("streams") or [{}])[0]
    duration = float((probe.get("format") or {}).get("duration") or 0)
    if int(stream.get("sample_rate") or 0) != int(sample_rate) or int(stream.get("channels") or 0) != int(channels) or duration <= 0:
        raise SystemExit(1)
except Exception:
    raise SystemExit(1)
PY
}

srt_has_spoken_text() {
  local srt_path="$1"
  python3 - "$srt_path" <<'PY'
import re, sys
try:
    text = open(sys.argv[1], encoding='utf-8', errors='replace').read()
except Exception:
    raise SystemExit(1)
for block in re.split(r'\n\s*\n', text.strip()):
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) >= 3 and '-->' in lines[1] and re.sub(r'<[^>]+>', '', ' '.join(lines[2:])).strip():
        raise SystemExit(0)
raise SystemExit(1)
PY
}

dubbing_cache_is_complete() {
  local report_path="$1"
  python3 - "$report_path" <<'PY'
import json, sys
try:
    report = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    raise SystemExit(1)
if report.get('translate_failed_groups') or int(report.get('translate_failed_segments') or 0):
    raise SystemExit(1)
raise SystemExit(0)
PY
}

# Quality gate: every cue must contain text and no CJK.
# Names, numbers, and English terms may legitimately match the source.
srt_looks_vietnamese() {
  local vi_srt="$1"
  python3 - "$vi_srt" <<'PY'
import re, sys
vi_path = sys.argv[1]
CJK = r'[一-鿿豈-鶴]'
def srt_text(path):
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except Exception:
        return ""
    out = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) >= 3 and '-->' in lines[1]:
            out.append(re.sub(r'<[^>]+>', '', ' '.join(lines[2:])))
    return out
vi_cues = srt_text(vi_path)
if not vi_cues:
    print("FAIL: empty"); sys.exit(1)
for cue_index, cue in enumerate(vi_cues, 1):
    chars = re.sub(r'\s+', '', cue)
    if not chars:
        print(f"FAIL: empty_cue={cue_index}"); sys.exit(1)
    if re.search(CJK, cue):
        print(f"FAIL: cjk_cue={cue_index}"); sys.exit(1)
print(f"OK: vietnamese_cues={len(vi_cues)}")
PY
}

[[ -n "$INPUT" ]] || fail "Chưa truyền video/link. Cách dùng: bash run.sh \"/path/to/video.mp4 hoặc link Douyin\""
if [[ -n "$RESUME_JOB_DIR" ]]; then
  case "$(realpath -m "$RESUME_JOB_DIR")" in
    "$(realpath -m "$BASE_DIR")"/*) ;;
    *) fail "OPENCLAW_RESUME_JOB_DIR không nằm trong output root an toàn: $RESUME_JOB_DIR" ;;
  esac
fi
need_cmd ffmpeg
need_cmd python3
need_cmd curl
voice_lower="${VOICE,,}"
if [[ "$voice_lower" == ai33:* ]]; then
  [[ -n "$AI33_API_KEY" ]] || fail "Thiếu AI33_API_KEY cho voice $VOICE."
elif [[ "$voice_lower" == resona:* ]]; then
  [[ -n "$RESONA_API_TOKEN" ]] || fail "Thiếu RESONA_API_TOKEN cho voice $VOICE."
elif [[ "$voice_lower" == kokoro:* ]]; then
  [[ -x "$KOKORO_TTS_PYTHON" ]] || fail "Kokoro TTS runtime chưa sẵn sàng: không thấy executable $KOKORO_TTS_PYTHON"
else
  need_cmd edge-tts
fi
[[ -x "$WHISPER_BIN" ]] || fail "Không tìm thấy whisper-cli tại $WHISPER_BIN. Chạy: bash run.sh --doctor"
[[ -f "$WHISPER_MODEL" ]] || fail "Không tìm thấy model Whisper tại $WHISPER_MODEL. Chạy: bash run.sh --doctor"
API_KEY="$(get_api_key)" || fail "Thiếu API key cho provider $OPENCLAW_AI_PROVIDER."
[[ "$OPENCLAW_AI_PROVIDER" == "ollama" ]] || [[ -n "$API_KEY" ]] || fail "Thiếu API key cho provider $OPENCLAW_AI_PROVIDER."
check_api_base "$API_KEY" || fail "Không connect được $OPENCLAW_AI_PROVIDER tại $API_BASE."

mkdir -p "$OUT_DIR" "$BASE_DIR/translated" "$BASE_DIR/temp"
printf '%s\n' "$OUT_DIR" > "$LATEST_OUTPUT_TXT"
exec > >(tee -a "$LOG") 2>&1
START_TS="$(date +%s)"
printf '%s\n' "${SOURCE_URL_OVERRIDE:-$INPUT}" > "$SOURCE_INPUT_TXT"
if [[ -n "${SOURCE_PLATFORM:-}" ]]; then
  printf '%s\n' "$SOURCE_PLATFORM" > "$OUT_DIR/source_platform.txt"
fi
if [[ -n "${SOURCE_TITLE:-}" ]]; then
  printf '%s\n' "$SOURCE_TITLE" > "$OUT_DIR/source_title.txt"
fi
status_update "queued" "3" "Đã tạo job, chuẩn bị xử lý" "0"

VIDEO="$OUT_DIR/input.mp4"
AUDIO="$OUT_DIR/audio.wav"
ASR_AUDIO="$OUT_DIR/asr_speech.wav"
VOCALS_WAV="$OUT_DIR/vocals.wav"
NO_VOCALS_WAV="$OUT_DIR/no_vocals.wav"
SPEECH_REGIONS_JSON="$OUT_DIR/speech_regions.json"
SPEECH_PREPROCESS_REPORT_JSON="$OUT_DIR/speech_preprocess_report.json"
ASR_POSTPROCESS_REPORT_JSON="$OUT_DIR/asr_postprocess_report.json"
ASR_HALLUCINATION_REPORT_JSON="$OUT_DIR/asr_hallucination_report.json"
ORIGINAL_BASE="$OUT_DIR/original"
ORIGINAL_SRT="$OUT_DIR/original.srt"
ORIGINAL_ASR_RAW_SRT="$OUT_DIR/original_asr.raw.srt"
ORIGINAL_ASR_SRT="$OUT_DIR/original_asr.srt"
ORIGINAL_ASR_SPLIT_SRT="$OUT_DIR/original_asr.split.srt"
TRANSCRIPT_ORIGINAL_JSON="$OUT_DIR/transcript_original.json"
TRANSCRIPT_VI_JSON="$OUT_DIR/transcript_vi.json"
ORIGINAL_OCR_SRT="$OUT_DIR/original_ocr.srt"
SELECTED_TRANSCRIPT_SRT="$OUT_DIR/selected_transcript.srt"
OCR_TRANSCRIPT_REPORT_JSON="$OUT_DIR/ocr_transcript_report.json"
TRANSCRIPT_DECISION_JSON="$OUT_DIR/transcript_source_decision.json"
ASR_OCR_CONSISTENCY_REPORT_JSON="$OUT_DIR/asr_ocr_consistency_report.json"
VIETNAMESE_SRT="$OUT_DIR/vietnamese.srt"
DUB_SRT="$OUT_DIR/dub.srt"
DUBBING_SEGMENTS_JSON="$OUT_DIR/dubbing_segments.json"
DUBBING_REPORT_JSON="$OUT_DIR/dubbing_report.json"
VIETNAMESE_VOICE_WAV="$OUT_DIR/vietnamese_voice.wav"
TTS_AUDIO_STAGE_REPORT_JSON="$OUT_DIR/tts_audio_stage_report.json"
FINAL_VIDEO="$OUT_DIR/final_video_vi.mp4"
AUDIO_ONLY_VIDEO="$OUT_DIR/final_video_audio_only.mp4"
TMP_DIR="$OUT_DIR/temp"
TTS_STATS_JSON="$TMP_DIR/tts_stats.json"
TTS_ALIGNMENT_REPORT_JSON="$TMP_DIR/tts_alignment_report.json"
SPEED_REPORT_CSV="$TMP_DIR/speed_report.csv"
TTS_TEXT_QUALITY_REPORT_JSON="$OUT_DIR/tts_text_quality_report.json"
TTS_VOICE_QUALITY_REPORT_JSON="$OUT_DIR/tts_voice_quality_report.json"
mkdir -p "$TMP_DIR"

echo "Bắt đầu douyin-vietnamese-dubber"
echo "Input: $INPUT"
echo "Output: $OUT_DIR"
if [[ -n "$RESUME_JOB_DIR" ]]; then
  echo "Resume job dir: $RESUME_JOB_DIR"
fi
echo "Voice preset: ${VOICE_PRESET:-kokoro:${KOKORO_DEFAULT_VOICE}}"
echo "Voice: $VOICE"
status_update "queued" "5" "Đang kiểm tra runtime và lock" "0"
echo "Vietnamese Dub Timing Optimizer: ${OPTIMIZER_ENABLED:-1}"
if [[ "${SYNC_MODE:-balanced_dub}" == "aggressive_legacy" && "${TTS_SYNC_POLICY:-bounded}" == "frame_strict" ]]; then
  echo "TTS sync: ${SYNC_MODE} / frame_strict (Max TTS speed: unbounded legacy atempo chain)"
else
  echo "TTS sync: ${SYNC_MODE:-balanced_dub} / ${TTS_SYNC_POLICY:-bounded} (AI33 native<=${AI33_MAX_SPEED}x post_atempo<=${POST_ATEMPO_MAX}x total<=${TOTAL_AUDIO_SPEED_MAX}x)"
fi
echo "Speed caps: target=${TARGET_MAX_SPEED}x soft=${SOFT_MAX_SPEED}x hard=${HARD_MAX_SPEED}x overhang=${ALLOW_AUDIO_OVERHANG}s"
echo "Subtitle burn-in: burn=${BURN_VIET_SUBTITLE} mask=${MASK_ORIGINAL_SUBTITLE} mask_style=${SUBTITLE_MASK_STYLE} band_detect_engine=${SUBTITLE_BAND_DETECT_ENGINE} ocr_engine=${SUBTITLE_OCR_ENGINE} vision_model=${OCR_VISION_MODEL} band_sample_count=${SUBTITLE_BAND_SAMPLE_COUNT} band_height_ratio=${SUBTITLE_BAND_HEIGHT_RATIO} band_blur=${SUBTITLE_BAND_BLUR} band_tint=${SUBTITLE_BAND_TINT_OPACITY} text_color=${SUBTITLE_TEXT_COLOR} text_align=${SUBTITLE_TEXT_ALIGN} dynamic_mask=${SUBTITLE_DYNAMIC_MASK} mask_height_ratio=${SUBTITLE_MASK_HEIGHT_RATIO} mask_opacity=${SUBTITLE_MASK_OPACITY} bottom_margin_ratio=${SUBTITLE_BOTTOM_MARGIN_RATIO} font_size_ratio=${SUBTITLE_FONT_SIZE_RATIO} vi_min_font_size=${VI_SUBTITLE_MIN_FONT_SIZE} vi_max_font_size=${VI_SUBTITLE_MAX_FONT_SIZE} vi_max_lines=${VI_SUBTITLE_MAX_LINES} vi_wrap_chars=${VI_SUBTITLE_WRAP_CHARS} vi_target_band_fill=${VI_SUBTITLE_TARGET_BAND_FILL} vi_safe_width_ratio=${VI_SUBTITLE_SAFE_WIDTH_RATIO} vi_safe_height_ratio=${VI_SUBTITLE_SAFE_HEIGHT_RATIO} vi_min_band_fill_warn=${VI_SUBTITLE_MIN_BAND_FILL_WARN} vi_max_small_cue_ratio=${VI_SUBTITLE_MAX_SMALL_CUE_RATIO} vi_font_file=${VI_SUBTITLE_FONT_FILE} vi_font_name=${VI_SUBTITLE_FONT_NAME} vi_font_preset=${VI_SUBTITLE_FONT_PRESET} vi_font_dir=${VI_SUBTITLE_FONT_DIR} vi_layout_gate=${VI_SUBTITLE_LAYOUT_GATE} subtitle_render_failure_policy=${SUBTITLE_RENDER_FAILURE_POLICY} box_mode=${SUBTITLE_BOX_MODE} max_lines=${SUBTITLE_MAX_LINES} max_chars=${SUBTITLE_MAX_CHARS_PER_LINE}"
echo "Optimizer timeout: ${OPTIMIZER_TIMEOUT_SECONDS:-7200}s"
echo "Speech-only preprocess: ${SPEECH_ONLY_PREPROCESS_ENABLED:-1}"
echo "Speech-only config: subtitle_mode=${SUBTITLE_MODE:-dialogue_only}, ignore_background_music=${IGNORE_BACKGROUND_MUSIC:-true}, ignore_song_lyrics=${IGNORE_SONG_LYRICS:-true}, keep_original_music_bed=${KEEP_ORIGINAL_MUSIC_BED:-true}"
echo "Music bed: volume=${MUSIC_BED_VOLUME}; ducking=${ENABLE_BGM_DUCKING} amount=${BGM_DUCK_AMOUNT}; voice_volume=${VOICE_VOLUME}; tts_master=${TTS_MASTER_SAMPLE_RATE}Hz/${TTS_MASTER_CHANNELS}ch; final_audio=${FINAL_AUDIO_SAMPLE_RATE}Hz/${FINAL_AUDIO_CHANNELS}ch/${FINAL_AUDIO_BITRATE}; loudness=${FINAL_LOUDNESS_TARGET}LUFS TP=${FINAL_TRUE_PEAK_LIMIT}dBFS; slow_fit=${ALLOW_SLOW_FIT} (${POST_ATEMPO_MIN}..0.99 opt-in); allow_final_trim=${ALLOW_FINAL_TRIM}; retime=${ALLOW_VIDEO_RETIME}/${ALLOW_FREEZE_FRAME}/safe=${LOCAL_RETIME_SCENE_SAFE} max_freeze=${MAX_FREEZE_PER_SEGMENT_MS}/${MAX_FREEZE_PER_SCENE_MS}ms"
echo "BGM mode: ${BGM_MODE:-auto} fallback=${BGM_MODE_FALLBACK:-none}"
echo "ASR split long segments: ${ASR_SPLIT_LONG_SEGMENTS:-1} max_seconds=${ASR_SPLIT_MAX_SECONDS:-10} max_chars=${ASR_SPLIT_MAX_CHARS:-120}"
echo "Thời gian bắt đầu: $(date '+%F %T')"

if [[ -s "$VIDEO" ]]; then
  echo "Dùng cache video đầu vào: $VIDEO"
elif [[ "$INPUT" =~ ^https?:// ]]; then
  need_cmd yt-dlp
  echo "Đang tải video từ link..."
  status_update "download" "8" "Đang tải video Douyin" "0"
  if [[ "$INPUT" == *"douyin.com"* || "$INPUT" == *"iesdouyin.com"* ]]; then
    BROWSER_DOWNLOAD_LOG="$OUT_DIR/douyin-browser-download.log"
    if [[ -f "$DOUYIN_STEALTH_PATH" ]]; then
      echo "Link Douyin: ưu tiên browser/CDP downloader clean-media; cho phép fallback watermark nếu cần..."
      set +e
      DOUYIN_CLEAN_MEDIA_RESOLVER="$DOUYIN_CLEAN_MEDIA_RESOLVER" \
      DOUYIN_CLEAN_ONLY_DEFAULT="$DOUYIN_CLEAN_ONLY_DEFAULT" \
      DOUYIN_ALLOW_WATERMARKED_FALLBACK="$DOUYIN_ALLOW_WATERMARKED_FALLBACK" \
      python3 "$DOUYIN_STEALTH_PATH" download-video "$INPUT" --out "$VIDEO" 2>&1 | tee "$BROWSER_DOWNLOAD_LOG"
      browser_status=${PIPESTATUS[0]}
      set -e
      if [[ "$browser_status" -eq 0 && -s "$VIDEO" ]]; then
        echo "Đã tải Douyin bằng browser/CDP downloader."
      else
        if [[ "$DOUYIN_CLEAN_MEDIA_RESOLVER" == "1" && !( "$DOUYIN_CLEAN_ONLY_DEFAULT" == "0" && "$DOUYIN_ALLOW_WATERMARKED_FALLBACK" == "1" ) ]]; then
          fail "Không có video Douyin đạt clean-only hoặc browser/CDP không tải được; đã chặn fallback yt-dlp để tránh nhận video có logo. Xem $BROWSER_DOWNLOAD_LOG"
        else
          echo "WARN: Douyin browser/CDP downloader không tải được video, fallback sang yt-dlp. Xem $BROWSER_DOWNLOAD_LOG"
          if ! yt-dlp -f 'bv*+ba/best' --merge-output-format mp4 --no-playlist -o "$VIDEO" "$INPUT"; then
            fail "Không tải được video Douyin bằng browser/CDP downloader hoặc yt-dlp."
          fi
        fi
      fi
    else
      if [[ "$DOUYIN_CLEAN_MEDIA_RESOLVER" == "1" && !( "$DOUYIN_CLEAN_ONLY_DEFAULT" == "0" && "$DOUYIN_ALLOW_WATERMARKED_FALLBACK" == "1" ) ]]; then
        fail "Không tìm thấy douyin-stealth downloader cần cho clean-only; đã chặn fallback yt-dlp để tránh nhận video có logo."
      else
        echo "WARN: Không tìm thấy douyin-stealth downloader tại $DOUYIN_STEALTH_PATH; fallback sang yt-dlp."
        if ! yt-dlp -f 'bv*+ba/best' --merge-output-format mp4 --no-playlist -o "$VIDEO" "$INPUT"; then
          fail "Không tải được video từ link. Nếu là Douyin, có thể đang bị chặn/captcha/login; script đã dừng an toàn."
        fi
      fi
    fi
  elif ! yt-dlp -f 'bv*+ba/best' --merge-output-format mp4 --no-playlist -o "$VIDEO" "$INPUT"; then
    fail "Không tải được video từ link. Nếu là Douyin, có thể đang bị chặn/captcha/login; script đã dừng an toàn."
  fi
else
  [[ -f "$INPUT" ]] || fail "File video không tồn tại: $INPUT"
  cp "$INPUT" "$VIDEO"
fi

[[ -s "$VIDEO" ]] || fail "Video đầu vào rỗng hoặc tải/copy thất bại"
status_update "download" "15" "Đã có video đầu vào" "0"

if [[ -s "$AUDIO" && -s "$ASR_AUDIO" && -s "$SPEECH_PREPROCESS_REPORT_JSON" ]]; then
  WHISPER_AUDIO="$ASR_AUDIO"
  echo "Dùng cache speech-only preprocess: $ASR_AUDIO"
else
echo "Đang tiền xử lý audio speech-only trước Whisper/ASR..."
status_update "preprocess" "18" "Đang tách giọng/nhạc trước ASR" "0"
set +e
speech_only_preprocess "$VIDEO" "$AUDIO" "$ASR_AUDIO" "$VOCALS_WAV" "$NO_VOCALS_WAV" "$SPEECH_REGIONS_JSON" "$SPEECH_PREPROCESS_REPORT_JSON" "$TMP_DIR"
speech_preprocess_status=$?
set -e
if [[ "$speech_preprocess_status" -eq 0 && -s "$ASR_AUDIO" ]]; then
  WHISPER_AUDIO="$ASR_AUDIO"
  echo "Speech-only preprocess OK: Whisper sẽ dùng asr_speech.wav, không dùng trực tiếp audio gốc."
elif [[ "$speech_preprocess_status" -eq 2 ]]; then
  echo "Speech-only preprocess tắt bằng SPEECH_ONLY_PREPROCESS=0; fallback flow cũ extract audio gốc."
  echo "Đang tách audio WAV 16kHz mono..."
  ffmpeg -y -i "$VIDEO" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$AUDIO"
  cp "$AUDIO" "$ASR_AUDIO"
  WHISPER_AUDIO="$ASR_AUDIO"
else
  echo "WARN: Speech-only preprocess lỗi hoặc timeout (exit=$speech_preprocess_status); fallback flow cũ để không phá pipeline."
  echo "Đang tách audio WAV 16kHz mono..."
  ffmpeg -y -i "$VIDEO" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$AUDIO"
  cp "$AUDIO" "$ASR_AUDIO"
  WHISPER_AUDIO="$ASR_AUDIO"
fi
fi
[[ -s "$AUDIO" ]] || fail "Không tạo được audio.wav"
[[ -s "$WHISPER_AUDIO" ]] || fail "Không tạo được audio ASR cho Whisper"
case "$(printf '%s' "${BGM_MODE:-auto}" | tr '[:upper:]' '[:lower:]')" in
  auto|demucs)
    if [[ "${KEEP_ORIGINAL_MUSIC_BED:-true}" != "false" ]] && ! background_separation_ready; then
      status_update "needs_attention" "30" "Không tách được nhạc nền sạch" "0" "BackgroundSeparationFailed" "Demucs không tạo được no_vocals.wav hợp lệ; cài/bật Demucs hoặc đặt BGM_MODE=none. Không dùng audio gốc vì sẽ giữ giọng Trung."
      fail "BackgroundSeparationFailed: Demucs không tạo được no_vocals.wav hợp lệ; dừng trước ASR/TTS để tránh video cuối còn giọng Trung."
    fi
    ;;
esac
status_update "preprocess" "30" "Tiền xử lý audio xong" "0"

if [[ -s "$ORIGINAL_ASR_SRT" && -s "$ORIGINAL_ASR_RAW_SRT" ]]; then
  echo "Dùng cache ASR transcript: $ORIGINAL_ASR_SRT"
  cp "$ORIGINAL_ASR_SRT" "$ORIGINAL_SRT"
else
echo "Đang chạy Whisper tạo original.srt..."
status_update "asr" "32" "Đang chạy Whisper/ASR" "0"
"$WHISPER_BIN" -m "$WHISPER_MODEL" -f "$WHISPER_AUDIO" -l zh -osrt -of "$ORIGINAL_BASE"
[[ -s "$ORIGINAL_SRT" ]] || fail "Whisper không tạo được original.srt"
cp "$ORIGINAL_SRT" "$ORIGINAL_ASR_RAW_SRT"
status_update "asr" "42" "Whisper tạo original.srt xong" "0"

if [[ "${SPEECH_ONLY_PREPROCESS_ENABLED:-1}" != "0" && -s "$SPEECH_REGIONS_JSON" && -x "$ASR_POSTPROCESS_SCRIPT" ]]; then
  echo "Đang lọc hậu xử lý ASR theo speech regions/repetition/noise..."
  status_update "postprocess_asr" "43" "Đang lọc hậu xử lý ASR" "0"
  python3 "$ASR_POSTPROCESS_SCRIPT" --srt "$ORIGINAL_SRT" --speech-regions-json "$SPEECH_REGIONS_JSON" --report-json "$ASR_POSTPROCESS_REPORT_JSON" --hallucination-report-json "$ASR_HALLUCINATION_REPORT_JSON"
  [[ -s "$ORIGINAL_SRT" ]] || fail "original.srt rỗng sau lọc hậu xử lý ASR; audio có thể chỉ là nhạc/noise."
fi
cp "$ORIGINAL_SRT" "$ORIGINAL_ASR_SRT"
fi
status_update "postprocess_asr" "45" "Lọc ASR xong" "0"

ocr_transcript_previously_failed=0
if [[ -n "$RESUME_JOB_DIR" && "$SUBTITLE_TRANSCRIPT_SOURCE" == "auto" && "$OCR_TRANSCRIPT_REBUILD" != "1" && -s "$ORIGINAL_ASR_SRT" && -s "$OCR_TRANSCRIPT_REPORT_JSON" && ! -s "$ORIGINAL_OCR_SRT" ]]; then
  set +e
  python3 - "$OCR_TRANSCRIPT_REPORT_JSON" <<'PY'
import json, sys
from pathlib import Path
try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    sys.exit(1)
status = str(data.get("status") or "").lower()
exit_code = str(data.get("exit") or "")
sys.exit(0 if status in {"failed", "error", "timeout", "timeout_partial", "missing_script"} or exit_code in {"124", "137", "143"} else 1)
PY
  resume_ocr_failed=$?
  set -e
  if [[ "$resume_ocr_failed" -eq 0 ]]; then
    echo "Resume: OCR transcript trước đó lỗi/timeout và OCR SRT rỗng; bỏ retry OCR, giữ mode auto để QC ASR trước khi dùng."
    ocr_transcript_previously_failed=1
  fi
fi

if [[ "$SUBTITLE_TRANSCRIPT_SOURCE" == "auto" || "$SUBTITLE_TRANSCRIPT_SOURCE" == "ocr" ]] \
  && [[ "$SUBTITLE_OCR_ENGINE" == "9router_vision" ]] \
  && [[ "$OCR_VISION_PROVIDER" == "ninerouter" ]] \
  && [[ -z "$OCR_VISION_API_KEY" ]]; then
  echo "WARN: Thiếu OCR_VISION_API_KEY; bỏ qua OCR 9Router và dùng ASR."
  status_update "ocr_transcript" "45" "Thiếu key OCR, dùng ASR fallback" "0" "OcrTranscriptFallback" "OCR 9Router không có API key; dùng ASR transcript."
  printf '{"status":"skipped","reason":"missing_ocr_api_key","fallback":"asr"}\n' > "$OCR_TRANSCRIPT_REPORT_JSON"
  : > "$ORIGINAL_OCR_SRT"
  SUBTITLE_TRANSCRIPT_SOURCE="asr"
fi

if [[ "$SUBTITLE_TRANSCRIPT_SOURCE" == "auto" || "$SUBTITLE_TRANSCRIPT_SOURCE" == "ocr" ]]; then
  if [[ "$ocr_transcript_previously_failed" == "1" ]]; then
    echo "Resume: dùng OCR failure cache, không chạy lại OCR transcript."
    status_update "ocr_transcript" "45" "OCR trước đó timeout/rỗng, kiểm ASR QC" "0" "OcrTranscriptFallback" "OCR transcript trước đó lỗi/timeout; bỏ retry OCR nhưng vẫn để auto kiểm ASR severe trước khi quyết định."
    : > "$ORIGINAL_OCR_SRT"
  elif [[ "$OCR_TRANSCRIPT_REBUILD" != "1" && -s "$ORIGINAL_OCR_SRT" && -s "$OCR_TRANSCRIPT_REPORT_JSON" ]]; then
    echo "Dùng cache OCR transcript: $ORIGINAL_OCR_SRT"
  elif [[ -x "$OCR_TRANSCRIPT_SCRIPT" && -x "$SUBTITLE_MASK_RENDER_PYTHON" ]]; then
    echo "Đang OCR subtitle Trung gốc để QC/chọn transcript..."
    status_update "ocr_transcript" "45" "Đang OCR subtitle gốc" "0"
    # Bounded fast mode: shell timeout cao hơn budget nội bộ (720s) một chút để script kịp
    # ghi partial report trước khi bị kill mù. Giữ backward-compat qua OCR_TRANSCRIPT_TIMEOUT_SECONDS.
    ocr_internal_budget="${OCR_TRANSCRIPT_TOTAL_TIMEOUT_SECONDS:-720}"
    ocr_transcript_timeout="${OCR_TRANSCRIPT_TIMEOUT_SECONDS:-$((ocr_internal_budget + 120))}"
    # Lock tránh xung đột model vision: nếu OCR_VISION_MODEL == NINEROUTER_MODEL,
    # lấy exclusive flock trước khi chạy OCR vision để không chạy song song với optimizer/dịch.
    ocr_vision_lock_dir="$(dirname "$OUT_DIR")"
    ocr_vision_lock_file="${OCR_VISION_MODEL_LOCK:-$ocr_vision_lock_dir/.ocr-vision-model.lock}"
    mkdir -p "$ocr_vision_lock_dir"
    ocr_vision_needs_lock=0
    if [[ "$SUBTITLE_OCR_ENGINE" == "9router_vision" && "$OCR_VISION_MODEL" == "$NINEROUTER_MODEL" && -n "$OCR_VISION_MODEL" ]]; then
      ocr_vision_needs_lock=1
      echo "OCR vision và optimizer dùng chung model '$OCR_VISION_MODEL'; lấy exclusive flock để tránh nghẽn."
    fi
    set +e
    # Dùng exec fd cho flock để tránh phải export function sang subprocess.
    if [[ "$ocr_vision_needs_lock" == "1" ]]; then
      exec 9>"$ocr_vision_lock_file"
      ocr_lock_wait_seconds="${OPENCLAW_LONG_STEP_HEARTBEAT_SECONDS:-30}"
      while ! flock -x -n 9; do
        status_update "ocr_transcript" "45" "Đợi model vision rảnh" "0" "VisionModelBusy" "OCR vision đang đợi job khác dùng chung model $OCR_VISION_MODEL."
        sleep "$ocr_lock_wait_seconds"
      done
      ocr_lock_held=1
    else
      ocr_lock_held=0
    fi
    export SUBTITLE_OCR_FPS="${SUBTITLE_OCR_TRANSCRIPT_FPS:-${SUBTITLE_OCR_FPS:-1}}"
    export SUBTITLE_DETECT_REGION_TOP_RATIO="${OCR_TRANSCRIPT_REGION_TOP_RATIO:-0.58}"
    export SUBTITLE_DETECT_REGION_BOTTOM_RATIO="${OCR_TRANSCRIPT_REGION_BOTTOM_RATIO:-1.0}"
    export SUBTITLE_OCR_ENGINE
    export SUBTITLE_OCR_LANG
    export SUBTITLE_OCR_MIN_CONFIDENCE
    export OCR_VISION_MODEL
    export OCR_VISION_API_BASE
    export OCR_VISION_PROVIDER
    if [[ "$OCR_VISION_PROVIDER" == "ninerouter" && -z "$OCR_VISION_API_KEY" ]]; then
      OCR_VISION_API_KEY="$(get_ninerouter_api_key)"
    fi
    if [[ "$SUBTITLE_OCR_ENGINE" == "9router_vision" && "$OCR_VISION_PROVIDER" == "ninerouter" ]]; then
      [[ -n "$OCR_VISION_API_KEY" ]] || fail "Thiếu OCR_VISION_API_KEY cho OCR 9Router vision."
    fi
    export OCR_VISION_API_KEY="$OCR_VISION_API_KEY"
    export OCR_VISION_MIN_CONFIDENCE
    export OCR_VISION_DEDUP_THRESHOLD
    export OCR_TRANSCRIPT_FRAME_STRIDE
    export OCR_TRANSCRIPT_MAX_FRAMES
    export OCR_TRANSCRIPT_VISION_TIMEOUT_SECONDS
    export OCR_TRANSCRIPT_TOTAL_TIMEOUT_SECONDS="$ocr_internal_budget"
    export OCR_TRANSCRIPT_DISABLE_PADDLE_FALLBACK
    export NINEROUTER_MODEL
    export OPENCLAW_AI_PROVIDER
    run_with_status_heartbeat "ocr_transcript" "45" "Đang OCR subtitle gốc" "$ocr_transcript_timeout" "${OPENCLAW_LONG_STEP_HEARTBEAT_SECONDS:-30}" \
      timeout "$ocr_transcript_timeout" \
        "$SUBTITLE_MASK_RENDER_PYTHON" "$OCR_TRANSCRIPT_SCRIPT" --video "$VIDEO" --output-srt "$ORIGINAL_OCR_SRT" --report-json "$OCR_TRANSCRIPT_REPORT_JSON"
    ocr_transcript_status=$?
    if [[ "$ocr_lock_held" == "1" ]]; then
      flock -u 9 2>/dev/null || true
      exec 9>&- 2>/dev/null || true
    fi
    set -e
    if [[ "$ocr_transcript_status" -ne 0 ]]; then
      echo "WARN: OCR transcript lỗi exit=$ocr_transcript_status; auto sẽ fallback ASR nếu ASR đạt QC."
      status_update "ocr_transcript" "45" "OCR subtitle lỗi/timeout, fallback ASR nếu đủ QC" "0" "OcrTranscriptFallback" "OCR transcript exit=$ocr_transcript_status; pipeline sẽ dùng ASR nếu đạt QC."
      # KHÔNG overwrite report thành JSON nghèo nếu script đã ghi partial report đầy đủ.
      # Chỉ ghi error nghèo khi report rỗng/thiếu (script crash trước khi ghi, hoặc shell SIGKILL).
      if [[ ! -s "$OCR_TRANSCRIPT_REPORT_JSON" ]] || ! python3 -c 'import json,sys; json.loads(open(sys.argv[1]).read())' "$OCR_TRANSCRIPT_REPORT_JSON" 2>/dev/null; then
        printf '{"status":"failed","exit":%s,"timeout_reason":"shell_timeout_or_crash"}\n' "$ocr_transcript_status" > "$OCR_TRANSCRIPT_REPORT_JSON"
      fi
      # OCR SRT rỗng/không tồn tại thì tạo file rỗng để transcript_decision không lỗi.
      [[ -s "$ORIGINAL_OCR_SRT" ]] || : > "$ORIGINAL_OCR_SRT"
    fi
  else
    echo "WARN: Thiếu OCR_TRANSCRIPT_SCRIPT hoặc SUBTITLE_MASK_RENDER_PYTHON; bỏ OCR transcript."
    printf '{"status":"missing_script"}\n' > "$OCR_TRANSCRIPT_REPORT_JSON"
    : > "$ORIGINAL_OCR_SRT"
  fi
fi

if [[ -x "$TRANSCRIPT_DECISION_SCRIPT" ]]; then
  echo "Đang chọn nguồn transcript cuối cùng (${SUBTITLE_TRANSCRIPT_SOURCE})..."
  status_update "transcript_decision" "46" "Đang chọn nguồn transcript" "0"
  set +e
  python3 "$TRANSCRIPT_DECISION_SCRIPT" \
    --mode "$SUBTITLE_TRANSCRIPT_SOURCE" \
    --asr-srt "$ORIGINAL_ASR_SRT" \
    --ocr-srt "$ORIGINAL_OCR_SRT" \
    --output-srt "$SELECTED_TRANSCRIPT_SRT" \
    --asr-report "$ASR_POSTPROCESS_REPORT_JSON" \
    --ocr-report "$OCR_TRANSCRIPT_REPORT_JSON" \
    --decision-json "$TRANSCRIPT_DECISION_JSON" \
    --consistency-json "$ASR_OCR_CONSISTENCY_REPORT_JSON" \
    --dub-favor-asr-ratio "${CHOOSE_DUB_FAVOR_ASR_RATIO:-1.25}"
  transcript_decision_status=$?
  set -e
  if [[ "$transcript_decision_status" -eq 7 ]]; then
    transcript_decision_msg="$(python3 -c 'import json,sys; from pathlib import Path; p=Path(sys.argv[1]); d=json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}; print(d.get("error_message") or "ASR bị hallucination nặng, OCR không tạo được transcript; cần retry OCR/ASR từ đầu hoặc dán transcript_vi.json.")' "$TRANSCRIPT_DECISION_JSON" 2>/dev/null || printf '%s' 'ASR bị hallucination nặng, OCR không tạo được transcript; cần retry OCR/ASR từ đầu hoặc dán transcript_vi.json.')"
    echo "ERROR: $transcript_decision_msg" >&2
    create_translate_pending "$transcript_decision_msg"
    status_update "manual_translate" "58" "Transcript gốc lỗi, cần dán transcript_vi.json" "0" "TranscriptSourcesFailedQC" "$transcript_decision_msg"
    status_add_failure_context \
      "both_sources_failed_qc" \
      "retry_transcript_sources" \
      "$TRANSCRIPT_DECISION_JSON" \
      "$ASR_OCR_CONSISTENCY_REPORT_JSON" \
      "$OCR_TRANSCRIPT_REPORT_JSON"
    exit 7
  elif [[ "$transcript_decision_status" -ne 0 ]]; then
    fail "Chọn nguồn transcript lỗi (exit=$transcript_decision_status)."
  fi
else
  echo "WARN: Thiếu TRANSCRIPT_DECISION_SCRIPT; dùng ASR transcript."
  cp "$ORIGINAL_ASR_SRT" "$SELECTED_TRANSCRIPT_SRT"
fi
# selected_transcript.srt is canonical and immutable after selection. Keep the
# legacy variable pointing to it so every translator/optimizer consumer uses the
# unchanged selected source; ASR-only splitting is intentionally not applied to
# an OCR-selected transcript.
[[ -s "$SELECTED_TRANSCRIPT_SRT" ]] || fail "Không có selected_transcript.srt sau bước chọn transcript."
ORIGINAL_SRT="$SELECTED_TRANSCRIPT_SRT"
write_transcript_json "$ORIGINAL_SRT" "$TRANSCRIPT_ORIGINAL_JSON" "original"

# Transcript quality gate thresholds: định nghĩa TRƯỚC ASR timing repair vì repair
# dùng --max-thin-seconds/--min-text-chars. Trước đây block này nằm sau repair →
# `set -u` bắt unbound variable khi gọi repair → TX_GATE skip → fail long-thin.
vi_gate_min_cues_per_min="${VI_GATE_MIN_CUES_PER_MIN:-4}"
vi_gate_max_cue_seconds="${VI_GATE_MAX_CUE_SECONDS:-15}"
vi_gate_max_thin_seconds="${VI_GATE_MAX_THIN_SECONDS:-6}"
vi_gate_min_text_chars="${VI_GATE_MIN_TEXT_CHARS:-12}"
vi_gate_allow_asr_long_thin_with_failed_ocr="${VI_GATE_ALLOW_ASR_LONG_THIN_WITH_FAILED_OCR:-1}"
vi_gate_asr_max_long_thin_cues="${VI_GATE_ASR_MAX_LONG_THIN_CUES:-5}"
vi_gate_asr_max_long_thin_ratio="${VI_GATE_ASR_MAX_LONG_THIN_RATIO:-0.05}"
vi_gate_asr_max_warn_cue_seconds="${VI_GATE_ASR_MAX_WARN_CUE_SECONDS:-10}"

# ASR timing repair: nếu chosen=asr và ASR có long-thin cue nhưng OCR quality_ok,
# chia long-thin ASR cue theo ranh giới OCR cue chồng lấp (display timing thật) thay vì
# fail TranscriptTooSparse false-positive (job 201915: ASR 94/OCR 65, ASR 3 long-thin).
# Repair output is diagnostic only. It must never replace selected_transcript.srt.
TX_TIMING_REPAIR_REPORT_JSON="$OUT_DIR/transcript_timing_repair_report.json"
TX_TIMING_REPAIR_SIDECAR_SRT="$OUT_DIR/selected_transcript.timing-repair.srt"
TX_TIMING_REPAIR_SCRIPT="$SKILL_DIR/asr_timing_repair.py"
if [[ -s "$TRANSCRIPT_DECISION_JSON" && -s "$ORIGINAL_OCR_SRT" && -x "$TX_TIMING_REPAIR_SCRIPT" ]]; then
  set +e
  python3 "$TX_TIMING_REPAIR_SCRIPT" \
    --asr-srt "$ORIGINAL_ASR_SRT" \
    --ocr-srt "$ORIGINAL_OCR_SRT" \
    --decision-json "$TRANSCRIPT_DECISION_JSON" \
    --output-srt "$TX_TIMING_REPAIR_SIDECAR_SRT" \
    --report-json "$TX_TIMING_REPAIR_REPORT_JSON" \
    --max-thin-seconds "$vi_gate_max_thin_seconds" \
    --min-text-chars "$vi_gate_min_text_chars" \
    --max-remaining-long-thin "$vi_gate_asr_max_long_thin_cues"
  tx_repair_status=$?
  set -e
  if [[ "$tx_repair_status" -eq 0 ]]; then
    echo "ASR timing repair: OK/skip (xem transcript_timing_repair_report.json)"
  elif [[ "$tx_repair_status" -eq 9 ]]; then
    echo "WARN: ASR timing repair incomplete (vẫn còn long-thin cue không có OCR chồng). TX_GATE sẽ xử lý." >&2
  else
    echo "WARN: asr_timing_repair.py exit=$tx_repair_status (KHÔNG fatal, để TX_GATE xử lý)." >&2
  fi
else
  echo "ASR timing repair: skip (thiếu decision/ocr/repair script)."
  printf '{"skipped":true,"reason":"missing_decision_or_ocr_or_script","status":"skipped","repaired":0,"remaining_long_thin":0}\n' > "$TX_TIMING_REPAIR_REPORT_JSON" 2>/dev/null || true
fi

# Transcript quality gate: original.srt không được quá thưa / có cue dài bất thường.
# Bắt đúng bug OCR 17-cue cho video 338s (cue kéo 62s/112s một câu) -> mất vietsub/mất giọng.
# Gate: max cue > 15s, hoặc long-thin (text<12 chars & dur>6s), hoặc cue density < 4/min.
# (biến vi_gate_* đã định nghĩa ở block trên, trước ASR timing repair)
tx_video_duration="$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$VIDEO" 2>/dev/null | tr -d '\r' || echo 0)"
set +e
TX_GATE_DECISION_JSON="$TRANSCRIPT_DECISION_JSON" \
TX_GATE_REPAIR_REPORT_JSON="$TX_TIMING_REPAIR_REPORT_JSON" \
TX_GATE_ALLOW_ASR_LONG_THIN_WITH_FAILED_OCR="$vi_gate_allow_asr_long_thin_with_failed_ocr" \
TX_GATE_ASR_MAX_LONG_THIN_CUES="$vi_gate_asr_max_long_thin_cues" \
TX_GATE_ASR_MAX_LONG_THIN_RATIO="$vi_gate_asr_max_long_thin_ratio" \
TX_GATE_ASR_MAX_WARN_CUE_SECONDS="$vi_gate_asr_max_warn_cue_seconds" \
python3 - "$ORIGINAL_SRT" "$tx_video_duration" "$vi_gate_min_cues_per_min" "$vi_gate_max_cue_seconds" "$vi_gate_max_thin_seconds" "$vi_gate_min_text_chars" <<'PY'
import json, os, re, sys
from pathlib import Path

def parse(path):
    content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    out = []
    if not content:
        return out
    for block in re.split(r"\n\s*\n", content):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        try:
            a, b = [p.strip() for p in lines[1].split("-->", 1)]
            def ms(t):
                hh, mm, rest = t.split(":")
                ss, mmm = rest.split(",")
                return ((int(hh)*60+int(mm))*60+int(ss))*1000 + int(mmm)
            out.append((ms(a), ms(b), " ".join(lines[2:])))
        except Exception:
            continue
    return out

cues = parse(sys.argv[1])
video_duration = float(sys.argv[2] or 0)
min_per_min = float(sys.argv[3])
max_cue_s = float(sys.argv[4])
max_thin_s = float(sys.argv[5])
min_chars = int(float(sys.argv[6]))

# Source-aware: đọc decision + repair report để không hard-fail long_thin khi
# chosen=asr & !severe & OCR ok & repair đã giảm long_thin về 0 (job 201915).
def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}
dec = load_json(os.environ.get("TX_GATE_DECISION_JSON") or "") or {}
repair = load_json(os.environ.get("TX_GATE_REPAIR_REPORT_JSON") or "") or {}
chosen = dec.get("chosen") or ""
severe_asr = bool(dec.get("severe_asr"))
ocr_quality_ok = bool(dec.get("ocr_quality_ok"))
ocr_transcript_usable = bool(dec.get("ocr_transcript_usable", ocr_quality_ok))
ocr_timing_anchor_usable = bool(dec.get("ocr_timing_anchor_usable", ocr_transcript_usable))
asr_timeline_ok = bool(dec.get("asr_timeline_ok"))
repair_status = repair.get("status") or ""
repair_remaining = int(repair.get("remaining_long_thin") or 0)
repair_repaired = int(repair.get("repaired_cues") or repair.get("repaired") or 0)
allow_asr_failed_ocr = (os.environ.get("TX_GATE_ALLOW_ASR_LONG_THIN_WITH_FAILED_OCR") or "1") == "1"
asr_max_long_thin_cues = int(float(os.environ.get("TX_GATE_ASR_MAX_LONG_THIN_CUES") or 5))
asr_max_long_thin_ratio = float(os.environ.get("TX_GATE_ASR_MAX_LONG_THIN_RATIO") or 0.05)
asr_max_warn_cue_s = float(os.environ.get("TX_GATE_ASR_MAX_WARN_CUE_SECONDS") or 10)

if not cues:
    print("TX_GATE_FAIL: original.srt không có cue")
    sys.exit(7)

max_cue = 0.0
long_thin = 0
for s, e, text in cues:
    dur = (e - s) / 1000.0
    if dur > max_cue:
        max_cue = dur
    if len(re.sub(r"\s+", "", text)) < min_chars and dur > max_thin_s:
        long_thin += 1

dur_min = video_duration / 60.0 if video_duration > 0 else 0
density = len(cues) / dur_min if dur_min > 0 else 999

# Hard-fail: max cue quá dài hoặc density quá thấp (dù nguồn nào).
if max_cue > max_cue_s:
    src_msg = "OCR sai" if (chosen == "ocr" or not ocr_quality_ok) else "transcript quá thưa"
    print(f"TX_GATE_FAIL: max cue {max_cue:.2f}s > {max_cue_s}s ({src_msg})")
    sys.exit(7)
if dur_min > 0 and density < min_per_min:
    src_msg = "OCR sai" if (chosen == "ocr" or not ocr_quality_ok) else "transcript quá thưa"
    print(f"TX_GATE_FAIL: cue density {density:.2f}/min < {min_per_min}/min ({src_msg})")
    sys.exit(7)

# long_thin: the timing-repair sidecar is diagnostic only; this gate always
# evaluates the immutable selected transcript and is not relaxed by sidecar data.
if long_thin > 0:
    long_thin_ratio = long_thin / len(cues)
    asr_failed_ocr_but_usable = (
        allow_asr_failed_ocr
        and chosen == "asr"
        and not severe_asr
        and not ocr_timing_anchor_usable
        and asr_timeline_ok
        and long_thin <= asr_max_long_thin_cues
        and long_thin_ratio <= asr_max_long_thin_ratio
        and max_cue <= asr_max_warn_cue_s
        and (dur_min <= 0 or density >= min_per_min)
    )
    if asr_failed_ocr_but_usable:
        print(f"TX_GATE_WARN: ASR có {long_thin}/{len(cues)} long-thin cue "
              f"({long_thin_ratio:.1%}) nhưng OCR fail/unusable và ASR coverage/density OK; "
              f"pipeline tiếp tục bằng ASR.")
        sys.exit(0)
    if chosen == "ocr" or not ocr_timing_anchor_usable:
        print(f"TX_GATE_FAIL: {long_thin} long-thin cue (text<{min_chars} chars & dur>{max_thin_s}s) "
              f"(OCR sai: chosen={chosen} ocr_timing_anchor_usable={ocr_timing_anchor_usable})")
        sys.exit(7)
    # ASR nhưng repair chưa chạy/ chưa ok -> repair failed.
    print(f"TX_GATE_FAIL: {long_thin} long-thin ASR cue, repair {repair_status or 'not_run'} "
          f"(remaining={repair_remaining}); ASR timing repair failed. Cần retry ASR hoặc dán transcript.")
    sys.exit(7)
print(f"TX_GATE_OK: cues={len(cues)} max_cue={max_cue:.2f}s long_thin={long_thin} density={density:.2f}/min")
sys.exit(0)
PY
tx_gate_status=$?
set -e
if [[ "$tx_gate_status" -eq 7 ]]; then
  # Đọc source để message chính xác (không hardcode "OCR sai" khi nguồn là ASR).
  tx_gate_chosen="$(python3 -c "import json,sys; d=json.load(open('$TRANSCRIPT_DECISION_JSON')); print(d.get('chosen',''))" 2>/dev/null || echo '')"
  tx_gate_ocr_ok="$(python3 -c "import json,sys; d=json.load(open('$TRANSCRIPT_DECISION_JSON')); print('1' if d.get('ocr_quality_ok') else '0')" 2>/dev/null || echo '0')"
  tx_gate_ocr_anchor_ok="$(python3 -c "import json,sys; d=json.load(open('$TRANSCRIPT_DECISION_JSON')); print('1' if d.get('ocr_timing_anchor_usable', d.get('ocr_quality_ok')) else '0')" 2>/dev/null || echo '0')"
  tx_gate_repair_status="$(python3 -c "import json,sys; d=json.load(open('$TX_TIMING_REPAIR_REPORT_JSON')); print(d.get('status',''))" 2>/dev/null || echo '')"
  if [[ "$tx_gate_chosen" == "asr" && "$tx_gate_ocr_anchor_ok" == "1" ]]; then
    if [[ "$tx_gate_repair_status" == "ok" || "$tx_gate_repair_status" == "partial_ok" ]]; then
      # Repair ok nhưng fail vì max_cue/density -> thật sự thưa, vẫn needs_attention.
      tx_gate_msg="original.srt (ASR) quá thưa (max_cue/density thấp) sau khi repair; cần retry ASR hoặc dán transcript_vi.json."
    else
      tx_gate_msg="ASR timing repair failed (vẫn còn long-thin cue không có OCR chồng); cần retry ASR hoặc dán transcript_vi.json."
    fi
  elif [[ "$tx_gate_chosen" == "asr" && "$tx_gate_ocr_anchor_ok" != "1" ]]; then
    tx_gate_msg="ASR transcript vẫn quá thưa/dài trong khi OCR không dùng được; cần retry ASR/OCR hoặc dán transcript_vi.json."
  else
    tx_gate_msg="original.srt cue quá dài/quá thưa (OCR sai); bấm Chạy tiếp từ job cũ (xóa original.srt để rebuild OCR/ASR) hoặc dán transcript_vi.json."
  fi
  echo "ERROR: $tx_gate_msg Dừng job, không dịch/render." >&2
  # selected_transcript.srt is the canonical manual-translation input; keep it
  # until create_translate_pending has serialized it for resume.
  rm -f "$ORIGINAL_ASR_SPLIT_SRT"
  create_translate_pending "$tx_gate_msg"
  status_update "needs_attention" "97" "Transcript gốc quá thưa, cần retry/dán thủ công" "0" "TranscriptTooSparse" "$tx_gate_msg"
  exit 7
fi

if [[ -n "$RESUME_JOB_DIR" && -s "$VIETNAMESE_SRT" && -s "$DUB_SRT" ]] \
  && srt_has_spoken_text "$VIETNAMESE_SRT" && srt_has_spoken_text "$DUB_SRT" \
  && dubbing_cache_is_complete "$DUBBING_REPORT_JSON"; then
  # A TTS-only resume must not spend time or quota re-running translation.  The
  # AI33 cue manifest fingerprints dub.srt, so a changed cue is still precisely
  # invalidated before any provider call.
  echo "Dùng cached vietnamese.srt/dub.srt hợp lệ để resume TTS."
  TTS_SOURCE_SRT="$DUB_SRT"
elif load_manual_translation_if_available; then
  echo "Dùng transcript_vi.json thủ công có sẵn để resume dịch."
  rm -f "$OUT_DIR/TRANSLATE_PENDING.txt"
  TTS_SOURCE_SRT="$DUB_SRT"
else
echo "Đang tối ưu dịch/lồng tiếng Việt qua Vietnamese Dub Timing Optimizer..."
status_update "optimizer" "46" "Đang dịch/tối ưu timing qua ${OPENCLAW_AI_PROVIDER}" "1"
set +e
optimize_vietnamese_dub_timing "$ORIGINAL_SRT" "$VIETNAMESE_SRT" "$DUB_SRT" "$DUBBING_SEGMENTS_JSON" "$DUBBING_REPORT_JSON" "$API_KEY" "$TMP_DIR"
optimizer_status=$?
set -e
if [[ "$optimizer_status" -eq 0 && -s "$VIETNAMESE_SRT" && -s "$DUB_SRT" ]]; then
  TTS_SOURCE_SRT="$DUB_SRT"
  echo "Optimizer OK: dùng dub.srt để tạo TTS, vietnamese.srt dùng cho phụ đề đầy đủ."
  if ! srt_has_spoken_text "$DUB_SRT"; then
    echo "WARN: Optimizer tạo dub.srt không có dòng thoại; fallback dịch flow cũ để vẫn tạo lồng tiếng Việt."
    status_update "optimizer" "60" "dub.srt rỗng, fallback dịch SRT flow cũ" "1"
    if try_translate_srt; then
      TTS_SOURCE_SRT="$DUB_SRT"
    fi
  fi
elif [[ "$optimizer_status" -eq 2 ]]; then
  echo "Optimizer tắt bằng VIET_DUB_TIMING_OPTIMIZER=0; dùng flow dịch cũ."
  echo "Đang dịch original.srt sang vietnamese.srt qua 9Router/OpenAI-compatible API..."
  if try_translate_srt; then
    TTS_SOURCE_SRT="$VIETNAMESE_SRT"
  fi
elif [[ "$optimizer_status" -eq 3 ]]; then
  echo "WARN: Optimizer dịch lỗi hàng loạt (429/timeout, exit=3); thử fallback dịch flow cũ 1 lần."
  status_update "optimizer" "60" "Optimizer dịch lỗi 429/timeout, đang thử fallback dịch" "1" "OptimizerTranslateFailed" "9router 429/timeout; thử lại flow dịch cũ."
  echo "Đang dịch original.srt sang vietnamese.srt qua 9Router/OpenAI-compatible API..."
  if try_translate_srt; then
    TTS_SOURCE_SRT="$VIETNAMESE_SRT"
  fi
  # Nếu fallback vẫn không ra vietnamese.srt hợp lệ -> quality gate dưới sẽ dừng manual_translate.
else
  echo "WARN: Vietnamese Dub Timing Optimizer lỗi hoặc thiếu output (exit=$optimizer_status); fallback về flow dịch cũ để không làm fail pipeline."
  echo "Đang dịch original.srt sang vietnamese.srt qua 9Router/OpenAI-compatible API..."
  if try_translate_srt; then
    TTS_SOURCE_SRT="$VIETNAMESE_SRT"
  fi
fi
fi
# Fallback an toàn: nếu optimizer/TTS-probe lỗi nhưng vietnamese.srt vẫn có nội dung,
# dùng luôn vietnamese.srt làm dub.srt thay vì bắt người dùng dán bản dịch thủ công.
# Manual translate CHỈ dùng khi KHÔNG tạo được vietnamese.srt thật sự.
if [[ -s "$VIETNAMESE_SRT" && ! -s "$DUB_SRT" ]]; then
  echo "WARN: dub.srt rỗng nhưng vietnamese.srt có nội dung; dùng vietnamese.srt làm dub.srt (không bắt manual translate)."
  cp "$VIETNAMESE_SRT" "$DUB_SRT"
  TTS_SOURCE_SRT="$DUB_SRT"
fi
if [[ ! -s "$VIETNAMESE_SRT" ]]; then
  create_translate_pending "optimizer/dịch tự động không tạo được vietnamese.srt"
  status_update "manual_translate" "58" "Đang chờ bạn dán bản dịch thủ công" "0"
  fail "Đang chờ bạn dán bản dịch thủ công vào transcript_vi.json rồi bấm resume."
fi
# Quality gate: vietnamese.srt PHẢI là tiếng Việt, không được fallback thành tiếng Trung.
# Reject nếu CJK ratio cao hoặc text trùng source (dịch không xảy ra do 429/timeout).
if ! srt_looks_vietnamese "$VIETNAMESE_SRT" "$ORIGINAL_SRT"; then
  echo "ERROR: vietnamese.srt KHÔNG phải tiếng Việt (fallback source_text do dịch lỗi 429/timeout). Dừng job, không render." >&2
  rm -f "$VIETNAMESE_SRT" "$DUB_SRT"
  create_translate_pending "optimizer/vietnamese.srt fallback thành tiếng Trung do dịch lỗi (429/timeout)"
  status_update "manual_translate" "58" "Bản dịch tự động lỗi (tiếng Trung), cần dán lại hoặc retry" "0" "TranslateNotVietnamese" "vietnamese.srt bị fallback source_text; bấm Chạy tiếp từ job cũ để retry khi 9router hết 429."
  fail "Bản dịch tự động lỗi: vietnamese.srt vẫn tiếng Trung. Bấm Chạy tiếp từ job cũ khi 9Router hết rate-limit, hoặc dán transcript_vi.json thủ công."
fi
# Quality gate: vietnamese.srt phải bám từng cue gốc, không bị gộp thành vài khối dài ("đứng im một dòng").
# - Gate 1: cue count VI >= 80% cue count original (env VI_GATE_MIN_CUE_RATIO, mặc định 0.80).
# - Gate 2: không cue VI nào dài quá VI_GATE_MAX_CUE_SECONDS (mặc định 8s) trừ khi cue gốc cùng ordinal cũng dài.
# Khi subtitle per-cue đúng, vi cue duration == original cue duration nên gate 2 tự thoả; gate chỉ bắt bug gộp.
vi_gate_min_ratio="${VI_GATE_MIN_CUE_RATIO:-0.80}"
vi_gate_max_seconds="${VI_GATE_MAX_CUE_SECONDS:-8}"
vi_gate_max_repeat_run="${VI_GATE_MAX_REPEAT_RUN:-8}"
vi_gate_min_repeat_count="${VI_GATE_MIN_REPEAT_COUNT:-12}"
vi_gate_max_repeat_ratio="${VI_GATE_MAX_REPEAT_RATIO:-0.25}"
vi_gate_min_repeat_chars="${VI_GATE_MIN_REPEAT_CHARS:-8}"
set +e
python3 - "$ORIGINAL_SRT" "$VIETNAMESE_SRT" "$vi_gate_min_ratio" "$vi_gate_max_seconds" "$vi_gate_max_repeat_run" "$vi_gate_min_repeat_count" "$vi_gate_max_repeat_ratio" "$vi_gate_min_repeat_chars" <<'PY'
import re, sys
import collections
from pathlib import Path

def parse_srt(path):
    content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    out = []
    if not content:
        return out
    for block in re.split(r"\n\s*\n", content):
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        try:
            a, b = [p.strip() for p in lines[1].split("-->", 1)]
            def ms(t):
                hh, mm, rest = t.split(":")
                ss, mmm = rest.split(",")
                return ((int(hh)*60+int(mm))*60+int(ss))*1000 + int(mmm)
            text = " ".join(lines[2:]).strip()
            out.append((ms(a), ms(b), text))
        except Exception:
            continue
    return out

orig = parse_srt(sys.argv[1])
vi = parse_srt(sys.argv[2])
min_ratio = float(sys.argv[3])
max_s = float(sys.argv[4])
max_repeat_run = int(float(sys.argv[5]))
min_repeat_count = int(float(sys.argv[6]))
max_repeat_ratio = float(sys.argv[7])
min_repeat_chars = int(float(sys.argv[8]))

if not orig:
    print("VI_GATE_FAIL: original.srt không có cue")
    sys.exit(7)
if not vi:
    print("VI_GATE_FAIL: vietnamese.srt không có cue")
    sys.exit(7)

ratio = len(vi) / len(orig)
if ratio < min_ratio:
    print(f"VI_GATE_FAIL: cue count vi={len(vi)} orig={len(orig)} ratio={ratio:.3f} < {min_ratio:.2f}")
    sys.exit(7)

# Gate 2: cue quá dài (trừ khi cue gốc cùng ordinal cũng dài).
max_ms = int(max_s * 1000)
for i, (a, b, _text) in enumerate(vi):
    dur = b - a
    if dur <= max_ms:
        continue
    orig_dur = (orig[i][1] - orig[i][0]) if i < len(orig) else 0
    if orig_dur > max_ms:
        continue  # cue gốc cũng dài -> cho qua.
    print(f"VI_GATE_FAIL: vi cue #{i+1} dài {dur/1000:.2f}s > {max_s}s (orig cùng vị trí {orig_dur/1000:.2f}s)")
    sys.exit(7)

def norm_text(s):
    s = (s or "").lower()
    s = re.sub(r"[\\s\\W_]+", "", s, flags=re.UNICODE)
    return s

# Gate 3: bản dịch/TTS source không được bị kẹt một câu lặp hàng loạt.
# Đây bắt đúng lỗi ASR hallucination/dịch loop: "mai tôi ghé ăn cơm" lặp tới cuối phim.
texts = [norm_text(t) for _a, _b, t in vi]
texts = [t for t in texts if len(t) >= min_repeat_chars]
counts = collections.Counter(texts)
top_text, top_count = counts.most_common(1)[0] if counts else ("", 0)
top_ratio = top_count / max(1, len(vi))
max_run = 0
run = 0
last = None
for t in [norm_text(x[2]) for x in vi]:
    if len(t) < min_repeat_chars:
        if run > max_run:
            max_run = run
        last = None
        run = 0
        continue
    if t == last:
        run += 1
    else:
        if run > max_run:
            max_run = run
        last = t
        run = 1
if run > max_run:
    max_run = run
if max_run > max_repeat_run:
    print(f"VI_GATE_FAIL: repeated translation run={max_run}>{max_repeat_run} (một câu bị lặp liên tiếp)")
    sys.exit(8)
if top_count >= min_repeat_count and top_ratio > max_repeat_ratio:
    print(f"VI_GATE_FAIL: repeated translation top_count={top_count} ratio={top_ratio:.3f}>{max_repeat_ratio}")
    sys.exit(8)

print(f"VI_GATE_OK: vi={len(vi)} orig={len(orig)} ratio={ratio:.3f}")
sys.exit(0)
PY
vi_gate_status=$?
set -e
if [[ "$vi_gate_status" -eq 7 ]]; then
  echo "ERROR: vietnamese.srt bị gộp/vụn (cue count thấp hoặc cue quá dài, đứng im một dòng). Dừng job, không render." >&2
  rm -f "$VIETNAMESE_SRT" "$DUB_SRT"
  create_translate_pending "optimizer/vietnamese.srt bị gộp cue (count<80% hoặc cue>8s) - standing-still"
  status_update "manual_translate" "58" "Bản dịch bị gộp/vụn (standing-still), cần retry hoặc dán thủ công" "0" "ViSubtitlesMerged" "vietnamese.srt cue count thấp/cue quá dài do optimizer gộp group; bấm Chạy tiếp từ job cũ khi 9Router sẵn sàng, hoặc dán transcript_vi.json."
  fail "Bản dịch Việt bị gộp cue (đứng im một dòng). Retry khi 9Router sẵn sàng hoặc dán transcript_vi.json thủ công."
fi
if [[ "$vi_gate_status" -eq 8 ]]; then
  echo "ERROR: vietnamese.srt bị lặp một câu nhiều lần (dịch/ASR loop). Dừng job, không TTS/render." >&2
  rm -f "$VIETNAMESE_SRT" "$DUB_SRT"
  create_translate_pending "optimizer/vietnamese.srt bị lặp một câu nhiều lần - cần rebuild transcript hoặc retry dịch"
  status_update "manual_translate" "58" "Bản dịch bị lặp câu, cần retry/rebuild transcript" "0" "TranslationRepeatedLoop" "vietnamese.srt/dub.srt có một câu lặp nhiều lần; đây thường là ASR hallucination hoặc optimizer loop. Bấm Chạy lại video từ đầu để rebuild transcript, hoặc dán transcript_vi.json."
  exit 7
fi
[[ -s "$DUB_SRT" ]] || cp "$VIETNAMESE_SRT" "$DUB_SRT"
write_transcript_json "$VIETNAMESE_SRT" "$TRANSCRIPT_VI_JSON" "vietnamese"
[[ -s "$VIETNAMESE_SRT" ]] || fail "Không tạo được vietnamese.srt"
[[ -s "$TTS_SOURCE_SRT" ]] || fail "Không tạo được SRT nguồn để TTS"
# The selected dub.srt can differ from vietnamese.srt. Audit the exact per-cue
# TTS input here so a mixed CJK response can never reach voice generation.
if ! srt_looks_vietnamese "$TTS_SOURCE_SRT" "$ORIGINAL_SRT"; then
  echo "ERROR: SRT nguồn TTS không phải tiếng Việt. Dừng trước TTS/render." >&2
  create_translate_pending "pre-TTS/TTS_SOURCE_SRT chứa CJK, rỗng, hoặc trùng source"
  status_update "needs_attention" "58" "SRT nguồn TTS lỗi ngôn ngữ, cần dán bản dịch thủ công" "0" "TranslateNotVietnamese" "TTS_SOURCE_SRT chứa CJK/rỗng/trùng source; job đã dừng trước generate_vietnamese_voice."
  fail "SRT nguồn TTS không hợp lệ cho giọng Việt. Dán transcript_vi.json thủ công rồi resume."
fi
set +e
python3 "$TTS_VOICE_QUALITY_SCRIPT" text-gate --srt "$TTS_SOURCE_SRT" --report "$TTS_TEXT_QUALITY_REPORT_JSON"
tts_text_quality_status=$?
set -e
if [[ "$tts_text_quality_status" -ne 0 ]]; then
  create_translate_pending "pre-TTS text quality gate phát hiện câu lỗi; xem tts_text_quality_report.json"
  status_update "needs_attention" "58" "Văn bản tiếng Việt chưa đạt chất lượng đọc" "0" "VietnameseTextQualityFailed" "Phát hiện CJK, encoding lỗi, câu rỗng hoặc âm tiết lặp; xem tts_text_quality_report.json."
  fail "Văn bản nguồn TTS không đạt quality gate; dừng trước khi gọi TTS."
fi
status_update "optimizer" "65" "Dịch/tối ưu timing xong" "0"

# Dub timing quality gate: dub.srt phải bám từng cue, không có cue TTS quá dài.
# Bắt đúng bug dub.srt 30 cue max 28s (TTS đọc 1 đoạn dài -> giọng không bám timing).
# Fail khi: cue count quá thấp, HOẶC có cue >8s, HOẶC >20% cue dài >6s.
# Với ASR timing có rất nhiều cue ngắn 0.8-1.2s, optimizer được phép gộp nhẹ
# tối đa 2 cue nếu mỗi dub cue vẫn ngắn. Case đó có thể ratio ~0.65 nhưng vẫn
# an toàn hơn là bắt user dán transcript thủ công.
dub_timing_report="$OUT_DIR/dub_timing_quality_report.json"
dub_gate_min_ratio="${DUB_GATE_MIN_RATIO:-0.75}"
dub_gate_short_group_min_ratio="${DUB_GATE_SHORT_GROUP_MIN_RATIO:-0.65}"
dub_gate_short_group_max_cue_seconds="${DUB_GATE_SHORT_GROUP_MAX_CUE_SECONDS:-4.5}"
dub_gate_max_cue_seconds="${DUB_GATE_MAX_CUE_SECONDS:-8}"
dub_gate_long_cue_seconds="${DUB_GATE_LONG_CUE_SECONDS:-6}"
dub_gate_long_cue_ratio="${DUB_GATE_LONG_CUE_RATIO:-0.20}"
set +e
python3 - "$VIETNAMESE_SRT" "$DUB_SRT" "$dub_timing_report" "$dub_gate_min_ratio" "$dub_gate_short_group_min_ratio" "$dub_gate_short_group_max_cue_seconds" "$dub_gate_max_cue_seconds" "$dub_gate_long_cue_seconds" "$dub_gate_long_cue_ratio" <<'PY'
import json, re, sys
from pathlib import Path

def cues(path):
    content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    out = []
    if not content:
        return out
    for block in re.split(r"\n\s*\n", content):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        try:
            a, b = [p.strip() for p in lines[1].split("-->", 1)]
            def ms(t):
                hh, mm, rest = t.split(":")
                ss, mmm = rest.split(",")
                return ((int(hh)*60+int(mm))*60+int(ss))*1000 + int(mmm)
            out.append((ms(a), ms(b)))
        except Exception:
            continue
    return out

vi_srt, dub_srt, report_path = sys.argv[1:4]
min_ratio = float(sys.argv[4])
short_group_min_ratio = float(sys.argv[5])
short_group_max_cue_s = float(sys.argv[6])
max_cue_s = float(sys.argv[7])
long_cue_s = float(sys.argv[8])
long_cue_ratio = float(sys.argv[9])

vi = cues(vi_srt)
dub = cues(dub_srt)
dub_durs = [(e - s) / 1000.0 for (s, e) in dub]
dub_count = len(dub)
vi_count = len(vi)
ratio = dub_count / max(1, vi_count)
max_cue = max(dub_durs) if dub_durs else 0.0
overlong = sum(1 for d in dub_durs if d > max_cue_s)
long_cues = sum(1 for d in dub_durs if d > long_cue_s)
long_ratio = (long_cues / max(1, dub_count))
safe_short_group_relaxation = (
    ratio >= short_group_min_ratio
    and max_cue <= short_group_max_cue_s
    and overlong == 0
    and long_cues == 0
)

report = {
    "dub_cue_count": dub_count,
    "vi_cue_count": vi_count,
    "dub_vi_ratio": round(ratio, 3),
    "dub_max_cue_seconds": round(max_cue, 3),
    "dub_overlong_cues": overlong,
    "dub_long_cues": long_cues,
    "dub_long_cue_ratio": round(long_ratio, 3),
    "safe_short_group_relaxation": safe_short_group_relaxation,
    "gate_thresholds": {
        "min_ratio": min_ratio,
        "short_group_min_ratio": short_group_min_ratio,
        "short_group_max_cue_seconds": short_group_max_cue_s,
        "max_cue_seconds": max_cue_s,
        "long_cue_seconds": long_cue_s,
        "long_cue_ratio": long_cue_ratio,
    },
}
Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

fail_reasons = []
if ratio < min_ratio and not safe_short_group_relaxation:
    fail_reasons.append(f"dub_cue_ratio={ratio:.3f}<{min_ratio}")
if overlong > 0:
    fail_reasons.append(f"overlong_cues={overlong} (cue>{max_cue_s}s)")
if dub_count > 0 and long_ratio > long_cue_ratio:
    fail_reasons.append(f"long_cue_ratio={long_ratio:.3f}>{long_cue_ratio}")
if fail_reasons:
    print("DUB_GATE_FAIL: " + "; ".join(fail_reasons) + f" | dub={dub_count} vi={vi_count} max={max_cue:.2f}s")
    sys.exit(7)
suffix = " relaxed_short_group=1" if ratio < min_ratio and safe_short_group_relaxation else ""
print(f"DUB_GATE_OK: dub={dub_count} vi={vi_count} ratio={ratio:.3f} max={max_cue:.2f}s long={long_cues}{suffix}")
sys.exit(0)
PY
dub_gate_status=$?
set -e
if [[ "$dub_gate_status" -eq 7 ]]; then
  echo "ERROR: dub.srt bị gộp cue quá mạnh (cue quá dài, không bám timing). Dừng job, không TTS/render." >&2
  rm -f "$DUB_SRT"
  create_translate_pending "optimizer/dub.srt bị gộp cue quá mạnh (cue >8s hoặc count quá thấp không thuộc short-group an toàn) - voice không bám timing"
  status_update "needs_attention" "97" "Dub.srt gộp cue quá mạnh, cần retry/dán thủ công" "0" "DubTimingMerged" "dub.srt cue quá dài/quá ít (TTS không bám timing); bấm Chạy tiếp từ job cũ khi 9Router sẵn sàng, hoặc dán transcript_vi.json."
  echo "Output giữ lại tại: $OUT_DIR" >&2
  exit "$dub_gate_status"
fi

VIDEO_DURATION="$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$VIDEO" | tr -d '\r')"
echo "Đang tạo lồng tiếng tiếng Việt bằng TTS theo master timeline video gốc (${VIDEO_DURATION}s)..."
status_update "tts" "66" "Đang tạo giọng Việt bằng TTS" "0"
# Đặt đường dẫn report voice-sync ra job dir để dashboard đọc được cả khi gate fail.
export TRANSCRIPT_DECISION_JSON="$TRANSCRIPT_DECISION_JSON"
export VOICE_SYNC_REPORT_JSON="$OUT_DIR/voice_sync_quality_report.json"
# Inline rewrite câu TTS quá dài dùng cùng route dịch; Ollama không cần API key.
export DOUYIN_DUBBER_API_BASE="$API_BASE"
export DOUYIN_DUBBER_API_KEY="${DOUYIN_DUBBER_API_KEY:-$API_KEY}"
export DOUYIN_DUBBER_MODEL="$MODEL"
export DOUYIN_DUBBER_SEGMENTS_JSON="${DUBBING_SEGMENTS_JSON:-}"
export TTS_REWRITE_MAX_ATTEMPTS="${TTS_REWRITE_MAX_ATTEMPTS:-1}"
set +e
tts_total_timeout="${TTS_TOTAL_TIMEOUT_SECONDS:-3600}"
if [[ -n "$RESUME_JOB_DIR" ]] && tts_resume_cache_is_complete \
  "$TTS_SOURCE_SRT" "$VIETNAMESE_VOICE_WAV" "$TTS_STATS_JSON" "$TMP_DIR/tts_checkpoint.json" "$VOICE"; then
  echo "Dùng cached vietnamese_voice.wav/tts_stats.json hợp lệ."
  tts_synth_status=0
else
  run_with_status_heartbeat_guarded "tts" "66" "Đang tạo giọng Việt bằng TTS" "$tts_total_timeout" "${OPENCLAW_LONG_STEP_HEARTBEAT_SECONDS:-30}" \
    generate_vietnamese_voice "$TTS_SOURCE_SRT" "$VIETNAMESE_VOICE_WAV" "$VOICE" "$TMP_DIR" "$VIDEO_DURATION"
  tts_synth_status=$?
fi
set -e
# Copy reports ra OUT_DIR trước khi handle exit 9 (để dashboard/Telegram có thông tin).
cp "$TMP_DIR/resona_probe_report.json" "$OUT_DIR/resona_probe_report.json" 2>/dev/null || true
cp "$TMP_DIR/voice_sync_quality_report.json" "$OUT_DIR/voice_sync_quality_report.json" 2>/dev/null || true
cp "$TTS_STATS_JSON" "$OUT_DIR/tts_stats.json" 2>/dev/null || true
if [[ "$tts_synth_status" -eq 9 ]]; then
  # Probe fail: Resona không dùng được với bất kỳ voice nào (primary + fallback).
  probe_err_code=""
  probe_err_msg=""
  if [[ -f "$OUT_DIR/voice_sync_quality_report.json" ]]; then
    probe_err_code="$(python3 -c "import json; d=json.load(open('$OUT_DIR/voice_sync_quality_report.json')); print(d.get('error_code') or '')" 2>/dev/null || echo '')"
  fi
  [[ -z "$probe_err_code" || "$probe_err_code" == "None" ]] && probe_err_code="ResonaProbeFail"
  case "$probe_err_code" in
    ResonaAuthMissing) probe_err_msg="Thiếu token Resona (probe). Thiết lập env rồi chạy lại." ;;
    ResonaAuthFailed) probe_err_msg="Token Resona không hợp lệ/hết hạn (probe)." ;;
    ResonaQuotaFailed) probe_err_msg="Resona hết credit/rate-limit (probe)." ;;
    ResonaTimeout) probe_err_msg="Resona probe timeout." ;;
    ResonaNoAudioUrl) probe_err_msg="Resona probe: voice không sinh audio (NoAudioUrl). Thử voice khác hoặc đặt RESONA_FALLBACK_VOICE_IDS." ;;
    *) probe_err_msg="Resona probe fail: $probe_err_code" ;;
  esac
  echo "ERROR: Resona pre-TTS probe fail ($probe_err_code). Không chạy full TTS, không render. $probe_err_msg" >&2
  status_update "error" "66" "Resona probe fail: $probe_err_code" "0" "$probe_err_code" "$probe_err_msg Xem resona_probe_report.json / voice_sync_quality_report.json / resona_tts_debug/probe/."
  fail "Resona pre-TTS probe fail ($probe_err_code). $probe_err_msg"
elif [[ "$tts_synth_status" -ne 0 ]]; then
  tts_early_err_code=""
  tts_early_err_msg=""
  if [[ -f "$OUT_DIR/voice_sync_quality_report.json" ]]; then
    tts_early_err_code="$(python3 - "$OUT_DIR/voice_sync_quality_report.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    data = {}
print(data.get("error_code") or "")
PY
)"
    tts_early_err_msg="$(python3 - "$OUT_DIR/voice_sync_quality_report.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    data = {}
print((data.get("error_message") or "; ".join(data.get("fail_reasons") or []))[:500])
PY
)"
  fi
  [[ -z "$tts_early_err_code" || "$tts_early_err_code" == "None" ]] && tts_early_err_code="TTSGenerationFailed"
  [[ -z "$tts_early_err_msg" || "$tts_early_err_msg" == "None" ]] && tts_early_err_msg="TTS synthesis lỗi sớm (exit=$tts_synth_status). Xem log và voice_sync_quality_report.json."
  tts_early_state="needs_attention"
  case "$tts_early_err_code" in
    AI33CircuitOpen|AI33*RateLimited|AI33*Http5xx|AI33*Timeout|AI33*Network) tts_early_state="waiting_provider" ;;
  esac
  case "$tts_early_err_code" in
    VoiceInvalid) tts_early_err_hint="Voice ID không hợp lệ hoặc chưa nằm trong registry; kiểm tra Voice Manager." ;;
    AI33AuthMissing|AI33AuthFailed) tts_early_err_hint="Kiểm tra AI33_API_KEY/AI33_ACCESS_TOKEN." ;;
    AI33QuotaFailed) tts_early_err_hint="Kiểm tra credit/rate-limit AI33." ;;
    AI33CircuitOpen) tts_early_err_hint="AI33 đang cooldown sau lỗi provider; giữ checkpoint và chạy lại sau AI33_CIRCUIT_COOLDOWN_SECONDS." ;;
    AI33Timeout) tts_early_err_hint="AI33 timeout; thử lại hoặc tăng AI33_TIMEOUT_SECONDS." ;;
    AI33NoAudioUrl) tts_early_err_hint="AI33 không trả audio cho voice/text này; thử Test giọng hoặc voice khác." ;;
    TTSFfmpegFailed) tts_early_err_hint="ffmpeg lỗi khi tạo/concat TTS segment." ;;
    TTSDependencyMissing) tts_early_err_hint="Thiếu dependency TTS/ffmpeg/wrapper." ;;
    *) tts_early_err_hint="Xem voice_sync_quality_report.json / tts_stats.json / log.txt." ;;
  esac
  echo "ERROR: TTS synthesis fail ($tts_early_err_code, exit=$tts_synth_status). $tts_early_err_msg $tts_early_err_hint" >&2
  # Legacy static-contract shape: status_update "error" "66" "TTS synthesis fail: $tts_early_err_code"
  status_update "$tts_early_state" "66" "TTS synthesis fail: $tts_early_err_code" "0" "$tts_early_err_code" "$tts_early_err_msg $tts_early_err_hint"
  echo "Output giữ lại tại: $OUT_DIR" >&2
  exit "$tts_synth_status"
fi
[[ -s "$VIETNAMESE_VOICE_WAV" ]] || fail "Không tạo được vietnamese_voice.wav"

tts_qa_status=0
if [[ "$TTS_VOICE_QA_ENABLED" == "1" ]]; then
  echo "Đang kiểm tra phát âm TTS bằng Whisper..."
  status_update "tts_qa" "76" "Đang kiểm tra phát âm giọng Việt" "0"
  set +e
  run_tts_voice_qa
  tts_qa_status=$?
  set -e
  if [[ "$tts_qa_status" -eq 8 ]]; then
    tts_qa_failed_cues="$(python3 - "$TTS_VOICE_QUALITY_REPORT_JSON" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    data = {}
print(",".join(str(value) for value in data.get("critical_cue_ids") or []))
PY
)"
    set +e
    python3 - "$TTS_STATS_JSON" >/dev/null <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    data = {}
raise SystemExit(0 if int(data.get("ai33_segments") or 0) > 0 else 1)
PY
    tts_qa_ai33=$?
    set -e
    if [[ -n "$tts_qa_failed_cues" && "$tts_qa_ai33" -eq 0 && "$TTS_VOICE_QA_RETRY_MAX" -ge 1 ]]; then
      tts_qa_overrides="$TMP_DIR/tts_spoken_text_overrides.json"
      python3 "$TTS_VOICE_QUALITY_SCRIPT" retry-overrides --report "$TTS_VOICE_QUALITY_REPORT_JSON" --output "$tts_qa_overrides"
      echo "Retry AI33 cho cue phát âm lỗi: $tts_qa_failed_cues"
      set +e
      TTS_FORCE_CUE_IDS="$tts_qa_failed_cues" \
      TTS_SPOKEN_TEXT_OVERRIDES_JSON="$tts_qa_overrides" \
      run_with_status_heartbeat_guarded "tts_qa_retry" "77" "Đang tạo lại cue phát âm lỗi" "$tts_total_timeout" "${OPENCLAW_LONG_STEP_HEARTBEAT_SECONDS:-30}" \
        generate_vietnamese_voice "$TTS_SOURCE_SRT" "$VIETNAMESE_VOICE_WAV" "$VOICE" "$TMP_DIR" "$VIDEO_DURATION"
      tts_qa_retry_status=$?
      set -e
      cp "$TTS_STATS_JSON" "$OUT_DIR/tts_stats.json" 2>/dev/null || true
      if [[ "$tts_qa_retry_status" -ne 0 ]]; then
        status_update "needs_attention" "77" "Tạo lại cue phát âm lỗi thất bại" "0" "TTSPronunciationRetryFailed" "AI33 retry cue=$tts_qa_failed_cues exit=$tts_qa_retry_status; checkpoint cue đạt vẫn được giữ."
        exit "$tts_qa_retry_status"
      fi
      set +e
      run_tts_voice_qa "$tts_qa_failed_cues"
      tts_qa_status=$?
      set -e
    fi
  fi
  if [[ "$tts_qa_status" -ne 0 ]]; then
    status_update "needs_attention" "78" "Giọng Việt không đạt kiểm tra phát âm" "0" "TTSPronunciationQualityFailed" "Whisper QA exit=$tts_qa_status; xem tts_voice_quality_report.json. Pipeline dừng trước render."
    exit 8
  fi
fi
status_update "tts" "78" "Tạo giọng Việt xong" "0"

VOICE_DURATION_RAW="$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$VIETNAMESE_VOICE_WAV" | tr -d '\r')"
if [[ -f "$TTS_STATS_JSON" ]]; then
  set +e
  python3 - "$TTS_STATS_JSON" "$VIDEO_DURATION" "$VOICE_DURATION_RAW" "$ORIGINAL_SRT" "$VOICE" <<'PY'
import json, os, re, sys
from pathlib import Path
sys.path.insert(0, os.environ.get('DOUYIN_DUBBER_SKILL_DIR', ''))
from voice_sync_overhang import summarize_unresolved_overhang
stats_path, video_duration, voice_duration, original_srt, voice = sys.argv[1:6]
stats = json.load(open(stats_path, 'r', encoding='utf-8'))
from voice_sync_status import normalize_resona_grouped_source_cue_ids
serialized_resona_grouped_source_cue_ids = normalize_resona_grouped_source_cue_ids(stats)
RESONA_ERROR_SEVERITY = [
    'ResonaAuthMissing', 'ResonaAuthFailed', 'ResonaQuotaFailed',
    'ResonaTimeout', 'ResonaNoAudioUrl', 'ResonaTextTooShortUngroupable',
    'ResonaTextTooShort', 'ResonaCoverageTooLow', 'TTSResonaFailed',
]
AI33_ERROR_SEVERITY = [
    'AI33AuthMissing', 'AI33AuthFailed', 'AI33QuotaFailed',
    'AI33Timeout', 'AI33NoAudioUrl', 'TTSAI33Failed',
]
print(f"TTS target video duration: {float(video_duration):.3f}s")
print(f"TTS raw/generated voice duration: {float(voice_duration):.3f}s")
print(f"TTS raw segment total: {stats.get('raw_tts_ms', 0)/1000:.3f}s")
print(f"TTS adjusted segment end: {stats.get('adjusted_tts_ms', 0)/1000:.3f}s")
print(f"TTS final voice duration: {stats.get('final_voice_ms', 0)/1000:.3f}s")
if stats.get('subtitle_only_all'):
    print('TTS subtitle-only all: không có đoạn lồng tiếng, chỉ giữ phụ đề + nhạc nền gốc')
print(f"TTS speed-up segments: {stats.get('speedup_segments', 0)}")
print(f"TTS over max-speed segments: {stats.get('tts_over_max_speed_segments', 0)}")
print(f"TTS clipped-to-slot segments: {stats.get('tts_clipped_to_slot_segments', 0)}")
print(f"TTS padded segments: {stats.get('padded_segments', 0)}")
print(f"TTS final tail silence: {stats.get('final_tail_silence_ms', 0)/1000:.3f}s")
print(f"TTS retry segments: {stats.get('tts_retry_segments', 0)}")
print(f"TTS silence fallback segments: {stats.get('tts_silence_fallback_segments', 0)}")
print(f"TTS circuit-breaker segments: {stats.get('tts_circuit_breaker_segments', 0)}")
print(f"TTS per-segment timeout: {stats.get('tts_timeout_seconds', 'unknown')}s")
# TTS quality gate: nếu gần như toàn segment rơi vào silence fallback (không có giọng thật),
# pipeline không được coi output thành công. non_silence = tổng - silence - circuit_breaker.
total = stats.get('entries', 0) or 0
silence = stats.get('tts_silence_fallback_segments', 0) or 0
cb = stats.get('tts_circuit_breaker_segments', 0) or 0
capcut = stats.get('capcut_segments', 0) or 0
capcut_fb = stats.get('capcut_fallback_edge_segments', 0) or 0
capcut_fail = stats.get('capcut_failed_segments', 0) or 0
kokoro = stats.get('kokoro_segments', 0) or 0
ai33 = stats.get('ai33_segments', 0) or 0
ai33_fail = stats.get('ai33_failed_segments', 0) or 0
ai33_fail_codes = stats.get('ai33_fail_error_codes') or []
resona = stats.get('resona_segments', 0) or 0
resona_fail = stats.get('resona_failed_segments', 0) or 0
resona_short = stats.get('resona_short_text_segments', 0) or 0
resona_short_fb = stats.get('resona_short_edge_fallback_segments', 0) or 0
resona_fail_codes = stats.get('resona_fail_error_codes') or []
source_total = stats.get('source_entries', total) or total
resona_grouped_units = stats.get('resona_short_grouped_units', 0) or 0
resona_grouped_source_segments = stats.get('resona_short_grouped_source_segments', 0) or 0
non_silence = max(0, total - silence)
# Cho phép capcut/resona hoặc edge_fallback tính như giọng thật.
real_voice = non_silence - cb  # circuit breaker cũng là fail
# AI33 fail gate: bất kỳ segment AI33 nào fail API thật (auth/quota/timeout/no-audio)
# -> dừng job với error_code cụ thể. KHÔNG render/organize output lỗi.
if ai33_fail > 0 and ai33_fail_codes:
    chosen = next((c for c in AI33_ERROR_SEVERITY if c in ai33_fail_codes), ai33_fail_codes[0])
    print(f"TTS_GATE_FAIL: ai33_failed={ai33_fail}/{total} codes={ai33_fail_codes} -> {chosen}")
    try:
        Path(os.environ.get('VOICE_SYNC_REPORT_JSON') or '').write_text(
            json.dumps({
                "status": "fail",
                "error_code": chosen,
                "tts_entries": total,
                "ai33_segments": ai33,
                "ai33_failed_segments": ai33_fail,
                "ai33_fail_error_codes": ai33_fail_codes,
                "ai33_voice_used": stats.get('ai33_voice_used', '') or '',
                "voice_source": stats.get('voice_source', '') or '',
                "voice_label": stats.get('voice_label', '') or '',
                "voice_id": stats.get('voice_id', '') or stats.get('ai33_voice_used', '') or '',
                "canonical_voice": stats.get('canonical_voice', '') or (f"ai33:{stats.get('ai33_voice_used', '')}" if stats.get('ai33_voice_used') else ''),
                "timing_profile": stats.get('timing_profile', '') or '',
                "min_slow_ratio": stats.get('min_slow_ratio', '') or stats.get("slow_fit_min_ratio", 1.0) or 1.0,
                "tts_engine_requested": stats.get('tts_engine_requested', ''),
                "tts_engine_used": stats.get('tts_engine_used', ''),
                "tts_engines_used": stats.get('tts_engines_used') or [],
                "padded_segments": stats.get('padded_segments', 0) or 0,
                "speech_padding_ms": stats.get('speech_padding_ms', 0) or 0,
                "final_tail_silence_ms": stats.get('final_tail_silence_ms', 0) or 0,
                "final_low_ratio_segments": stats.get('final_low_ratio_segments', 0) or 0,
                "fail_reasons": [f"ai33_failed={ai33_fail}/{total} codes={ai33_fail_codes}"],
            }, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    print(f"AI33_GATE_FAIL: {chosen}")
    sys.exit(7)
# Resona fail gate: bất kỳ segment Resona nào fail API thật (auth/quota/timeout/no-audio)
# -> dừng job với error_code cụ thể. KHÔNG fallback Edge, KHÔNG render/organize.
if resona_fail > 0 and resona_fail_codes:
    # Chọn error_code đại diện có severity cao nhất.
    chosen = next((c for c in RESONA_ERROR_SEVERITY if c in resona_fail_codes), resona_fail_codes[0])
    print(f"TTS_GATE_FAIL: resona_failed={resona_fail}/{total} codes={resona_fail_codes} -> {chosen}")
    # Ghi status + exit 7 (TTS_GATE). Bash wrapper sẽ map exit 7 -> TTSAllSilence hoặc code riêng.
    # Truyền error_code qua env/file để bash wrapper đọc.
    try:
        Path(os.environ.get('VOICE_SYNC_REPORT_JSON') or '').write_text(
            json.dumps({
                "status": "fail",
                "error_code": chosen,
                "resona_failed_segments": resona_fail,
                "resona_fail_error_codes": resona_fail_codes,
                "fail_reasons": [f"resona_failed={resona_fail}/{total} codes={resona_fail_codes}"],
            }, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    # In marker cho bash wrapper bắt (Resona-specific error_code).
    print(f"RESONA_GATE_FAIL: {chosen}")
    sys.exit(7)
# Resona coverage gate: khi Resona là engine chính (requested=resona) nhưng phần lớn segment
# bị bypass/fallback (short_text_ungroupable hoặc edge fallback), pipeline không được coi OK.
# Fail rõ ResonaCoverageTooLow thay vì VoiceSyncFail (đây là lỗi TTS, không phải drift).
resona_requested = (voice or '').lower().startswith('resona')
resona_coverage_ratio = 0.0
if resona_requested and total > 0:
    resona_coverage_ratio = resona / total
    resona_bypassed = resona_short + resona_short_fb
    min_resona_coverage = float(os.environ.get("RESONA_GATE_MIN_COVERAGE", "0.85"))
    if resona_coverage_ratio < min_resona_coverage:
        chosen = "ResonaCoverageTooLow"
        print(f"TTS_GATE_FAIL: resona_coverage={resona_coverage_ratio:.3f}<{min_resona_coverage} resona={resona}/{total} bypassed={resona_bypassed} short_fb={resona_short_fb} -> {chosen}")
        try:
            Path(os.environ.get('VOICE_SYNC_REPORT_JSON') or '').write_text(
                json.dumps({
                    "status": "fail",
                    "error_code": chosen,
                    "resona_segments": resona,
                    "tts_entries": total,
                    "resona_coverage_ratio": round(resona_coverage_ratio, 4),
                    "resona_bypassed_short_segments": resona_bypassed,
                    "resona_short_edge_fallback_segments": resona_short_fb,
                    "fail_reasons": [f"resona_coverage={resona_coverage_ratio:.3f}<{min_resona_coverage} resona={resona}/{total}"],
                }, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        print(f"RESONA_GATE_FAIL: {chosen}")
        sys.exit(7)
# Generic all-silence is deliberately last among provider gates: provider
# failures above must retain their actionable error_code instead of TTSAllSilence.
if total > 0 and real_voice <= 0 and (kokoro + ai33 + capcut + capcut_fb + resona + resona_short_fb) == 0:
    print(f"TTS_GATE_FAIL: total={total} silence={silence} circuit_breaker={cb} kokoro={kokoro} ai33={ai33} capcut={capcut} capcut_fallback={capcut_fb} resona={resona} resona_short_fb={resona_short_fb} -> no real voice")
    sys.exit(7)
# TTS coverage gate: giọng thật quá ít so với video (case raw 32s/339s + chỉ 11 entries).
min_raw_coverage = float(os.environ.get("TTS_GATE_MIN_RAW_COVERAGE", "0.25"))
min_entries_ratio = float(os.environ.get("TTS_GATE_MIN_ENTRIES_RATIO", "0.5"))
video_ms = float(video_duration) * 1000
sync_mode = (os.environ.get("SYNC_MODE", "balanced_dub") or "balanced_dub").strip().lower()
sync_policy = (os.environ.get("TTS_SYNC_POLICY", "bounded") or "bounded").strip().lower()
frame_strict = (sync_policy == "frame_strict")
frame_strict_max_segment_drift = max(0, int(float(os.environ.get("FRAME_STRICT_MAX_SEGMENT_DRIFT_MS", "80"))))
frame_strict_base_total_drift = max(0, int(float(os.environ.get("FRAME_STRICT_MAX_TOTAL_DRIFT_MS", "200"))))
frame_strict_total_drift_per_segment = max(0, int(float(os.environ.get("FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS", "5"))))
frame_strict_max_total_drift = max(frame_strict_base_total_drift, total * frame_strict_total_drift_per_segment)
raw_ratio = (stats.get('raw_tts_ms', 0) or 0) / video_ms if video_ms > 0 else 1.0
# Đếm cue transcript gốc để so sánh tỷ lệ entries.
tx_cues = 0
try:
    content = Path(original_srt).read_text(encoding="utf-8", errors="replace").strip()
    if content:
        tx_cues = sum(1 for blk in re.split(r"\n\s*\n", content) if blk.strip())
except Exception:
    pass
entries_ratio = (total / tx_cues) if tx_cues > 0 else 1.0
if video_ms > 0 and raw_ratio < min_raw_coverage and entries_ratio < min_entries_ratio:
    print(f"TTS_GATE_FAIL: raw_ratio={raw_ratio:.3f}<{min_raw_coverage} entries={total}/tx={tx_cues} ratio={entries_ratio:.3f}<{min_entries_ratio} (giọng thật quá ít)")
    sys.exit(7)
# Voice-sync local gate. In balanced/quality, ordinary natural short pauses are
# reported without forcing unnatural speed-up.  Severe, broad under-fill is not a
# pause: it indicates a bad timing master or unusable dub alignment and must stop
# before render/organize in every mode.
raw_ratios = sorted(stats.get('raw_slot_ratios') or [])
ratios = sorted(stats.get('final_slot_ratios') or stats.get('raw_slot_ratios') or [])
median_raw_ratio = 0.0
if raw_ratios:
    mid = len(raw_ratios) // 2
    median_raw_ratio = raw_ratios[mid] if len(raw_ratios) % 2 == 1 else (raw_ratios[mid - 1] + raw_ratios[mid]) / 2.0
median_ratio = 0.0
if ratios:
    mid = len(ratios) // 2
    median_ratio = ratios[mid] if len(ratios) % 2 == 1 else (ratios[mid - 1] + ratios[mid]) / 2.0
median_ratio_metric = "median_final_fill_ratio" if stats.get('final_slot_ratios') else "median_raw_fill_ratio"
padded_segments = stats.get('padded_segments', 0) or 0
synthetic_padding_ms = stats.get('synthetic_padding_ms')
if synthetic_padding_ms is None:
    synthetic_padding_ms = stats.get('speech_padding_ms')
if synthetic_padding_ms is None:
    synthetic_padding_ms = stats.get('padding_total_ms', 0)
synthetic_padding_ms = synthetic_padding_ms or 0
padding_total_ms = synthetic_padding_ms  # compatibility alias: never includes source gaps/tail
proven_synthetic_padding_ms = stats.get('proven_synthetic_padding_ms', 0) or 0
proven_synthetic_padding_evidence_backends = stats.get('proven_synthetic_padding_evidence_backends') or []
source_gap_ms = stats.get('source_gap_ms', 0) or 0
longest_consecutive_padding_ms = stats.get('longest_consecutive_synthetic_padding_ms', 0) or 0
longest_proven_padding_ms = stats.get('longest_proven_synthetic_padding_ms', 0) or 0
longest_unproven_padding_ms = stats.get('longest_unproven_synthetic_padding_ms', 0) or 0
padded_ratio = (padded_segments / total) if total > 0 else 0.0
padding_video_ratio = (synthetic_padding_ms / video_ms) if video_ms > 0 else 0.0
proven_padding_video_ratio = (proven_synthetic_padding_ms / video_ms) if video_ms > 0 else 0.0
raw_low_ratio_segs = stats.get('low_ratio_segments', 0) or 0
low_ratio_segs = stats.get('final_low_ratio_segments')
if low_ratio_segs is None:
    low_ratio_segs = raw_low_ratio_segs
low_ratio_segs = low_ratio_segs or 0
low_ratio_frac = (low_ratio_segs / total) if total > 0 else 0.0
max_padded_ratio = float(os.environ.get("TTS_LOCAL_SYNC_MAX_PADDED_RATIO", "0.4"))
max_padding_video = float(os.environ.get("TTS_LOCAL_SYNC_MAX_PADDING_VIDEO", "0.15"))
min_median_ratio = float(os.environ.get("TTS_LOCAL_SYNC_MIN_MEDIAN_RATIO", "0.75"))
max_low_ratio = float(os.environ.get("TTS_LOCAL_SYNC_MAX_LOW_RATIO", "0.4"))
fail_on_padded_ratio = (os.environ.get("TTS_LOCAL_SYNC_FAIL_ON_PADDED_RATIO", "0") or "0").strip().lower() in ("1", "true", "yes", "on")
strict_quality_gate = (os.environ.get("STRICT_QUALITY_GATE", "0") or "0").strip().lower() in ("1", "true", "yes", "on")
relaxed_short_audio_mode = sync_mode in ("balanced_dub", "quality_dub")
padding_warn_ratio = float(os.environ.get("VOICE_SYNC_PADDING_WARN_RATIO", "0.20"))
# 30% of the full video filled by synthetic cue-tail silence plus a low median
# fill is a timing-master failure, not natural pacing.  This still leaves normal
# pauses and isolated short cues on the warning path.
padding_fail_ratio = float(os.environ.get("VOICE_SYNC_PADDING_FAIL_RATIO", "0.30"))
min_median_fill_ratio = float(os.environ.get("VOICE_SYNC_MIN_MEDIAN_FILL_RATIO", "0.55"))
long_padding_warn_ms = max(0, int(float(os.environ.get("VOICE_SYNC_LONG_PADDING_WARN_MS", "1500"))))
long_padding_fail_ms = max(0, int(float(os.environ.get("VOICE_SYNC_LONG_PADDING_FAIL_MS", "2500"))))
sync_fail_reasons = []
sync_warning_reasons = []
needs_attention_reasons = []
def add_sync_quality_issue(reason):
    if frame_strict:
        sync_warning_reasons.append(reason)
        print(f"WARN frame_strict: {reason} (reported, not failing)")
    else:
        sync_fail_reasons.append(reason)
if relaxed_short_audio_mode:
    # Do not promote OCR/display holds or ordinary natural pauses into failure.
    # Broad under-fill is hard evidence only where an allowlisted speech-aware
    # backend proves synthetic padding overlaps source speech; unknown, missing,
    # energy-VAD, and ASR evidence never contribute to this ratio.
    if padded_ratio > max_padded_ratio:
        sync_warning_reasons.append(f"padded_ratio={padded_ratio:.3f}>{max_padded_ratio} (reported_only)")
    if padding_video_ratio > padding_warn_ratio:
        sync_warning_reasons.append(f"synthetic_padding_video={padding_video_ratio:.3f}>{padding_warn_ratio}")
    if total > 0 and median_ratio < min_median_fill_ratio:
        sync_warning_reasons.append(f"{median_ratio_metric}={median_ratio:.3f}<{min_median_fill_ratio}")
    if longest_consecutive_padding_ms > long_padding_warn_ms:
        sync_warning_reasons.append(f"longest_synthetic_padding={longest_consecutive_padding_ms}ms>{long_padding_warn_ms}")
    low_fill_after_restore = stats.get('low_fill_after_restore_segments', 0) or 0
    if low_fill_after_restore:
        needs_attention_reasons.append(f"LOW_FILL_AFTER_RESTORE={low_fill_after_restore}>0")
    combined_short_audio_failure = (
        proven_padding_video_ratio > padding_fail_ratio
        and total > 0 and median_ratio < min_median_fill_ratio
    )
    if combined_short_audio_failure:
        reason = (f"combined_short_audio proven_synthetic_padding_video={proven_padding_video_ratio:.3f}>{padding_fail_ratio} "
                  f"and {median_ratio_metric}={median_ratio:.3f}<{min_median_fill_ratio}")
        sync_fail_reasons.append(reason)
    if longest_proven_padding_ms > long_padding_fail_ms:
        reason = f"longest_proven_synthetic_padding={longest_proven_padding_ms}ms>{long_padding_fail_ms}"
        # A multi-second synthetic silence inside positive source VAD evidence is
        # a broken speech interval, not an ordinary natural pause.
        sync_fail_reasons.append(reason)
    elif longest_consecutive_padding_ms > long_padding_fail_ms:
        reason = f"unproven_long_synthetic_padding={longest_consecutive_padding_ms}ms>{long_padding_fail_ms}"
        sync_warning_reasons.append(reason)
        needs_attention_reasons.append(reason)
else:
    # strict_timeline and aggressive_legacy: preserve pre-existing behavior.
    if padded_ratio > max_padded_ratio:
        reason = f"padded_ratio={padded_ratio:.3f}>{max_padded_ratio}"
        if fail_on_padded_ratio:
            add_sync_quality_issue(reason)
        else:
            sync_warning_reasons.append(reason + " (warn_only)")
            print(f"WARN: {reason} (warning only; gate dùng padding_video/median/low_ratio để fail)")
    if padding_video_ratio > max_padding_video:
        add_sync_quality_issue(f"padding_video={padding_video_ratio:.3f}>{max_padding_video}")
    if total > 0 and median_ratio < min_median_ratio:
        add_sync_quality_issue(f"{median_ratio_metric}={median_ratio:.3f}<{min_median_ratio}")
    if total > 0 and low_ratio_frac > max_low_ratio:
        add_sync_quality_issue(f"low_ratio_segs={low_ratio_frac:.3f}>{max_low_ratio}")

# Voice-sync too-long gate: bắt TTS quá dài so với slot -> audio tràn sang slot kế -> drift
# tích lũy (case Douyin: 80 over-max-speed, 77 kept too-long, 97 overhang, 123/163 start late,
# median drift ~2.1s max ~9.8s, voice 319.7s trim về 297.1s). Fail khi một trong:
#   - too_long_not_clipped_segments > 0 (bất kỳ segment nào vẫn quá slot sau speed-fit+rewrite)
#   - over_max_speed_segments/entries > TTS_LOCAL_SYNC_MAX_OVER_SPEED_RATIO (0.20)
#   - max_start_drift_ms > 500
#   - median_start_drift_ms > 150
#   - trimmed_ms > 500 (voice dài hơn video > 500ms -> bash trim sẽ cắt đuôi)
drift_list = sorted([int(x) for x in (stats.get('start_drift_ms_list') or [])])
median_drift = 0.0
max_drift = 0
p90_drift = 0
if drift_list:
    max_drift = drift_list[-1]
    mid = len(drift_list) // 2
    median_drift = float(drift_list[mid] if len(drift_list) % 2 == 1 else (drift_list[mid - 1] + drift_list[mid]) / 2.0)
    p90_drift = drift_list[min(len(drift_list) - 1, int(0.9 * len(drift_list)))]
too_long_not_clipped = stats.get('tts_too_long_not_clipped_segments', 0) or 0
over_max_speed = stats.get('tts_over_max_speed_segments', 0) or 0
overhang_segs = stats.get('tts_overhang_segments', 0) or 0
rewritten_segs = stats.get('rewritten_segments', 0) or 0
rewrite_failed_segs = stats.get('rewrite_failed_segments', 0) or 0
adapt_needs_attention = stats.get('adapt_needs_attention_segments', 0) or 0
too_long_ratio = (too_long_not_clipped / total) if total > 0 else 0.0
over_max_ratio = (over_max_speed / total) if total > 0 else 0.0
max_too_long_ratio = float(os.environ.get("TTS_LOCAL_SYNC_MAX_TOO_LONG_RATIO", "0.10"))
max_over_max_ratio = float(os.environ.get("TTS_LOCAL_SYNC_MAX_OVER_SPEED_RATIO", "0.20"))
max_start_drift_threshold = float(os.environ.get("TTS_LOCAL_SYNC_MAX_START_DRIFT_MS", "500"))
median_start_drift_threshold = float(os.environ.get("TTS_LOCAL_SYNC_MEDIAN_START_DRIFT_MS", "150"))
max_trimmed_threshold = float(os.environ.get("TTS_LOCAL_SYNC_MAX_TRIMMED_MS", "500"))
unresolved_overhang = summarize_unresolved_overhang(
    stats.get('unresolved_contiguous_overhang_events') or [],
    os.environ.get('VOICE_SYNC_MAX_UNRESOLVED_CONTIGUOUS_OVERHANG_MS', '120'),
)
final_voice_ms = stats.get('final_voice_ms', 0) or 0
target_video_ms_report = stats.get('target_video_ms', 0) or 0
trimmed_ms = stats.get('trimmed_ms', 0) or 0
# A candidate that cannot be safely adapted is never hidden. balanced/quality keeps
# its natural speech plus an explicit needs-attention report; strict can stop it.
if adapt_needs_attention:
    reason = f"adapt_needs_attention={adapt_needs_attention}>0"
    if frame_strict:
        sync_warning_reasons.append(reason)
    elif relaxed_short_audio_mode and not strict_quality_gate:
        needs_attention_reasons.append(reason)
    else:
        sync_fail_reasons.append(reason)
if unresolved_overhang['failed']:
    sync_fail_reasons.append(
        f"unresolved_contiguous_overhang_max={unresolved_overhang['max_ms']}ms>"
        f"{unresolved_overhang['threshold_ms']}ms"
    )
# frame_strict metrics: drift slot thật sau fit.
final_drift_list = sorted([int(x) for x in (stats.get('final_segment_drift_ms_list') or [])])
max_final_drift = final_drift_list[-1] if final_drift_list else 0
total_final_drift = int(stats.get('total_final_drift_ms', 0) or 0)
if frame_strict:
    # frame_strict: các gate cũ -> warning only (vẫn report, không fail). Chỉ fail khi
    # final audio lệch slot quá tolerance.
    if too_long_not_clipped > 0:
        sync_warning_reasons.append(f"too_long_not_clipped={too_long_not_clipped}>0")
        print(f"WARN frame_strict: too_long_not_clipped={too_long_not_clipped} (reported, not failing)")
    if total > 0 and over_max_ratio > max_over_max_ratio:
        sync_warning_reasons.append(f"over_max_speed_ratio={over_max_ratio:.3f}>{max_over_max_ratio}")
        print(f"WARN frame_strict: over_max_speed_ratio={over_max_ratio:.3f}>{max_over_max_ratio} (reported, not failing)")
    if max_drift > max_start_drift_threshold:
        sync_warning_reasons.append(f"max_start_drift={max_drift}ms>{int(max_start_drift_threshold)}")
        print(f"WARN frame_strict: max_start_drift={max_drift}ms>{int(max_start_drift_threshold)} (reported, not failing)")
    if drift_list and median_drift > median_start_drift_threshold:
        sync_warning_reasons.append(f"median_start_drift={median_drift:.0f}ms>{int(median_start_drift_threshold)}")
        print(f"WARN frame_strict: median_start_drift={median_drift:.0f}ms>{int(median_start_drift_threshold)} (reported, not failing)")
    if trimmed_ms > max_trimmed_threshold:
        sync_warning_reasons.append(f"voice_longer_than_video={trimmed_ms}ms>{int(max_trimmed_threshold)}")
        print(f"WARN frame_strict: voice_longer_than_video={trimmed_ms}ms>{int(max_trimmed_threshold)} (reported, not failing)")
    if max_final_drift > frame_strict_max_segment_drift:
        sync_fail_reasons.append(f"frame_strict_max_segment_drift={max_final_drift}ms>{frame_strict_max_segment_drift}")
    if total_final_drift > frame_strict_max_total_drift:
        sync_fail_reasons.append(f"frame_strict_total_drift={total_final_drift}ms>{frame_strict_max_total_drift}")
else:
    # Bounded/legacy policy: giữ gate thật, không render khi voice bị drift/trim/padding nặng.
    # Một vài cue rất ngắn (ví dụ tên gọi 400-700ms) có thể vượt slot nhẹ khi giữ giọng tự nhiên;
    # cho qua nếu tỷ lệ thấp và không tạo drift/trim lớn. Nếu nhiều cue vỡ slot thì fail.
    if too_long_not_clipped > 0:
        reason = f"too_long_not_clipped={too_long_not_clipped}>0"
        if total > 0 and too_long_ratio > max_too_long_ratio:
            sync_fail_reasons.append(f"too_long_ratio={too_long_ratio:.3f}>{max_too_long_ratio}")
        else:
            sync_warning_reasons.append(reason + " (local_overhang_warn)")
            print(f"WARN: {reason} ratio={too_long_ratio:.3f} (warning only; drift/trim gates decide)")
    if total > 0 and over_max_ratio > max_over_max_ratio:
        sync_fail_reasons.append(f"over_max_speed_ratio={over_max_ratio:.3f}>{max_over_max_ratio}")
    if max_drift > max_start_drift_threshold:
        sync_fail_reasons.append(f"max_start_drift={max_drift}ms>{int(max_start_drift_threshold)}")
    if drift_list and median_drift > median_start_drift_threshold:
        sync_fail_reasons.append(f"median_start_drift={median_drift:.0f}ms>{int(median_start_drift_threshold)}")
    if trimmed_ms > max_trimmed_threshold:
        sync_fail_reasons.append(f"voice_longer_than_video={trimmed_ms}ms>{int(max_trimmed_threshold)}")

# Ghi voice_sync_quality_report.json (report mới, yêu cầu 5).
decision_path = os.environ.get("TRANSCRIPT_DECISION_JSON") or ""
transcript_source = ""
speech_timing_source = ""
display_subtitle_timing = ""
dub_tts_timing = ""
asr_cues = 0
ocr_cues = 0
try:
    if decision_path and Path(decision_path).exists():
        dec = json.loads(Path(decision_path).read_text(encoding="utf-8"))
        transcript_source = dec.get("chosen") or ""
        speech_timing_source = dec.get("speech_timing_source") or ""
        display_subtitle_timing = dec.get("display_subtitle_timing") or ""
        dub_tts_timing = dec.get("dub_tts_timing") or ""
        asr_cues = int(dec.get("asr_segments") or 0)
        ocr_cues = int(dec.get("ocr_segments") or 0)
except Exception:
    pass
voice_sync_report = {
    "transcript_source": transcript_source,
    "speech_timing_source": speech_timing_source,
    "display_subtitle_timing": display_subtitle_timing,
    "dub_tts_timing": dub_tts_timing,
    "asr_cues": asr_cues,
    "ocr_cues": ocr_cues,
    "tts_source_entries": source_total,
    "tts_entries": total,
    "raw_slot_median_ratio": round(median_raw_ratio, 4),
    "raw_slot_ratios_count": len(raw_ratios),
    "final_slot_median_ratio": round(median_ratio, 4),
    "median_final_fill_ratio": round(median_ratio, 4),
    "final_slot_ratios_count": len(ratios),
    "sync_gate_median_ratio": round(median_ratio, 4),
    "sync_gate_median_metric": median_ratio_metric,
    "padded_segments": padded_segments,
    "padding_total_ms": padding_total_ms,
    "synthetic_padding_ms": synthetic_padding_ms,
    "proven_synthetic_padding_ms": proven_synthetic_padding_ms,
    "proven_synthetic_padding_evidence_backends": proven_synthetic_padding_evidence_backends,
    "source_gap_ms": source_gap_ms,
    "longest_consecutive_synthetic_padding_ms": longest_consecutive_padding_ms,
    "longest_proven_synthetic_padding_ms": longest_proven_padding_ms,
    "longest_unproven_synthetic_padding_ms": longest_unproven_padding_ms,
    "padding_ratio": round(padded_ratio, 4),
    "padding_video_ratio": round(padding_video_ratio, 4),
    "proven_padding_video_ratio": round(proven_padding_video_ratio, 4),
    "padded_ratio_policy": "fail" if fail_on_padded_ratio else "warn",
    "max_padded_ratio": max_padded_ratio,
    "max_padding_video_ratio": max_padding_video,
    "min_median_raw_slot_ratio": min_median_ratio,
    "max_low_ratio_fraction": max_low_ratio,
    "voice_sync_padding_warn_ratio": padding_warn_ratio,
    "voice_sync_padding_fail_ratio": padding_fail_ratio,
    "voice_sync_min_median_fill_ratio": min_median_fill_ratio,
    "voice_sync_long_padding_warn_ms": long_padding_warn_ms,
    "voice_sync_long_padding_fail_ms": long_padding_fail_ms,
    "strict_quality_gate": strict_quality_gate,
    "relaxed_short_audio_mode": relaxed_short_audio_mode,
    "speech_padding_ms": stats.get('speech_padding_ms', 0) or 0,
    "speech_padding_video_ratio": round((stats.get('speech_padding_ms', 0) or 0) / video_ms, 4) if video_ms > 0 else 0.0,
    "final_tail_silence_ms": stats.get('final_tail_silence_ms', 0) or 0,
    "kokoro_segments": kokoro,
    "kokoro_voice_used": stats.get('kokoro_voice_used', '') or '',
    "ai33_segments": ai33,
    "ai33_failed_segments": ai33_fail,
    "ai33_fail_error_codes": ai33_fail_codes,
    "ai33_voice_used": stats.get('ai33_voice_used', '') or '',
    "tts_checkpoint_schema": stats.get('tts_checkpoint_schema', 0) or 0,
    "tts_checkpoint_path": Path(str(stats.get('tts_checkpoint_path', '') or '')).name,
    "tts_cues_completed": stats.get('tts_cues_completed', stats.get('tts_completed_cues', 0)) or 0,
    "tts_cues_total": stats.get('tts_cues_total', stats.get('tts_total_cues', total)) or 0,
    "tts_cues_reused": stats.get('tts_cues_reused', stats.get('tts_reusable_cues', 0)) or 0,
    "failed_cue": stats.get('tts_failed_cue', 0) or 0,
    "failed_stage": stats.get('tts_failed_stage', '') or '',
    "failed_code": stats.get('tts_failed_code', '') or '',
    "failed_attempts": stats.get('tts_failed_attempts', 0) or 0,
    "resume_from_cue": stats.get('tts_resume_from_cue', 1) or 1,
    "voice_source": stats.get('voice_source', '') or '',
    "voice_label": stats.get('voice_label', '') or '',
    "voice_id": stats.get('voice_id', '') or stats.get('ai33_voice_used', '') or '',
    "canonical_voice": stats.get('canonical_voice', '') or (f"ai33:{stats.get('ai33_voice_used', '')}" if stats.get('ai33_voice_used') else ''),
    "timing_profile": stats.get('timing_profile', '') or '',
    "timing_overrides_applied": stats.get('timing_overrides_applied') or {},
    "dub_text_overrides_applied": stats.get('dub_text_overrides_applied') or {},
    "min_slow_ratio": stats.get('min_slow_ratio', '') or stats.get("slow_fit_min_ratio", 1.0) or 1.0,
    "ai33_fail_reasons": [f"ai33_failed={ai33_fail}/{total} codes={ai33_fail_codes}"] if ai33_fail else [],
    "edge_segments": stats.get('edge_segments', 0) or 0,
    "edge_fallback_reason": stats.get('edge_fallback_reason', '') or '',
    "resona_coverage_ratio": round(resona_coverage_ratio, 4) if resona_requested else 0.0,
    "resona_bypassed_short_segments": (resona_short + resona_short_fb) if resona_requested else 0,
    "raw_low_ratio_segments": raw_low_ratio_segs,
    "final_low_ratio_segments": stats.get('final_low_ratio_segments', low_ratio_segs) or 0,
    "low_ratio_segments": low_ratio_segs,
    "low_ratio_fraction": round(low_ratio_frac, 4),
    "too_long_not_clipped_segments": too_long_not_clipped,
    "too_long_ratio": round(too_long_ratio, 4),
    "max_too_long_ratio": max_too_long_ratio,
    "over_max_speed_segments": over_max_speed,
    "over_max_speed_ratio": round(over_max_ratio, 4),
    "overhang_segments": overhang_segs,
    "unresolved_contiguous_overhang_count": unresolved_overhang["count"],
    "unresolved_contiguous_overhang_max_ms": unresolved_overhang["max_ms"],
    "unresolved_contiguous_overhang_threshold_ms": unresolved_overhang["threshold_ms"],
    "unresolved_contiguous_overhang_reasons": unresolved_overhang["reasons"],
    "rewritten_segments": rewritten_segs,
    "rewrite_failed_segments": rewrite_failed_segs,
    "adapt_enabled": stats.get("adapt_enabled", False),
    "adapt_max_attempts": stats.get("adapt_max_attempts", 0) or 0,
    "adapt_shorten_segments": stats.get("adapt_shorten_segments", 0) or 0,
    "adapt_restore_segments": stats.get("adapt_restore_segments", 0) or 0,
    "restore_safe_detail_attempted_segments": stats.get("restore_safe_detail_attempted_segments", 0) or 0,
    "restore_safe_detail_success_segments": stats.get("restore_safe_detail_success_segments", 0) or 0,
    "adapt_keep_natural_segments": stats.get("adapt_keep_natural_segments", 0) or 0,
    "adapt_needs_attention_segments": adapt_needs_attention,
    "adapt_native_speed_resolved_segments": stats.get("adapt_native_speed_resolved_segments", 0) or 0,
    "low_fill_after_restore_segments": stats.get("low_fill_after_restore_segments", 0) or 0,
    "max_start_drift_ms": max_drift,
    "median_start_drift_ms": round(median_drift, 1),
    "p90_start_drift_ms": p90_drift,
    "final_voice_duration_ms": final_voice_ms,
    "target_video_ms": target_video_ms_report,
    "trimmed_ms": trimmed_ms,
    "sync_mode": sync_mode,
    "sync_policy": sync_policy,
    "semantic_rewrite_schema_version": stats.get("semantic_rewrite_schema_version", 1) or 1,
    "semantic_rewrite_mode": stats.get("semantic_rewrite_mode", "batch1_placeholders_only") or "batch1_placeholders_only",
    "semantic_rewrite_fields": stats.get("semantic_rewrite_fields") or ["subtitle_text", "dub_text", "kept_meaning", "dropped_details", "meaning_risk"],
    "ai33_native_speed_segments": stats.get("ai33_native_speed_segments", 0) or 0,
    "ai33_native_speed_failed_segments": stats.get("ai33_native_speed_failed_segments", 0) or 0,
    "ai33_max_native_speed_used": stats.get("ai33_max_native_speed_used", 1.0) or 1.0,
    "ai33_max_speed": stats.get("ai33_max_speed", 1.0) or 1.0,
    "post_atempo_max": stats.get("post_atempo_max", 1.0) or 1.0,
    "total_audio_speed_max": stats.get("total_audio_speed_max", 1.0) or 1.0,
    "slow_fit_min_ratio": stats.get("slow_fit_min_ratio", 1.0) or 1.0,
    "min_final_speed": stats.get("min_final_speed", 1.0) or 1.0,
    "final_speed_below_1_segments": stats.get("final_speed_below_1_segments", 0) or 0,
    "max_required_speed": round(max([r for r in (stats.get('raw_slot_ratios') or []) if r >= 1.0] or [0.0]), 4),
    "max_required_slow": round(min([r for r in (stats.get('raw_slot_ratios') or []) if r < 1.0] or [1.0]), 4),
    "extreme_fit_segments": sum(1 for r in (stats.get('raw_slot_ratios') or []) if r > 2.0 or r < 0.6),
    "max_final_segment_drift_ms": max_final_drift,
    "total_final_drift_ms": total_final_drift,
    "frame_strict_max_segment_drift_ms": frame_strict_max_segment_drift,
    "frame_strict_base_total_drift_ms": frame_strict_base_total_drift,
    "frame_strict_total_drift_per_segment_ms": frame_strict_total_drift_per_segment,
    "frame_strict_max_total_drift_ms": frame_strict_max_total_drift,
    "capcut_failed_segments": stats.get('capcut_failed_segments', 0) or 0,
    "edge_fallback_segments": capcut_fb,
    "resona_segments": resona,
    "resona_failed_segments": resona_fail,
    "resona_short_text_segments": resona_short,
    "resona_short_edge_fallback_segments": resona_short_fb,
    "resona_short_grouped_units": resona_grouped_units,
    "resona_short_grouped_source_segments": resona_grouped_source_segments,
    "resona_grouped_source_cue_ids": serialized_resona_grouped_source_cue_ids,
    "resona_short_group_max_cues": stats.get('resona_short_group_max_cues', 0) or 0,
    "resona_short_group_max_duration_ms": stats.get('resona_short_group_max_duration_ms', 0) or 0,
    "resona_fail_error_codes": resona_fail_codes,
    "resona_fail_reasons": [f"resona_failed={resona_fail}/{total} codes={resona_fail_codes}"] if resona_fail else [],
    "tts_engine_requested": stats.get('tts_engine_requested', ''),
    "tts_engine_used": stats.get('tts_engine_used', ''),
    "tts_engines_used": stats.get('tts_engines_used') or [],
    "normalized_for_concat_segments": stats.get("normalized_for_concat_segments", 0) or 0,
    "expected_final_voice_ms": stats.get("expected_final_voice_ms", 0) or 0,
    "concat_duration_extra_ms": stats.get("concat_duration_extra_ms", 0) or 0,
    "final_tail_safe_trim_ms": stats.get("final_tail_safe_trim_ms", 0) or 0,
    "warning_reasons": sync_warning_reasons,
    "needs_attention_reasons": needs_attention_reasons,
    "fail_reasons": sync_fail_reasons,
    "status": "fail" if sync_fail_reasons else ("warning" if (sync_warning_reasons or needs_attention_reasons) else "ok"),
}
report_out = os.environ.get("VOICE_SYNC_REPORT_JSON") or ""
if report_out:
    try:
        Path(report_out).write_text(json.dumps(voice_sync_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"WARN: không ghi được voice_sync_quality_report.json: {exc}")
if sync_fail_reasons:
    print("VOICE_SYNC_GATE_FAIL: " + "; ".join(sync_fail_reasons)
          + f" | entries={total} padded={padded_segments}/{total} padding_ms={padding_total_ms}"
          + f" raw_median_slot={median_raw_ratio:.3f} {median_ratio_metric}={median_ratio:.3f}"
          + f" too_long={too_long_not_clipped} over_max_speed={over_max_speed}/{total}"
          + f" max_drift={max_drift}ms median_drift={median_drift:.0f}ms trimmed={trimmed_ms}ms")
    sys.exit(8)
if sync_warning_reasons or needs_attention_reasons:
    print("VOICE_SYNC_GATE_WARNING: " + "; ".join(sync_warning_reasons + needs_attention_reasons)
          + f" | entries={total} padded={padded_segments}/{total} synthetic_padding_ms={synthetic_padding_ms} proven_synthetic_padding_ms={proven_synthetic_padding_ms}"
          + f" source_gap_ms={source_gap_ms} {median_ratio_metric}={median_ratio:.3f}")
else:
    print(f"VOICE_SYNC_GATE_OK: entries={total} padded={padded_segments}/{total} padding_ms={padding_total_ms} raw_median_slot={median_raw_ratio:.3f} {median_ratio_metric}={median_ratio:.3f}"
          f" too_long={too_long_not_clipped} over_max_speed={over_max_speed}/{total}"
          f" max_drift={max_drift}ms median_drift={median_drift:.0f}ms trimmed={trimmed_ms}ms")
print(f"TTS_GATE_OK: total={total} silence={silence} circuit_breaker={cb} kokoro={kokoro} ai33={ai33} capcut={capcut} capcut_fallback={capcut_fb} resona={resona} raw_ratio={raw_ratio:.3f}")
PY
  tts_gate_status=$?
  set -e
  # Luôn copy TTS reports ra OUT_DIR trước khi exit 7/8 để dashboard/Telegram có thông tin.
  if [[ -f "$TTS_STATS_JSON" ]]; then
    cp "$TTS_STATS_JSON" "$OUT_DIR/tts_stats.json" 2>/dev/null || true
  fi
  if [[ -s "$TTS_ALIGNMENT_REPORT_JSON" ]]; then
    cp "$TTS_ALIGNMENT_REPORT_JSON" "$OUT_DIR/tts_alignment_report.json" 2>/dev/null || true
  fi
  if [[ -s "$TMP_DIR/voice_sync_quality_report.json" ]]; then
    cp "$TMP_DIR/voice_sync_quality_report.json" "$OUT_DIR/voice_sync_quality_report.json" 2>/dev/null || true
  fi
  if [[ ! -s "$OUT_DIR/voice_sync_quality_report.json" ]]; then
    PYTHONPATH="$SKILL_DIR" python3 - "$OUT_DIR/voice_sync_quality_report.json" "$TTS_STATS_JSON" "$tts_gate_status" <<'PY'
import json
import sys
from pathlib import Path
from voice_sync_status import build_voice_sync_fallback_report

report_path, stats_path, exit_status = sys.argv[1:4]
try:
    report = build_voice_sync_fallback_report(
        f"checker exit={exit_status}",
        stats_available=bool(stats_path and Path(stats_path).is_file()),
    )
    Path(report_path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
except Exception as exc:
    print(f"WARN: failed to write VoiceSyncReportBuildFailed report: {exc}", file=sys.stderr)
PY
  fi
  if [[ "$tts_gate_status" -eq 7 ]]; then
    # Heredoc có thể ghi provider-specific error_code vào voice_sync_quality_report.json
    # khi AI33/Resona fail (auth/quota/timeout/no-audio). Đọc để dashboard/Telegram báo đúng.
    tts_provider_err_code=""
    tts_provider_err_msg=""
    tts_provider_err_hint=""
    if [[ -f "$OUT_DIR/voice_sync_quality_report.json" ]]; then
      tts_provider_err_code="$(python3 -c "import json; d=json.load(open('$OUT_DIR/voice_sync_quality_report.json')); print(d.get('error_code') or '')" 2>/dev/null || echo '')"
    fi
    if [[ -n "$tts_provider_err_code" && "$tts_provider_err_code" != "None" ]]; then
      case "$tts_provider_err_code" in
        AI33AuthMissing) tts_provider_err_msg="Thiếu AI33_API_KEY/AI33_ACCESS_TOKEN. Thiết lập env rồi chạy lại." ;;
        AI33AuthFailed) tts_provider_err_msg="AI33 API key không hợp lệ hoặc hết hạn (401/403)." ;;
        AI33QuotaFailed) tts_provider_err_msg="AI33 hết credit hoặc bị rate-limit (429)." ;;
        AI33CircuitOpen) tts_provider_err_msg="AI33 đang tạm ngưng tạo task sau các lỗi provider liên tiếp; checkpoint được giữ nguyên." ;;
        AI33Timeout) tts_provider_err_msg="AI33 sinh giọng quá thời gian (timeout). Thử lại hoặc tăng AI33_TIMEOUT_SECONDS." ;;
        AI33NoAudioUrl) tts_provider_err_msg="AI33 tạo task nhưng không trả audio. Thử giọng khác hoặc kiểm tra task/debug response." ;;
        TTSAI33Failed) tts_provider_err_msg="AI33 TTS lỗi (wrapper missing / network / unknown)." ;;
        ResonaAuthMissing) tts_provider_err_msg="Thiếu token Resona (RESONA_API_TOKEN). Thiết lập env rồi chạy lại." ;;
        ResonaAuthFailed) tts_provider_err_msg="Token Resona không hợp lệ hoặc hết hạn (401/403)." ;;
        ResonaQuotaFailed) tts_provider_err_msg="Resona hết credit hoặc bị rate-limit (429)." ;;
        ResonaTimeout) tts_provider_err_msg="Resona sinh giọng quá thời gian (timeout). Thử lại hoặc tăng RESONA_TIMEOUT_SECONDS." ;;
        ResonaNoAudioUrl) tts_provider_err_msg="Resona tạo request nhưng không sinh được audio. Thường do voice/text không được model đó hỗ trợ; thử voice Resona khác như Nữ Tuệ An." ;;
        ResonaTextTooShort) tts_provider_err_msg="Có cue quá ngắn cho Resona (<$RESONA_MIN_CHARS ký tự) và RESONA_SHORT_TEXT_POLICY=fail." ;;
        ResonaTextTooShortUngroupable) tts_provider_err_msg="Có cue quá ngắn và không gom được đủ credit Resona (>= $RESONA_MIN_CHARS ký tự) dù đã gom tối đa." ;;
        ResonaCoverageTooLow) tts_provider_err_msg="Pipeline chưa dùng đủ giọng Resona (coverage < 85%), nhiều cue bị bypass/fallback Edge." ;;
        TTSResonaFailed) tts_provider_err_msg="Resona TTS lỗi (wrapper missing / network / unknown)." ;;
        *) tts_provider_err_msg="TTS provider fail: $tts_provider_err_code" ;;
      esac
      echo "ERROR: TTS provider fail ($tts_provider_err_code). $tts_provider_err_msg Dừng job, không render/organize." >&2
      case "$tts_provider_err_code" in
        AI33AuthMissing|AI33AuthFailed) tts_provider_err_hint="Kiểm tra AI33_API_KEY." ;;
        AI33QuotaFailed) tts_provider_err_hint="Kiểm tra credit/rate-limit AI33." ;;
        AI33CircuitOpen) tts_provider_err_hint="Đợi cooldown AI33 rồi Chạy tiếp từ job cũ; không đổi voice hoặc xoá checkpoint." ;;
        AI33Timeout|TTSAI33Failed) tts_provider_err_hint="Kiểm tra kết nối AI33 hoặc thử lại." ;;
        AI33NoAudioUrl) tts_provider_err_hint="Không phải lỗi key nếu task đã tạo được; thử voice khác hoặc rút ngắn/chỉnh text." ;;
        ResonaAuthMissing|ResonaAuthFailed) tts_provider_err_hint="Kiểm tra token Resona." ;;
        ResonaQuotaFailed) tts_provider_err_hint="Kiểm tra credit/rate-limit Resona." ;;
        ResonaTimeout|TTSResonaFailed) tts_provider_err_hint="Kiểm tra kết nối Resona hoặc thử lại." ;;
        ResonaNoAudioUrl) tts_provider_err_hint="Không phải lỗi token nếu request đã tạo được; thử voice khác hoặc rút ngắn/chỉnh text." ;;
        AI33*) tts_provider_err_hint="Xem voice_sync_quality_report.json / ai33_tts_debug/." ;;
        Resona*) tts_provider_err_hint="Xem voice_sync_quality_report.json / resona_tts_debug/." ;;
        *) tts_provider_err_hint="Xem voice_sync_quality_report.json / tts_alignment_report.json." ;;
      esac
      tts_provider_state="needs_attention"
      case "$tts_provider_err_code" in
        AI33CircuitOpen|AI33*RateLimited|AI33*Http5xx|AI33*Timeout|AI33*Network) tts_provider_state="waiting_provider" ;;
      esac
      status_update "$tts_provider_state" "78" "TTS provider fail: $tts_provider_err_code" "0" "$tts_provider_err_code" "$tts_provider_err_msg $tts_provider_err_hint"
      echo "Output giữ lại tại: $OUT_DIR" >&2
      exit 7
    fi
    echo "ERROR: TTS fail toàn bộ (silence/circuit-breaker, không có giọng thật) HOẶC giọng thật quá ít so với video. Dừng job, không render/organize." >&2
    status_update "error" "78" "TTS fail/giọng quá ít, không có đủ giọng Việt" "0" "TTSAllSilence" "TTS rơi silence/circuit-breaker toàn segment hoặc raw voice quá ít; kiểm tra Resona/edge-tts/9router và transcript gốc."
    echo "Output giữ lại tại: $OUT_DIR" >&2
    exit 7
  fi
  if [[ "$tts_gate_status" -eq 8 ]]; then
    echo "ERROR: Voice-sync local gate fail: TTS quá ngắn (padding im lặng nhiều) HOẶC quá dài (drift/overhang/voice dài hơn video). Xem voice_sync_quality_report.json. Dừng job, không render/organize." >&2
    status_update "needs_attention" "78" "Voice-sync hỏng (TTS quá ngắn padding HOẶC quá dài drift/overhang/trim)" "0" "VoiceSyncFail" "TTS tiếng Việt không khớp timeline gốc: quá ngắn (padding im lặng) hoặc quá dài (drift tích lũy, overhang, voice dài hơn video bị trim cắt đuôi). Xem voice_sync_quality_report.json. Cần rewrite/regenerate dub timing; bấm Chạy tiếp từ job cũ khi 9Router/TTS sẵn sàng, hoặc dán transcript_vi.json."
    echo "Output giữ lại tại: $OUT_DIR" >&2
    exit 8
  fi
  if [[ "$tts_gate_status" -ne 0 ]]; then
    echo "ERROR: TTS gate internal error (exit=$tts_gate_status). Dừng job, không render/organize để tránh final lỗi." >&2
    tts_gate_internal_code="$(PYTHONPATH="$SKILL_DIR" python3 - "$tts_gate_status" <<'PY'
import sys
from voice_sync_status import gate_terminal_status
print((gate_terminal_status(sys.argv[1]) or {}).get("error_code") or "VoiceSyncGateInternalError")
PY
)"
    status_update "needs_attention" "78" "Voice-sync gate lỗi nội bộ" "0" "$tts_gate_internal_code" "Voice-sync gate trả exit=$tts_gate_status; pipeline dừng để không render/organize. Xem tts_stats.json / voice_sync_quality_report.json."
    echo "Output giữ lại tại: $OUT_DIR" >&2
    exit "$tts_gate_status"
  fi
fi
if [[ -s "$TTS_ALIGNMENT_REPORT_JSON" ]]; then
  cp "$TTS_ALIGNMENT_REPORT_JSON" "$OUT_DIR/tts_alignment_report.json"
  echo "tts_alignment_report.json: $OUT_DIR/tts_alignment_report.json"
fi
# voice_sync_quality_report.json được TTS gate heredoc ghi vào TMP_DIR; copy ra OUT_DIR.
if [[ -s "$TMP_DIR/voice_sync_quality_report.json" ]]; then
  cp "$TMP_DIR/voice_sync_quality_report.json" "$OUT_DIR/voice_sync_quality_report.json"
  echo "voice_sync_quality_report.json: $OUT_DIR/voice_sync_quality_report.json"
elif [[ -s "$OUT_DIR/voice_sync_quality_report.json" ]]; then
  echo "voice_sync_quality_report.json: $OUT_DIR/voice_sync_quality_report.json"
fi
if [[ -s "$SPEED_REPORT_CSV" ]]; then
  cp "$SPEED_REPORT_CSV" "$OUT_DIR/speed_report.csv"
  echo "speed_report.csv: $OUT_DIR/speed_report.csv"
fi

MUX_VOICE_WAV="$OUT_DIR/vietnamese_voice_mux.wav"
VIDEO_MUX_SOURCE="$VIDEO"
VIDEO_FIT_ACTION="none"
FINAL_VIDEO_FREEZE_SECONDS="0.000"
MUX_TARGET_DURATION="$VIDEO_DURATION"
FINAL_VIDEO_FIT_PLAN_JSON="$OUT_DIR/final_video_fit_plan.json"
voice_fit_plan_line="$(python3 "$SKILL_DIR/final_mix_quality.py" --video-fit \
  --video-duration "$VIDEO_DURATION" --voice-duration "$VOICE_DURATION_RAW" \
  --allow-video-retime "$ALLOW_VIDEO_RETIME" --allow-freeze-frame "$ALLOW_FREEZE_FRAME" --scene-safe "$LOCAL_RETIME_SCENE_SAFE" \
  --max-freeze-per-segment-ms "$MAX_FREEZE_PER_SEGMENT_MS" --max-freeze-per-scene-ms "$MAX_FREEZE_PER_SCENE_MS" \
  --max-output-duration-increase "$MAX_OUTPUT_DURATION_INCREASE" --allow-final-trim "$ALLOW_FINAL_TRIM" \
  --strict-quality-gate "$STRICT_QUALITY_GATE" --plan-path "$FINAL_VIDEO_FIT_PLAN_JSON")"
IFS=$'\t' read -r VIDEO_FIT_ACTION MUX_TARGET_DURATION FINAL_VIDEO_FREEZE_SECONDS VIDEO_FIT_MESSAGE <<< "$voice_fit_plan_line"
echo "$VIDEO_FIT_MESSAGE"
if [[ "$VIDEO_FIT_ACTION" == "needs_attention_no_trim" ]]; then
  status_update "needs_attention" "79" "Giọng Việt dài hơn video, không tự cắt đuôi" "0" "VoiceLongerThanVideo" "vietnamese_voice.wav dài hơn video vượt tolerance ${FINAL_VOICE_OVERHANG_TOLERANCE:-0.20}s. Pipeline dừng để tránh trim/cắt mất câu; xem voice_sync_quality_report.json, speed_report.csv và final_video_fit_plan.json."
  echo "WARN: Vietnamese voice longer than video and ALLOW_FINAL_TRIM=0. Không mux để tránh cắt đuôi." >&2
  echo "Output giữ lại tại: $OUT_DIR" >&2
  if [[ "$STRICT_QUALITY_GATE" == "1" ]]; then
    echo "ERROR: STRICT_QUALITY_GATE=1 -> hard fail on unresolved voice overhang." >&2
    exit 8
  fi
  # Non-strict mode ends as needs_attention (not success) without producing a
  # silently-trimmed final.  A caller that requires a final artifact enables
  # STRICT_QUALITY_GATE=1 and receives the hard failure instead.
  exit 0
fi
if [[ "$VIDEO_FIT_ACTION" == "tail_freeze_local" ]]; then
  VIDEO_MUX_SOURCE="$OUT_DIR/video_tail_freeze_mux.mp4"
  echo "Final video fit: explicit local tail-freeze ${FINAL_VIDEO_FREEZE_SECONDS}s để giữ nguyên đuôi giọng Việt."
  ffmpeg -y -i "$VIDEO" \
    -vf "tpad=stop_mode=clone:stop_duration=${FINAL_VIDEO_FREEZE_SECONDS},format=yuv420p" \
    -t "$MUX_TARGET_DURATION" -c:v libx264 -preset veryfast -crf 18 -c:a copy "$VIDEO_MUX_SOURCE" >/dev/null 2>&1
  [[ -s "$VIDEO_MUX_SOURCE" ]] || fail "Không tạo được video tail-freeze để mux"
fi
ffmpeg -y -i "$VIETNAMESE_VOICE_WAV" -af "apad" -t "$MUX_TARGET_DURATION" -ac "$TTS_MASTER_CHANNELS" -ar "$TTS_MASTER_SAMPLE_RATE" -c:a pcm_s16le "$MUX_VOICE_WAV" >/dev/null 2>&1
[[ -s "$MUX_VOICE_WAV" ]] || fail "Không chuẩn bị được audio Việt để mux"
MUX_VOICE_DURATION="$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$MUX_VOICE_WAV" | tr -d '\r')"
echo "Mux-ready Vietnamese voice duration: ${MUX_VOICE_DURATION}s (${TTS_MASTER_SAMPLE_RATE}Hz/${TTS_MASTER_CHANNELS}ch; center to stereo only in final mix)"

echo "Đang ghép audio tiếng Việt vào video..."
status_update "mux" "80" "Đang ghép audio/video" "0"
select_bgm_source
if [[ "$SELECTED_BGM_MODE" == "error" ]]; then
  status_update "needs_attention" "80" "Không có nhạc nền đã tách giọng" "0" "BackgroundSeparationFailed" "BGM_MODE=$BGM_MODE yêu cầu no_vocals.wav từ Demucs; không fallback sang audio gốc để tránh giữ giọng Trung."
  fail "BackgroundSeparationFailed: thiếu no_vocals.wav hợp lệ cho final mix."
fi
if [[ "${KEEP_ORIGINAL_MUSIC_BED:-true}" != "false" && "$SELECTED_BGM_MODE" == "demucs" && -s "$SELECTED_BGM_SOURCE" ]]; then
  FINAL_MIX_FILTER="$(python3 "$SKILL_DIR/final_mix_quality.py" --ffmpeg-filter --voice-input 1:a --bed-input 2:a --voice-volume "$VOICE_VOLUME" --music-volume "$MUSIC_BED_VOLUME" --ducking "$ENABLE_BGM_DUCKING" --duck-amount "$BGM_DUCK_AMOUNT" --sample-rate "$FINAL_AUDIO_SAMPLE_RATE" --loudness-target "$FINAL_LOUDNESS_TARGET" --true-peak-limit "$FINAL_TRUE_PEAK_LIMIT" --enable-loudness "$ENABLE_FINAL_LOUDNESS_NORMALIZATION")"
  echo "BGM_MODE=demucs: stereo bed + centered voice; ducking=${ENABLE_BGM_DUCKING} amount=${BGM_DUCK_AMOUNT}; $SELECTED_BGM_SOURCE volume=${MUSIC_BED_VOLUME}"
  ffmpeg -y -i "$VIDEO_MUX_SOURCE" -i "$MUX_VOICE_WAV" -i "$SELECTED_BGM_SOURCE" \
    -filter_complex "$FINAL_MIX_FILTER" \
    -map 0:v:0 -map "[aout]" -c:v copy -c:a aac -b:a "$FINAL_AUDIO_BITRATE" -ar "$FINAL_AUDIO_SAMPLE_RATE" -ac "$FINAL_AUDIO_CHANNELS" -shortest "$AUDIO_ONLY_VIDEO"
elif [[ "${KEEP_ORIGINAL_MUSIC_BED:-true}" != "false" && "$SELECTED_BGM_MODE" == "duck" ]]; then
  FINAL_MIX_FILTER="$(python3 "$SKILL_DIR/final_mix_quality.py" --ffmpeg-filter --voice-input 1:a --bed-input 0:a --voice-volume "$VOICE_VOLUME" --music-volume "$MUSIC_BED_VOLUME" --ducking "$ENABLE_BGM_DUCKING" --duck-amount "$BGM_DUCK_AMOUNT" --sample-rate "$FINAL_AUDIO_SAMPLE_RATE" --loudness-target "$FINAL_LOUDNESS_TARGET" --true-peak-limit "$FINAL_TRUE_PEAK_LIMIT" --enable-loudness "$ENABLE_FINAL_LOUDNESS_NORMALIZATION")"
  echo "BGM_MODE=duck: stereo source bed + centered voice; ducking=${ENABLE_BGM_DUCKING} amount=${BGM_DUCK_AMOUNT}; volume=${MUSIC_BED_VOLUME}"
  ffmpeg -y -i "$VIDEO_MUX_SOURCE" -i "$MUX_VOICE_WAV" \
    -filter_complex "$FINAL_MIX_FILTER" \
    -map 0:v:0 -map "[aout]" -c:v copy -c:a aac -b:a "$FINAL_AUDIO_BITRATE" -ar "$FINAL_AUDIO_SAMPLE_RATE" -ac "$FINAL_AUDIO_CHANNELS" -shortest "$AUDIO_ONLY_VIDEO"
else
  echo "BGM_MODE=none: chỉ dùng giọng Việt, bỏ nhạc nền."
  FINAL_MIX_FILTER="$(python3 "$SKILL_DIR/final_mix_quality.py" --voice-only-filter --voice-input 1:a --voice-volume "$VOICE_VOLUME" --sample-rate "$FINAL_AUDIO_SAMPLE_RATE" --loudness-target "$FINAL_LOUDNESS_TARGET" --true-peak-limit "$FINAL_TRUE_PEAK_LIMIT" --enable-loudness "$ENABLE_FINAL_LOUDNESS_NORMALIZATION")"
  ffmpeg -y -i "$VIDEO_MUX_SOURCE" -i "$MUX_VOICE_WAV" -filter_complex "$FINAL_MIX_FILTER" -map 0:v:0 -map "[aout]" -c:v copy -c:a aac -b:a "$FINAL_AUDIO_BITRATE" -ar "$FINAL_AUDIO_SAMPLE_RATE" -ac "$FINAL_AUDIO_CHANNELS" -shortest "$AUDIO_ONLY_VIDEO"
fi
write_fit_adjustments_report
[[ -s "$AUDIO_ONLY_VIDEO" ]] || fail "Không tạo được final_video_audio_only.mp4"

render_policy="${SUBTITLE_RENDER_FAILURE_POLICY:-fail}"
if [[ "${BURN_VIET_SUBTITLE:-1}" != "0" && -x "$SUBTITLE_MASK_RENDER_SCRIPT" && -s "$VIETNAMESE_SRT" ]]; then
  echo "Đang detect vị trí sub gốc + blur vùng chữ Trung và chèn phụ đề Việt vào video final..."
  status_update "subtitle_render" "84" "Đang blur vùng chữ Trung và chèn phụ đề Việt" "0"
  subtitle_render_timeout="${SUBTITLE_RENDER_TIMEOUT_SECONDS:-1800}"
  SUBTITLE_REGION_ARTIFACT="$OUT_DIR/subtitle_region.json"
  # Geometry cache is independent from ASR/OCR-content/translation/TTS/download.
  # A detector-only invocation writes a fingerprinted artifact; the renderer only reads it.
  subtitle_region_valid=0
  if [[ -s "$SUBTITLE_REGION_ARTIFACT" && "$SUBTITLE_REGION_REBUILD" != "1" ]]; then
    "$SUBTITLE_MASK_RENDER_PYTHON" "$SUBTITLE_MASK_RENDER_SCRIPT" --input-video "$AUDIO_ONLY_VIDEO" --srt "$VIETNAMESE_SRT" --output-video "$FINAL_VIDEO" --font "$SUBTITLE_FONT" --subtitle-region "$SUBTITLE_REGION_ARTIFACT" --validate-subtitle-region-only >/dev/null 2>&1 || subtitle_region_valid=1
  else
    subtitle_region_valid=1
  fi
  if [[ "$subtitle_region_valid" == "1" ]]; then
    "$SUBTITLE_MASK_RENDER_PYTHON" "$SUBTITLE_MASK_RENDER_SCRIPT" --input-video "$AUDIO_ONLY_VIDEO" --srt "$VIETNAMESE_SRT" --output-video "$FINAL_VIDEO" --font "$SUBTITLE_FONT" --subtitle-region "$SUBTITLE_REGION_ARTIFACT" --detect-subtitle-region-only
  fi
  set +e
  OCR_VISION_API_KEY="${OCR_VISION_API_KEY:-$API_KEY}"
  if [[ "$SUBTITLE_BAND_DETECT_ENGINE" == "9router_vision" && -z "$OCR_VISION_API_KEY" ]]; then
    echo "WARN: Thiếu OCR_VISION_API_KEY; dùng CV để detect/render subtitle band."
    SUBTITLE_BAND_DETECT_ENGINE="cv"
  fi
  export OCR_VISION_API_KEY
  run_with_status_heartbeat "subtitle_render" "84" "Đang detect vị trí sub gốc + render blur band" "$subtitle_render_timeout" "${OPENCLAW_LONG_STEP_HEARTBEAT_SECONDS:-30}" \
    timeout "$subtitle_render_timeout" \
    env \
    SUBTITLE_MASK_STYLE="$SUBTITLE_MASK_STYLE" \
    SUBTITLE_BAND_SAMPLE_COUNT="$SUBTITLE_BAND_SAMPLE_COUNT" \
    SUBTITLE_BAND_REGION_TOP_RATIO="$SUBTITLE_BAND_REGION_TOP_RATIO" \
    SUBTITLE_BAND_REGION_BOTTOM_RATIO="$SUBTITLE_BAND_REGION_BOTTOM_RATIO" \
    SUBTITLE_BAND_HEIGHT_RATIO="$SUBTITLE_BAND_HEIGHT_RATIO" \
    SUBTITLE_BAND_MIN_HEIGHT="$SUBTITLE_BAND_MIN_HEIGHT" \
    SUBTITLE_BAND_BLUR="$SUBTITLE_BAND_BLUR" \
    SUBTITLE_BAND_TINT_OPACITY="$SUBTITLE_BAND_TINT_OPACITY" \
    SUBTITLE_TEXT_COLOR="$SUBTITLE_TEXT_COLOR" \
    SUBTITLE_TEXT_ALIGN="$SUBTITLE_TEXT_ALIGN" \
    SUBTITLE_MASK_OPACITY="$SUBTITLE_MASK_OPACITY" \
    SUBTITLE_MASK_HEIGHT_RATIO="$SUBTITLE_MASK_HEIGHT_RATIO" \
    SUBTITLE_BOTTOM_MARGIN_RATIO="$SUBTITLE_BOTTOM_MARGIN_RATIO" \
    SUBTITLE_FONT_SIZE_RATIO="$SUBTITLE_FONT_SIZE_RATIO" \
    SUBTITLE_OUTLINE="$SUBTITLE_OUTLINE" \
    SUBTITLE_MAX_LINES="$SUBTITLE_MAX_LINES" \
    SUBTITLE_MAX_CHARS_PER_LINE="$SUBTITLE_MAX_CHARS_PER_LINE" \
    SUBTITLE_BOX_MODE="$SUBTITLE_BOX_MODE" \
    SUBTITLE_BOX_OPACITY="$SUBTITLE_BOX_OPACITY" \
    SUBTITLE_BOX_MARGIN_X="$SUBTITLE_BOX_MARGIN_X" \
    SUBTITLE_BOX_MARGIN_Y="$SUBTITLE_BOX_MARGIN_Y" \
    SUBTITLE_BOX_VERTICAL_OFFSET_RATIO="$SUBTITLE_BOX_VERTICAL_OFFSET_RATIO" \
    SUBTITLE_DYNAMIC_MASK="$SUBTITLE_DYNAMIC_MASK" \
    SUBTITLE_DYNAMIC_MASK_MODE="$SUBTITLE_DYNAMIC_MASK_MODE" \
    SUBTITLE_DETECT_REGION_TOP_RATIO="$SUBTITLE_DETECT_REGION_TOP_RATIO" \
    SUBTITLE_DETECT_REGION_BOTTOM_RATIO="$SUBTITLE_DETECT_REGION_BOTTOM_RATIO" \
    SUBTITLE_DETECT_LUMA_THRESHOLD="$SUBTITLE_DETECT_LUMA_THRESHOLD" \
    SUBTITLE_DETECT_MAX_RGB_SPREAD="$SUBTITLE_DETECT_MAX_RGB_SPREAD" \
    SUBTITLE_DYNAMIC_MASK_PAD_X_RATIO="$SUBTITLE_DYNAMIC_MASK_PAD_X_RATIO" \
    SUBTITLE_DYNAMIC_MASK_PAD_Y_RATIO="$SUBTITLE_DYNAMIC_MASK_PAD_Y_RATIO" \
    SUBTITLE_DYNAMIC_MASK_MIN_WIDTH_RATIO="$SUBTITLE_DYNAMIC_MASK_MIN_WIDTH_RATIO" \
    SUBTITLE_DETECT_MAX_WIDTH_RATIO="$SUBTITLE_DETECT_MAX_WIDTH_RATIO" \
    SUBTITLE_DYNAMIC_MASK_DEBUG="$SUBTITLE_DYNAMIC_MASK_DEBUG" \
    SUBTITLE_FALLBACK_MASK_HEIGHT_RATIO="$SUBTITLE_FALLBACK_MASK_HEIGHT_RATIO" \
    SUBTITLE_FALLBACK_MASK_MAX_WIDTH_RATIO="$SUBTITLE_FALLBACK_MASK_MAX_WIDTH_RATIO" \
    SUBTITLE_SOURCE_TRACK="$SUBTITLE_SOURCE_TRACK" \
    SUBTITLE_RENDER_MASK_FROM_SOURCE="$SUBTITLE_RENDER_MASK_FROM_SOURCE" \
    SUBTITLE_SOURCE_DETECT_FPS="$SUBTITLE_SOURCE_DETECT_FPS" \
    SUBTITLE_SOURCE_TRACK_REBUILD="$SUBTITLE_SOURCE_TRACK_REBUILD" \
    SUBTITLE_SOURCE_TRACK_MIN_CONFIDENCE="$SUBTITLE_SOURCE_TRACK_MIN_CONFIDENCE" \
    SUBTITLE_SOURCE_MERGE_GAP_SEC="$SUBTITLE_SOURCE_MERGE_GAP_SEC" \
    SUBTITLE_SOURCE_HOLD_OUT_SEC="$SUBTITLE_SOURCE_HOLD_OUT_SEC" \
    SUBTITLE_SOURCE_LEAD_IN_SEC="$SUBTITLE_SOURCE_LEAD_IN_SEC" \
    SUBTITLE_SOURCE_BBOX_SMOOTH_WINDOW="$SUBTITLE_SOURCE_BBOX_SMOOTH_WINDOW" \
    SUBTITLE_SOURCE_PAD_X="$SUBTITLE_SOURCE_PAD_X" \
    SUBTITLE_SOURCE_PAD_Y="$SUBTITLE_SOURCE_PAD_Y" \
    SUBTITLE_SOURCE_WIDE_WIDTH_RATIO="$SUBTITLE_SOURCE_WIDE_WIDTH_RATIO" \
    SUBTITLE_SOURCE_TRACK_DEBUG="$SUBTITLE_SOURCE_TRACK_DEBUG" \
    SUBTITLE_SOURCE_DETECT_MODE="$SUBTITLE_SOURCE_DETECT_MODE" \
    SUBTITLE_OCR_FALLBACK="$SUBTITLE_OCR_FALLBACK" \
    SUBTITLE_OCR_ENGINE="$SUBTITLE_OCR_ENGINE" \
    SUBTITLE_OCR_LANG="$SUBTITLE_OCR_LANG" \
    SUBTITLE_OCR_FPS="$SUBTITLE_OCR_FPS" \
    SUBTITLE_OCR_ROI_ONLY="$SUBTITLE_OCR_ROI_ONLY" \
    SUBTITLE_OCR_BATCH_SIZE="$SUBTITLE_OCR_BATCH_SIZE" \
    SUBTITLE_OCR_MIN_CONFIDENCE="$SUBTITLE_OCR_MIN_CONFIDENCE" \
    SUBTITLE_OCR_REBUILD="$SUBTITLE_OCR_REBUILD" \
    SUBTITLE_MASK_ROUNDED="$SUBTITLE_MASK_ROUNDED" \
    SUBTITLE_MASK_RADIUS="$SUBTITLE_MASK_RADIUS" \
    SUBTITLE_MASK_ALPHA="$SUBTITLE_MASK_ALPHA" \
    SUBTITLE_BAND_DETECT_ENGINE="$SUBTITLE_BAND_DETECT_ENGINE" \
    SUBTITLE_BAND_VISION_TIMEOUT="$SUBTITLE_BAND_VISION_TIMEOUT" \
    VI_SUBTITLE_MIN_FONT_SIZE="$VI_SUBTITLE_MIN_FONT_SIZE" \
    VI_SUBTITLE_MAX_LINES="$VI_SUBTITLE_MAX_LINES" \
    VI_SUBTITLE_WRAP_CHARS="$VI_SUBTITLE_WRAP_CHARS" \
    VI_SUBTITLE_BOTTOM_MARGIN_RATIO="$VI_SUBTITLE_BOTTOM_MARGIN_RATIO" \
    VI_SUBTITLE_VERTICAL_OFFSET_RATIO="$VI_SUBTITLE_VERTICAL_OFFSET_RATIO" \
    VI_SUBTITLE_FONT_FILE="$VI_SUBTITLE_FONT_FILE" \
    VI_SUBTITLE_FONT_NAME="$VI_SUBTITLE_FONT_NAME" \
    VI_SUBTITLE_FONT_PRESET="$VI_SUBTITLE_FONT_PRESET" \
    VI_SUBTITLE_FONT_DIR="$VI_SUBTITLE_FONT_DIR" \
    VI_SUBTITLE_MAX_FONT_SIZE="$VI_SUBTITLE_MAX_FONT_SIZE" \
    VI_SUBTITLE_TARGET_BAND_FILL="$VI_SUBTITLE_TARGET_BAND_FILL" \
    VI_SUBTITLE_SAFE_WIDTH_RATIO="$VI_SUBTITLE_SAFE_WIDTH_RATIO" \
    VI_SUBTITLE_SAFE_HEIGHT_RATIO="$VI_SUBTITLE_SAFE_HEIGHT_RATIO" \
    VI_SUBTITLE_MIN_BAND_FILL_WARN="$VI_SUBTITLE_MIN_BAND_FILL_WARN" \
    VI_SUBTITLE_MAX_SMALL_CUE_RATIO="$VI_SUBTITLE_MAX_SMALL_CUE_RATIO" \
    VI_SUBTITLE_LAYOUT_GATE="$VI_SUBTITLE_LAYOUT_GATE" \
    VI_SUBTITLE_MIN_FONT_SIZE_GATE="$VI_SUBTITLE_MIN_FONT_SIZE_GATE" \
    SUBTITLE_BAND_MIN_CENTER_Y_RATIO="$SUBTITLE_BAND_MIN_CENTER_Y_RATIO" \
    SUBTITLE_BAND_OUTLIER_CONSISTENCY="$SUBTITLE_BAND_OUTLIER_CONSISTENCY" \
    SUBTITLE_BAND_OUTLIER_MAD_K="$SUBTITLE_BAND_OUTLIER_MAD_K" \
    OCR_VISION_MODEL="$OCR_VISION_MODEL" \
    OCR_VISION_API_BASE="$OCR_VISION_API_BASE" \
    NINEROUTER_MODEL="$NINEROUTER_MODEL" \
    OPENCLAW_AI_PROVIDER="$OPENCLAW_AI_PROVIDER" \
    "$SUBTITLE_MASK_RENDER_PYTHON" "$SUBTITLE_MASK_RENDER_SCRIPT" --input-video "$AUDIO_ONLY_VIDEO" --srt "$VIETNAMESE_SRT" --output-video "$FINAL_VIDEO" --font "$SUBTITLE_FONT" --subtitle-region "$SUBTITLE_REGION_ARTIFACT"
  subtitle_render_status=$?
  set -e
  # Xử lý lỗi render theo SUBTITLE_RENDER_FAILURE_POLICY.
  # - fail (mặc định): exit 8 (gate) hoặc render lỗi -> needs_attention + fail, KHÔNG copy audio-only.
  # - audio_only_fallback: render lỗi (không phải exit 8) -> copy audio-only; exit 8 vẫn fail.
  # - warn: gate warn -> vẫn render, không fail.
  if [[ "$subtitle_render_status" -eq 8 ]]; then
    echo "FAIL: Subtitle readability gate fail (exit 8) — layout/font không đạt; không tạo final_video_vi.mp4."
    rm -f "$FINAL_VIDEO"
    status_update "needs_attention" "97" "Render phụ đề Việt không đạt gate đọc chữ" "0" "SubtitleLayoutGateFail" "renderer exit 8 (median_fill thấp / small_cue_ratio cao / font thiếu glyph); bấm Chạy tiếp từ job cũ, kiểm font/band hoặc đặt VI_SUBTITLE_LAYOUT_GATE=warn."
    fail "Render phụ đề Việt không đạt gate đọc chữ (exit 8); xem *.subtitle_layout_report.json / *.subtitle_readability_report.json / *.subtitle_font_report.json."
  fi
  if [[ "$subtitle_render_status" -ne 0 || ! -s "$FINAL_VIDEO" ]]; then
    if [[ "$render_policy" == "audio_only_fallback" ]]; then
      echo "WARN: Render phụ đề Việt/mask sub Trung lỗi exit=$subtitle_render_status; SUBTITLE_RENDER_FAILURE_POLICY=audio_only_fallback -> dùng video audio-only."
      cp "$AUDIO_ONLY_VIDEO" "$FINAL_VIDEO"
    else
      echo "FAIL: Render phụ đề Việt lỗi exit=$subtitle_render_status; SUBTITLE_RENDER_FAILURE_POLICY=$render_policy -> không tạo final_video_vi.mp4 (không che lỗi bằng audio-only)."
      rm -f "$FINAL_VIDEO"
      status_update "needs_attention" "97" "Render phụ đề Việt lỗi" "0" "SubtitleRenderFail" "renderer exit=$subtitle_render_status; bấm Chạy tiếp từ job cũ khi ffmpeg/font sẵn sàng, hoặc set SUBTITLE_RENDER_FAILURE_POLICY=audio_only_fallback."
      fail "Render phụ đề Việt lỗi exit=$subtitle_render_status (policy=$render_policy); không fallback audio-only để tránh che lỗi 'không hiện sub'."
    fi
  fi
else
  if [[ "$render_policy" == "audio_only_fallback" ]]; then
    echo "Bỏ qua burn-in phụ đề Việt; dùng video audio-only làm final."
    cp "$AUDIO_ONLY_VIDEO" "$FINAL_VIDEO"
  else
    echo "BURN_VIET_SUBTITLE=0 và SUBTITLE_RENDER_FAILURE_POLICY=$render_policy -> giữ video audio-only làm final (không render sub)."
    cp "$AUDIO_ONLY_VIDEO" "$FINAL_VIDEO"
  fi
fi
append_tts_audio_stage_report "$TTS_AUDIO_STAGE_REPORT_JSON" "final_mix" "$AUDIO_ONLY_VIDEO" "$FINAL_AUDIO_SAMPLE_RATE"
[[ -s "$FINAL_VIDEO" ]] || fail "Không tạo được final_video_vi.mp4"
append_tts_audio_stage_report "$TTS_AUDIO_STAGE_REPORT_JSON" "final_mp4" "$FINAL_VIDEO" "$FINAL_AUDIO_SAMPLE_RATE"
status_update "mux" "86" "Đang kiểm tra duration final" "0"

TIMELINE_REPORT_JSON="$OUT_DIR/timeline_duration_report.json"
python3 - "$VIDEO" "$FINAL_VIDEO" "$MUX_VOICE_WAV" "$TIMELINE_REPORT_JSON" "${MAX_VIDEO_DURATION_DRIFT:-0.1}" "${MAX_AUDIO_VIDEO_DURATION_DRIFT:-0.2}" "$VIDEO_FIT_ACTION" "$FINAL_VIDEO_FREEZE_SECONDS" "$MUX_TARGET_DURATION" <<'PY'
import json, subprocess, sys
from pathlib import Path

input_video, output_video, mixed_audio, report_path, max_video_drift_raw, max_audio_drift_raw, fit_action, freeze_raw, mux_target_raw = sys.argv[1:]
max_video_drift = float(max_video_drift_raw)
max_audio_drift = float(max_audio_drift_raw)
tail_freeze = max(0.0, float(freeze_raw or 0))
mux_target_duration = max(0.0, float(mux_target_raw or 0))

def ffprobe_duration(path: str) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nk=1:nw=1", path,
    ], text=True).strip()
    return float(out)

input_duration = ffprobe_duration(input_video)
output_duration = ffprobe_duration(output_video)
audio_duration = ffprobe_duration(mixed_audio)
expected_output_duration = mux_target_duration if mux_target_duration > 0 else input_duration
video_drift = abs(output_duration - expected_output_duration)
audio_video_drift = abs(audio_duration - output_duration)
source_video_duration_delta = output_duration - input_duration
final_video_policy = "explicit_local_tail_freeze_no_global_retime" if fit_action == "tail_freeze_local" else "keep_original_video_timeline_no_setpts_no_freeze"
report = {
    "input_video_duration": round(input_duration, 3),
    "expected_output_duration": round(expected_output_duration, 3),
    "output_video_duration": round(output_duration, 3),
    "output_audio_duration": round(audio_duration, 3),
    "max_video_duration_drift": max_video_drift,
    "max_audio_video_duration_drift": max_audio_drift,
    "video_duration_drift": round(video_drift, 3),
    "audio_video_duration_drift": round(audio_video_drift, 3),
    "source_video_duration_delta": round(source_video_duration_delta, 3),
    "tail_freeze_seconds": round(tail_freeze, 3),
    "duration_check_passed": video_drift <= max_video_drift and audio_video_drift <= max_audio_drift,
    "master_timeline": "input_video_plus_explicit_local_tail_freeze" if fit_action == "tail_freeze_local" else "input_video",
    "final_video_policy": final_video_policy,
}
Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Duration check: input={input_duration:.3f}s expected={expected_output_duration:.3f}s output={output_duration:.3f}s audio={audio_duration:.3f}s video_drift={video_drift:.3f}s audio_drift={audio_video_drift:.3f}s policy={final_video_policy}")
if not report["duration_check_passed"]:
    raise SystemExit("Duration check failed: output không khớp timeline mux kỳ vọng")
PY
FINAL_MIX_QUALITY_REPORT_JSON="$OUT_DIR/final_mix_quality_report.json"
python3 "$SKILL_DIR/final_mix_quality.py" \
  --stage-report "$TTS_AUDIO_STAGE_REPORT_JSON" --voice "$MUX_VOICE_WAV" --music "$SELECTED_BGM_SOURCE" \
  --final "$FINAL_VIDEO" --timeline-report "$TIMELINE_REPORT_JSON" --fit-plan "$FINAL_VIDEO_FIT_PLAN_JSON" \
  --speed-report "$SPEED_REPORT_CSV" \
  --max-output-duration-increase "$MAX_OUTPUT_DURATION_INCREASE" --report-path "$FINAL_MIX_QUALITY_REPORT_JSON"
[[ -s "$FINAL_MIX_QUALITY_REPORT_JSON" ]] || fail "Không tạo được final_mix_quality_report.json"
status_update "mux" "88" "Ghép video và duration check xong" "0"

cp "$VIETNAMESE_SRT" "$BASE_DIR/translated/vietnamese-$RUN_ID.srt"
cp "$FINAL_VIDEO" "$BASE_DIR/final_video_vi.mp4"
cp "$VIETNAMESE_SRT" "$BASE_DIR/vietnamese.srt"
printf '%s\n' "$INPUT" > "$LATEST_SOURCE_TXT"
printf '%s\n' "$OUT_DIR" > "$LATEST_OUTPUT_TXT"

if [[ "${AUTO_THUMBNAIL:-${YOUTUBE_THUMBNAIL_AUTO:-1}}" != "0" ]]; then
  if [[ -x "$THUMBNAIL_SCRIPT" ]]; then
    echo "Đang tạo thumbnail YouTube tự động bằng Google Flow/Chrome CDP..."
    status_update "thumbnail" "89" "Đang tạo thumbnail Google Flow/local" "0"
    set +e
    "$THUMBNAIL_SCRIPT" "$OUT_DIR"
    thumbnail_status=$?
    set -e
    if [[ "$thumbnail_status" -ne 0 ]]; then
      echo "WARN: Tạo thumbnail Google Flow thất bại với exit=$thumbnail_status; video vẫn hoàn tất. Nếu cần, đăng nhập/xử lý Google Flow trong Chrome CDP rồi chạy lại thumbnail-only. Xem google_flow_thumbnail.log hoặc google_flow_debug nếu có."
      status_update "thumbnail" "94" "Thumbnail lỗi, video vẫn hoàn tất" "0" "ThumbnailFailed" "Google Flow thumbnail exit=$thumbnail_status"
    elif [[ -s "$THUMBNAIL_FILE" ]]; then
      echo "thumbnail.jpg: $THUMBNAIL_FILE"
      status_update "thumbnail" "96" "Thumbnail xong" "0"
      if [[ -s "$OUT_DIR/THUMBNAIL_NEEDS_ATTENTION.txt" ]]; then
        echo "WARN_USER_ACTION_REQUIRED: Google Flow cần anh Hào can thiệp; thumbnail hiện tại là bản fallback local. Chi tiết: $OUT_DIR/THUMBNAIL_NEEDS_ATTENTION.txt"
      fi
    else
      echo "WARN: Thumbnail script chạy xong nhưng chưa thấy $THUMBNAIL_FILE"
    fi
  else
    echo "WARN: Không tìm thấy thumbnail script executable tại $THUMBNAIL_SCRIPT; bỏ qua tạo thumbnail."
  fi
else
  echo "Bỏ qua tạo thumbnail vì AUTO_THUMBNAIL/YOUTUBE_THUMBNAIL_AUTO=0"
fi

ORGANIZED_VIDEO=""
ORGANIZED_THUMBNAIL=""

# FINAL quality gate trước khi organize vào "Phim đã xử lý":
# - vietnamese.srt phải là tiếng Việt (không fallback tiếng Trung)
# - dub.srt không được toàn tiếng Trung
# - tts_alignment_report phải có ít nhất 1 segment giọng thật (không toàn silence)
# Nếu fail: KHÔNG organize, giữ trong job dir, dashboard báo lỗi.
final_gate_ok=1
voice_sync_report_gate_code=""
voice_sync_report_gate_message=""
if ! srt_looks_vietnamese "$VIETNAMESE_SRT" "$ORIGINAL_SRT" 2>/dev/null; then
  echo "FINAL_GATE_FAIL: vietnamese.srt không phải tiếng Việt -> không organize." >&2
  final_gate_ok=0
fi
if [[ -s "$DUB_SRT" ]] && ! srt_looks_vietnamese "$DUB_SRT" "$ORIGINAL_SRT" 2>/dev/null; then
  echo "FINAL_GATE_FAIL: dub.srt vẫn tiếng Trung -> không organize." >&2
  final_gate_ok=0
fi
if [[ -f "$OUT_DIR/tts_alignment_report.json" ]]; then
  if ! python3 - "$OUT_DIR/tts_alignment_report.json" >/dev/null 2>&1 <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
s = d.get('stats', {})
total = s.get('entries', 0) or 0
silence = s.get('tts_silence_fallback_segments', 0) or 0
cb = s.get('tts_circuit_breaker_segments', 0) or 0
capcut = s.get('capcut_segments', 0) or 0
capcut_fb = s.get('capcut_fallback_edge_segments', 0) or 0
real = max(0, total - silence - cb) + capcut + capcut_fb
sys.exit(0 if real > 0 else 1)
PY
  then
    echo "FINAL_GATE_FAIL: TTS toàn silence, không có giọng thật -> không organize." >&2
    final_gate_ok=0
  fi
fi
# Voice-sync report is mandatory after TTS/render.  Missing or malformed must not
# silently permit organization; explicit ok/warning preserve the established pass path.
voice_sync_report_gate="$(python3 - "$SKILL_DIR" "$OUT_DIR/voice_sync_quality_report.json" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from voice_sync_status import final_report_status
path = Path(sys.argv[2])
result = final_report_status(path.read_text(encoding='utf-8') if path.is_file() else None)
if result:
    print(result['error_code'] + '\t' + result['message'])
PY
)"
if [[ -n "$voice_sync_report_gate" ]]; then
  IFS=$'\t' read -r voice_sync_report_gate_code voice_sync_report_gate_message <<< "$voice_sync_report_gate"
  echo "FINAL_GATE_FAIL: $voice_sync_report_gate_code -> không organize." >&2
  final_gate_ok=0
fi
if [[ "$final_gate_ok" -ne 1 ]]; then
  echo "ERROR: Final quality gate fail. Giữ output trong job dir, KHÔNG copy vào 'Phim đã xử lý'." >&2
  if [[ -n "$voice_sync_report_gate_code" ]]; then
    status_update "needs_attention" "97" "Voice-sync report không hợp lệ, chưa organize" "0" "$voice_sync_report_gate_code" "$voice_sync_report_gate_message"
    echo "Output giữ lại tại: $OUT_DIR" >&2
    exit 1
  fi
  status_update "needs_attention" "97" "Output lỗi (bản dịch/TTS fail), chưa organize" "0" "FinalQualityGateFail" "vietnamese.srt/dub.srt tiếng Trung, TTS toàn silence, hoặc voice-sync fail; bấm Chạy tiếp từ job cũ khi 9Router/TTS sẵn sàng."
  fail "Final quality gate fail: bản dịch hoặc TTS lỗi. Output giữ trong job dir, không organize."
fi

if [[ "${ORGANIZE_OUTPUT:-1}" != "0" ]]; then
  if [[ -x "$ORGANIZE_OUTPUT_SCRIPT" ]]; then
    echo "Đang sắp xếp video final vào thư mục Phim đã xử lý..."
    status_update "organize" "97" "Đang sắp xếp output" "0"
    set +e
    organize_output_json="$(python3 "$ORGANIZE_OUTPUT_SCRIPT" --job-dir "$OUT_DIR" --base-dir "$BASE_DIR" 2>&1)"
    organize_status=$?
    set -e
    if [[ "$organize_status" -eq 0 ]]; then
      echo "$organize_output_json" > "$OUT_DIR/organize_output.log"
      ORGANIZED_VIDEO="$(python3 - "$FINAL_METADATA_JSON" <<'PY'
import json, sys
try:
    data=json.load(open(sys.argv[1], encoding='utf-8'))
    print((data.get('outputs') or {}).get('video') or '')
except Exception:
    print('')
PY
)"
      ORGANIZED_THUMBNAIL="$(python3 - "$FINAL_METADATA_JSON" <<'PY'
import json, sys
try:
    data=json.load(open(sys.argv[1], encoding='utf-8'))
    print((data.get('outputs') or {}).get('thumbnail') or '')
except Exception:
    print('')
PY
)"
      echo "organized_video: $ORGANIZED_VIDEO"
      if [[ -n "$ORGANIZED_THUMBNAIL" ]]; then
        echo "organized_thumbnail: $ORGANIZED_THUMBNAIL"
      fi
    else
      echo "WARN: organize_output.py thất bại exit=$organize_status; video vẫn hoàn tất. Output: $organize_output_json"
    fi
  else
    echo "WARN: Không tìm thấy organize_output.py executable tại $ORGANIZE_OUTPUT_SCRIPT; bỏ qua sắp xếp thư viện."
  fi
else
  echo "Bỏ qua sắp xếp output vì ORGANIZE_OUTPUT=0"
fi
END_TS="$(date +%s)"
ELAPSED="$((END_TS - START_TS))"
echo "HOÀN TẤT"
status_update "completed" "100" "Hoàn tất video" "0"
echo "source_input.txt: $SOURCE_INPUT_TXT"
echo "original.srt: $ORIGINAL_SRT"
echo "vietnamese.srt: $VIETNAMESE_SRT"
echo "dub.srt: $DUB_SRT"
if [[ -s "$DUBBING_REPORT_JSON" ]]; then
  echo "dubbing_report.json: $DUBBING_REPORT_JSON"
fi
if [[ -s "$TIMELINE_REPORT_JSON" ]]; then
  echo "timeline_duration_report.json: $TIMELINE_REPORT_JSON"
fi
echo "vietnamese_voice.wav: $VIETNAMESE_VOICE_WAV"
echo "final_video_vi.mp4: $FINAL_VIDEO"
if [[ -s "$THUMBNAIL_FILE" ]]; then
  echo "thumbnail.jpg: $THUMBNAIL_FILE"
fi
if [[ -n "$ORGANIZED_VIDEO" ]]; then
  echo "organized_video: $ORGANIZED_VIDEO"
fi
if [[ -n "$ORGANIZED_THUMBNAIL" ]]; then
  echo "organized_thumbnail: $ORGANIZED_THUMBNAIL"
fi
if [[ -s "$FINAL_METADATA_JSON" ]]; then
  echo "final_metadata.json: $FINAL_METADATA_JSON"
fi
if [[ "${AUTO_TELEGRAM_RESULT:-1}" != "0" ]]; then
  if [[ -x "$TELEGRAM_RESULT_SCRIPT" ]]; then
    echo "Đang gửi link kết quả qua Telegram/Google Drive..."
    status_update "telegram" "99" "Đang gửi link Google Drive qua Telegram" "0"
    set +e
    timeout "$TELEGRAM_RESULT_TIMEOUT" "$TELEGRAM_RESULT_SCRIPT" "$OUT_DIR"
    telegram_result_status=$?
    set -e
    if [[ "$telegram_result_status" -ne 0 ]]; then
      echo "WARN: Gửi Telegram/Google Drive thất bại exit=$telegram_result_status; video vẫn hoàn tất. Có thể chạy lại: $TELEGRAM_RESULT_SCRIPT '$OUT_DIR'"
      status_update "completed" "100" "Hoàn tất video (Telegram lỗi exit=$telegram_result_status)" "0"
    else
      echo "telegram_result: sent"
      status_update "completed" "100" "Hoàn tất video và đã gửi Telegram" "0"
    fi
  else
    echo "WARN: Không tìm thấy TELEGRAM_RESULT_SCRIPT executable tại $TELEGRAM_RESULT_SCRIPT; bỏ qua gửi Telegram."
    status_update "completed" "100" "Hoàn tất video (bỏ qua Telegram)" "0"
  fi
else
  echo "Bỏ qua gửi Telegram vì AUTO_TELEGRAM_RESULT=0"
  status_update "completed" "100" "Hoàn tất video" "0"
fi
echo "latest_final_video: $BASE_DIR/final_video_vi.mp4"
echo "latest_vietnamese_srt: $BASE_DIR/vietnamese.srt"
echo "latest_source_url: $LATEST_SOURCE_TXT"
echo "latest_output_dir: $LATEST_OUTPUT_TXT"
echo "log.txt: $LOG"
echo "Tổng thời gian xử lý: ${ELAPSED} giây"
