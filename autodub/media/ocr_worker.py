"""Optional PaddleOCR subprocess worker.

The main app invokes this file with the OCR virtualenv Python so PaddleOCR
never becomes a hard import dependency of the GUI/runtime.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# PaddlePaddle 3.x + oneDNN can fail on Windows while converting OCR
# attributes. CPU OCR remains correct with oneDNN disabled.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")

def choose_ocr_device(requested: str, cuda_ready: bool) -> str:
    requested = (requested or "auto").strip().lower()
    if requested == "cpu":
        return "cpu"
    if requested in ("gpu", "cuda") and cuda_ready:
        return "gpu:0"
    if requested == "auto" and cuda_ready:
        return "gpu:0"
    return "cpu"

def _ocr_engine():
    import paddle
    from paddleocr import PaddleOCR

    requested = os.environ.get("OCR_DEVICE", "auto")
    cuda_ready = bool(getattr(paddle, "is_compiled_with_cuda", lambda: False)())
    device = choose_ocr_device(requested, cuda_ready)
    common = {
        "lang": "ch",
        "enable_mkldnn": device == "cpu",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    candidates = [device, "gpu", "cpu"] if device != "cpu" else ["cpu"]
    for candidate in candidates:
        try:
            try:
                return PaddleOCR(device=candidate, **common)
            except TypeError:
                if candidate != "cpu":
                    return PaddleOCR(use_gpu=True, **common)
                return PaddleOCR(use_angle_cls=False, **common)
        except Exception as exc:
            if candidate == "cpu":
                raise
            print(f"[ocr] GPU unavailable ({exc}); falling back to CPU",
                  file=sys.stderr, flush=True)
    raise RuntimeError("OCR device initialization failed")


def _value(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _parse_result(result) -> list[dict]:
    """Accept PaddleOCR 2.x and 3.x result shapes."""
    output = []
    items = result if isinstance(result, (list, tuple)) else [result]
    for item in items:
        texts = _value(item, "rec_texts")
        scores = _value(item, "rec_scores")
        boxes = _value(item, "dt_polys")
        if texts is not None and boxes is not None:
            for text, score, box in zip(texts, scores or [], boxes):
                output.append({
                    "text": str(text),
                    "confidence": float(score),
                    "box": box.tolist() if hasattr(box, "tolist") else box,
                })
            continue
        rows = item if isinstance(item, list) else []
        for row in rows:
            if len(row) < 2:
                continue
            box, payload = row[0], row[1]
            if isinstance(payload, (list, tuple)):
                text = payload[0] if payload else ""
                score = payload[1] if len(payload) > 1 else 0.0
            else:
                text, score = str(payload), 0.0
            output.append({"text": str(text), "confidence": float(score), "box": box})
    return output


def _frames(video: str, times: list[float], output_dir: str) -> list[str]:
    """Extract all sampled frames with one FFmpeg process."""
    if not times:
        return []
    interval = max(0.1, times[1] - times[0] if len(times) > 1 else 1.0)
    pattern = os.path.join(output_dir, "%05d.png")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", video,
         "-vf", f"fps=1/{interval:.3f}", "-vsync", "vfr",
         "-frames:v", str(len(times)), "-y", pattern],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-500:] or "OCR frame extraction failed")
    return [
        os.path.join(output_dir, f"{index:05d}.png")
        for index in range(1, len(times) + 1)
        if os.path.isfile(os.path.join(output_dir, f"{index:05d}.png"))
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--times", required=True,
                        help="JSON array of sample timestamps")
    args = parser.parse_args()
    try:
        engine = _ocr_engine()
        times = [float(t) for t in json.loads(args.times)]
        with tempfile.TemporaryDirectory(prefix="autodub-ocr-") as tmp:
            images = _frames(args.video, times, tmp)
            for index, image in enumerate(images):
                at = times[index]
                if hasattr(engine, "predict"):
                    result = engine.predict(image)
                else:
                    result = engine.ocr(image, cls=False)
                for detection in _parse_result(result):
                    detection["time"] = at
                    print(json.dumps(detection, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:  # worker boundary: report structured failure
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
