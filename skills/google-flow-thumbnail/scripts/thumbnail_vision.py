#!/usr/bin/env python3
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

from PIL import Image, ImageStat

CONFIG = {
    "enabled": os.environ.get("THUMBNAIL_VISION_ENABLED", "1") != "0",
    "device": os.environ.get("THUMBNAIL_VISION_DEVICE", "auto"),
    "prefer_gpu": os.environ.get("THUMBNAIL_VISION_PREFER_GPU", "1") != "0",
    "gpu_backend": os.environ.get("THUMBNAIL_VISION_GPU_BACKEND", "vulkan"),
    "timeout_seconds": int(float(os.environ.get("THUMBNAIL_VISION_TIMEOUT_SECONDS", "90"))),
    "image_max_size": int(float(os.environ.get("THUMBNAIL_VISION_IMAGE_MAX_SIZE", "768"))),
    "fail_open": os.environ.get("THUMBNAIL_VISION_FAIL_OPEN", "1") != "0",
    "model_dir": os.environ.get("THUMBNAIL_VISION_MODEL_DIR", "/home/haonguyen/.local/share/openclaw-vision-models"),
    "ollama_model": os.environ.get("THUMBNAIL_VISION_OLLAMA_MODEL", "moondream"),
    "ollama_url": os.environ.get("THUMBNAIL_VISION_OLLAMA_URL", "http://127.0.0.1:11434"),
    "llama_cli": os.environ.get("THUMBNAIL_VISION_LLAMA_CLI", "llama-cli"),
    "llama_model": os.environ.get("THUMBNAIL_VISION_LLAMA_MODEL", ""),
    "llama_mmproj": os.environ.get("THUMBNAIL_VISION_LLAMA_MMPROJ", ""),
}

PROMPT = """Describe the image layout for making a similar YouTube thumbnail.
Mention only visible objects, characters, positions (left, center, right, top, bottom), background, colors, and empty areas suitable for title text.
Keep it short and practical."""


def log(msg):
    print(f"thumbnail_vision: {msg}", flush=True)


def resize_image(src: Path, dst: Path) -> None:
    img = Image.open(src).convert("RGB")
    img.thumbnail((CONFIG["image_max_size"], CONFIG["image_max_size"]))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=90)


def heuristic_analysis(image_path: Path, reason: str, runtime_errors=None) -> dict:
    img = Image.open(image_path).convert("RGB").resize((320, 180))
    w, h = img.size
    regions = {
        "top": (0, 0, w, int(h * 0.22)),
        "center": (int(w * 0.25), int(h * 0.18), int(w * 0.75), int(h * 0.82)),
        "bottom": (0, int(h * 0.74), w, h),
        "left": (0, 0, int(w * 0.42), h),
        "right": (int(w * 0.58), 0, w, h),
    }
    scores = {}
    for name, box in regions.items():
        crop = img.crop(box).convert("L")
        stat = ImageStat.Stat(crop)
        scores[name] = {"brightness": stat.mean[0], "contrast": stat.stddev[0], "saliency": stat.stddev[0] + abs(stat.mean[0] - 110) * 0.2}
    busy = sorted(scores, key=lambda k: scores[k]["saliency"], reverse=True)
    quiet = sorted(scores, key=lambda k: scores[k]["saliency"])
    return {
        "status": "heuristic_fallback",
        "reason": reason,
        "device": "none",
        "backend": "pillow_heuristic",
        "config": CONFIG,
        "runtime_errors": runtime_errors or [],
        "main_subjects": ["unknown character/scene from reference image"],
        "character_count": "unknown",
        "subject_positions": busy[:2],
        "face_or_head_regions": [busy[0]],
        "background": "derived from reference image; exact semantic vision unavailable",
        "mood": "dramatic YouTube thumbnail style",
        "colors": "keep high contrast and saturated colors from reference",
        "composition": f"busy/salient regions likely: {', '.join(busy[:3])}; quieter text regions: {', '.join(quiet[:3])}",
        "avoid_text_regions": busy[:2],
        "recommended_text_regions": quiet[:3],
        "prompt_hint": f"Use the reference image composition. Keep main subjects away from text. Avoid placing title over {', '.join(busy[:2])}; prefer {', '.join(quiet[:2])} for text.",
        "region_scores": scores,
    }


