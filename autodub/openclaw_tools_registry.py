"""Tool registry for OpenClaw dynamic app control."""
from __future__ import annotations

import math
import os
import re
from typing import Any, Callable

from dotenv import set_key

from autodub.config import Settings
from autodub.utils import data_root

#: Tên biến môi trường hợp lệ. Siết chặt vì dotenv.set_key KHÔNG trích dẫn tên
#: khoá: một tên chứa ký tự xuống dòng sẽ đẻ ra khoá mới trong .env, vòng qua
#: mọi danh sách trắng.
_ENV_KEY_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9_]*\Z")

#: Ký tự điều khiển bị cấm trong giá trị (tab được phép). Xuống dòng thật sẽ phá
#: cấu trúc tệp .env; muốn ngắt dòng thì gửi chuỗi \n như .env vẫn lưu.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

#: Trần độ dài giá trị chuỗi — rộng cho ngữ cảnh dịch dài, vẫn có chặn trên.
_MAX_TEXT = 8000

_TRUE_WORDS = ("true", "1", "yes", "on")
_FALSE_WORDS = ("false", "0", "no", "off")


def _as_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and value in (0, 1):
        return "true" if value else "false"
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_WORDS:
            return "true"
        if text in _FALSE_WORDS:
            return "false"
    raise ValueError(f"cần true/false, nhận {value!r}")


def _as_float(low: float, high: float) -> Callable[[Any], str]:
    def coerce(value: Any) -> str:
        if isinstance(value, bool):
            raise ValueError(f"cần số, nhận {value!r}")
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                raise ValueError(f"cần số, nhận {value!r}") from None
        else:
            raise ValueError(f"cần số, nhận {value!r}")
        if not math.isfinite(number):
            raise ValueError(f"cần số hữu hạn, nhận {value!r}")
        if not low <= number <= high:
            raise ValueError(f"phải trong khoảng {low}-{high}, nhận {number}")
        return repr(number)

    return coerce


def _as_choice(*allowed: str) -> Callable[[Any], str]:
    def coerce(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(f"cần chuỗi, nhận {value!r}")
        text = value.strip().lower()
        if text not in allowed:
            raise ValueError(
                f"phải là một trong {', '.join(allowed)}; nhận {value!r}"
            )
        return text

    return coerce


def _as_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"cần chuỗi, nhận {value!r}")
    text = value.strip()
    if _CONTROL_RE.search(text):
        raise ValueError("không được chứa ký tự điều khiển hoặc xuống dòng")
    if len(text) > _MAX_TEXT:
        raise ValueError(f"dài quá {_MAX_TEXT} ký tự")
    return text


#: Danh sách trắng khoá được ghi vào .env, kèm hàm ép kiểu và miền giá trị.
#: Cố ý trùng ĐÚNG tám khoá mà get_settings trả về — đọc được gì thì ghi được
#: nấy. Mọi khoá khác (TRANSLATION_ENDPOINT, TRANSLATION_API_KEY,
#: BILIBILI_COOKIES_FILE, các *_PATH, ...) đều bị từ chối.
_WRITABLE: dict[str, Callable[[Any], str]] = {
    "TRANSLATE_ENABLED": _as_bool,
    "TRANSLATE_DOMAIN": _as_text,
    "TRANSLATE_CONTEXT": _as_text,
    "SUBTITLE_MODE": _as_choice("none", "soft", "burn"),
    "QUALITY_PRESET": _as_choice("fast", "balanced", "quality"),
    "VIENEU_VOICE": _as_text,
    "VIDEO_SPEED": _as_float(0.5, 1.0),
    "VOICE_SPEED": _as_float(0.5, 2.0),
}


def get_settings(*args, settings: Settings | None = None, **kwargs) -> dict[str, Any]:
    """Get current application settings."""
    settings = Settings.load(override=True)
    return {
        "ok": True,
        "settings": {
            "translate_enabled": settings.translate_enabled,
            "translate_domain": settings.translate_domain,
            "translate_context": settings.translate_context,
            "subtitle_mode": settings.subtitle_mode,
            "quality_preset": settings.quality_preset,
            "vieneu_voice": settings.vieneu_voice,
            "video_speed": settings.video_speed,
            "voice_speed": settings.voice_speed,
        }
    }


def update_settings(updates: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
    """Update application settings — chỉ những khoá trong _WRITABLE.

    Kiểm tra TOÀN BỘ lô trước khi ghi câu nào, nên một lô lẫn khoá bị từ chối sẽ
    không để lại thay đổi dở dang nào trong .env.
    """
    if not isinstance(updates, dict):
        raise TypeError("updates phải là đối tượng key-value")
    if not updates:
        raise ValueError("updates rỗng: không có gì để cập nhật")

    problems: list[str] = []
    normalized: dict[str, Any] = {}

    for key, value in updates.items():
        if not isinstance(key, str) or not _ENV_KEY_RE.match(key.strip()):
            problems.append(f"tên khoá không hợp lệ: {key!r}")
            continue
        env_key = key.strip().upper()
        if env_key not in _WRITABLE:
            problems.append(f"khoá không nằm trong danh sách trắng: {env_key}")
            continue
        normalized[env_key] = value

    resolved: dict[str, str] = {}
    for env_key, value in normalized.items():
        try:
            resolved[env_key] = _WRITABLE[env_key](value)
        except ValueError as exc:
            problems.append(f"{env_key}: {exc}")

    if problems:
        raise ValueError(
            "; ".join(problems)
            + ". Khoá được phép: " + ", ".join(sorted(_WRITABLE))
        )

    env_path = os.path.join(data_root(), ".env")
    if not os.path.exists(env_path):
        open(env_path, "a", encoding="utf-8").close()

    for env_key, val_str in resolved.items():
        set_key(env_path, env_key, val_str)

    # Reload settings to ensure they take effect
    Settings.load(override=True)
    return {"ok": True, "updated_keys": list(resolved)}


def list_voices(*args, settings: Settings, **kwargs) -> dict[str, Any]:
    """List available voices for dubbing."""
    try:
        from autodub.speech.tts.voices import catalog
        voices = catalog(settings)
        return {
            "ok": True, 
            "voices": [
                {
                    "name": v.name, 
                    "gender": v.gender, 
                    "region": v.region
                } for v in voices
            ]
        }
    except Exception as exc:
        return {"ok": False, "error": f"Failed to list voices: {exc}"}


def get_system_status(*args, **kwargs) -> dict[str, Any]:
    """Get system resource status (RAM, CPU)."""
    from autodub.sysinfo import available_ram_gb
    
    return {
        "ok": True,
        "cpu_cores": os.cpu_count(),
        "ram_gb_free": available_ram_gb(),
    }


_REGISTRY = {
    "get_settings": get_settings,
    "update_settings": update_settings,
    "list_voices": list_voices,
    "get_system_status": get_system_status,
}


def dispatch_tool(name: str | None, arguments: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    if not name:
        raise ValueError("Tool name is required")
    func = _REGISTRY.get(name)
    if not func:
        raise ValueError(f"Tool not found: {name}")
    try:
        return func(**arguments, settings=settings)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
