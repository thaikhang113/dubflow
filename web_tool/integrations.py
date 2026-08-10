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


def _workflow(identifier, label, required, missing, optional=()):
    return {
        "id": identifier,
        "label": label,
        "status": "ready" if not missing else "missing",
        "required": list(required),
        "missing": list(missing),
        "optional": list(optional),
    }

def host_login_helper_available() -> bool:
    endpoint = os.environ.get(
        "BILIBILI_HOST_HELPER_URL",
        "http://host.docker.internal:18794",
    ).rstrip("/")
    try:
        with urllib.request.urlopen(f"{endpoint}/status", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("ok") is True
    except Exception:
        return False

def host_hardware_status() -> dict:
    endpoint = os.environ.get(
        "BILIBILI_HOST_HELPER_URL",
        "http://host.docker.internal:18794",
    ).rstrip("/")
    try:
        with urllib.request.urlopen(f"{endpoint}/hardware", timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if response.status == 200 and isinstance(payload, dict) else {}
    except Exception:
        return {}

def host_install_status(component: str) -> dict:
    if component not in {"qwen-asr", "vieneu"}:
        return {}
    endpoint = os.environ.get(
        "BILIBILI_HOST_HELPER_URL",
        "http://host.docker.internal:18794",
    ).rstrip("/")
    try:
        query = urllib.parse.urlencode({"component": component})
        with urllib.request.urlopen(
            f"{endpoint}/install/status?{query}",
            timeout=3,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if response.status == 200 and isinstance(payload, dict) else {}
    except Exception:
        return {}

def local_ai_health(component: str) -> dict:
    endpoints = {
        "qwen-asr": os.environ.get(
            "QWEN_ASR_ENDPOINT",
            "http://qwen-asr:8000",
        ),
        "vieneu": os.environ.get(
            "VIENEU_ENDPOINT",
            "http://vieneu:8000",
        ),
    }
    endpoint = endpoints.get(component)
    if not endpoint:
        return {}
    try:
        with urllib.request.urlopen(
            f"{endpoint.rstrip('/')}/health",
            timeout=3,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if response.status == 200 and isinstance(payload, dict) else {}
    except Exception:
        return {}

def _ollama_available(provider) -> bool:
    if not provider:
        return False
    endpoint = str(provider.get("endpoint") or "").rstrip("/")
    if not endpoint:
        return False
    try:
        with urllib.request.urlopen(f"{endpoint}/api/tags", timeout=1) as response:
            return 200 <= response.status < 400
    except Exception:
        return False

def runtime_doctor(
    settings,
    providers,
    runtime_settings=None,
    login_status=None,
    telegram_configured=False,
    host_helper_available=False,
    ollama_available=None,
    hardware_status=None,
    install_status=None,
    runtime_health=None,
) -> dict:
    runtime_settings = runtime_settings or {}
    login_status = login_status or {}
    install_status = install_status or {}
    runtime_health = runtime_health or {}
    whisper_binary = settings.models_dir / "whisper.cpp" / "build" / "bin" / (
        "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    )
    whisper_model = str(runtime_settings.get("whisper_model") or "medium").lower()
    if whisper_model not in {"small", "medium"}:
        whisper_model = "medium"
    whisper_model_path = (
        settings.models_dir
        / "whisper.cpp"
        / "models"
        / f"ggml-{whisper_model}.bin"
    )
    writable = {}
    for name in ("data_dir", "secrets_dir", "jobs_dir", "output_dir", "models_dir", "browser_dir"):
        path = getattr(settings, name)
        writable[name] = path.is_dir() and os.access(path, os.W_OK)
    checks = {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "chromium": bool(shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("msedge")),
        "yt_dlp": bool(shutil.which("yt-dlp")),
        "whisper": whisper_binary.is_file() and whisper_model_path.is_file(),
        "whisper_binary": whisper_binary.is_file(),
        "whisper_model": whisper_model,
        "whisper_model_installed": whisper_model_path.is_file(),
        "demucs": importlib.util.find_spec("demucs") is not None,
        "edge_tts": bool(shutil.which("edge-tts")),
        "host_login_helper": bool(host_helper_available),
        "volumes": writable,
        "providers": [
            {"id": provider["id"], "kind": provider["kind"], "configured": provider["configured"]}
            for provider in providers
        ],
    }
    hardware_status = hardware_status or {}
    gpu = hardware_status.get("gpu")
    if not isinstance(gpu, dict):
        gpu = None
    stages = hardware_status.get("stages")
    if not isinstance(stages, dict):
        stages = {}
    selected_profile = str(
        hardware_status.get("selected_profile")
        or runtime_settings.get("hardware_profile")
        or "cpu"
    ).lower()
    if selected_profile not in {"cpu", "hybrid", "gpu"}:
        selected_profile = "cpu"
    checks["hardware"] = {
        "available": bool(hardware_status),
        "gpu": {
            "name": str(gpu.get("name") or "")[:200],
            "memory_mb": int(gpu.get("memory_mb") or 0),
        } if gpu else None,
        "docker_gpu": bool(hardware_status.get("docker_gpu")),
        "selected_profile": selected_profile,
        "fallback_reason": str(hardware_status.get("fallback_reason") or "")[:200],
        "stages": {
            name: "gpu" if stages.get(name) == "gpu" else "cpu"
            for name in ("ollama", "whisper", "demucs", "render")
        },
    }
    qwen_install = install_status.get("qwen_asr")
    if not isinstance(qwen_install, dict):
        qwen_install = {}
    qwen = runtime_health.get("qwen_asr")
    if not isinstance(qwen, dict):
        qwen = {}
    qwen_checks = {
        "service": bool(qwen),
        "model": qwen.get("model_ready") is True,
        "aligner": qwen.get("aligner_ready") is True,
        "install_state": str(qwen_install.get("state") or "unknown"),
    }
    qwen_checks["ready"] = all(
        qwen_checks[key] for key in ("service", "model", "aligner")
    )
    requested_asr = str(runtime_settings.get("asr_engine") or "auto").lower()
    if requested_asr not in {"auto", "whisper", "qwen3"}:
        requested_asr = "auto"
    selected_asr = (
        "qwen3"
        if requested_asr == "qwen3"
        or (
            requested_asr == "auto"
            and selected_profile in {"hybrid", "gpu"}
            and qwen_checks["ready"]
        )
        else "whisper"
    )
    checks["asr"] = {
        "requested": requested_asr,
        "selected": selected_asr,
        "ready": qwen_checks["ready"] if selected_asr == "qwen3" else checks["whisper"],
        "engines": {
            "whisper": {
                "ready": checks["whisper"],
                "binary": checks["whisper_binary"],
                "model": checks["whisper_model"],
                "model_installed": checks["whisper_model_installed"],
            },
            "qwen3": qwen_checks,
        },
    }
    core_required = ("FFmpeg", "Demucs", "Runtime volumes")
    core_missing = []
    if not checks["ffmpeg"]:
        core_missing.append("FFmpeg")
    if not checks["demucs"]:
        core_missing.append("Demucs")
    if not all(writable.values()):
        core_missing.append("Writable runtime volumes")
    asr_missing = []
    if selected_asr == "whisper" and not checks["whisper"]:
        asr_missing.append("Whisper model/binary")
    if selected_asr == "qwen3":
        asr_missing.extend(
            label
            for key, label in (
                ("service", "Qwen service"),
                ("model", "Qwen model"),
                ("aligner", "Qwen aligner"),
            )
            if not qwen_checks[key]
        )

    providers_by_id = {provider["id"]: provider for provider in providers}
    translation = providers_by_id.get(
        str(runtime_settings.get("default_provider_id") or "")
    )
    if translation and translation.get("kind") == "ai33":
        translation = None
    if translation is None:
        translation = next(
            (
                provider
                for provider in providers
                if provider.get("kind") in {"ollama", "openai_compatible"}
            ),
            None,
        )
    ollama = (
        translation
        if translation and translation.get("kind") == "ollama"
        else next(
            (
                provider
                for provider in providers
                if provider.get("kind") == "ollama"
            ),
            None,
        )
    )
    if ollama_available is None:
        ollama_available = _ollama_available(ollama)
    checks["ollama"] = bool(ollama_available)
    translation_missing = []
    if translation is None:
        translation_missing.append("Ollama hoặc provider dịch")
    elif translation.get("kind") == "ollama" and not ollama_available:
        translation_missing.append("Ollama endpoint không kết nối được")
    elif (
        translation.get("kind") == "openai_compatible"
        and not translation.get("configured")
    ):
        translation_missing.append("API key provider dịch")

    ai33 = next(
        (provider for provider in providers if provider.get("kind") == "ai33"),
        None,
    )
    ai33_missing = []
    if ai33 is None:
        ai33_missing.extend(("AI33 provider", "AI33_API_KEY"))
    elif not ai33.get("configured"):
        ai33_missing.append("AI33_API_KEY")

    voice = str(runtime_settings.get("default_voice") or "")
    vieneu_install = install_status.get("vieneu")
    if not isinstance(vieneu_install, dict):
        vieneu_install = {}
    vieneu = runtime_health.get("vieneu")
    if not isinstance(vieneu, dict):
        vieneu = {}
    try:
        vieneu_sample_rate = int(vieneu.get("sample_rate") or 0)
    except (TypeError, ValueError):
        vieneu_sample_rate = 0
    vieneu_device = str(vieneu.get("device") or "unknown").lower()
    vieneu_checks = {
        "health": vieneu.get("ready") is True,
        "sample_rate": vieneu_sample_rate,
        "device": vieneu_device,
        "clone_ready": vieneu.get("ready") is True and vieneu_device == "cuda",
        "install_state": str(vieneu_install.get("state") or "unknown"),
    }
    vieneu_checks["ready"] = (
        vieneu_checks["health"] and vieneu_checks["sample_rate"] == 48000
    )
    selected_tts = (
        "vieneu"
        if voice.lower().startswith("vieneu:")
        else "ai33"
        if voice.lower().startswith("ai33:")
        else "edge"
    )
    ai33_checks = {
        "provider": ai33 is not None,
        "configured": bool(ai33 and ai33.get("configured")),
    }
    ai33_checks["ready"] = all(ai33_checks.values())
    edge_checks = {"ready": checks["edge_tts"]}
    checks["tts"] = {
        "selected": selected_tts,
        "ready": {
            "vieneu": vieneu_checks["ready"],
            "ai33": ai33_checks["ready"],
            "edge": edge_checks["ready"],
        }[selected_tts],
        "engines": {
            "vieneu": vieneu_checks,
            "ai33": ai33_checks,
            "edge": edge_checks,
        },
    }
    tts_missing = []
    if selected_tts == "vieneu":
        if not vieneu_checks["health"]:
            tts_missing.append("VieNeu health")
        if vieneu_checks["sample_rate"] != 48000:
            tts_missing.append("VieNeu 48 kHz")
    elif selected_tts == "ai33":
        tts_missing.extend(ai33_missing)
    elif not checks["edge_tts"]:
        tts_missing.append("Edge TTS")

    local_missing = core_missing + translation_missing + asr_missing + tts_missing
    if ollama is None:
        ollama_missing = ["Ollama provider/endpoint"]
    elif not ollama_available:
        ollama_missing = ["Ollama endpoint không kết nối được"]
    else:
        ollama_missing = []
    bilibili_missing = list(local_missing)
    if not checks["yt_dlp"]:
        bilibili_missing.append("yt-dlp")
    bilibili_optional = []
    if not login_status.get("logged_in"):
        bilibili_optional.append("Bilibili cookie")
    if not host_helper_available:
        bilibili_optional.append("Host login helper")

    telegram_missing = []
    if not telegram_configured:
        telegram_missing.append("Telegram bot credential")
    if not str(runtime_settings.get("telegram_chat_id") or "").strip():
        telegram_missing.append("Telegram chat ID")
    telegram = _workflow(
        "telegram",
        "Telegram",
        ("Telegram bot credential", "Telegram chat ID"),
        telegram_missing,
    )
    telegram["status"] = "ready" if not telegram_missing else "optional"

    trend_runner = Path(
        os.environ.get(
            "OPENCLAW_HOST_RUNNER",
            "/home/node/host-bin/openclaw-call-host-runner.sh",
        )
    ).is_file()
    trend = _workflow(
        "trend",
        "Trend Scout",
        ("Trend host runner", "PostgreSQL"),
        () if trend_runner else ("Trend host runner",),
    )
    if trend["missing"]:
        trend["status"] = "optional"
    ai33_workflow = _workflow(
        "ai33_voice",
        "Giọng AI33",
        ("AI33 provider", "AI33_API_KEY"),
        ai33_missing,
    )
    if selected_tts != "ai33":
        ai33_workflow["status"] = "optional"

    workflows = [
        _workflow(
            "hardware",
            "Ph\u1ea7n c\u1ee9ng",
            (),
            (),
            tuple(
                f"{name.capitalize()}: {backend.upper()}"
                for name, backend in checks["hardware"]["stages"].items()
            ) + (
                (f"Fallback: {checks['hardware']['fallback_reason']}",)
                if checks["hardware"]["fallback_reason"]
                else ()
            ),
        ),
        _workflow(
            "asr",
            "Nhận dạng giọng nói",
            ("Whisper fallback",) if requested_asr == "auto" else (selected_asr,),
            asr_missing,
        ),
        _workflow(
            "tts",
            "Giọng đọc",
            (selected_tts,),
            tts_missing,
        ),
        _workflow(
            "local_video",
            "Video local",
            core_required + ("ASR", "Provider dịch", "TTS"),
            local_missing,
        ),
        _workflow(
            "bilibili",
            "Bilibili",
            core_required + ("yt-dlp", "ASR", "Provider dịch", "TTS"),
            bilibili_missing,
            bilibili_optional,
        ),
        _workflow(
            "ollama_translation",
            "Dịch bằng Ollama",
            ("Ollama provider/endpoint",),
            ollama_missing,
        ),
        ai33_workflow,
        telegram,
        trend,
    ]
    core_ok = (
        checks["ffmpeg"]
        and checks["chromium"]
        and checks["yt_dlp"]
        and checks["asr"]["ready"]
        and checks["demucs"]
        and all(writable.values())
    )
    return {
        "ok": core_ok,
        "ready": not local_missing,
        "checks": checks,
        "workflows": workflows,
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
