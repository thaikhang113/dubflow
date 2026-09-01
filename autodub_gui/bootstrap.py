"""Persistent first-run dependency bootstrap state."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

from autodub.hardware import BackendPlan, detect_hardware, select_backends
from autodub.utils import data_root as runtime_data_root
from autodub.utils import ensure_dir

STATE_VERSION = 1
STATE_NAME = "bootstrap-state.json"
PLAN_NAME = "backend-plan.json"


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

def plan_path() -> str:
    return os.path.join(data_root(), PLAN_NAME)


@dataclass(frozen=True)
class BootstrapStep:
    key: str
    label: str
    kind: str
    script: str = ""


def load_plan() -> BackendPlan | None:
    try:
        with open(plan_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
        return BackendPlan(
            str(payload["ocr_backend"]),
            str(payload["vsr_backend"]),
            tuple(str(item) for item in payload.get("reasons", [])),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

def ensure_hardware_plan() -> BackendPlan:
    profile = detect_hardware(disk_path=data_root())
    plan = load_plan()
    deepseek_enabled = os.environ.get(
        "DEEPSEEK_OCR_ENABLED", "false").strip().lower() in (
            "1", "true", "yes", "on")
    try:
        with open(plan_path(), encoding="utf-8") as handle:
            stored = json.load(handle).get("hardware", {})
        current = profile.as_dict()
        comparable = set(current) - {"disk_free_gb"}
        if plan is not None and all(
            stored.get(key) == current[key] for key in comparable
        ) and (deepseek_enabled or not plan.ocr_backend.startswith("deepseek")):
            os.environ["DUBFLOW_BACKEND_PLAN"] = plan_path()
            return plan
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    plan = select_backends(profile, deepseek_enabled)
    ensure_dir(data_root())
    with open(plan_path(), "w", encoding="utf-8") as handle:
        json.dump({
            "hardware": profile.as_dict(),
            **plan.as_dict(),
        }, handle, ensure_ascii=False, indent=2)
    os.environ["DUBFLOW_BACKEND_PLAN"] = plan_path()
    return plan

def steps(plan: BackendPlan | None = None) -> tuple[BootstrapStep, ...]:
    plan = plan or load_plan()
    common = (
        BootstrapStep("vieneu", "VieNeu voice engine", "script",
                      "scripts/setup_vieneu.py"),
        BootstrapStep("whisper", "Whisper ASR", "script",
                      "scripts/setup_whisper.py"),
        BootstrapStep("paraformer", "Paraformer Chinese ASR", "script",
                      "scripts/setup_paraformer.py"),
        BootstrapStep("ocr", "PaddleOCR", "script",
                      "scripts/setup_ocr.py"),
        BootstrapStep("douyin", "Douyin downloader", "script",
                      "scripts/setup_douyin.py"),
        BootstrapStep("demucs", "Demucs vocal separation", "script",
                      "scripts/setup_demucs.py"),
        BootstrapStep("voices", "Voice library", "voices"),
    )
    steps = [BootstrapStep("python", "Python runtime", "python")]
    steps.insert(0, BootstrapStep("hardware", "Hardware scan", "hardware"))
    if not sys.platform.startswith("linux"):
        steps.append(BootstrapStep("ffmpeg", "FFmpeg", "ffmpeg"))
    result = tuple(steps) + common
    if plan and plan.vsr_backend == "video-subtitle-remover":
        result += (
            BootstrapStep("vsr", "Video subtitle remover", "script",
                          "scripts/setup_vsr.py"),
        )
    return result


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
    if load_plan() is None:
        return False
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
