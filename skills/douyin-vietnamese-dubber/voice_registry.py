#!/usr/bin/env python3
"""Shared OpenClaw voice registry for video TTS voices.

The registry stores public voice metadata only. API keys/tokens stay in env.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

RUNTIME_REGISTRY = Path(os.environ.get("OPENCLAW_VOICE_REGISTRY_JSON") or "/home/haonguyen/.openclaw/config/voice_registry.json")
DEFAULT_REGISTRY = Path(os.environ.get("OPENCLAW_VOICE_REGISTRY_DEFAULT_JSON") or Path(__file__).with_name("voice_registry.default.json"))

VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{3,160}$")
ALIAS_RE = re.compile(r"^[a-z0-9_.:-]{1,80}$")
CANONICAL_RE = re.compile(r"^ai33:([A-Za-z0-9_.:-]{3,160})$")
KNOWN_PROVIDER_ID_RE = re.compile(r"(?:^|[^A-Za-z0-9_:-])((?:vbee|elevenlabs)_[A-Za-z0-9_.:-]{3,160})", re.I)
VOICE_ID_KEYS = {
    "voice_id",
    "voiceid",
    "voice",
    "speaker_id",
    "speakerid",
    "speaker",
    "tts_voice",
    "ttsvoice",
}
TIMING_OVERRIDE_BOUNDS = {
    "ai33_max_speed": (1.0, 1.5),
    "post_atempo_max": (1.0, 1.5),
    "total_audio_speed_max": (1.0, 1.5),
}
DUB_TEXT_OVERRIDE_BOUNDS = {
    # A higher threshold restores omitted source/subtitle details sooner after the
    # measured natural-speed probe. It never adds filler or stretches audio.
    "restore_if_slot_ratio_below": (0.5, 0.95),
}


class VoiceRegistryError(ValueError):
    pass


def _strip_ai33_prefix(voice_id: str) -> str:
    voice_id = str(voice_id or "").strip()
    if voice_id.lower().startswith("ai33:"):
        return voice_id.split(":", 1)[1].strip()
    return voice_id


def _valid_voice_id_or_empty(value: str) -> str:
    voice_id = _strip_ai33_prefix(value)
    if not VOICE_ID_RE.match(voice_id):
        return ""
    return voice_id


def _extract_from_mapping(data: Any) -> str:
    if isinstance(data, dict):
        for key, value in data.items():
            norm_key = str(key or "").replace("-", "_").lower()
            if norm_key in VOICE_ID_KEYS:
                voice_id = _valid_voice_id_or_empty(str(value or ""))
                if voice_id:
                    return voice_id
        for value in data.values():
            found = _extract_from_mapping(value)
            if found:
                return found
    if isinstance(data, list):
        for value in data:
            found = _extract_from_mapping(value)
            if found:
                return found
    return ""


def extract_ai33_voice_id(value: str | None) -> str:
    """Extract a clean AI33 voice_id from a raw id, canonical id, JSON, or UI URL.

    This is intentionally offline: it never fetches the URL or touches credentials.
    """
    raw = str(value or "").strip()
    if not raw:
        raise VoiceRegistryError("VoiceInvalid: thiếu voice_id hoặc link giọng AI33")

    direct = _valid_voice_id_or_empty(raw)
    if direct and not re.search(r"[/?#=&\s]", raw):
        return direct

    try:
        parsed_json = json.loads(raw)
        found = _extract_from_mapping(parsed_json)
        if found:
            return found
    except Exception:
        pass

    decoded = urllib.parse.unquote(raw)
    parsed = urllib.parse.urlparse(decoded)
    query_parts = [parsed.query]
    if parsed.fragment:
        frag = parsed.fragment[1:] if parsed.fragment.startswith("?") else parsed.fragment
        query_parts.append(urllib.parse.urlparse(frag).query or frag)
    for query in query_parts:
        for key, values in urllib.parse.parse_qs(query, keep_blank_values=False).items():
            norm_key = str(key or "").replace("-", "_").lower()
            if norm_key in VOICE_ID_KEYS:
                for item in values:
                    voice_id = _valid_voice_id_or_empty(item)
                    if voice_id:
                        return voice_id

    for key in sorted(VOICE_ID_KEYS, key=len, reverse=True):
        pattern = rf"(?:[?&#/\s\"']|^){re.escape(key)}(?:=|:|/)(?:[\"']?)([A-Za-z0-9_.:-]{{3,160}})"
        match = re.search(pattern, decoded, re.I)
        if match:
            voice_id = _valid_voice_id_or_empty(match.group(1).rstrip(".,;)'\""))
            if voice_id:
                return voice_id

    match = KNOWN_PROVIDER_ID_RE.search(decoded)
    if match:
        voice_id = _valid_voice_id_or_empty(match.group(1).rstrip(".,;)'\""))
        if voice_id:
            return voice_id

    raise VoiceRegistryError("VoiceInvalid: không tìm thấy voice_id trong link/chuỗi đã dán")


def canonical_ai33(voice_id: str) -> str:
    voice_id = extract_ai33_voice_id(voice_id)
    if not VOICE_ID_RE.match(voice_id):
        raise VoiceRegistryError("VoiceInvalid: voice_id không hợp lệ")
    return f"ai33:{voice_id}"


def _normalize_timing_overrides(value: Any, voice_id: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise VoiceRegistryError(f"VoiceRegistryInvalid: timing_overrides phải là object: {voice_id}")
    normalized: dict[str, float] = {}
    for key, raw_value in value.items():
        if key not in TIMING_OVERRIDE_BOUNDS:
            raise VoiceRegistryError(f"VoiceRegistryInvalid: timing_overrides không hỗ trợ: {key}")
        try:
            number = float(raw_value)
        except Exception as exc:
            raise VoiceRegistryError(f"VoiceRegistryInvalid: timing_overrides {key} không hợp lệ: {voice_id}") from exc
        low, high = TIMING_OVERRIDE_BOUNDS[key]
        if number < low or number > high:
            raise VoiceRegistryError(
                f"VoiceRegistryInvalid: timing_overrides {key} phải trong khoảng {low}-{high}: {voice_id}"
            )
        normalized[key] = number
    return normalized


def _normalize_dub_text_overrides(value: Any, voice_id: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise VoiceRegistryError(f"VoiceRegistryInvalid: dub_text_overrides phải là object: {voice_id}")
    normalized: dict[str, float] = {}
    for key, raw_value in value.items():
        if key not in DUB_TEXT_OVERRIDE_BOUNDS:
            raise VoiceRegistryError(f"VoiceRegistryInvalid: dub_text_overrides không hỗ trợ: {key}")
        try:
            number = float(raw_value)
        except Exception as exc:
            raise VoiceRegistryError(f"VoiceRegistryInvalid: dub_text_overrides {key} không hợp lệ: {voice_id}") from exc
        low, high = DUB_TEXT_OVERRIDE_BOUNDS[key]
        if number < low or number > high:
            raise VoiceRegistryError(
                f"VoiceRegistryInvalid: dub_text_overrides {key} phải trong khoảng {low}-{high}: {voice_id}"
            )
        normalized[key] = number
    return normalized


def _fallback_registry() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "default_voice": "ai33:vbee_hn_female_maiphuong_vdts_48k-fhg",
        "voices": [
            {
                "provider": "ai33",
                "voice_id": "vbee_hn_female_maiphuong_vdts_48k-fhg",
                "label": "Mai Phuong - Vbee",
                "aliases": ["ai33", "vbee", "vbee-maiphuong", "vbee-mai-phuong", "maiphuong", "mai-phuong", "mai_phuong"],
                "enabled": True,
                "timing_profile": "ai33_balanced_fast",
                "min_slow_ratio": 0.85,
            },
            {
                "provider": "ai33",
                "voice_id": "elevenlabs_UuMSQK8FdLwaY2M8ZAnh",
                "label": "Phanh - ElevenLabs",
                "aliases": ["elevenlabs", "elevenlabs-phanh", "eleven-phanh", "phanh", "phan"],
                "enabled": True,
                "timing_profile": "ai33_balanced_fast",
                "min_slow_ratio": 0.85,
            },
        ],
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise VoiceRegistryError(f"VoiceRegistryInvalid: không đọc được {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise VoiceRegistryError("VoiceRegistryInvalid: root phải là object")
    return data


def load_raw_registry(path: Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else RUNTIME_REGISTRY
    if path.exists():
        return _read_json(path)
    if DEFAULT_REGISTRY.exists():
        return _read_json(DEFAULT_REGISTRY)
    return _fallback_registry()


def validate_registry(data: dict[str, Any]) -> dict[str, Any]:
    voices_in = data.get("voices")
    if not isinstance(voices_in, list):
        raise VoiceRegistryError("VoiceRegistryInvalid: thiếu voices list")

    voices: list[dict[str, Any]] = []
    seen_voice_ids: set[str] = set()
    seen_lookups: dict[str, str] = {}

    for item in voices_in:
        if not isinstance(item, dict):
            raise VoiceRegistryError("VoiceRegistryInvalid: voice entry phải là object")
        provider = str(item.get("provider") or "ai33").strip().lower()
        if provider != "ai33":
            raise VoiceRegistryError(f"VoiceRegistryInvalid: provider chưa hỗ trợ: {provider}")
        voice_id = extract_ai33_voice_id(item.get("voice_id") or item.get("id") or item.get("voice_url") or "")
        canonical = canonical_ai33(voice_id)
        key = voice_id.lower()
        if key in seen_voice_ids:
            raise VoiceRegistryError(f"VoiceRegistryInvalid: voice_id trùng: {voice_id}")
        seen_voice_ids.add(key)
        for lookup in (key, canonical.lower()):
            existing = seen_lookups.get(lookup)
            if existing and existing != canonical:
                raise VoiceRegistryError(f"VoiceRegistryInvalid: alias trùng: {lookup}")
            seen_lookups[lookup] = canonical

        aliases: list[str] = []
        raw_aliases = item.get("aliases") or []
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        if not isinstance(raw_aliases, list):
            raise VoiceRegistryError(f"VoiceRegistryInvalid: aliases phải là list: {voice_id}")
        for alias in raw_aliases:
            norm_alias = str(alias or "").strip().lower()
            if not norm_alias:
                continue
            if norm_alias.startswith("ai33:"):
                norm_alias = norm_alias.split(":", 1)[1]
            if not ALIAS_RE.match(norm_alias):
                raise VoiceRegistryError(f"VoiceRegistryInvalid: alias không hợp lệ: {alias}")
            existing = seen_lookups.get(norm_alias)
            if existing and existing != canonical:
                raise VoiceRegistryError(f"VoiceRegistryInvalid: alias trùng: {norm_alias}")
            seen_lookups[norm_alias] = canonical
            if norm_alias not in aliases:
                aliases.append(norm_alias)

        try:
            min_slow_ratio = float(item.get("min_slow_ratio", 0.85))
        except Exception as exc:
            raise VoiceRegistryError(f"VoiceRegistryInvalid: min_slow_ratio không hợp lệ: {voice_id}") from exc
        min_slow_ratio = max(0.5, min(1.0, min_slow_ratio))
        timing_overrides = _normalize_timing_overrides(item.get("timing_overrides"), voice_id)
        dub_text_overrides = _normalize_dub_text_overrides(item.get("dub_text_overrides"), voice_id)

        voices.append(
            {
                "provider": "ai33",
                "voice_id": voice_id,
                "canonical_voice": canonical,
                "label": str(item.get("label") or item.get("display_name") or voice_id).strip() or voice_id,
                "aliases": aliases,
                "enabled": bool(item.get("enabled", True)),
                "timing_profile": str(item.get("timing_profile") or "ai33_balanced_fast").strip() or "ai33_balanced_fast",
                "min_slow_ratio": min_slow_ratio,
                "timing_overrides": timing_overrides,
                "dub_text_overrides": dub_text_overrides,
            }
        )

    default_voice = str(data.get("default_voice") or "").strip()
    if not default_voice:
        if voices:
            default_voice = voices[0]["canonical_voice"]
    else:
        m = CANONICAL_RE.match(default_voice)
        default_voice = canonical_ai33(m.group(1) if m else default_voice)

    default_entry = next((v for v in voices if v["canonical_voice"].lower() == default_voice.lower()), None)
    if not default_entry:
        raise VoiceRegistryError(f"VoiceRegistryInvalid: default_voice không nằm trong registry: {default_voice}")
    if not default_entry.get("enabled", True):
        raise VoiceRegistryError(f"VoiceRegistryInvalid: default_voice đang disabled: {default_voice}")

    return {
        "schema_version": int(data.get("schema_version") or 1),
        "default_voice": default_entry["canonical_voice"],
        "voices": voices,
        "updated_at": data.get("updated_at") or "",
    }


def load_registry(path: Path | None = None) -> dict[str, Any]:
    return validate_registry(load_raw_registry(path))


def _find_ai33(registry: dict[str, Any], value: str) -> dict[str, Any] | None:
    raw = str(value or "").strip()
    lower = raw.lower()
    folded = unicodedata.normalize("NFKD", lower).encode("ascii", "ignore").decode("ascii")
    lookup_keys = {lower, folded, folded.replace(" ", "-"), folded.replace(" ", "_")}
    if not lower:
        lower = str(registry.get("default_voice") or "").lower()
        lookup_keys = {lower}
    if lower == "ai33":
        lower = str(registry.get("default_voice") or "").lower()
        lookup_keys = {lower}
    if lower.startswith("ai33:"):
        lower_id = lower.split(":", 1)[1]
    else:
        lower_id = lower
    for item in registry.get("voices") or []:
        if not item.get("enabled", True):
            continue
        voice_id = str(item.get("voice_id") or "").lower()
        canonical = str(item.get("canonical_voice") or "").lower()
        aliases = {str(a).lower() for a in item.get("aliases") or []}
        alias_keys = aliases | {
            unicodedata.normalize("NFKD", alias).encode("ascii", "ignore").decode("ascii")
            for alias in aliases
        }
        if (
            lower == canonical
            or lower_id == voice_id
            or lookup_keys & alias_keys
            or lower_id in alias_keys
        ):
            return item
    return None


def looks_like_ai33(value: str) -> bool:
    lower = str(value or "").strip().lower()
    if not lower:
        return True
    return lower == "ai33" or lower.startswith("ai33:") or lower.startswith("vbee_") or lower.startswith("elevenlabs_")


def normalize_ai33_voice(value: str | None, registry: dict[str, Any] | None = None) -> str:
    registry = registry or load_registry()
    raw = str(value or "").strip()
    item = _find_ai33(registry, raw)
    if item:
        return str(item["canonical_voice"])
    if looks_like_ai33(raw):
        raise VoiceRegistryError(f"VoiceInvalid: AI33 voice chưa có trong registry: {raw or registry.get('default_voice')}")
    raise VoiceRegistryError(f"VoiceNotAI33: {raw}")


def ai33_metadata(value: str | None, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_registry()
    raw = str(value or "").strip()
    item = _find_ai33(registry, raw)
    if not item:
        raise VoiceRegistryError(f"VoiceInvalid: AI33 voice chưa có trong registry: {raw}")
    return dict(item)


def default_voice(registry: dict[str, Any] | None = None) -> str:
    registry = registry or load_registry()
    return str(registry["default_voice"])


def public_registry(path: Path | None = None) -> dict[str, Any]:
    registry = load_registry(path)
    return {
        "ok": True,
        "schema_version": registry["schema_version"],
        "default_voice": registry["default_voice"],
        "voices": list(registry["voices"]),
        "registry_path": str(Path(path) if path else RUNTIME_REGISTRY),
        "default_registry_path": str(DEFAULT_REGISTRY),
    }


def save_registry(data: dict[str, Any], path: Path | None = None, make_backup: bool = True) -> dict[str, Any]:
    path = Path(path) if path else RUNTIME_REGISTRY
    registry = validate_registry(data)
    registry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    path.parent.mkdir(parents=True, exist_ok=True)
    if make_backup and path.exists():
        backup = path.with_name(f"{path.name}.bak.{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return registry


def add_ai33_voice(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    registry = load_registry(path)
    voice_id = extract_ai33_voice_id(
        payload.get("voice_id")
        or payload.get("voiceId")
        or payload.get("voice_url")
        or payload.get("voiceUrl")
        or payload.get("voice_input")
        or payload.get("voiceInput")
        or payload.get("url")
        or payload.get("link")
        or ""
    )
    canonical = canonical_ai33(voice_id)
    label = str(payload.get("label") or payload.get("display_name") or voice_id).strip() or voice_id
    aliases_in = payload.get("aliases") or []
    if isinstance(aliases_in, str):
        aliases_in = [a.strip() for a in re.split(r"[,\s]+", aliases_in) if a.strip()]
    aliases = [str(a).strip().lower() for a in aliases_in if str(a).strip()]
    new_item = {
        "provider": "ai33",
        "voice_id": voice_id,
        "canonical_voice": canonical,
        "label": label,
        "aliases": aliases,
        "enabled": bool(payload.get("enabled", True)),
        "timing_profile": str(payload.get("timing_profile") or "ai33_balanced_fast"),
        "min_slow_ratio": float(payload.get("min_slow_ratio", 0.85) or 0.85),
        "timing_overrides": payload.get("timing_overrides") or {},
        "dub_text_overrides": payload.get("dub_text_overrides") or {},
    }
    voices = [v for v in registry["voices"] if str(v.get("voice_id", "")).lower() != voice_id.lower()]
    voices.append(new_item)
    registry["voices"] = voices
    if payload.get("set_default"):
        registry["default_voice"] = canonical
    return save_registry(registry, path)


def set_default_voice(voice: str, path: Path | None = None) -> dict[str, Any]:
    registry = load_registry(path)
    canonical = normalize_ai33_voice(voice, registry)
    registry["default_voice"] = canonical
    return save_registry(registry, path)


def disable_voice(voice: str, path: Path | None = None) -> dict[str, Any]:
    registry = load_registry(path)
    canonical = normalize_ai33_voice(voice, registry)
    if canonical.lower() == str(registry["default_voice"]).lower():
        raise VoiceRegistryError("VoiceDefaultDisableBlocked: không thể tắt giọng mặc định; hãy chọn default khác trước")
    for item in registry["voices"]:
        if str(item.get("canonical_voice", "")).lower() == canonical.lower():
            item["enabled"] = False
            break
    return save_registry(registry, path)


def restore_latest_backup(path: Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else RUNTIME_REGISTRY
    backups = sorted(path.parent.glob(f"{path.name}.bak.*"))
    if not backups:
        raise VoiceRegistryError("VoiceRegistryNoBackup: chưa có backup registry")
    latest = backups[-1]
    data = validate_registry(_read_json(latest))
    save_registry(data, path, make_backup=True)
    return load_registry(path)


def seed_runtime(path: Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else RUNTIME_REGISTRY
    if path.exists():
        return load_registry(path)
    data = load_registry(DEFAULT_REGISTRY if DEFAULT_REGISTRY.exists() else None)
    return save_registry(data, path, make_backup=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("default")
    p_norm = sub.add_parser("normalize-ai33")
    p_norm.add_argument("voice", nargs="?", default="")
    p_meta = sub.add_parser("metadata")
    p_meta.add_argument("voice", nargs="?", default="")
    sub.add_parser("list")
    sub.add_parser("seed-runtime")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "default":
            print(default_voice())
        elif args.cmd == "normalize-ai33":
            print(normalize_ai33_voice(args.voice))
        elif args.cmd == "metadata":
            print(json.dumps(ai33_metadata(args.voice), ensure_ascii=False))
        elif args.cmd == "list":
            print(json.dumps(public_registry(), ensure_ascii=False, indent=2))
        elif args.cmd == "seed-runtime":
            print(json.dumps(public_registry(path=RUNTIME_REGISTRY if seed_runtime() else None), ensure_ascii=False, indent=2))
    except VoiceRegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 7 if "VoiceInvalid" in str(exc) or "VoiceRegistry" in str(exc) else 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
