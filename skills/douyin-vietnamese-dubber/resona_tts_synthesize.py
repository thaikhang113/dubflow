#!/usr/bin/env python3
"""Wrapper synth 1 câu Resona TTS thành WAV ở TTS master format (mặc định 48 kHz).

Resona API (REST chuẩn + Bearer token):
  1. POST   /api/v1/generate-speech        -> {request_id}
  2. GET    /api/v1/generate-speech/{id}/status  (poll cho đến completed)
  3. GET    /api/v1/generate-speech/{id}    -> audio_urls[0]
  4. download audio -> ffmpeg convert -> WAV pipeline

Token chỉ đọc từ env (RESONA_API_TOKEN hoặc RESONA_ACCESS_TOKEN), KHÔNG bao giờ print.

Exit code (giữ same ngữ nghĩa với capcut_tts_synthesize.py):
  0  thành công, ghi WAV + in JSON metadata
  2  invalid args (text rỗng / voice rỗng)
  3  auth missing / auth failed (401/403) / quota-rate-limit (429) / network API error tạo request
  4  poll timeout hoặc task failed
  5  không có audio_urls trong result
  6  tải/convert audio thất bại
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

DEFAULT_API_BASE = "https://resona.live"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/126.0.0.0 Safari/537.36 OpenClaw/ResonaTTS"
)

# Marker stderr để run.sh map error_code chính xác.
MARKER_AUTH_MISSING = "ResonaAuthMissing"
MARKER_AUTH_FAILED = "ResonaAuthFailed"
MARKER_QUOTA = "ResonaQuotaFailed"
MARKER_TIMEOUT = "ResonaTimeout"
MARKER_NO_AUDIO = "ResonaNoAudioUrl"


def get_token() -> str | None:
    return os.environ.get("RESONA_API_TOKEN") or os.environ.get("RESONA_ACCESS_TOKEN")


def auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
        "Origin": "https://resona.live",
        "Referer": "https://resona.live/",
    }


def normalize_speaker_lines(text: str) -> str:
    """Resona API requires every non-empty line to start with `Speaker N:`."""
    lines = []
    speaker_re = re.compile(r"^\s*Speaker\s+\d+\s*:", re.IGNORECASE)
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if speaker_re.match(line):
            lines.append(line)
        else:
            lines.append(f"Speaker 1: {line}")
    return "\n".join(lines)


def _redact(obj):
    """Bỏ trường nhạy cảm trước khi dump debug. Không print token bao giờ."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in {"authorization", "token", "access_token", "api_token", "resona_api_token", "resona_access_token"}:
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def post_json(url: str, headers: dict, body: dict, timeout: int) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read()
    except urllib.error.HTTPError as e:
        code = e.code
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if code in (401, 403):
            print(f"{MARKER_AUTH_FAILED} http_{code} body={body_text}", file=sys.stderr)
            sys.exit(3)
        if code == 429:
            print(f"{MARKER_QUOTA} http_429 body={body_text}", file=sys.stderr)
            sys.exit(3)
        raise RuntimeError(f"http_{code} body={body_text}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"network_error {e}")
    if status != 200:
        raise RuntimeError(f"http_{status}")
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        raise RuntimeError(f"json_parse_error {e} body={raw[:300]!r}")


def get_json(url: str, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read()
    except urllib.error.HTTPError as e:
        code = e.code
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if code in (401, 403):
            print(f"{MARKER_AUTH_FAILED} http_{code} body={body_text}", file=sys.stderr)
            sys.exit(3)
        if code == 429:
            print(f"{MARKER_QUOTA} http_429 body={body_text}", file=sys.stderr)
            sys.exit(3)
        raise RuntimeError(f"http_{code} body={body_text}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"network_error {e}")
    if status != 200:
        raise RuntimeError(f"http_{status}")
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        raise RuntimeError(f"json_parse_error {e} body={raw[:300]!r}")


def create_request(api_base: str, headers: dict, text: str, voice_id: str, timeout: int) -> str:
    url = f"{api_base.rstrip('/')}/api/v1/generate-speech"
    body = {"text": normalize_speaker_lines(text), "voice_ids": [voice_id], "language": "vi"}
    data = post_json(url, headers, body, timeout)
    request_id = None
    if isinstance(data, dict):
        request_id = data.get("request_id") or data.get("id") or (data.get("data") or {}).get("request_id")
    if not request_id:
        raise RuntimeError(f"no_request_id resp={json.dumps(data, ensure_ascii=False)[:300]}")
    return str(request_id)


def poll_status(api_base: str, headers: dict, request_id: str, timeout_total: int, poll_interval: float) -> dict:
    url = f"{api_base.rstrip('/')}/api/v1/generate-speech/{request_id}/status"
    deadline = time.time() + max(5, timeout_total)
    last = None
    while time.time() < deadline:
        try:
            resp = get_json(url, headers, timeout=15)
        except SystemExit:
            raise
        except Exception as e:
            last = {"_error": str(e)}
            time.sleep(poll_interval)
            continue
        last = resp
        status = ""
        if isinstance(resp, dict):
            status = str(resp.get("status") or (resp.get("data") or {}).get("status") or "").lower()
        if status in ("completed", "complete", "done", "success", "succeeded", "ready"):
            return resp
        if status in ("failed", "error", "cancelled", "canceled"):
            raise RuntimeError(f"task_failed status={status} resp={json.dumps(resp, ensure_ascii=False)[:300]}")
        time.sleep(poll_interval)
    print(f"{MARKER_TIMEOUT} deadline_exceeded last={json.dumps(last, ensure_ascii=False)[:300] if last else 'no_response'}", file=sys.stderr)
    sys.exit(4)


def fetch_result(api_base: str, headers: dict, request_id: str, timeout: int) -> dict:
    url = f"{api_base.rstrip('/')}/api/v1/generate-speech/{request_id}"
    return get_json(url, headers, timeout)


def find_audio_url(result: dict) -> str | None:
    if not isinstance(result, dict):
        return None
    candidates = []
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    audio_urls = data.get("audio_urls") if isinstance(data, dict) else None
    if isinstance(audio_urls, list) and audio_urls:
        for u in audio_urls:
            if isinstance(u, str) and u.startswith("http"):
                candidates.append(u)
    if not candidates and isinstance(data, dict):
        for key in ("audio_url", "url", "output_url", "result_url"):
            v = data.get(key)
            if isinstance(v, str) and v.startswith("http"):
                candidates.append(v)
                break
    # Fallback: quét string URL .mp3/.m4a/.wav/.ogg/.aac trong toàn response.
    if not candidates:
        pattern = re.compile(r"https?://[^\s\"'<>]+\.(?:mp3|m4a|wav|ogg|aac)(?:\?[^\s\"'<>]*)?", re.IGNORECASE)
        found = pattern.findall(json.dumps(result, ensure_ascii=False))
        candidates = found
    return candidates[0] if candidates else None


def download_to(url: str, dest: Path, timeout: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if getattr(resp, "status", 200) != 200:
            raise RuntimeError(f"download_http_{getattr(resp, 'status', 0)}")
        data = resp.read()
    if len(data) < 256:
        raise RuntimeError(f"download_too_small bytes={len(data)}")
    dest.write_bytes(data)


def convert_to_wav(src: Path, wav: Path, sample_rate: int, channels: int) -> float:
    """ffmpeg -> TTS master WAV PCM; không dùng format 16 kHz mono của ASR."""
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", str(sample_rate), "-ac", str(channels), "-c:a", "pcm_s16le", str(wav)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(wav)],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        return max(0.0, float((proc.stdout or "0").strip() or 0.0)) * 1000.0
    except Exception:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--voice", required=True, help="Resona voice_id")
    ap.add_argument("--output", required=True, help="đường dẫn WAV output ở TTS master format")
    ap.add_argument("--sample-rate", type=int, default=int(os.environ.get("TTS_MASTER_SAMPLE_RATE", "48000")))
    ap.add_argument("--channels", type=int, default=int(os.environ.get("TTS_MASTER_CHANNELS", "1")))
    ap.add_argument("--api-base", default=os.environ.get("RESONA_API_BASE", DEFAULT_API_BASE))
    ap.add_argument("--timeout-create", type=int, default=int(os.environ.get("RESONA_TTS_TIMEOUT_CREATE", "20")))
    ap.add_argument("--timeout-total", type=int, default=int(os.environ.get("RESONA_TIMEOUT_SECONDS", "180")))
    ap.add_argument("--poll-interval", type=float, default=float(os.environ.get("RESONA_POLL_INTERVAL_SECONDS", "2")))
    ap.add_argument("--download-timeout", type=int, default=int(os.environ.get("RESONA_TTS_DOWNLOAD_TIMEOUT", "30")))
    ap.add_argument("--debug-dir", default=None, help="thư mục dump request/response (token redact)")
    args = ap.parse_args()

    text = (args.text or "").strip()
    if not text:
        print("ResonaTTS:EMPTY_TEXT", file=sys.stderr)
        return 2
    voice_id = (args.voice or "").strip()
    if not voice_id:
        print("ResonaTTS:EMPTY_VOICE", file=sys.stderr)
        return 2

    token = get_token()
    if not token:
        print(f"{MARKER_AUTH_MISSING} thiếu env RESONA_API_TOKEN/RESONA_ACCESS_TOKEN", file=sys.stderr)
        return 3

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    debug_dir = Path(args.debug_dir) if args.debug_dir else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    headers = auth_headers(token)
    api_base = args.api_base or DEFAULT_API_BASE

    try:
        request_id = create_request(api_base, headers, text, voice_id, args.timeout_create)
    except SystemExit:
        raise
    except Exception as e:
        print(f"ResonaTTS:CREATE_FAILED {e}", file=sys.stderr)
        return 3

    try:
        poll_status(api_base, headers, request_id, args.timeout_total, args.poll_interval)
    except SystemExit:
        raise
    except Exception as e:
        msg = str(e)
        if "task_failed" in msg:
            if "No generated" in msg or "no generated" in msg:
                print(f"{MARKER_NO_AUDIO} task_failed request_id={request_id}", file=sys.stderr)
                return 5
            print(f"ResonaTTS:TASK_FAILED {msg}", file=sys.stderr)
            return 4
        print(f"ResonaTTS:POLL_FAILED {msg}", file=sys.stderr)
        return 4

    try:
        result = fetch_result(api_base, headers, request_id, args.timeout_create)
    except SystemExit:
        raise
    except Exception as e:
        print(f"ResonaTTS:FETCH_FAILED {e}", file=sys.stderr)
        return 4

    if debug_dir:
        try:
            (debug_dir / f"resp_{request_id}.json").write_text(
                json.dumps(_redact(result), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    audio_url = find_audio_url(result)
    if not audio_url:
        print(f"{MARKER_NO_AUDIO} request_id={request_id}", file=sys.stderr)
        return 5

    tmp_audio = out_path.with_suffix(out_path.suffix + ".src")
    try:
        download_to(audio_url, tmp_audio, timeout=args.download_timeout)
    except Exception as e:
        print(f"ResonaTTS:DOWNLOAD_FAILED {e} url={audio_url[:120]}", file=sys.stderr)
        return 6

    try:
        duration_ms = convert_to_wav(
            tmp_audio,
            out_path,
            max(8000, int(args.sample_rate)),
            max(1, min(2, int(args.channels))),
        )
    except Exception as e:
        print(f"ResonaTTS:CONVERT_FAILED {e}", file=sys.stderr)
        return 6
    finally:
        try:
            tmp_audio.unlink(missing_ok=True)
        except Exception:
            pass

    meta = {
        "request_id": request_id,
        "voice": voice_id,
        "audio_url": audio_url,
        "bytes": out_path.stat().st_size,
        "duration_ms": duration_ms,
    }
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
