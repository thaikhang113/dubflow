#!/usr/bin/env bash
set -Eeuo pipefail

OUTPUT_DIR="${1:-}"
[[ -n "$OUTPUT_DIR" ]] || { echo "Usage: youtube-thumbnail-auto.sh OUTPUT_DIR" >&2; exit 1; }
[[ -d "$OUTPUT_DIR" ]] || { echo "ERROR: Output dir không tồn tại: $OUTPUT_DIR" >&2; exit 1; }

BASE_DIR="${DOUYIN_VIDEOS_DIR:-/mnt/hdd500/video douyin vietsub}"
IMAGE_API_BASE="${THUMBNAIL_IMAGE_API_BASE:-${NINEROUTER_IMAGE_API_BASE:-http://127.0.0.1:3030/v1}}"
IMAGE_MODEL="${THUMBNAIL_IMAGE_MODEL:-${NINEROUTER_IMAGE_MODEL:-gpt-image-2}}"
IMAGE_API_KEY="${THUMBNAIL_IMAGE_API_KEY:-}"
THUMBNAIL_FILE="$OUTPUT_DIR/thumbnail.jpg"
PROMPT_FILE="$OUTPUT_DIR/thumbnail_prompt.txt"
TITLE_FILE="$OUTPUT_DIR/thumbnail_title.txt"
META_FILE="$OUTPUT_DIR/thumbnail_meta.json"
LATEST_THUMBNAIL_TXT="$BASE_DIR/LATEST_THUMBNAIL.txt"
LATEST_THUMBNAIL_PROMPT_TXT="$BASE_DIR/LATEST_THUMBNAIL_PROMPT.txt"

get_api_key() {
  if [[ -n "$IMAGE_API_KEY" ]]; then
    printf '%s' "$IMAGE_API_KEY"
    return 0
  fi
  if [[ -n "${NINEROUTER_API_KEY:-}" ]]; then
    printf '%s' "$NINEROUTER_API_KEY"
    return 0
  fi
  python3 - <<'PY'
import json, os, sys
candidates = []
if os.environ.get('NINEROUTER_DB_PATH'):
    candidates.append(os.environ['NINEROUTER_DB_PATH'])
for raw in ('~/.9router/db.json', '/home/haonguyen/.9router/db.json', '/app/data/db.json'):
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
sys.exit(1)
PY
}

