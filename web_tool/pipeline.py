import json
from pathlib import Path
from urllib.parse import urlsplit

from .config import Settings
from .secrets import sanitize, validate_provider


PLATFORM_WRAPPERS = {
    "bilibili": ("bilibili-vietnamese-dubber", "run.sh"),
    "douyin": ("douyin-vietnamese-dubber", "run.sh"),
    "upload": ("douyin-vietnamese-dubber", "run.sh"),
}
STATUS_FIELDS = {
    "state",
    "phase",
    "progress",
    "progress_percent",
    "label",
    "error_code",
    "error_message",
    "reason",
    "retry_action",
    "failed_cue",
    "failed_stage",
    "resume_from_cue",
    "artifacts",
}
WHISPER_MODELS = {"small", "medium"}
ASR_ENGINES = {"auto", "whisper", "qwen3"}
HARDWARE_PROFILES = {"cpu", "hybrid", "gpu"}


def _request(job: dict) -> dict:
    values = dict(job.get("request") or {})
    for key, value in job.items():
        if key != "request":
            values.setdefault(key, value)
    return values


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _validate_url(source: str, platform: str) -> str:
    try:
        parsed = urlsplit(source)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid source URL") from exc
    allowed = {
        "bilibili": ("bilibili.com", "b23.tv"),
        "douyin": ("douyin.com", "iesdouyin.com"),
    }[platform]
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or port not in {None, 80, 443}
        or not any(hostname == domain or hostname.endswith("." + domain) for domain in allowed)
    ):
        raise ValueError(f"invalid {platform} URL")
    return source


def build_job_command(job: dict, settings: Settings) -> list[str]:
    request = _request(job)
    platform = str(request.get("platform") or "").strip().lower()
    source = str(request.get("source") or "").strip()
    if platform not in PLATFORM_WRAPPERS:
        raise ValueError("unsupported platform")
    if not source or "\n" in source or "\r" in source or "\0" in source:
        raise ValueError("invalid source")

    if platform == "upload":
        source_path = Path(source).expanduser().resolve()
        upload_root = settings.jobs_dir / "uploads"
        if not _inside(source_path, upload_root) or not source_path.is_file():
            raise ValueError("upload source is outside the managed upload directory")
        source = str(source_path)
    else:
        source = _validate_url(source, platform)

    resume = str(request.get("resume_job_dir") or "").strip()
    if resume:
        resume_path = Path(resume).expanduser().resolve()
        if not _inside(resume_path, settings.jobs_dir):
            raise ValueError("resume directory is outside jobs directory")

    skill, script = PLATFORM_WRAPPERS[platform]
    return ["bash", str(settings.repo_root / "skills" / skill / script), source]


def _provider(provider: dict) -> dict:
    if not provider:
        return {}
    values = validate_provider(
        {
            "name": provider.get("name") or "provider",
            "kind": provider.get("kind"),
            "endpoint": provider.get("endpoint"),
            "model": provider.get("model") or "",
            "timeout_seconds": provider.get("timeout_seconds", 90),
        }
    )
    values["api_key"] = str(provider.get("api_key") or "").strip()
    return values


