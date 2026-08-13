"""Optional local Ollama vision helper."""
from __future__ import annotations

import base64
import json
import subprocess
from urllib.request import Request, urlopen


def _region(value):
    if not isinstance(value, dict):
        return None
    try:
        x, y = float(value["x"]), float(value["y"])
        w, h = float(value["w"]), float(value["h"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
        return None
    if x + w > 1 or y + h > 1:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def detect_logo_region(
    image_bytes: bytes,
    model: str,
    *,
    endpoint: str = "http://127.0.0.1:11434/api/generate",
    timeout: float = 8.0,
) -> dict | None:
    prompt = (
        "Find persistent source watermark/logo. Return JSON only with "
        "normalized x,y,w,h in 0..1, or null. Do not identify subtitles."
    )
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "stream": False,
    }).encode()
    try:
        response = urlopen(
            Request(endpoint, data=body, headers={"Content-Type": "application/json"}),
            timeout=timeout,
        )
        with response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = payload.get("response")
        if not isinstance(raw, str):
            return None
        return _region(json.loads(raw))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def detect_logo_region_video(
    video_path: str,
    model: str,
    *,
    duration: float | None = None,
    samples: int = 3,
) -> dict | None:
    if not model or not video_path:
        return None
    times = [0.2, 1.0, 2.0][:max(1, samples)]
    if duration is not None:
        times = [value for value in times if value < max(0.3, duration)]
    regions = []
    for time_s in times:
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-ss", f"{time_s:.3f}",
                    "-i", video_path, "-frames:v", "1", "-f", "image2pipe",
                    "-vcodec", "mjpeg", "pipe:1",
                ],
                capture_output=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                region = detect_logo_region(result.stdout, model)
                if region:
                    regions.append(region)
        except (OSError, subprocess.SubprocessError):
            pass
    if not regions:
        return None
    stable = [
        region for region in regions
        if sum(_iou(region, other) >= 0.45 for other in regions) >= 2
    ]
    if not stable:
        return None
    return {
        key: round(sum(region[key] for region in stable) / len(stable), 6)
        for key in ("x", "y", "w", "h")
    }


def _iou(a: dict, b: dict) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    inter = max(0.0, min(ax2, bx2) - max(a["x"], b["x"])) * max(
        0.0, min(ay2, by2) - max(a["y"], b["y"])
    )
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union else 0.0
