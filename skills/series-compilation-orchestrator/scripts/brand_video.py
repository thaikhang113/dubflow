#!/usr/bin/env python3
"""Plan, validate, and execute explicit branding regions; stdout is JSON only."""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

REQUIRED = {"x", "y", "width", "height", "start", "end", "confidence"}


def normalize_regions(regions):
    """Convert documented aliases to the sole schema consumed by ffmpeg."""
    if not isinstance(regions, list) or not regions:
        raise ValueError("regions must be a non-empty list")
    normalized = []
    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            raise ValueError(f"region {index} must be an object")
        item = dict(region)
        for internal, alias in (("start", "start_seconds"), ("end", "end_seconds")):
            if internal in item and alias in item and item[internal] != item[alias]:
                raise ValueError(f"region {index} has conflicting {internal} and {alias}")
            if internal not in item and alias in item:
                item[internal] = item[alias]
            item.pop(alias, None)
        if not item.get("label"):
            item["label"] = "replacement" if item.get("replacement") is True else "blur"
        normalized.append(item)
    return normalized


def _number(value, field, index):
    if isinstance(value, bool):
        raise ValueError(f"region {index} {field} must be numeric")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"region {index} {field} must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"region {index} {field} must be finite")
    return value


def validate_regions(regions, allow_low_confidence=False, media_width=None, media_height=None, media_duration=None):
    """Validate regions fail-closed, optionally against probed input media bounds."""
    regions = normalize_regions(regions)
    out = []
    for i, region in enumerate(regions):
        if not isinstance(region, dict) or not REQUIRED.issubset(region):
            raise ValueError(f"region {i} missing required fields")
        if not isinstance(region["label"], str) or not region["label"].strip():
            raise ValueError(f"region {i} label must be a non-empty string")
        values = {key: _number(region[key], key, i) for key in REQUIRED - {"label"}}
        geometry = ("x", "y", "width", "height")
        if any(not values[key].is_integer() for key in geometry):
            raise ValueError(f"region {i} geometry must use whole pixels")
        # A 4px minimum keeps chroma-subsampled blur crops valid on yuv420p input.
        if values["x"] < 0 or values["y"] < 0 or values["width"] < 4 or values["height"] < 4:
            raise ValueError(f"region {i} has invalid geometry")
        if values["start"] < 0 or values["end"] <= values["start"]:
            raise ValueError(f"region {i} has invalid time bounds")
        if not 0 <= values["confidence"] <= 1:
            raise ValueError(f"region {i} confidence must be 0..1")
        if values["confidence"] < 0.8 and not allow_low_confidence:
            raise ValueError(f"region {i} is low-confidence; pass --allow-low-confidence")
        if region.get("blur") is not True and region.get("replacement") is not True:
            raise ValueError(f"region {i} must request blur or replacement")
        if media_width is not None and values["x"] + values["width"] > media_width:
            raise ValueError(f"region {i} exceeds input width")
        if media_height is not None and values["y"] + values["height"] > media_height:
            raise ValueError(f"region {i} exceeds input height")
        if media_duration is not None and values["end"] > media_duration:
            raise ValueError(f"region {i} exceeds input duration")
        normalized = dict(region)
        for key in geometry:
            normalized[key] = int(values[key])
        for key in ("start", "end", "confidence"):
            normalized[key] = values[key]
        out.append(normalized)
    return out


def circular_overlay_filter(regions, logo="1:v", video="0:v", start_index=0):
    """Chain circular logo replacements from *video*, preserving earlier changes."""
    parts, current, n = [], video, start_index
    for region in regions:
        if not region.get("replacement"):
            continue
        x, y, width, height = (region[key] for key in ("x", "y", "width", "height"))
        start, end = region["start"], region["end"]
        if region.get("conceal"):
            # Concealment must cover every source pixel before the logo is added.
            parts.append(
                f"color=c=0x0B1F3A@1:s={width}x{height},format=rgba[cover{n}];"
                f"[{current}][cover{n}]overlay={x}:{y}:"
                f"eof_action=pass:shortest=0:enable='between(t,{start},{end})'[v{n}]"
            )
            current, n = f"v{n}", n + 1
            size = min(width, height)
            logo_filter = (
                f"[{logo}]scale={size}:{size}:force_original_aspect_ratio=decrease,"
                f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=black@0,format=rgba,"
            )
            logo_x, logo_y = x + (width - size) / 2, y + (height - size) / 2
        else:
            logo_filter = f"[{logo}]scale={width}:{height},format=rgba,"
            logo_x, logo_y = x, y
        # geq retains RGB and makes pixels outside the circle fully transparent.
        parts.append(
            logo_filter +
            "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            "a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow(min(W,H)/2,2)),255,0)'"
            f"[stamp{n}];[{current}][stamp{n}]overlay={logo_x:g}:{logo_y:g}:"
            f"eof_action=pass:shortest=0:enable='between(t,{start},{end})'[v{n}]"
        )
        current = f"v{n}"
        n += 1
    return ";".join(parts), current, n


def build_filter(regions, logo="1:v"):
    """Build one ordered chain so every region starts from the previous label."""
    current, parts, n = "0:v", [], 0
    for region in regions:
        x, y, width, height = (region[key] for key in ("x", "y", "width", "height"))
        start, end = region["start"], region["end"]
        if region.get("blur"):
            parts.append(
                f"[{current}]split=2[base{n}][crop{n}];[crop{n}]crop={width}:{height}:{x}:{y},"
                f"boxblur=1[blur{n}];[base{n}][blur{n}]overlay={x}:{y}:"
                f"enable='between(t,{start},{end})'[v{n}]"
            )
            current, n = f"v{n}", n + 1
        if region.get("replacement"):
            replacement, current, n = circular_overlay_filter([region], logo, current, n)
            if replacement:
                parts.append(replacement)
    return ";".join(parts) or "[0:v]null[v0]", current


def probe_input(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    stream = data.get("streams", [{}])[0]
    width, height, duration = int(stream["width"]), int(stream["height"]), float(data["format"]["duration"])
    if width <= 0 or height <= 0 or not math.isfinite(duration) or duration <= 0:
        raise ValueError("input has invalid video dimensions or duration")
    return width, height, duration


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--regions", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--logo")
    parser.add_argument("--allow-low-confidence", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        width, height, input_duration = probe_input(args.input)
        with open(args.regions, encoding="utf-8") as handle:
            regions = validate_regions(json.load(handle), args.allow_low_confidence, width, height, input_duration)
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        output = out / "branded.mp4"
        filt, label = build_filter(regions, "1:v" if args.logo else "0:v")
        proof = {"input": str(Path(args.input).resolve()), "output": str(output.resolve()), "regions": regions, "filter_complex": filt, "status": "planned"}
        if args.execute:
            if any(region.get("replacement") for region in regions) and not args.logo:
                raise ValueError("replacement regions require --logo")
            cmd = ["ffmpeg", "-y", "-i", args.input]
            if args.logo:
                # A finite loop guarantees the logo exists for every requested timestamp.
                cmd += ["-loop", "1", "-t", str(input_duration), "-i", args.logo]
            cmd += ["-filter_complex", filt, "-map", f"[{label}]", "-map", "0:a?", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-ar", "48000", str(output)]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            proof["status"] = "executed"
        (out / "overlay_regions.json").write_text(json.dumps(regions, indent=2), encoding="utf-8")
        (out / "overlay_proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
        print(json.dumps(proof, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
