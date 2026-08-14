"""Optional DeepSeek-OCR subprocess worker.

Runs outside the main application environment and emits one JSON detection per
line. Model output is treated as untrusted text and only grounded boxes are
accepted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_GROUNDING_RE = re.compile(
    r"<\|ref\|>(.*?)<\|/ref\|>\s*"
    r"<\|det\|>\s*(.*?)\s*<\|/det\|>",
    re.DOTALL,
)
_BOX_RE = re.compile(
    r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*"
    r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]"
)


def _frames(video: str, times: list[float], output_dir: str) -> list[str]:
    if not times:
        return []
    interval = max(0.1, times[1] - times[0] if len(times) > 1 else 1.0)
    pattern = os.path.join(output_dir, "%05d.png")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", video,
         "-vf", f"fps=1/{interval:.3f}",
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


def parse_grounding(text: str, width: int, height: int,
                    timestamp: float) -> list[dict]:
    """Convert DeepSeek grounding tokens to the shared OCR detection schema."""
    output = []
    for match in _GROUNDING_RE.finditer(str(text or "")):
        label = re.sub(r"\s+", " ", match.group(1)).strip()
        if not label:
            continue
        for raw_box in _BOX_RE.findall(match.group(2)):
            values = [float(value) for value in raw_box]
            scale = 1000.0 if max(abs(value) for value in values) <= 1000 else 1.0
            x1, y1, x2, y2 = [
                max(0.0, min(1.0, value / scale))
                for value in values
            ]
            if x2 <= x1 or y2 <= y1:
                continue
            output.append({
                "text": label,
                "confidence": 0.85,
                "box": [
                    [x1 * width, y1 * height],
                    [x2 * width, y1 * height],
                    [x2 * width, y2 * height],
                    [x1 * width, y2 * height],
                ],
                "time": timestamp,
            })
    return output


def _load_model(model_dir: str):
    import torch
    from transformers import AutoModel, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("DeepSeek-OCR cần NVIDIA GPU/CUDA; dùng PaddleOCR CPU.")
    model_name = "deepseek-ai/DeepSeek-OCR"
    tokenizer = AutoTokenizer.from_pretrained(
        model_name, cache_dir=model_dir, trust_remote_code=True)
    try:
        model = AutoModel.from_pretrained(
            model_name,
            cache_dir=model_dir,
            trust_remote_code=True,
            use_safetensors=True,
            _attn_implementation="flash_attention_2",
        )
    except Exception:
        model = AutoModel.from_pretrained(
            model_name,
            cache_dir=model_dir,
            trust_remote_code=True,
            use_safetensors=True,
            _attn_implementation="eager",
        )
    return tokenizer, model.eval().cuda().to(torch.bfloat16)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--times", required=True)
    args = parser.parse_args()
    try:
        model_dir = os.environ["DEEPSEEK_OCR_MODEL_DIR"]
        tokenizer, model = _load_model(model_dir)
        times = [float(value) for value in json.loads(args.times)]
        with tempfile.TemporaryDirectory(prefix="dubflow-deepseek-ocr-") as tmp:
            images = _frames(args.video, times, tmp)
            for index, image in enumerate(images):
                result = model.infer(
                    tokenizer,
                    prompt="<image>\n<|grounding|>OCR this image.",
                    image_file=image,
                    output_path=tmp,
                    base_size=1024,
                    image_size=640,
                    crop_mode=True,
                    save_results=False,
                )
                from PIL import Image
                with Image.open(image) as frame:
                    width, height = frame.size
                for item in parse_grounding(
                    str(result), width, height, times[index]
                ):
                    print(json.dumps(item, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:  # worker boundary
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
