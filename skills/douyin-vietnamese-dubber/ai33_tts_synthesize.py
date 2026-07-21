#!/usr/bin/env python3
"""Wrapper synth 1 câu AI33 TTS thành WAV theo TTS master format.

AI33 external API:
  1. POST /v3/text-to-speech (multipart form) -> {task_id}
  2. GET  /v1/task/{task_id} until completed
  3. find audio URL in task response, download, ffmpeg convert -> WAV

API key chỉ đọc từ env (AI33_API_KEY hoặc AI33_ACCESS_TOKEN), KHÔNG bao giờ print.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

_CHECKPOINT_SPEC = __import__("importlib.util").util.spec_from_file_location("tts_checkpoint", Path(__file__).with_name("tts_checkpoint.py"))
tts_checkpoint = __import__("importlib.util").util.module_from_spec(_CHECKPOINT_SPEC)
_CHECKPOINT_SPEC.loader.exec_module(tts_checkpoint)

DEFAULT_API_BASE = "https://api.ai33.pro"
DEFAULT_USER_AGENT = "OpenClaw/AI33TTS"

MARKER_AUTH_MISSING = "AI33AuthMissing"
MARKER_AUTH_FAILED = "AI33AuthFailed"
MARKER_QUOTA = "AI33QuotaFailed"
MARKER_TIMEOUT = "AI33Timeout"
MARKER_NO_AUDIO = "AI33NoAudioUrl"


class AI33Error(RuntimeError):
    """Classified, URL-redacted AI33 failure suitable for status/report contracts."""
    def __init__(self, code: str, stage: str, detail: str = "", attempts: int = 0):
        self.code, self.stage, self.detail, self.attempts = code, stage, detail[:300], attempts
        super().__init__(f"{code} stage={stage} attempts={attempts} {self.detail}".strip())


TRANSIENT_CODES = frozenset({
    "AI33CreateRateLimited", "AI33CreateHttp5xx", "AI33CreateTimeout",
    "AI33PollingBusy", "AI33PollingRateLimited", "AI33PollingHttp5xx", "AI33PollingTimeout",
    "AI33DownloadRateLimited", "AI33DownloadHttp5xx", "AI33DownloadTimeout", "AI33DownloadNetwork",
})


class AI33CircuitBreaker:
    """Small, job-scoped AI33 health state; it never stores API credentials or URLs."""
    def __init__(self, path: Path, threshold: int = 2, cooldown_seconds: int = 60, now=None):
        self.path = Path(path)
        self.threshold = max(1, min(10, int(threshold)))
        self.cooldown_seconds = max(5, min(3600, int(cooldown_seconds)))
        self.now = now or time.time

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        return data if isinstance(data, dict) and data.get("provider") == "ai33" else {}

    @contextlib.contextmanager
    def _locked(self):
        """Serialize state transitions across cue subprocesses in one job."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _save(self, data):
        safe = {
            "schema_version": 1, "provider": "ai33", "state": data.get("state", "closed"),
            "consecutive_transient_failures": int(data.get("consecutive_transient_failures", 0) or 0),
            "opened_at": float(data.get("opened_at", 0) or 0), "open_code": str(data.get("open_code", ""))[:80],
            "threshold": self.threshold, "cooldown_seconds": self.cooldown_seconds,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.path, safe)
        return safe

    def snapshot(self):
        with self._locked():
            return self._save(self._load()) if self.path.exists() else self._save({})

    def before_create(self):
        with self._locked():
            data = self._load(); state = data.get("state", "closed"); now = self.now()
            if state == "open":
                if now - float(data.get("opened_at", 0) or 0) < self.cooldown_seconds:
                    raise AI33Error("AI33CircuitOpen", "circuit", str(data.get("open_code", "transient")), 0)
                data["state"] = "half_open"; self._save(data); return True
            if state == "half_open":
                raise AI33Error("AI33CircuitOpen", "circuit", "half_open_probe_in_flight", 0)
            self._save(data); return False

    def record_success(self):
        with self._locked():
            self._save({"state": "closed", "consecutive_transient_failures": 0, "opened_at": 0, "open_code": ""})

    def record_failure(self, error: AI33Error):
        with self._locked():
            data = self._load(); transient = error.code in TRANSIENT_CODES
            failures = int(data.get("consecutive_transient_failures", 0) or 0) + 1 if transient else 0
            # A half-open probe failure always reopens, even if the usual threshold is not met.
            open_now = data.get("state") == "half_open" or not transient or failures >= self.threshold
            data.update({"consecutive_transient_failures": failures})
            if open_now:
                data.update({"state": "open", "opened_at": self.now(), "open_code": error.code})
            else:
                data.update({"state": "closed", "opened_at": 0, "open_code": ""})
            return self._save(data)


