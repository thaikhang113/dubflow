#!/usr/bin/env python3
"""Compile ordered media manifests. All generated files stay under --output-dir."""
import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LIMIT = 5400


def probe_media(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=index,codec_type,width,height,avg_frame_rate", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"invalid duration: {path}")
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    if not video or int(video.get("width", 0)) <= 0 or int(video.get("height", 0)) <= 0:
        raise ValueError(f"missing video stream: {path}")
    fps = video.get("avg_frame_rate", "0/0")
    if fps in ("0/0", "0", None):
        raise ValueError(f"invalid frame rate: {path}")
    return {"duration": duration, "width": int(video["width"]), "height": int(video["height"]), "fps": fps, "has_audio": any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))}


def duration(path):
    return probe_media(path)["duration"]


def validate_max_seconds(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= LIMIT:
        raise ValueError(f"max_seconds must be an integer from 1 to {LIMIT}")
    return value


def validate_part(part, max_seconds=LIMIT):
    max_seconds = validate_max_seconds(max_seconds)
    if not isinstance(part, dict):
        raise ValueError("part must be an object")
    episodes = part.get("episodes", [])
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("part must contain at least one episode")
    try:
        numbers = [int(episode["episode_number"]) for episode in episodes]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("episodes require integer episode_number") from exc
    if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
        raise ValueError("episodes must be ordered and unique")
    intro, outro = part.get("intro"), part.get("outro")
    episode_paths = [episode.get("path") for episode in episodes]
    optional_paths = [path for path in (intro, outro) if path]
    paths = optional_paths + episode_paths
    if any(not path or not Path(path).is_file() for path in paths):
        raise ValueError("missing intro, episode, or outro file")
    if any(Path(episode["path"]).name != "final_video_vi.mp4" for episode in episodes):
        raise ValueError("episode must be final_video_vi.mp4")
    episode_metadata = [probe_media(path) for path in episode_paths]
    if any(not media["has_audio"] for media in episode_metadata):
        raise ValueError("episode must have an audio stream")
    intro_metadata = probe_media(intro) if intro else None
    outro_metadata = probe_media(outro) if outro else None
    warning = None
    if len(episodes) == 1 and episode_metadata[0]["duration"] > max_seconds:
        # An oversized source episode is still useful on its own, but must not be
        # combined with branding clips or another episode.
        inputs = episode_paths
        intro_included = outro_included = False
        warning = f"episode {numbers[0]} exceeds {max_seconds} seconds and was emitted alone"
    else:
        inputs = ([intro] if intro else []) + episode_paths + ([outro] if outro else [])
        intro_included, outro_included = bool(intro), bool(outro)
    total = sum(probe_media(path)["duration"] for path in inputs)
    if total > max_seconds and not warning:
        raise ValueError(f"part exceeds {max_seconds} seconds")
    return {
        "inputs": inputs,
        "duration_seconds": total,
        "episode_numbers": numbers,
        "intro_included": intro_included,
        "outro_included": outro_included,
        "warning": warning,
    }


def normalize_input(source, destination, profile):
    """Make a concat-safe file with the first episode's video profile and fixed audio."""
    metadata = probe_media(source)
    video_filter = (
        f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=decrease,"
        f"pad={profile['width']}:{profile['height']}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={profile['fps']}"
    )
    cmd = ["ffmpeg", "-y", "-i", str(source)]
    if metadata["has_audio"]:
        cmd += ["-map", "0:v:0", "-vf", video_filter, "-map", "0:a:0", "-af", "aresample=48000"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-vf", video_filter, "-map", "1:a:0", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(profile["fps"]), "-c:a", "aac", "-ac", "2", "-ar", "48000", str(destination)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def compile_part(part, target, output_dir, max_seconds, plan):
    inputs = plan["inputs"]
    profile = probe_media(part["episodes"][0]["path"])
    temp_dir = Path(tempfile.mkdtemp(prefix=".compile-normalized-", dir=str(output_dir)))
    try:
        normalized = []
        for index, source in enumerate(inputs):
            normalized_path = temp_dir / f"{index:03d}.mp4"
            normalize_input(source, normalized_path, profile)
            normalized.append(normalized_path)
        concat_list = temp_dir / "inputs.txt"
        concat_list.write_text("".join("file '" + str(path.resolve()).replace("'", "'\\''") + "'\n" for path in normalized), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(target)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        produced = duration(target)
        if produced > max_seconds and not plan["warning"]:
            raise ValueError(f"compiled part exceeds {max_seconds} seconds")
        return produced
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        with open(args.manifest, encoding="utf-8") as handle:
            data = json.load(handle)
        parts = data.get("parts", [])
        if not isinstance(parts, list) or not parts:
            raise ValueError("manifest must contain parts")
        max_seconds = validate_max_seconds(data.get("max_seconds", LIMIT))
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        result = {"limit_seconds": max_seconds, "parts": []}
        for index, part in enumerate(parts, 1):
            plan = validate_part(part, max_seconds)
            target = out / f"part-{index}.mp4"
            entry = {"part": index, "episode_numbers": plan["episode_numbers"], "duration_seconds": plan["duration_seconds"], "intro_included": plan["intro_included"], "outro_included": plan["outro_included"], "warning": plan["warning"], "output": str(target)}
            if args.execute:
                entry["duration_seconds"] = compile_part(part, target, out, max_seconds, plan)
            result["parts"].append(entry)
        (out / "compilation_manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
