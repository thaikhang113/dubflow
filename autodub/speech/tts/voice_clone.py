"""Small, dependency-light helpers for VieNeu reference voice cloning."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import wave


MIN_REFERENCE_SECONDS = 1.0
MAX_REFERENCE_SECONDS = 8.0


def validate_reference_duration(
    duration: float,
    *,
    minimum: float = MIN_REFERENCE_SECONDS,
    maximum: float = MAX_REFERENCE_SECONDS,
) -> bool:
    return minimum <= float(duration) <= maximum


def reference_duration_seconds(path: str) -> float:
    """Read WAV duration without importing audio libraries."""
    with wave.open(path, "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def select_reference_window(
    segments: list[dict],
    *,
    minimum: float = MIN_REFERENCE_SECONDS,
    maximum: float = MAX_REFERENCE_SECONDS,
) -> tuple[float, float] | None:
    """Choose the longest transcript segment usable as a voice reference."""
    candidates = []
    for segment in segments:
        try:
            start, end = float(segment["start"]), float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        duration = end - start
        if duration >= minimum:
            candidates.append((duration, start, min(end, start + maximum)))
    if not candidates:
        return None
    _, start, end = max(candidates)
    return round(start, 3), round(end, 3)


def reference_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clone_voice_name(ref_hash: str) -> str:
    return f"DubFlow Clone {ref_hash[:8]}"


def custom_voice_is_cached(path: str, name: str, ref_hash: str) -> bool:
    """Return true when an enrolled voice has the same reference fingerprint."""
    if not path or not os.path.isfile(path):
        return False
    try:
        import json

        with open(path, encoding="utf-8") as source:
            entry = json.load(source).get("presets", {}).get(name, {})
        return entry.get("source") == "custom" and entry.get("reference_hash") == ref_hash
    except (OSError, ValueError, AttributeError):
        return False


def prepare_reference_audio(
    source: str,
    output: str,
    *,
    start: float = 0.0,
    duration: float = MAX_REFERENCE_SECONDS,
) -> str:
    """Normalize any ffmpeg-readable source into a VieNeu-ready WAV."""
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.3f}",
         "-i", source, "-t", f"{duration:.3f}", "-ar", "16000", "-ac", "1",
         "-sample_fmt", "s16", "-y", output],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not os.path.isfile(output):
        raise RuntimeError(proc.stderr[-500:] or "Không chuẩn hóa được audio mẫu")
    actual = reference_duration_seconds(output)
    if not validate_reference_duration(actual):
        raise ValueError("Audio mẫu cần dài từ 1 đến 8 giây")
    return output


def enroll_reference_audio(
    settings,
    reference_audio: str,
    *,
    name: str | None = None,
    description: str = "Voice clone từ video",
) -> str:
    """Enroll once through the existing standalone VieNeu worker."""
    if not settings.vieneu_configured():
        raise RuntimeError("VieNeu chưa được cài")
    ref_hash = reference_hash(reference_audio)
    voice_name = name or clone_voice_name(ref_hash)
    custom_path = settings.vieneu_custom_voices_path()
    if custom_voice_is_cached(custom_path, voice_name, ref_hash):
        return voice_name

    from autodub.utils import bundled_file

    cmd = [
        settings.vieneu_venv_python_path(),
        bundled_file("autodub", "speech", "tts", "vieneu_worker.py"),
        "--model-dir", settings.vieneu_model_dir_path(),
        "--custom-voices", custom_path,
        "--enroll", reference_audio,
        "--enroll-name", voice_name,
        "--enroll-desc", description,
        "--style", settings.vieneu_style,
        "--enroll-reference-hash", ref_hash,
    ]
    from autodub.cancel import run_registered
    proc = run_registered(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600,
    )
    responses = []
    for line in (proc.stdout or "").splitlines():
        try:
            responses.append(json.loads(line))
        except ValueError:
            continue
    result = responses[-1] if responses else {}
    if proc.returncode != 0 or not result.get("ok"):
        raise RuntimeError(
            result.get("error") or (proc.stderr or "VieNeu enroll thất bại")[-500:])
    from autodub.speech.tts.voices import invalidate_catalog_cache
    invalidate_catalog_cache()
    return voice_name

def enroll_reference_audio_batch(settings, items: list[dict]) -> dict[str, str]:
    """Enroll several references in one VieNeu worker startup."""
    if not items:
        return {}
    if not settings.vieneu_configured():
        raise RuntimeError("VieNeu chưa được cài")

    from autodub.utils import bundled_file

    custom_path = settings.vieneu_custom_voices_path()
    batch_path = os.path.join(
        os.path.dirname(os.path.abspath(custom_path)),
        "speaker_enroll_batch.json",
    )
    payload = []
    names: dict[str, str] = {}
    for item in items:
        name = str(item["name"])
        names[str(item["speaker_id"])] = name
        payload.append({
            "wav": item["wav"],
            "name": name,
            "description": item.get("description", "Voice clone từ video"),
            "style": settings.vieneu_style,
            "source": "custom",
            "reference_hash": item.get("reference_hash", ""),
        })
    with open(batch_path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
    try:
        from autodub.cancel import run_registered
        cmd = [
            settings.vieneu_venv_python_path(),
            bundled_file("autodub", "speech", "tts", "vieneu_worker.py"),
            "--model-dir", settings.vieneu_model_dir_path(),
            "--custom-voices", custom_path,
            "--enroll-batch", batch_path,
            "--style", settings.vieneu_style,
        ]
        proc = run_registered(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600,
        )
        responses = []
        for line in (proc.stdout or "").splitlines():
            try:
                responses.append(json.loads(line))
            except ValueError:
                continue
        result = responses[-1] if responses else {}
        if proc.returncode != 0 or not result.get("ok"):
            raise RuntimeError(
                result.get("error") or
                (proc.stderr or "VieNeu enroll batch thất bại")[-500:]
            )
    finally:
        try:
            os.remove(batch_path)
        except OSError:
            pass
    from autodub.speech.tts.voices import invalidate_catalog_cache
    invalidate_catalog_cache()
    return names

def custom_voice_names(path: str) -> set[str]:
    if not path or not os.path.isfile(path):
        return set()
    try:
        with open(path, encoding="utf-8") as source:
            presets = json.load(source).get("presets", {})
        return {
            str(name) for name, entry in (presets or {}).items()
            if isinstance(entry, dict) and entry.get("source", "custom") == "custom"
        }
    except (OSError, ValueError, AttributeError):
        return set()

def delete_custom_voice(path: str, name: str) -> bool:
    """Delete one enrolled voice atomically; never touch source media."""
    if not path or not name or not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as source:
            data = json.load(source)
        presets = data.get("presets")
        if not isinstance(presets, dict) or name not in presets:
            return False
        if not isinstance(presets[name], dict) or (
            presets[name].get("source", "custom") != "custom"
        ):
            return False
        del presets[name]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as target:
            json.dump(data, target, ensure_ascii=False)
        os.replace(tmp, path)
        from autodub.speech.tts.voices import invalidate_catalog_cache
        invalidate_catalog_cache()
        return True
    except (OSError, ValueError, AttributeError, TypeError):
        try:
            if os.path.isfile(path + ".tmp"):
                os.remove(path + ".tmp")
        except OSError:
            pass
        return False