def _safe_detail(value) -> str:
    """Never permit a signed media URL into errors, reports, or debug output."""
    return re.sub(r"https?://[^\s\"']+", "<redacted-url>", str(value or "")).replace("\n", " ")[:300]


_atomic_json = tts_checkpoint._atomic_write
_sha256 = tts_checkpoint._sha256


def write_test_wav(path: Path, sample_rate: int, samples: list[int], channels: int = 1) -> None:
    """Small offline fixture writer; kept here so validation tests exercise stdlib WAV parsing."""
    import struct
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels); output.setsampwidth(2); output.setframerate(sample_rate)
        output.writeframes(b"".join(struct.pack("<h", value) for value in samples))


def validate_wav(path: Path, sample_rate: int, channels: int) -> dict:
    try:
        return tts_checkpoint.validate_canonical_wav(path, tts_checkpoint.CheckpointConfig("", "", {}, 1, sample_rate, channels, 1, 1800000))
    except tts_checkpoint.WavValidationError as exc:
        code = {"wav_silent": "AI33WavSilent", "duration_invalid": "AI33WavDurationInvalid"}.get(exc.code, "AI33WavInvalid")
        raise AI33Error(code, "wav_validate", exc.code) from exc


def _checkpoint_config(source_fingerprint, voice_id, settings_hash, total_cues, sample_rate, channels):
    return tts_checkpoint.CheckpointConfig(source_fingerprint, voice_id, {"settings_fingerprint": settings_hash}, total_cues, sample_rate, channels, 1, 1800000)


def reusable_checkpoint_cue(manifest_path: Path, cue_index: int, source_fingerprint: str, text_hash: str, voice_id: str, settings_hash: str, sample_rate: int, channels: int) -> bool:
    total = int(tts_checkpoint.load_checkpoint(manifest_path).get("total_cues") or max(cue_index, 1))
    config = _checkpoint_config(source_fingerprint, voice_id, settings_hash, total, sample_rate, channels)
    # AI33's public cue numbers are one-based; the shared checkpoint schema is zero-based.
    return tts_checkpoint.reusable_cue(manifest_path, config, tts_checkpoint.CueIdentity(cue_index - 1, text_hash, voice_id, config.settings))


def complete_checkpoint_cue(manifest_path: Path, cue_index: int, source_fingerprint: str, text_hash: str, voice_id: str, settings_hash: str, wav_path: Path, sample_rate: int, channels: int, attempts: int, total_cues: int = 0) -> dict:
    config = _checkpoint_config(source_fingerprint, voice_id, settings_hash, total_cues or cue_index, sample_rate, channels)
    return tts_checkpoint.complete_cue(manifest_path, config, tts_checkpoint.CueIdentity(cue_index - 1, text_hash, voice_id, config.settings), wav_path, attempts)


def fail_checkpoint_cue(manifest_path: Path, cue_index: int, source_fingerprint: str, text_hash: str, voice_id: str, settings_hash: str, error: AI33Error, total_cues: int = 0) -> None:
    config = _checkpoint_config(source_fingerprint, voice_id, settings_hash, total_cues or cue_index, 48000, 1)
    tts_checkpoint.record_failure(manifest_path, config, tts_checkpoint.CueIdentity(cue_index - 1, text_hash, voice_id, config.settings), error.stage, error.code, error.attempts)


def materialize_checkpoint_wav(manifest_path: Path, cue_index: int, output_path: Path) -> None:
    """Copy a validated checkpoint into this run's segment path atomically."""
    return tts_checkpoint.materialize_completed_wav(manifest_path, cue_index - 1, output_path)