build_prompt() {
  python3 - "$OUTPUT_DIR" "$IMAGE_MODEL" <<'PY'
import json, os, re, sys
from pathlib import Path
out = Path(sys.argv[1])
model = sys.argv[2]

def read_text(name, limit=9000):
    path = out / name
    if not path.exists():
        return ''
    text = path.read_text(encoding='utf-8', errors='ignore')
    text = re.sub(r'\d+\n\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:limit]

vi = read_text('vietnamese.srt')
orig = read_text('original.srt', 4000)
source = (out / 'source_input.txt').read_text(encoding='utf-8', errors='ignore').strip() if (out / 'source_input.txt').exists() else ''
seed = vi or orig or f'Video source: {source}' or out.name

# Simple deterministic hook/title from Vietnamese transcript. Keep short because AI-drawn text is fragile.
hook = 'BIẾN CỐ GIA TỘC'
keywords = [
    ('lão tổ', 'LÃO TỔ XUẤT QUAN'),
    ('ma vương', 'MA VƯƠNG XUẤT HIỆN'),
    ('sói', 'SÓI TỘC TẤN CÔNG'),
    ('gia tộc', 'BIẾN CỐ GIA TỘC'),
    ('báo thù', 'TRẢ THÙ ĐẪM MÁU'),
    ('tu tiên', 'TU TIÊN ĐẠI CHIẾN'),
]
low = seed.lower()
for needle, title in keywords:
    if needle in low:
        hook = title
        break

prompt = f"""Create a dramatic YouTube thumbnail in 16:9 landscape format for a Vietnamese fantasy cultivation / Chinese animation recap video.
Main visible Vietnamese title text must be exactly: \"{hook}\".
Text style: huge bold Vietnamese letters, high contrast, readable at mobile size, white/red brush-stroke horror-fantasy style, with dark outline and glow.
Scene should match this video content: {seed[:2500]}
Visual direction: cinematic dark fantasy, intense conflict, ancient clan estate at night, powerful young anime-style character, ominous enemies, red-black atmosphere, dramatic lighting, high-detail YouTube thumbnail composition.
Include only one main title phrase. Do not add extra random text, logos, watermarks, subtitles, UI, or misspelled text.
Output should look like a finished clickable YouTube thumbnail.""".strip()

print(json.dumps({'title': hook, 'prompt': prompt, 'model': model, 'source': source}, ensure_ascii=False))
PY
}

API_KEY="$(get_api_key)" || { echo "ERROR: Không lấy được API key cho thumbnail gateway" >&2; exit 1; }
META_JSON="$(build_prompt)"
printf '%s\n' "$META_JSON" > "$META_FILE"
TITLE="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["title"])' < "$META_FILE")"
PROMPT="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["prompt"])' < "$META_FILE")"
printf '%s\n' "$TITLE" > "$TITLE_FILE"
printf '%s\n' "$PROMPT" > "$PROMPT_FILE"

echo "Đang tạo thumbnail YouTube qua image gateway: $IMAGE_API_BASE | model: $IMAGE_MODEL"
HTTP_CODE="$(curl --noproxy '*' -sS -L -o "$THUMBNAIL_FILE.tmp" -w '%{http_code}' \
  --max-time "${THUMBNAIL_IMAGE_TIMEOUT_SECONDS:-180}" \
  -X POST "$IMAGE_API_BASE/images/generations?response_format=binary" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @- <<JSON
{"model":$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$IMAGE_MODEL"),"prompt":$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$PROMPT"),"size":"1792x1024","n":1,"response_format":"b64_json"}
JSON
)" || true

if [[ "$HTTP_CODE" != 2* ]]; then
  echo "ERROR: Image generation HTTP $HTTP_CODE" >&2
  cat "$THUMBNAIL_FILE.tmp" >&2 || true
  rm -f "$THUMBNAIL_FILE.tmp"
  exit 1
fi

if [[ ! -s "$THUMBNAIL_FILE.tmp" ]]; then
  echo "ERROR: Thumbnail response rỗng" >&2
  rm -f "$THUMBNAIL_FILE.tmp"
  exit 1
fi

# Keep exactly one final thumbnail file. 9Router binary may be PNG/JPEG; browser/uploaders accept jpg extension poorly if PNG.
# Detect type and convert to jpg for YouTube-friendly output.
if file "$THUMBNAIL_FILE.tmp" | grep -qi 'PNG image'; then
  ffmpeg -y -i "$THUMBNAIL_FILE.tmp" -frames:v 1 -q:v 2 "$THUMBNAIL_FILE" >/dev/null 2>&1
  rm -f "$THUMBNAIL_FILE.tmp"
else
  mv -f "$THUMBNAIL_FILE.tmp" "$THUMBNAIL_FILE"
fi

[[ -s "$THUMBNAIL_FILE" ]] || { echo "ERROR: Không tạo được thumbnail.jpg" >&2; exit 1; }
printf '%s\n' "$THUMBNAIL_FILE" > "$LATEST_THUMBNAIL_TXT"
printf '%s\n' "$PROMPT_FILE" > "$LATEST_THUMBNAIL_PROMPT_TXT"
echo "HOÀN TẤT thumbnail: $THUMBNAIL_FILE"
echo "thumbnail_title: $TITLE_FILE"
echo "thumbnail_prompt: $PROMPT_FILE"
echo "latest_thumbnail: $LATEST_THUMBNAIL_TXT"
