#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from PIL import Image, ImageFilter, ImageStat

REGIONS = {
    "top": (0.0, 0.0, 1.0, 0.20),
    "bottom": (0.0, 0.78, 1.0, 1.0),
    "bottom_left": (0.0, 0.64, 0.56, 1.0),
    "bottom_right": (0.44, 0.64, 1.0, 1.0),
    "top_left": (0.0, 0.0, 0.58, 0.26),
    "top_right": (0.42, 0.0, 1.0, 0.26),
}


def crop_region(img, box_norm):
    w, h = img.size
    x1, y1, x2, y2 = box_norm
    return img.crop((int(x1*w), int(y1*h), int(x2*w), int(y2*h)))


def region_score(img, box_norm):
    crop = crop_region(img, box_norm).convert("RGB")
    gray = crop.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    brightness = ImageStat.Stat(gray).mean[0]
    contrast = ImageStat.Stat(gray).stddev[0]
    edge = ImageStat.Stat(edges).mean[0]
    # Lower saliency is safer for text. Darker regions are slightly preferred.
    saliency = edge * 1.6 + contrast * 0.8 + max(0, brightness - 120) * 0.15
    return {"brightness": brightness, "contrast": contrast, "edge": edge, "saliency": saliency}


def analyze(reference: Path, layout_path: Path) -> dict:
    img = Image.open(reference).convert("RGB").resize((1280, 720))
    scores = {name: region_score(img, box) for name, box in REGIONS.items()}
    safe_order = sorted(scores, key=lambda name: scores[name]["saliency"])
    preferred = safe_order[0]
    # Avoid huge top banner if top is very busy; use bottom side when safer.
    if preferred == "top" and scores["top"]["saliency"] > min(scores["bottom_left"]["saliency"], scores["bottom_right"]["saliency"]) * 1.20:
        preferred = "bottom_left" if scores["bottom_left"]["saliency"] <= scores["bottom_right"]["saliency"] else "bottom_right"
    layout = {
        "reference": str(reference),
        "canvas": {"width": 1280, "height": 720},
        "regions": {name: {"box_norm": REGIONS[name], **scores[name]} for name in REGIONS},
        "safe_text_region": preferred,
        "safe_text_box_norm": REGIONS[preferred],
        "max_text_lines": 2,
        "top_banner_max_height": 0.20,
        "avoid_subject_center": True,
    }
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    return layout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference")
    parser.add_argument("layout")
    args = parser.parse_args()
    layout = analyze(Path(args.reference), Path(args.layout))
    print(json.dumps(layout, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
