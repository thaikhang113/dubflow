import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from .secrets import sanitize


SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
SAFE_BVID = re.compile(r"^(?:BV[A-Za-z0-9]+|av[0-9]+)$")
SAFE_SELECTOR = re.compile(
    r"^(?:all|latest|unprocessed|latest:[1-9][0-9]*|range:[0-9]+-[0-9]+|list:[0-9]+(?:,[0-9]+)*)$"
)
SHELL_META = re.compile(r"[;&|`$<>]")
SERIES_ACTIONS = {
    "list",
    "show",
    "add",
    "remove",
    "update",
    "find-episodes",
    "plan",
    "status",
    "resume",
    "compile",
}
TREND_ACTIONS = {
    "scan",
    "status",
    "top-candidates",
    "topic-details",
    "video-risk",
    "collection-tick",
}


def _text(payload, key, *, required=False, maximum=200):
    value = str(payload.get(key) or "").strip()
    if required and not value:
        raise ValueError(f"{key} is required")
    if len(value) > maximum or "\0" in value or "\r" in value or "\n" in value:
        raise ValueError(f"invalid {key}")
    return value


def _identifier(payload, key, *, required=True):
    value = _text(payload, key, required=required)
    if value and not SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid {key}")
    return value


def _bilibili_url(value):
    from urllib.parse import urlsplit

    value = str(value or "").strip()
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or not (host == "bilibili.com" or host.endswith(".bilibili.com"))
    ):
        raise ValueError("invalid Bilibili URL")
    return value


def _run_json(command, settings, *, environment=None, timeout=120):
    process_environment = os.environ.copy()
    if environment:
        process_environment.update(environment)
    result = subprocess.run(
        command,
        cwd=settings.repo_root,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            sanitize(result.stderr or "integration returned invalid JSON")
        ) from exc
    if result.returncode != 0 or payload.get("error"):
        raise ValueError(sanitize(payload.get("error") or result.stderr or "integration failed"))
    return payload


def _series_runtime(settings):
    root = settings.data_dir / "series"
    output = settings.output_dir / "series"
    root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    state = root / "series.json"
    if not state.exists():
        state.write_text('{"version":2,"series":[]}\n', encoding="utf-8")
    return root, state, output


def run_series_action(action: str, payload: dict, settings) -> dict:
    action = str(action or "").strip().lower()
    if action not in SERIES_ACTIONS:
        raise ValueError("unsupported series action")
    payload = payload if isinstance(payload, dict) else {}
    root, state, output = _series_runtime(settings)
    tracker = settings.repo_root / "skills" / "series-tracker" / "series-tracker.py"
    planner = (
        settings.repo_root
        / "skills"
        / "series-compilation-orchestrator"
        / "scripts"
        / "series_compilation.py"
    )
    job = planner.with_name("compilation_job.py")
    environment = {
        "OPENCLAW_SERIES_STATE_DIR": str(root),
        "OPENCLAW_HOST_RUNNER_QUEUE_DIR": str(settings.jobs_dir / "series-queue"),
    }

    if action == "list":
        command = [sys.executable, str(tracker), "list"]
    elif action == "show":
        command = [
            sys.executable,
            str(planner),
            "list",
            "--state",
            str(state),
            "--series-id",
            _identifier(payload, "series_id"),
        ]
    elif action == "add":
        command = [
            sys.executable,
            str(tracker),
            "add",
            "--name",
            _text(payload, "name", required=True, maximum=100),
            "--keyword",
            _text(payload, "keyword", required=True),
            "--source-url",
            _bilibili_url(payload.get("source_url")),
        ]
        channel_url = _text(payload, "channel_url")
        if channel_url:
            command += ["--channel-url", _bilibili_url(channel_url)]
        series_id = _identifier(payload, "series_id", required=False)
        if series_id:
            command += ["--series-id", series_id]
    elif action == "remove":
        command = [sys.executable, str(tracker), "remove", _identifier(payload, "series_id")]
    elif action in {"update", "find-episodes"}:
        limit = int(payload.get("limit", 500))
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        command = [
            sys.executable,
            str(tracker),
            "refresh",
            _identifier(payload, "series_id"),
            "--limit",
            str(limit),
        ]
    elif action == "plan":
        selector = _text(payload, "selector") or "all"
        if not SAFE_SELECTOR.fullmatch(selector):
            raise ValueError("invalid selector")
        command = [
            sys.executable,
            str(planner),
            "plan",
            "--state",
            str(state),
            "--series-id",
            _identifier(payload, "series_id"),
            "--selector",
            selector,
        ]
    else:
        compilation_id = _identifier(payload, "compilation_id")
        job_payload = {
            "compilation_id": compilation_id,
            "state": str(state),
            "output_root": str(output),
            "series_id": _identifier(payload, "series_id", required=False),
            "selector": _text(payload, "selector") or "all",
        }
        if not SAFE_SELECTOR.fullmatch(job_payload["selector"]):
            raise ValueError("invalid selector")
        command_name = {"compile": "run", "resume": "resume", "status": "status"}[action]
        command = [
            sys.executable,
            str(job),
            command_name,
            "--payload",
            json.dumps(job_payload, ensure_ascii=False, separators=(",", ":")),
        ]
    return _run_json(command, settings, environment=environment)


