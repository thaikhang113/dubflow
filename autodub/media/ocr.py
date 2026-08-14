"""Application-side orchestration for optional local PaddleOCR."""
from __future__ import annotations

import json
import math
import os
import subprocess

from autodub.media.ocr_regions import (
    detections_to_logo_regions,
    detections_to_regions,
    merge_regions,
)
from autodub.utils import setup_logging

logger = setup_logging("autodub.ocr")


def _sample_times(duration: float, interval: float) -> list[float]:
    if duration <= 0:
        return [0.0]
    count = max(1, int(math.ceil(duration / interval)))
    return [round(min(duration - 0.05, i * interval), 3) for i in range(count)]


def _run_detections(
    video_path: str,
    duration: float,
    settings,
) -> list[dict]:
    if not settings.ocr_configured():
        raise RuntimeError(
            "PaddleOCR chưa được cài. Chạy scripts/setup_ocr.py rồi thử lại.")
    times = _sample_times(duration, settings.ocr_sample_interval)
    cmd = [
        settings.ocr_venv_python_path(),
        os.path.join(os.path.dirname(__file__), "ocr_worker.py"),
        "--video", video_path,
        "--times", json.dumps(times),
    ]
    env = os.environ.copy()
    env["PADDLE_PDX_CACHE_HOME"] = settings.ocr_model_dir_path()
    env["OCR_DEVICE"] = settings.ocr_device
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=env,
                          timeout=max(300, int(duration * 2 + 120)))
    detections = []
    errors = []
    for line in (proc.stdout or "").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("error"):
            errors.append(item["error"])
        elif item.get("box"):
            detections.append(item)
    if proc.returncode != 0 and not detections:
        raise RuntimeError(errors[-1] if errors else
                           (proc.stderr or "PaddleOCR worker failed")[-500:])
    return detections

def detect_regions(
    video_path: str,
    video_w: int,
    video_h: int,
    duration: float,
    settings,
) -> list[dict]:
    return detect_regions_with_logo(
        video_path, video_w, video_h, duration, settings
    )[0]

def detect_regions_with_logo(
    video_path: str,
    video_w: int,
    video_h: int,
    duration: float,
    settings,
) -> tuple[list[dict], list[dict]]:
    """Run PaddleOCR once and return subtitle plus stable-logo regions."""
    detections = _run_detections(video_path, duration, settings)
    subtitle_regions = detections_to_regions(
        detections, video_w, video_h,
        min_confidence=settings.ocr_min_confidence,
        max_area=settings.ocr_max_region_area,
        subtitle_y_min=getattr(settings, "ocr_subtitle_y_min", 0.65),
        sample_interval=settings.ocr_sample_interval,
    )
    subtitle_regions = merge_regions(
        subtitle_regions, max_gap=settings.ocr_sample_interval * 1.25)
    logo_regions = detections_to_logo_regions(
        detections, video_w, video_h,
        min_confidence=settings.ocr_min_confidence,
        subtitle_y_min=getattr(settings, "ocr_subtitle_y_min", 0.65),
    )
    return subtitle_regions, logo_regions

def detect_logo_regions(
    video_path: str,
    video_w: int,
    video_h: int,
    duration: float,
    settings,
) -> list[dict]:
    """Detect stable non-subtitle CJK text that may be a source logo."""
    return detect_regions_with_logo(
        video_path, video_w, video_h, duration, settings
    )[1]