def try_ollama(image_path: Path) -> tuple[dict | None, str | None]:
    try:
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = json.dumps({
            "model": CONFIG["ollama_model"],
            "prompt": PROMPT,
            "images": [data],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 512},
        }).encode("utf-8")
        req = urllib.request.Request(
            CONFIG["ollama_url"].rstrip("/") + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=CONFIG["timeout_seconds"]) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        text = str(result.get("response") or "").strip()
        if not text:
            return None, "ollama_empty_response"
        avoid = []
        lower = text.lower()
        for region in ("top", "bottom", "left", "right", "center"):
            if region in lower and any(word in lower for word in ("face", "head", "character", "subject", "person")):
                avoid.append(region)
        prompt_hint = text
        for line in text.splitlines():
            if line.lower().startswith("prompt hint"):
                prompt_hint = line.split(":", 1)[-1].strip() or text
                break
        return {"status": "ok", "backend": "ollama", "device": CONFIG["device"], "model": CONFIG["ollama_model"], "raw_text": text, "prompt_hint": prompt_hint, "avoid_text_regions": avoid[:3]}, None
    except TimeoutError:
        return None, "ollama_timeout"
    except urllib.error.URLError as exc:
        return None, f"ollama_url_error: {exc}"
    except Exception as exc:
        return None, f"ollama_error: {exc}"


def try_llama_cpp(image_path: Path) -> tuple[dict | None, str | None]:
    llama = shutil.which(CONFIG["llama_cli"]) or (CONFIG["llama_cli"] if Path(CONFIG["llama_cli"]).exists() else "")
    if not llama:
        return None, "llama_cli_not_found"
    if not CONFIG["llama_model"] or not Path(CONFIG["llama_model"]).exists():
        return None, "llama_model_missing"
    if not CONFIG["llama_mmproj"] or not Path(CONFIG["llama_mmproj"]).exists():
        return None, "llama_mmproj_missing"
    cmd = [llama, "-m", CONFIG["llama_model"], "--mmproj", CONFIG["llama_mmproj"], "--image", str(image_path), "-p", PROMPT, "-n", "512"]
    if CONFIG["prefer_gpu"] and CONFIG["device"] != "cpu":
        cmd.extend(["-ngl", "99"])
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=CONFIG["timeout_seconds"])
        if proc.returncode != 0:
            return None, f"llama_cpp_failed: {proc.stderr[-500:]}"
        return {"status": "ok", "backend": "llama.cpp", "device": "gpu_or_cpu_auto", "raw_text": proc.stdout.strip()}, None
    except subprocess.TimeoutExpired:
        return None, "llama_cpp_timeout"
    except Exception as exc:
        return None, f"llama_cpp_error: {exc}"


def analyze(image_path: Path, analysis_path: Path, prompt_path: Path) -> dict:
    started = time.time()
    if not CONFIG["enabled"]:
        result = heuristic_analysis(image_path, "vision_disabled")
    else:
        work_img = analysis_path.with_suffix(".resized.jpg")
        resize_image(image_path, work_img)
        errors = []
        result = None
        if CONFIG["device"] in ("auto", "gpu", "cpu"):
            for fn in (try_llama_cpp, try_ollama):
                candidate, err = fn(work_img)
                if candidate:
                    result = candidate
                    result.update({"config": CONFIG, "image": str(image_path), "resized_image": str(work_img)})
                    break
                errors.append(err)
        if result is None:
            result = heuristic_analysis(work_img, "no_local_vision_runtime_or_model", errors)
            result["image"] = str(image_path)
            result["resized_image"] = str(work_img)
    result["elapsed_seconds"] = round(time.time() - started, 3)
    prompt_hint = result.get("prompt_hint") or result.get("raw_text") or "Use reference image composition and avoid covering faces with text."
    prompt_path.write_text(prompt_hint.strip() + "\n", encoding="utf-8")
    analysis_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("analysis_json")
    parser.add_argument("prompt_txt")
    args = parser.parse_args()
    result = analyze(Path(args.image), Path(args.analysis_json), Path(args.prompt_txt))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
