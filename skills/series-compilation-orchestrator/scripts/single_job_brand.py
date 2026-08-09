#!/usr/bin/env python3
"""Fail-closed branding for one completed Bilibili localization job.

This runs before any organize/upload hand-off.  It intentionally knows only the
approved, fixed Bilibili top-left profile and the approved brand assets.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets" / "brand-assets.json"
BRAND_VIDEO = HERE / "brand_video.py"
COMPILE_VIDEOS = HERE / "compile_videos.py"


def parse_bool(value, name):
    if isinstance(value, bool):
        return value
    if str(value).strip() in {"0", "false", "False"}:
        return False
    if str(value).strip() in {"1", "true", "True"}:
        return True
    raise ValueError(f"{name} must be 0 or 1")


def probe_media(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise ValueError("input must contain video and audio streams")
    width, height, duration = int(video["width"]), int(video["height"]), float(data["format"]["duration"])
    if width <= 0 or height <= 0 or duration <= 0:
        raise ValueError("input has invalid dimensions or duration")
    return {"width": width, "height": height, "duration": duration, "has_audio": True}


def decode_media(path):
    """Fail if either required stream cannot be decoded end-to-end."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def bilibili_top_left_region(width, height, duration):
    """Return the approved full uploader-text plus bilibili-mark block."""
    x, y = round(width * 0.015), round(height * 0.025)
    region_width, region_height = round(width * 0.18), round(height * 0.075)
    return {
        "label": "bilibili_top_left_block", "x": x, "y": y,
        "width": region_width, "height": region_height,
        "start": 0.0, "end": float(duration), "confidence": 0.99,
        "blur": True, "replacement": True, "conceal": True,
    }


def plan(video, logo, intro, outro, include_intro, include_outro):
    media = probe_media(video)
    for name, value in (("logo", logo), ("intro", intro), ("outro", outro)):
        required = name == "logo" or (name == "intro" and include_intro) or (name == "outro" and include_outro)
        if required and (value is None or not Path(value).is_file()):
            raise ValueError(f"missing approved {name} asset")
    inputs = ([str(intro)] if include_intro else []) + [str(video)] + ([str(outro)] if include_outro else [])
    return {
        "profile": "bilibili_top_left_block", "regions": [bilibili_top_left_region(media["width"], media["height"], media["duration"])],
        "inputs": inputs, "intro_included": include_intro, "outro_included": include_outro,
    }


def execute(video, output, logo, intro, outro, include_intro, include_outro):
    video, output = Path(video), Path(output)
    if not video.is_file():
        raise ValueError("input final_video_vi.mp4 is missing")
    plan_data = plan(video, logo, intro, outro, include_intro, include_outro)
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".single-job-brand-", dir=output.parent))
    try:
        regions = work / "regions.json"
        regions.write_text(json.dumps(plan_data["regions"], indent=2) + "\n", encoding="utf-8")
        brand_dir = work / "brand"
        subprocess.run([sys.executable, str(BRAND_VIDEO), "--input", str(video), "--regions", str(regions), "--logo", str(logo), "--output-dir", str(brand_dir), "--execute"], check=True, capture_output=True, text=True)
        branded = brand_dir / "branded.mp4"
        if not branded.is_file() or branded.stat().st_size == 0:
            raise ValueError("branding did not produce a video")
        candidate = branded
        if include_intro or include_outro:
            branded_episode = work / "final_video_vi.mp4"
            os.link(branded, branded_episode)
            manifest = work / "manifest.json"
            manifest.write_text(json.dumps({"max_seconds": 5400, "parts": [{
                "intro": str(intro) if include_intro else None,
                "episodes": [{"episode_number": 1, "path": str(branded_episode)}],
                "outro": str(outro) if include_outro else None,
            }]}), encoding="utf-8")
            compiled = work / "compiled"
            subprocess.run([sys.executable, str(COMPILE_VIDEOS), "--manifest", str(manifest), "--output-dir", str(compiled), "--execute"], check=True, capture_output=True, text=True)
            candidate = compiled / "part-1.mp4"
        verified = probe_media(candidate)
        if not verified["has_audio"]:
            raise ValueError("branded output lost its audio stream")
        decode_media(candidate)
        staged = work / "replacement-final_video_vi.mp4"
        shutil.copy2(candidate, staged)
        os.replace(staged, output)
        proof = {**plan_data, "input": str(video), "output": str(output), "status": "executed"}
        (output.parent / "bilibili_branding_proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return proof
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--assets", default=str(ASSETS))
    parser.add_argument("--logo")
    parser.add_argument("--include-intro", default="0")
    parser.add_argument("--include-outro", default="0")
    args = parser.parse_args(argv)
    try:
        assets = json.loads(Path(args.assets).read_text(encoding="utf-8"))
        root = Path(args.assets).resolve().parents[3]
        resolve = lambda value: Path(value) if Path(value).is_absolute() else root / value
        logo = Path(args.logo) if args.logo else resolve(assets["logo"])
        result = execute(args.input, args.output, logo, resolve(assets["approved_intro_mp4"]), resolve(assets["approved_outro_mp4"]), parse_bool(args.include_intro, "include_intro"), parse_bool(args.include_outro, "include_outro"))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
