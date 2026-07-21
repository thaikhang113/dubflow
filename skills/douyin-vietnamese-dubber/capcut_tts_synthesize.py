#!/usr/bin/env python3
"""Wrapper synth 1 câu CapCut TTS thành file MP3.

Tạo task `tts-new`, poll `tts-query` đến khi `status == success`, tìm URL audio
trong payload (defensive multi-field) rồi tải MP3 xuống `--output`.

Exit code:
  0  thành công, ghi MP3 + JSON metadata
  2  invalid args
  3  network/API error sau khi đã hết retry
  4  task fail / status không phải success trong timeout
  5  không tìm được audio url trong payload
  6  tải audio url thất bại
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from copy import deepcopy
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
CLIENT_PATH = SKILL_DIR / "capcut_common_task_client.py"
if not CLIENT_PATH.exists():
    print(f"CapCutTTS:CLIENT_MISSING path={CLIENT_PATH}", file=sys.stderr)
    sys.exit(3)

sys.path.insert(0, str(SKILL_DIR))
import capcut_common_task_client as cc  # noqa: E402

try:
    import requests  # noqa: F401
except Exception:
    print("CapCutTTS:REQUESTS_MISSING pip install requests", file=sys.stderr)
    sys.exit(3)


def load_device(device_json_path: str | None) -> dict:
    device = deepcopy(cc.DEFAULT_DEVICE)
    if device_json_path:
        try:
            with open(device_json_path, "r", encoding="utf-8") as fp:
                override = json.load(fp)
            if isinstance(override, dict):
                device.update(override)
        except Exception as e:
            print(f"CapCutTTS:DEVICE_JSON_ERROR {e}", file=sys.stderr)
    return device


def post_json(url: str, headers: dict, body_text: str, timeout: int) -> dict:
    import requests
    resp = requests.post(url, headers=headers, data=body_text.encode("utf-8"), timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"http_{resp.status_code} body={resp.text[:300]}")
    try:
        return resp.json()
    except Exception as e:
        raise RuntimeError(f"json_parse_error {e} body={resp.text[:300]}")


def build_query_url_and_headers(device: dict, task_id: str, token: str):
    body_dict = cc.query_body(task_id, token, "sami_text_to_speech", "")
    body_text = cc.compact_json(body_dict)
    query = cc.common_query(device, None, include_region=False)
    url = cc.BASE + "/lv/v1/common_task/query?" + urlencode_query(query)
    headers = cc.base_headers(device, body_text, appid=True)
    lower = {k.lower(): v for k, v in headers.items()}
    if "sign" not in lower:
        headers["sign"] = cc.make_sign_header(url, device["appvr"], lower["device-time"], device["tdid"])
    return url, headers, body_text


def urlencode_query(d: dict) -> str:
    from urllib.parse import urlencode
    return urlencode(d)


def create_tts_task(device: dict, text: str, voice: str, resource_id: str, rate: str, timeout: int) -> tuple[str, str]:
    babi, body = cc.tts_new_body([text], voice, resource_id, rate, device)
    body_text = cc.compact_json(body)
    query = cc.common_query(device, babi, include_region=True)
    url = cc.BASE + "/lv/v1/common_task/new?" + urlencode_query(query)
    headers = cc.base_headers(device, body_text, appid=True)
    lower = {k.lower(): v for k, v in headers.items()}
    if "sign" not in lower:
        headers["sign"] = cc.make_sign_header(url, device["appvr"], lower["device-time"], device["tdid"])
    data = post_json(url, headers, body_text, timeout)
    if not isinstance(data, dict):
        raise RuntimeError(f"bad_new_response not_dict")
    inner = (data.get("data") or {}).get("tasks") or []
    if not inner:
        raise RuntimeError(f"no_tasks_in_new_response code={data.get('code')} msg={data.get('msg')}")
    task = inner[0]
    task_id = task.get("id")
    token = task.get("token")
    if not task_id or not token:
        raise RuntimeError(f"missing_task_id_or_token task={json.dumps(task)[:300]}")
    return task_id, token


URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+\.(?:mp3|m4a|wav|ogg|aac)(?:\?[^\s\"'<>]*)?", re.IGNORECASE)


def find_audio_url(payload_obj) -> str | None:
    """Quét đệ quy mọi value trong payload tìm URL audio.

    CapCut chưa tài liệu nội bộ; ta bắt mọi key kiểu audio_url/url/audio/result/output_url
    và mọi chuỗi trông như URL audio.
    """
    candidate_keys = {
        "audio_url", "audioUrl", "audio", "url", "audio_uri", "audio_path",
        "output_url", "outputUrl", "result_url", "resultUrl", "media_url",
        "tts_url", "voice_url", "voice_audio_url", "speech_url", "speechUrl",
    }

    found = []

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and v.startswith("http") and k in candidate_keys:
                    found.append(v)
                walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)
        elif isinstance(obj, str):
            for m in URL_PATTERN.findall(obj):
                found.append(m)

    walk(payload_obj)
    if not found:
        return None
    found.sort(key=lambda u: (
        0 if "mime_type=audio" in u.lower() else 1,
        0 if any(u.lower().split("?", 1)[0].endswith(ext) for ext in (".mp3", ".m4a", ".wav", ".ogg", ".aac")) else 1,
        len(u),
    ))
    return found[0]


def poll_until_done(device: dict, task_id: str, token: str, timeout_total: int, poll_interval: float) -> dict:
    url, headers, body_text = build_query_url_and_headers(device, task_id, token)
    deadline = time.time() + max(5, timeout_total)
    last = None
    while time.time() < deadline:
        try:
            resp = post_json(url, headers, body_text, timeout=15)
        except Exception as e:
            last = {"_error": str(e)}
            time.sleep(poll_interval)
            continue
        last = resp
        tasks = (resp.get("data") or {}).get("tasks") or []
        if tasks:
            t = tasks[0]
            status = (t.get("status") or "").lower()
            if status in ("success", "succeed", "succeeded", "done", "finished", "finish"):
                return resp
            if status in ("failed", "fail", "error"):
                raise RuntimeError(f"task_failed status={status} task={json.dumps(t)[:300]}")
        time.sleep(poll_interval)
    raise TimeoutError(f"poll_timeout last={json.dumps(last)[:300] if last else 'no_response'}")


def download_to(url: str, dest: Path, timeout: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"download_http_{resp.status}")
        data = resp.read()
    if len(data) < 256:
        raise RuntimeError(f"download_too_small bytes={len(data)}")
    dest.write_bytes(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--voice", required=True, help="capcut voice_type, vd BV074_streaming")
    ap.add_argument("--resource-id", required=True)
    ap.add_argument("--rate", default="1.0")
    ap.add_argument("--output", required=True, help="đường dẫn MP3 output")
    ap.add_argument("--device-json", default=None)
    ap.add_argument("--timeout-create", type=int, default=int(os.environ.get("CAPCUT_TTS_TIMEOUT_CREATE", "15")))
    ap.add_argument("--timeout-total", type=int, default=int(os.environ.get("CAPCUT_TTS_TIMEOUT_TOTAL", "45")))
    ap.add_argument("--poll-interval", type=float, default=float(os.environ.get("CAPCUT_TTS_POLL_INTERVAL", "1.0")))
    ap.add_argument("--debug-dir", default=None, help="thư mục dump request/response để chẩn đoán")
    args = ap.parse_args()

    text = args.text.strip()
    if not text:
        print("CapCutTTS:EMPTY_TEXT", file=sys.stderr)
        return 2
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    device = load_device(args.device_json)
    debug_dir = Path(args.debug_dir) if args.debug_dir else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    try:
        task_id, token = create_tts_task(device, text, args.voice, args.resource_id, args.rate, args.timeout_create)
    except Exception as e:
        print(f"CapCutTTS:CREATE_FAILED {e}", file=sys.stderr)
        return 3

    try:
        resp = poll_until_done(device, task_id, token, args.timeout_total, args.poll_interval)
    except TimeoutError as e:
        print(f"CapCutTTS:POLL_TIMEOUT {e}", file=sys.stderr)
        return 4
    except Exception as e:
        print(f"CapCutTTS:POLL_FAILED {e}", file=sys.stderr)
        return 4

    if debug_dir:
        try:
            (debug_dir / f"resp_{task_id}.json").write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    tasks = (resp.get("data") or {}).get("tasks") or []
    payload_obj = None
    if tasks:
        raw_payload = tasks[0].get("payload")
        if isinstance(raw_payload, str):
            try:
                payload_obj = json.loads(raw_payload)
            except Exception:
                payload_obj = raw_payload
        else:
            payload_obj = raw_payload

    audio_url = find_audio_url(payload_obj if payload_obj is not None else resp)
    if not audio_url:
        print(f"CapCutTTS:NO_AUDIO_URL task_id={task_id}", file=sys.stderr)
        if debug_dir is None:
            print("CapCutTTS:HINT pass --debug-dir để dump response cho lần đầu probe.", file=sys.stderr)
        return 5

    try:
        download_to(audio_url, out_path, timeout=int(os.environ.get("CAPCUT_TTS_DOWNLOAD_TIMEOUT", "30")))
    except Exception as e:
        print(f"CapCutTTS:DOWNLOAD_FAILED {e} url={audio_url[:120]}", file=sys.stderr)
        return 6

    meta = {
        "task_id": task_id,
        "voice": args.voice,
        "resource_id": args.resource_id,
        "rate": args.rate,
        "audio_url": audio_url,
        "bytes": out_path.stat().st_size,
    }
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
