"""Persistent first-run dependency bootstrap state."""
from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass

from autodub.utils import data_root as runtime_data_root, ensure_dir

STATE_VERSION = 1
STATE_NAME = "bootstrap-state.json"


def data_root() -> str:
    if os.environ.get("DUBFLOW_DATA_DIR"):
        return os.environ["DUBFLOW_DATA_DIR"]
    if getattr(sys, "frozen", False):
        return runtime_data_root()
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        if root:
            return os.path.join(root, "DubFlow")
    root = os.environ.get("XDG_DATA_HOME")
    if root:
        return os.path.join(root, "dubflow")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "dubflow")


def state_path() -> str:
    return os.path.join(data_root(), STATE_NAME)


@dataclass(frozen=True)
class BootstrapStep:
    key: str
    label: str
    kind: str
    script: str = ""


def steps() -> tuple[BootstrapStep, ...]:
    common = (
        BootstrapStep("vieneu", "VieNeu voice engine", "script",
                      "scripts/setup_vieneu.py"),
        BootstrapStep("whisper", "Whisper ASR", "script",
                      "scripts/setup_whisper.py"),
        BootstrapStep("paraformer", "Paraformer Chinese ASR", "script",
                      "scripts/setup_paraformer.py"),
        BootstrapStep("ocr", "OCR support", "script",
                      "scripts/setup_ocr.py"),
        BootstrapStep("douyin", "Douyin downloader", "script",
                      "scripts/setup_douyin.py"),
        BootstrapStep("demucs", "Demucs vocal separation", "script",
                      "scripts/setup_demucs.py"),
        BootstrapStep("voices", "Voice library", "voices"),
    )
    steps = [BootstrapStep("python", "Python runtime", "python")]
    if not sys.platform.startswith("linux"):
        steps.append(BootstrapStep("ffmpeg", "FFmpeg", "ffmpeg"))
    return tuple(steps) + common


def load_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as handle:
            state = json.load(handle)
        if state.get("version") != STATE_VERSION:
            raise ValueError("unsupported state version")
        return state
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"version": STATE_VERSION, "completed": {}, "failed": {}}


def save_state(state: dict) -> None:
    path = state_path()
    ensure_dir(os.path.dirname(path))
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def mark_completed(key: str) -> None:
    state = load_state()
    state.setdefault("completed", {})[key] = True
    state.setdefault("failed", {}).pop(key, None)
    save_state(state)


def mark_failed(key: str, message: str) -> None:
    state = load_state()
    state.setdefault("failed", {})[key] = str(message)
    save_state(state)


def is_complete() -> bool:
    completed = load_state().get("completed", {})
    for step in steps():
        if step.key == "ffmpeg" and sys.platform.startswith("linux"):
            # Debian declares FFmpeg as a package dependency. Do not send
            # installed Debian users through the download worker.
            from autodub_gui.workers_setup import _system_ffmpeg_pair

            if _system_ffmpeg_pair():
                continue
        if completed.get(step.key) is not True:
            return False
    return True


def reset_state() -> None:
    try:
        os.remove(state_path())
    except FileNotFoundError:
        pass
