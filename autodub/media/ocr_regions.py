"""Safe OCR detections for hardcoded subtitle blur regions.

The OCR engine is deliberately kept out of this module. This file only turns
engine output into the normalized blur format already consumed by ffmpeg.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_CACHE_VERSION = 2


def _box_bounds(box) -> tuple[float, float, float, float] | None:
    try:
        points = [(float(p[0]), float(p[1])) for p in box]
        if len(points) < 4:
            return None
    except (TypeError, ValueError, IndexError):
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x, y = min(xs), min(ys)
    return x, y, max(xs) - x, max(ys) - y


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def detections_to_regions(
    detections: list[dict],
    video_w: int,
    video_h: int,
    *,
    min_confidence: float = 0.8,
    max_area: float = 0.25,
    subtitle_y_min: float = 0.65,
    min_width_px: int = 24,
    min_height_px: int = 8,
    sample_interval: float = 1.0,
) -> list[dict]:
    """Filter OCR results and convert pixel boxes to timed normalized regions."""
    if video_w <= 0 or video_h <= 0:
        return []
    out = []
    frame_area = float(video_w * video_h)
    for detection in detections:
        text = str(detection.get("text") or "").strip()
        confidence = float(detection.get("confidence", 0.0) or 0.0)
        bounds = _box_bounds(detection.get("box"))
        if confidence < min_confidence or not _has_cjk(text) or bounds is None:
            continue
        x, y, w, h = bounds
        if (y + h) / video_h < max(0.0, min(1.0, subtitle_y_min)):
            continue
        if w < min_width_px or h < min_height_px:
            continue
        if (w * h) / frame_area > max_area:
            continue
        x = max(0.0, min(x, video_w - 1))
        y = max(0.0, min(y, video_h - 1))
        w = max(1.0, min(w, video_w - x))
        h = max(1.0, min(h, video_h - y))
        t_start = max(0.0, float(detection.get("time", 0.0) or 0.0))
        t_end = float(detection.get("t_end", t_start + sample_interval) or
                      (t_start + sample_interval))
        out.append({
            "x": round(x / video_w, 6),
            "y": round(y / video_h, 6),
            "w": round(w / video_w, 6),
            "h": round(h / video_h, 6),
            "t_start": round(t_start, 3),
            "t_end": round(max(t_start, t_end), 3),
            "source": "ocr",
            "text": text,
            "confidence": round(confidence, 4),
        })
    return out


def _iou(a: dict, b: dict) -> float:
    ax1, ay1 = float(a["x"]), float(a["y"])
    ax2, ay2 = ax1 + float(a["w"]), ay1 + float(a["h"])
    bx1, by1 = float(b["x"]), float(b["y"])
    bx2, by2 = bx1 + float(b["w"]), by1 + float(b["h"])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = float(a["w"]) * float(a["h"]) + float(b["w"]) * float(b["h"]) - inter
    return inter / union if union > 0 else 0.0


def merge_regions(regions: list[dict], *, max_gap: float = 1.5) -> list[dict]:
    """Merge adjacent samples tracking the same subtitle box."""
    merged: list[dict] = []
    for region in sorted(regions, key=lambda r: (float(r["t_start"]), float(r["x"]))):
        match = None
        for candidate in reversed(merged):
            gap = float(region["t_start"]) - float(candidate["t_end"])
            if gap > max_gap:
                break
            if _iou(candidate, region) >= 0.45:
                match = candidate
                break
        if match is None:
            merged.append(dict(region))
            continue
        match["t_end"] = round(max(float(match["t_end"]), float(region["t_end"])), 3)
        match["confidence"] = round(
            max(float(match.get("confidence", 0)), float(region.get("confidence", 0))), 4
        )
        if len(str(region.get("text", ""))) > len(str(match.get("text", ""))):
            match["text"] = region["text"]
    return merged


def save_regions(path: str, regions: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _CACHE_VERSION, "regions": regions}
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)


def load_regions(path: str) -> list[dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("version") != _CACHE_VERSION:
        return []
    regions = payload.get("regions")
    return regions if isinstance(regions, list) else []
