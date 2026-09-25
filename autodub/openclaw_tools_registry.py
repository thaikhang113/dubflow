"""Tool registry for OpenClaw dynamic app control."""
from __future__ import annotations

import os
from typing import Any

from dotenv import set_key

from autodub.config import Settings
from autodub.utils import data_root

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
    """Update application settings."""
    env_path = os.path.join(data_root(), ".env")
    if not os.path.exists(env_path):
        open(env_path, "a", encoding="utf-8").close()

    # Apply updates
    for key, value in updates.items():
        env_key = key.upper()
        if isinstance(value, bool):
            val_str = "true" if value else "false"
        else:
            val_str = str(value)
        set_key(env_path, env_key, val_str)
    
    # Reload settings to ensure they take effect
    Settings.load(override=True)
    return {"ok": True, "updated_keys": list(updates.keys())}

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
        result = func(**arguments, settings=settings)
        return result
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