def build_job_environment(
    job: dict,
    providers: dict,
    settings: Settings,
) -> dict[str, str]:
    request = _request(job)
    job_id = str(job.get("id") or request.get("id") or "job-preview")
    if not job_id.startswith("job-") or not job_id[4:].replace("-", "").isalnum():
        raise ValueError("invalid job id")
    job_root = (settings.jobs_dir / job_id).resolve()
    if not _inside(job_root, settings.jobs_dir):
        raise ValueError("invalid job directory")

    whisper_dir = settings.models_dir / "whisper.cpp"
    whisper_model = str(request.get("whisper_model") or "medium").strip().lower()
    if whisper_model not in WHISPER_MODELS:
        raise ValueError("invalid whisper model")
    environment = {
        "OPENCLAW_AI_PROVIDER": "ollama",
        "OPENCLAW_AI_API_BASE": "http://host.docker.internal:11434",
        "OPENCLAW_AI_MODEL": "translategemma:4b",
        "OLLAMA_API_BASE": "http://host.docker.internal:11434",
        "OLLAMA_MODEL": "translategemma:4b",
        "AI33_TTS_WORKERS": "3",
        "BASE_ROOT": str(job_root),
        "DOUYIN_VIDEOS_DIR": str(job_root),
        "BILIBILI_OUTPUT_ROOT": str(job_root),
        "WHISPER_DIR": str(whisper_dir),
        "WHISPER_BIN": str(whisper_dir / "build" / "bin" / "whisper-cli"),
        "WHISPER_MODEL": str(whisper_dir / "models" / f"ggml-{whisper_model}.bin"),
        "CHROME_CDP_URL": "http://127.0.0.1:9222",
        "BILIBILI_CDP_URL": "http://127.0.0.1:9222",
    }
    asr_engine = str(request.get("asr_engine") or "auto").strip().lower()
    if asr_engine not in ASR_ENGINES:
        raise ValueError("invalid ASR engine")
    environment["ASR_PROVIDER"] = asr_engine
    environment["QWEN_ASR_ENDPOINT"] = "http://qwen-asr:8000"
    environment["VIENEU_ENDPOINT"] = "http://vieneu:8000"

    vieneu_style = str(request.get("vieneu_style") or "").strip()
    if vieneu_style:
        if len(vieneu_style) > 200 or any(
            character in vieneu_style for character in "\r\n\0"
        ):
            raise ValueError("invalid VieNeu style")
        environment["VIENEU_STYLE"] = vieneu_style

    hardware_profile = str(
        request.get("hardware_profile") or "cpu"
    ).strip().lower()
    if hardware_profile not in HARDWARE_PROFILES:
        raise ValueError("invalid hardware profile")
    environment["OPENCLAW_HARDWARE_PROFILE"] = hardware_profile

    translation = _provider(providers.get("translation") or {})
    if translation:
        environment["OPENCLAW_AI_API_BASE"] = translation["endpoint"]
        environment["OPENCLAW_AI_MODEL"] = translation["model"]
        if translation["kind"] == "ollama":
            environment["OPENCLAW_AI_PROVIDER"] = "ollama"
            environment["OLLAMA_API_BASE"] = translation["endpoint"]
            environment["OLLAMA_MODEL"] = translation["model"]
        elif translation["kind"] == "openai_compatible":
            environment["OPENCLAW_AI_PROVIDER"] = "ninerouter"
            environment["NINEROUTER_API_BASE"] = translation["endpoint"]
            environment["NINEROUTER_MODEL"] = translation["model"]
            if translation["api_key"]:
                environment["NINEROUTER_API_KEY"] = translation["api_key"]
        else:
            raise ValueError("translation provider must be Ollama or OpenAI-compatible")

    tts = _provider(providers.get("tts") or {})
    if tts:
        if tts["kind"] != "ai33":
            raise ValueError("TTS provider must be AI33")
        environment["AI33_API_BASE"] = tts["endpoint"]
        if tts["api_key"]:
            environment["AI33_API_KEY"] = tts["api_key"]

    model = str(request.get("model") or "").strip()
    if model:
        if len(model) > 200 or any(character in model for character in "\r\n\0"):
            raise ValueError("invalid model")
        environment["OPENCLAW_AI_MODEL"] = model
        if environment["OPENCLAW_AI_PROVIDER"] == "ollama":
            environment["OLLAMA_MODEL"] = model
        elif environment["OPENCLAW_AI_PROVIDER"] == "ninerouter":
            environment["NINEROUTER_MODEL"] = model

    default_voice = str(request.get("default_voice") or "").strip()
    if default_voice:
        if len(default_voice) > 200 or any(
            character in default_voice for character in "\r\n\0"
        ):
            raise ValueError("invalid default voice")
        environment["OPENCLAW_DEFAULT_TTS_VOICE"] = default_voice

    voice = str(request.get("voice") or default_voice).strip()
    if voice:
        if len(voice) > 200 or any(character in voice for character in "\r\n\0"):
            raise ValueError("invalid voice")
        environment["VOICE"] = voice
        environment["EDGE_TTS_VOICE_PRESET"] = voice

    resume = str(request.get("resume_job_dir") or "").strip()
    if resume:
        resume_path = Path(resume).expanduser().resolve()
        if not _inside(resume_path, settings.jobs_dir):
            raise ValueError("resume directory is outside jobs directory")
        environment["OPENCLAW_RESUME_JOB_DIR"] = str(resume_path)
    cookie_path = settings.secrets_dir / "bilibili-cookies.txt"
    if cookie_path.is_file():
        environment["BILIBILI_COOKIES_FILE"] = str(cookie_path)
    logo_path = settings.data_dir / "branding-logo.png"
    if logo_path.is_file():
        environment["BILIBILI_BRAND_LOGO"] = str(logo_path)
        environment["BILIBILI_BRAND_REQUIRED"] = "1"
    return environment


def _clean(value):
    if isinstance(value, str):
        return sanitize(value)
    if isinstance(value, list):
        return [_clean(item) for item in value[:100]]
    if isinstance(value, dict):
        return {str(key)[:100]: _clean(item) for key, item in list(value.items())[:100]}
    return value


def read_job_status(job_dir: Path) -> dict:
    path = Path(job_dir) / "job_status.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: _clean(payload[key])
        for key in STATUS_FIELDS
        if key in payload
    }