def classified_error(stage: str, exc: Exception, attempts: int = 0) -> AI33Error:
    """Map boundary failures without leaking provider bodies or signed URLs."""
    detail = _safe_detail(exc)
    lowered = detail.lower()
    if "timed out" in lowered:
        code = {"create": "AI33CreateTimeout", "poll": "AI33PollingTimeout"}.get(stage, "AI33DownloadTimeout")
    elif "http_429" in lowered or " 429" in lowered:
        code = {"create": "AI33CreateRateLimited", "poll": "AI33PollingRateLimited"}.get(stage, "AI33DownloadRateLimited")
    elif "http_" in lowered or "http " in lowered:
        code = {"create": "AI33CreateHttp5xx", "poll": "AI33PollingHttp5xx"}.get(stage, "AI33DownloadHttp5xx")
    else:
        code = {"create": "AI33CreateHttp5xx", "poll": "AI33PollingHttp5xx"}.get(stage, "AI33DownloadNetwork")
    return AI33Error(code, stage, detail, attempts)


class AI33PollingBusy(RuntimeError):
    """A polling-only transient response that should consume the poll deadline."""


def get_token() -> str | None:
    return os.environ.get("AI33_API_KEY") or os.environ.get("AI33_ACCESS_TOKEN")


def base_headers(token: str, content_type: str | None = None) -> dict:
    headers = {
        "xi-api-key": token,
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in {"authorization", "xi-api-key", "api_key", "ai33_api_key", "token", "access_token"}:
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    if isinstance(obj, str) and re.match(r"https?://", obj, re.I):
        return "<redacted-url>"
    return obj


def encode_multipart(fields: dict[str, str], boundary: str) -> bytes:
    chunks = []
    for name, value in fields.items():
        if value is None:
            continue
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks)


