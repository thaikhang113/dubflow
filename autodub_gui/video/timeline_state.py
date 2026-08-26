"""Persistent timeline state for editor projects."""
from __future__ import annotations

import json
import os
from typing import Any

from autodub.utils import save_json_atomic
from autodub.workdir import data_path
from autodub_gui.video.layer_bridge import build_timeline
from autodub_gui.video.layer_model import Timeline

TIMELINE_FILE = "timeline.json"


def load_timeline(
    work_dir: str,
    segments: list[dict[str, Any]],
    blur_regions: list[dict[str, Any]] | None,
    duration: float,
    *,
    video_path: str = "",
    audio_paths: dict[str, str] | None = None,
    branding: dict[str, Any] | None = None,
) -> Timeline:
    path = data_path(work_dir, TIMELINE_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return Timeline.from_dict(data)
    except (OSError, TypeError, ValueError):
        pass
    return build_timeline(
        segments,
        blur_regions,
        duration,
        video_path=video_path,
        audio_paths=audio_paths,
        branding=branding,
    )


def save_timeline(work_dir: str, timeline: Timeline) -> None:
    save_json_atomic(
        timeline.to_dict(),
        data_path(work_dir, TIMELINE_FILE, create_dir=True),
    )


def timeline_exists(work_dir: str) -> bool:
    return os.path.isfile(data_path(work_dir, TIMELINE_FILE))