def _trend_command(action, payload, runner):
    if action == "scan":
        query = _text(payload, "query", required=True)
        if SHELL_META.search(query):
            raise ValueError("invalid query")
        mode = _text(payload, "mode") or "trend"
        if mode not in {"trend", "archive"}:
            raise ValueError("invalid trend mode")
        days = int(payload.get("days", 7))
        maximum = 30 if mode == "trend" else 180
        if not 1 <= days <= maximum:
            raise ValueError(f"{mode} days must be between 1 and {maximum}")
        return [runner, "trend-start-scan", query, str(days), mode]
    if action == "status":
        return [runner, "trend-scan-status", _identifier(payload, "scan_id")]
    if action == "top-candidates":
        scan_id = _identifier(payload, "scan_id")
        limit = int(payload.get("limit", 5))
        if not 1 <= limit <= 10:
            raise ValueError("limit must be between 1 and 10")
        return [runner, "trend-top-candidates", scan_id, str(limit)]
    if action == "topic-details":
        return [runner, "trend-topic-details", _identifier(payload, "topic_id")]
    if action == "video-risk":
        bvid = _text(payload, "bvid", required=True)
        if not SAFE_BVID.fullmatch(bvid):
            raise ValueError("invalid bvid")
        return [runner, "trend-video-risk", bvid]
    return [runner, "trend-collection-tick"]


def run_trend_action(action: str, payload: dict, settings) -> dict:
    action = str(action or "").strip().lower()
    if action not in TREND_ACTIONS:
        raise ValueError("unsupported trend action")
    runner = os.environ.get(
        "OPENCLAW_HOST_RUNNER",
        "/home/node/host-bin/openclaw-call-host-runner.sh",
    )
    command = _trend_command(action, payload if isinstance(payload, dict) else {}, runner)
    if not Path(runner).is_file():
        return {
            "ok": False,
            "configured": False,
            "error_code": "TrendRuntimeUnavailable",
        }
    result = _run_json(command, settings, timeout=180)
    if isinstance(result.get("stdout"), str):
        try:
            nested = json.loads(result["stdout"])
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(nested, dict):
                return nested
    return result


def hyperframes_status(settings) -> dict:
    script = (
        settings.repo_root
        / "skills"
        / "series-compilation-orchestrator"
        / "scripts"
        / "hyperframes_adapter.py"
    )
    return _run_json([sys.executable, str(script), "status"], settings, timeout=30)


def thumbnail_status(settings) -> dict:
    script = (
        settings.repo_root
        / "skills"
        / "google-flow-thumbnail"
        / "google-flow-thumbnail.sh"
    )
    reports = list(settings.output_dir.rglob("thumbnail_flow_status.json"))
    latest = max(reports, key=lambda path: path.stat().st_mtime) if reports else None
    payload = {"available": script.is_file(), "latest_report": None}
    if latest:
        try:
            report = json.loads(latest.read_text(encoding="utf-8"))
            payload["latest_report"] = {
                key: sanitize(report.get(key))
                for key in ("status", "error_code", "detail")
                if report.get(key) is not None
            }
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    return payload


def runtime_doctor(settings, providers) -> dict:
    whisper = settings.models_dir / "whisper.cpp" / "build" / "bin" / (
        "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    )
    writable = {}
    for name in ("data_dir", "secrets_dir", "jobs_dir", "output_dir", "models_dir", "browser_dir"):
        path = getattr(settings, name)
        writable[name] = path.is_dir() and os.access(path, os.W_OK)
    checks = {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "chromium": bool(shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("msedge")),
        "yt_dlp": bool(shutil.which("yt-dlp")),
        "whisper": whisper.is_file(),
        "demucs": importlib.util.find_spec("demucs") is not None,
        "volumes": writable,
        "providers": [
            {"id": provider["id"], "kind": provider["kind"], "configured": provider["configured"]}
            for provider in providers
        ],
    }
    return {
        "ok": (
            checks["ffmpeg"]
            and checks["chromium"]
            and checks["yt_dlp"]
            and checks["whisper"]
            and checks["demucs"]
            and all(writable.values())
        ),
        "checks": checks,
    }


def test_telegram(secret_store, chat_id: str, thread_id: str = "") -> dict:
    token = secret_store.environment("telegram-bot").get("PROVIDER_API_KEY", "")
    if not token or not str(chat_id).strip():
        return {"ok": False, "error_code": "TelegramNotConfigured"}
    body = {
        "chat_id": str(chat_id).strip(),
        "text": "Auto Vietsub: kết nối Telegram hoạt động.",
    }
    if str(thread_id).strip():
        body["message_thread_id"] = str(thread_id).strip()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urllib.parse.urlencode(body).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {"ok": bool(payload.get("ok")), "message": f"HTTP {response.status}"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "message": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "error_code": type(exc).__name__}