def decode_json(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:
        raise RuntimeError(f"json_parse_error {exc} body={raw[:300]!r}") from exc


def is_transient_polling_busy(body_text: str) -> bool:
    """Recognize AI33's temporary task-polling saturation without masking quota errors."""
    return bool(re.search(
        r"\b(?:task\s+)?poll(?:ing)?\s+(?:is\s+)?(?:temporarily\s+)?busy\b",
        body_text or "",
        re.IGNORECASE,
    ))


def handle_http_error(exc: urllib.error.HTTPError, retry_polling_busy: bool = False) -> None:
    body_text = ""
    try:
        body_text = exc.read().decode("utf-8", "replace")[:300]
    except Exception:
        pass
    if exc.code in (401, 403):
        print(f"{MARKER_AUTH_FAILED} http_{exc.code} body={body_text}", file=sys.stderr)
        sys.exit(3)
    if exc.code == 429 and retry_polling_busy and is_transient_polling_busy(body_text):
        raise AI33PollingBusy(f"http_429 polling_busy body={body_text}")
    if exc.code == 429:
        print(f"{MARKER_QUOTA} http_429 body={body_text}", file=sys.stderr)
        sys.exit(3)
    raise RuntimeError(f"http_{exc.code} body={body_text}")


def post_multipart(url: str, headers: dict, fields: dict[str, str], timeout: int) -> dict:
    boundary = "----openclaw-ai33-" + uuid.uuid4().hex
    body = encode_multipart(fields, boundary)
    req_headers = dict(headers)
    req_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        handle_http_error(exc)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error {exc}") from exc
    if not 200 <= status < 300:
        raise RuntimeError(f"http_{status}")
    return decode_json(raw)


def get_json(url: str, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        handle_http_error(exc, retry_polling_busy=True)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error {exc}") from exc
    if not 200 <= status < 300:
        raise RuntimeError(f"http_{status}")
    return decode_json(raw)


def normalize_bool(value: str) -> str:
    return "true" if str(value or "").strip().lower() in {"1", "true", "yes", "on"} else "false"


def extract_task_id(resp: dict) -> str | None:
    if not isinstance(resp, dict):
        return None
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    for obj in (resp, data):
        for key in ("task_id", "taskId", "id"):
            value = obj.get(key)
            if value:
                return str(value)
    return None


def create_task(api_base: str, headers: dict, args) -> dict:
    url = f"{api_base.rstrip('/')}/v3/text-to-speech"
    fields = {
        "text": args.text,
        "voice_id": args.voice,
        "speed": f"{args.speed:.3f}",
        "with_transcript": normalize_bool(args.with_transcript),
        "context_chaining": normalize_bool(args.context_chaining),
        "file_name": args.file_name or f"openclaw-{int(time.time())}",
    }
    if args.receive_url:
        fields["receive_url"] = args.receive_url
    if args.pronunciation_dictionary_id:
        fields["pronunciation_dictionary_id"] = args.pronunciation_dictionary_id
    resp = post_multipart(url, headers, fields, args.timeout_create)
    if isinstance(resp, dict) and resp.get("success") is False:
        raise RuntimeError(f"create_unsuccessful resp={json.dumps(_redact(resp), ensure_ascii=False)[:300]}")
    return resp


def task_payload(resp: dict) -> dict:
    if not isinstance(resp, dict):
        return {}
    data = resp.get("data")
    if isinstance(data, dict):
        return data
    return resp


def task_status(resp: dict) -> str:
    payload = task_payload(resp)
    for key in ("status", "state", "task_status", "taskStatus"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if value:
            return str(value).lower()
    return ""


def poll_task(api_base: str, headers: dict, task_id: str, timeout_total: int, poll_interval: float) -> dict:
    url = f"{api_base.rstrip('/')}/v1/task/{task_id}"
    deadline = time.time() + max(5, timeout_total)
    last = None
    polling_busy_retries = 0
    while time.time() < deadline:
        try:
            resp = get_json(url, headers, timeout=15)
        except SystemExit:
            raise
        except AI33PollingBusy as exc:
            last = {"_error": str(exc)}
            polling_busy_retries += 1
            base_delay = max(0.1, poll_interval)
            backoff = min(8.0, base_delay * (2 ** min(polling_busy_retries, 3)))
            retry_delay = backoff + random.uniform(0.0, min(0.5, backoff * 0.25))
            time.sleep(min(retry_delay, max(0.0, deadline - time.time())))
            continue
        except Exception as exc:
            last = {"_error": str(exc)}
            time.sleep(poll_interval)
            continue
        last = resp
        polling_busy_retries = 0
        status = task_status(resp)
        if find_audio_url(resp):
            return resp
        if status in {"completed", "complete", "done", "success", "succeeded", "ready", "finished"}:
            return resp
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"task_failed status={status} resp={json.dumps(_redact(resp), ensure_ascii=False)[:300]}")
        time.sleep(poll_interval)
    last_text = json.dumps(_redact(last), ensure_ascii=False)[:300] if last else "no_response"
    print(f"{MARKER_TIMEOUT} deadline_exceeded last={last_text}", file=sys.stderr)
    sys.exit(4)


def iter_strings(obj, parent_key=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            joined = f"{parent_key}.{key}" if parent_key else str(key)
            yield from iter_strings(value, joined)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from iter_strings(value, f"{parent_key}[{index}]")
    elif isinstance(obj, str):
        yield parent_key, obj


def find_audio_url(result: dict) -> str | None:
    priority_key_re = re.compile(r"(audio|voice|speech|media|file|download).*(url|path)|url", re.I)
    for key, value in iter_strings(result):
        if value.startswith("http") and priority_key_re.search(key):
            return value
    text = json.dumps(result, ensure_ascii=False)
    pattern = re.compile(r"https?://[^\s\"'<>]+\.(?:mp3|m4a|wav|ogg|aac)(?:\?[^\s\"'<>]*)?", re.IGNORECASE)
    found = pattern.findall(text)
    return found[0] if found else None


def download_with_retry(url: str, dest: Path, timeout: int, max_attempts: int, cue_timeout: int, refresh_url=None, on_retry=None) -> int:
    """Retry only transient CDN failures. `refresh_url` re-polls the same task, never creates one."""
    deadline = time.monotonic() + max(1, cue_timeout)
    current_url = url
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            req = urllib.request.Request(current_url, headers={"User-Agent": DEFAULT_USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, data = getattr(resp, "status", 200), resp.read()
            if not 200 <= status < 300:
                raise AI33Error("AI33DownloadHttp5xx" if status >= 500 else "AI33DownloadHttp4xx", "download", f"http_{status}", attempt)
            if len(data) < 256:
                raise AI33Error("AI33DownloadEmpty", "download", f"bytes={len(data)}", attempt)
            tmp = dest.with_name(dest.name + ".tmp-" + uuid.uuid4().hex)
            try:
                tmp.write_bytes(data); os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
            return attempt
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 400, 404):
                raise AI33Error("AI33DownloadHttp4xx", "download", f"http_{exc.code}", attempt) from exc
            error = AI33Error("AI33DownloadRateLimited" if exc.code == 429 else "AI33DownloadHttp5xx", "download", f"http_{exc.code}", attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            detail = _safe_detail(exc)
            error = AI33Error("AI33DownloadTimeout" if "timed out" in detail.lower() else "AI33DownloadNetwork", "download", detail, attempt)
        except AI33Error as exc:
            error = exc
            if exc.code in {"AI33DownloadHttp4xx", "AI33DownloadEmpty"}:
                raise
        if attempt >= max_attempts or time.monotonic() >= deadline:
            raise error
        if on_retry is not None:
            on_retry(attempt, error)
        # A re-poll is only an optional URL refresh after a transient download error.
        if refresh_url is not None:
            try:
                current_url = refresh_url() or current_url
            except Exception:
                pass
        delay = min(8.0, 0.25 * (2 ** min(attempt - 1, 5))) + random.uniform(0, 0.1)
        time.sleep(min(delay, max(0, deadline - time.monotonic())))


def download_to(url: str, dest: Path, timeout: int) -> None:
    """Compatibility entrypoint for callers outside the AI33 orchestration."""
    download_with_retry(url, dest, timeout, 1, timeout)


def audio_info(path: Path) -> dict:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels,codec_name:format=duration",
            "-of", "json", str(path),
        ],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        data = json.loads(proc.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        return {
            "sample_rate": int(stream.get("sample_rate") or 0),
            "channels": int(stream.get("channels") or 0),
            "codec": stream.get("codec_name") or "",
            "duration_ms": int(round(float((data.get("format") or {}).get("duration") or 0) * 1000)),
        }
    except Exception:
        return {"sample_rate": 0, "channels": 0, "codec": "", "duration_ms": 0}


def append_audio_report(path: str, stage: str, audio_path: Path) -> None:
    if not path:
        return
    report_path = Path(path)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    except Exception:
        report = {}
    stages = report.get("stages") if isinstance(report.get("stages"), list) else []
    info = audio_info(audio_path)
    stages.append({"stage": stage, "file_path": str(audio_path), **info})
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    if info["sample_rate"] == 16000 and "TTS_MASTER_DOWNGRADED_TO_ASR_FORMAT" not in warnings:
        warnings.append("TTS_MASTER_DOWNGRADED_TO_ASR_FORMAT")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"stages": stages, "warnings": warnings}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def convert_to_wav(src: Path, wav: Path, sample_rate: int, channels: int) -> float:
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-af", f"aresample={sample_rate}", "-ar", str(sample_rate), "-ac", str(channels), "-c:a", "pcm_s16le", str(wav)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(wav)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        return max(0.0, float((proc.stdout or "0").strip() or 0.0)) * 1000.0
    except Exception:
        return 0.0


def write_provider_status(path: str, state: str, cue_index: int, total_cues: int, error: AI33Error | None = None, reused: int | None = None, completed_cues: int | None = None):
    """Update the existing per-job status document with secret-free provider progress."""
    if not path:
        return
    target = Path(path)
    try:
        current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    except Exception:
        current = {}
    if not isinstance(current, dict):
        current = {}
    completed = max(0, cue_index - 1) if completed_cues is None else max(0, completed_cues)
    current.update({
        "status_schema": current.get("status_schema", 1), "phase": state,
        "state": state, "provider": "ai33", "tts_cues_completed": completed,
        "tts_cues_total": total_cues, "tts_cues_reused": int(current.get("tts_cues_reused", 0) if reused is None else reused),
        "failed_cue": cue_index if error else 0, "failed_stage": error.stage if error else "",
        "failed_code": error.code if error else "", "failed_attempts": error.attempts if error else 0,
        "resume_from_cue": cue_index, "updated_at_epoch": time.time(),
    })
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(target, current)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--voice", required=True, help="AI33 voice_id, e.g. elevenlabs_xxx")
    ap.add_argument("--output", required=True, help="đường dẫn WAV output theo TTS master format")
    ap.add_argument("--sample-rate", type=int, default=int(os.environ.get("TTS_MASTER_SAMPLE_RATE", "48000")))
    ap.add_argument("--channels", type=int, default=int(os.environ.get("TTS_MASTER_CHANNELS", "1")))
    ap.add_argument("--report-json", default=os.environ.get("TTS_AUDIO_STAGE_REPORT_JSON", ""))
    ap.add_argument("--api-base", default=os.environ.get("AI33_API_BASE", DEFAULT_API_BASE))
    ap.add_argument("--speed", type=float, default=float(os.environ.get("AI33_TTS_SPEED", "1.0")))
    ap.add_argument("--with-transcript", default=os.environ.get("AI33_WITH_TRANSCRIPT", "false"))
    ap.add_argument("--context-chaining", default=os.environ.get("AI33_CONTEXT_CHAINING", "false"))
    ap.add_argument("--file-name", default=None)
    ap.add_argument("--receive-url", default=os.environ.get("AI33_RECEIVE_URL", ""))
    ap.add_argument("--pronunciation-dictionary-id", default=os.environ.get("AI33_PRONUNCIATION_DICTIONARY_ID", ""))
    ap.add_argument("--timeout-create", type=int, default=int(os.environ.get("AI33_TTS_TIMEOUT_CREATE", "20")))
    ap.add_argument("--timeout-total", type=int, default=int(os.environ.get("AI33_TIMEOUT_SECONDS", "180")))
    ap.add_argument("--poll-interval", type=float, default=float(os.environ.get("AI33_POLL_INTERVAL_SECONDS", "2")))
    ap.add_argument("--download-timeout", type=int, default=int(os.environ.get("AI33_TTS_DOWNLOAD_TIMEOUT", "30")))
    ap.add_argument("--download-attempts", type=int, default=int(os.environ.get("AI33_DOWNLOAD_ATTEMPTS", "3")))
    ap.add_argument("--cue-timeout", type=int, default=int(os.environ.get("AI33_CUE_TIMEOUT_SECONDS", "240")))
    ap.add_argument("--breaker-threshold", type=int, default=int(os.environ.get("AI33_CIRCUIT_BREAKER_FAILURES", "2")))
    ap.add_argument("--breaker-cooldown-seconds", type=int, default=int(os.environ.get("AI33_CIRCUIT_COOLDOWN_SECONDS", "60")))
    ap.add_argument("--provider-state", default=os.environ.get("AI33_PROVIDER_STATE", ""))
    ap.add_argument("--status-json", default=os.environ.get("AI33_STATUS_JSON", ""))
    ap.add_argument("--checkpoint", default=os.environ.get("AI33_TTS_CHECKPOINT", ""))
    ap.add_argument("--cue-index", type=int, default=0)
    ap.add_argument("--total-cues", type=int, default=0)
    ap.add_argument("--source-fingerprint", default="")
    ap.add_argument("--settings-fingerprint", default="")
    ap.add_argument("--debug-dir", default=None, help="thư mục dump response (key redact)")
    args = ap.parse_args()

    text = (args.text or "").strip()
    if not text:
        print("AI33InputEmpty stage=input", file=sys.stderr)
        return 2
    voice_id = (args.voice or "").strip()
    if not voice_id:
        print("AI33VoiceInvalid stage=input", file=sys.stderr)
        return 2
    args.speed = max(0.5, min(1.5, float(args.speed)))
    args.sample_rate = max(8000, int(args.sample_rate))
    args.channels = max(1, min(2, int(args.channels)))

    checkpoint = Path(args.checkpoint) if args.checkpoint and args.cue_index > 0 else None
    out_path = Path(args.output)
    provider_state = Path(args.provider_state) if args.provider_state else out_path.parent / "ai33_provider_state.json"
    breaker = AI33CircuitBreaker(provider_state, args.breaker_threshold, args.breaker_cooldown_seconds)
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    settings_hash = args.settings_fingerprint or hashlib.sha256(json.dumps({"speed": args.speed, "context_chaining": args.context_chaining, "sample_rate": args.sample_rate, "channels": args.channels}, sort_keys=True).encode()).hexdigest()
    token = get_token()
    if not token:
        error = AI33Error(MARKER_AUTH_MISSING, "auth", "missing API credential", 0)
        breaker.record_failure(error)
        write_provider_status(args.status_json, "needs_attention", args.cue_index, args.total_cues, error)
        if checkpoint:
            fail_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, error, args.total_cues)
        print(f"{error.code} stage={error.stage} attempts=0", file=sys.stderr)
        return 3

    out_path.parent.mkdir(parents=True, exist_ok=True)
    debug_dir = Path(args.debug_dir) if args.debug_dir else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    headers = base_headers(token)
    api_base = args.api_base or DEFAULT_API_BASE
    if checkpoint and reusable_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, args.sample_rate, args.channels):
        try:
            materialize_checkpoint_wav(checkpoint, args.cue_index, out_path)
        except OSError as exc:
            error = AI33Error("AI33WavInvalid", "checkpoint", _safe_detail(exc), 0)
            fail_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, error, args.total_cues)
            print(f"{error.code} stage={error.stage} attempts=0", file=sys.stderr)
            return 6
        write_provider_status(args.status_json, "tts", args.cue_index, args.total_cues, reused=1, completed_cues=args.cue_index)
        print(json.dumps({"cue": args.cue_index, "reused": True, "stage": "checkpoint", "attempts": 0}, ensure_ascii=False)); return 0
    try:
        breaker.before_create()
        create_resp = create_task(api_base, headers, args)
    except AI33Error as error:
        # Open circuits block before create and deliberately retain checkpoints/output choices.
        write_provider_status(args.status_json, "waiting_provider", args.cue_index, args.total_cues, error)
        print(f"{error.code} stage={error.stage} attempts=0", file=sys.stderr)
        return 3
    except SystemExit:
        raise
    except Exception as exc:
        error = classified_error("create", exc)
        breaker.record_failure(error)
        write_provider_status(args.status_json, "waiting_provider" if error.code in TRANSIENT_CODES else "needs_attention", args.cue_index, args.total_cues, error)
        if checkpoint:
            fail_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, error, args.total_cues)
        print(f"{error.code} stage=create attempts=0 detail={error.detail}", file=sys.stderr)
        return 3

    task_id = extract_task_id(create_resp)
    result = create_resp
    audio_url = find_audio_url(create_resp)
    if not audio_url:
        if not task_id:
            error = AI33Error(MARKER_NO_AUDIO, "create", "create response without task/audio", 0)
            breaker.record_failure(error)
            write_provider_status(args.status_json, "needs_attention", args.cue_index, args.total_cues, error)
            print(f"{MARKER_NO_AUDIO} no_task_id resp={json.dumps(_redact(create_resp), ensure_ascii=False)[:300]}", file=sys.stderr)
            return 5
        try:
            result = poll_task(api_base, headers, task_id, args.timeout_total, args.poll_interval)
        except SystemExit:
            raise
        except Exception as exc:
            msg = str(exc)
            if "task_failed" in msg:
                error = AI33Error("AI33TaskFailed", "poll", _safe_detail(msg))
                breaker.record_failure(error)
                write_provider_status(args.status_json, "needs_attention", args.cue_index, args.total_cues, error)
                if checkpoint:
                    fail_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, error, args.total_cues)
                print(f"{error.code} stage=poll detail={error.detail}", file=sys.stderr)
                return 4
            error = classified_error("poll", exc)
            breaker.record_failure(error)
            write_provider_status(args.status_json, "waiting_provider" if error.code in TRANSIENT_CODES else "needs_attention", args.cue_index, args.total_cues, error)
            if checkpoint:
                fail_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, error, args.total_cues)
            print(f"{error.code} stage=poll detail={error.detail}", file=sys.stderr)
            return 4
        audio_url = find_audio_url(result)

    if debug_dir:
        try:
            name = task_id or f"sync_{int(time.time())}"
            (debug_dir / f"resp_{name}.json").write_text(
                json.dumps(_redact(result), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    if not audio_url:
        error = AI33Error(MARKER_NO_AUDIO, "poll", "task completed without audio", 0)
        breaker.record_failure(error)
        write_provider_status(args.status_json, "needs_attention", args.cue_index, args.total_cues, error)
        if checkpoint:
            fail_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, error, args.total_cues)
        print(f"{MARKER_NO_AUDIO} stage=poll attempts=0 task_id={task_id or '-'}", file=sys.stderr)
        return 5

    tmp_audio = out_path.with_suffix(out_path.suffix + ".src")
    wav_tmp = None
    try:
        def refresh_url():
            if not task_id:
                return None
            return find_audio_url(poll_task(api_base, headers, task_id, min(args.timeout_total, 30), args.poll_interval))
        def retry_status(attempt, error):
            write_provider_status(args.status_json, "retrying", args.cue_index, args.total_cues, error)
        download_attempts = download_with_retry(audio_url, tmp_audio, args.download_timeout, max(1, min(3, args.download_attempts)), max(5, min(1800, args.cue_timeout)), refresh_url, retry_status)
    except AI33Error as exc:
        breaker.record_failure(exc)
        write_provider_status(args.status_json, "waiting_provider" if exc.code in TRANSIENT_CODES else "needs_attention", args.cue_index, args.total_cues, exc)
        if checkpoint:
            fail_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, exc, args.total_cues)
        print(f"{exc.code} stage={exc.stage} attempts={exc.attempts} detail={_safe_detail(exc.detail)}", file=sys.stderr)
        return 6

    try:
        append_audio_report(args.report_json, "ai33_response", tmp_audio)
        downloaded_info = audio_info(tmp_audio)
        if not downloaded_info.get("codec") or downloaded_info.get("duration_ms", 0) <= 0:
            raise AI33Error("AI33DownloadCorrupt", "download_validate", "ffprobe could not decode downloaded media", download_attempts)
        wav_tmp = out_path.with_name(out_path.stem + ".tmp-" + uuid.uuid4().hex + ".wav")
        duration_ms = convert_to_wav(tmp_audio, wav_tmp, args.sample_rate, args.channels)
        validate_wav(wav_tmp, args.sample_rate, args.channels)
        os.replace(wav_tmp, out_path)
        append_audio_report(args.report_json, "tts_raw", out_path)
    except Exception as exc:
        error = exc if isinstance(exc, AI33Error) else AI33Error("AI33ConvertFailed", "convert", _safe_detail(exc), 1)
        breaker.record_failure(error)
        write_provider_status(args.status_json, "needs_attention", args.cue_index, args.total_cues, error)
        if checkpoint:
            fail_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, error, args.total_cues)
        print(f"{error.code} stage={error.stage} detail={_safe_detail(error.detail)}", file=sys.stderr)
        return 6
    finally:
        try:
            tmp_audio.unlink(missing_ok=True)
        except Exception:
            pass
        if wav_tmp:
            try:
                wav_tmp.unlink(missing_ok=True)
            except Exception:
                pass

    meta = {
        "task_id": task_id,
        "voice": voice_id,
        "bytes": out_path.stat().st_size,
        "duration_ms": duration_ms,
        "attempts": download_attempts,
    }
    if checkpoint:
        complete_checkpoint_cue(checkpoint, args.cue_index, args.source_fingerprint, text_hash, voice_id, settings_hash, out_path, args.sample_rate, args.channels, download_attempts, args.total_cues)
    breaker.record_success()
    write_provider_status(args.status_json, "tts", args.cue_index, args.total_cues, completed_cues=args.cue_index)
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
