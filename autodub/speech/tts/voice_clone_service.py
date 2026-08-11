"""Local enrollment boundary for reusable VieNeu clone voices."""
from __future__ import annotations

import os
import tempfile

from .voice_clone import (
    enroll_reference_audio,
    prepare_reference_audio,
)

_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}

def validate_clone_request(values: dict) -> str | None:
    source = str(values.get("source", "")).strip().lower()
    path = str(values.get("path", "")).strip()
    name = str(values.get("name", "")).strip()
    if source not in {"audio", "video"}:
        return "Chọn nguồn audio hoặc video."
    if not path:
        return "Chọn file nguồn."
    if not name:
        return "Nhập tên giọng clone."
    ext = os.path.splitext(path)[1].lower()
    allowed = _AUDIO_EXTENSIONS if source == "audio" else _VIDEO_EXTENSIONS
    if ext not in allowed:
        return "Định dạng file không được hỗ trợ."
    return None

def _enroll(settings, source: str, name: str, suffix: str) -> str:
    with tempfile.TemporaryDirectory(prefix="voxdub_clone_") as temp:
        reference = os.path.join(temp, "reference.wav")
        normalized = prepare_reference_audio(source, reference)
        return enroll_reference_audio(settings, normalized, name=name)

def enroll_from_audio(settings, source_audio: str, name: str) -> str:
    if not os.path.isfile(source_audio):
        raise FileNotFoundError(source_audio)
    error = validate_clone_request(
        {"source": "audio", "path": source_audio, "name": name})
    if error:
        raise ValueError(error)
    return _enroll(settings, source_audio, name, ".wav")

def enroll_from_video(
    settings,
    video_path: str,
    name: str,
    *,
    source_lang: str = "zh-CN",
) -> str:
    del source_lang
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    error = validate_clone_request(
        {"source": "video", "path": video_path, "name": name})
    if error:
        raise ValueError(error)
    return _enroll(settings, video_path, name, ".mp4")
