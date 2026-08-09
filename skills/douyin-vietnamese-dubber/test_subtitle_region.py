#!/usr/bin/env python3
"""Small, synthetic regression tests for the fixed subtitle-region artifact."""
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace


SKILL_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("subtitle_mask_render", SKILL_DIR / "subtitle_mask_render.py")
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


W, H = 1920, 1080


def sample(frame, y, h=34, x=520, w=880):
    return {"frame": frame, "time": frame / 24, "bbox": [x, y, x + w, y + h], "method": "synthetic"}


def test_prefers_stable_low_subtitle_over_center_title():
    samples = [sample(i, 472, 44, 360, 1200) for i in range(7)]  # title card
    samples += [sample(i, 904 + (i % 3), 36) for i in range(24)]
    cluster = renderer.select_subtitle_cluster(samples, W, H, 24)
    assert cluster and cluster["median_center_y"] > 900, cluster
    assert cluster["accepted_sample_count"] >= 20, cluster
    assert cluster["band"]["y"] <= 904 and cluster["band"]["y"] + cluster["band"]["h"] >= 940, cluster
    assert cluster["band"]["h"] < 150, cluster


def test_one_and_two_line_bands_cover_text_without_giant_merge():
    one_line = [sample(i, 920 + (i % 2), 34) for i in range(22)]
    two_line = [sample(i, 838 + (i % 2), 78, 430, 1060) for i in range(22)]
    for samples, bottom in ((one_line, 954), (two_line, 917)):
        cluster = renderer.select_subtitle_cluster(samples, W, H, 24)
        band = cluster["band"]
        assert band["y"] <= min(s["bbox"][1] for s in samples)
        assert band["y"] + band["h"] >= bottom
        assert 70 <= band["h"] <= 150, cluster
        assert cluster["stability"] >= 0.85, cluster


def test_empty_and_sparse_title_only_need_fallback():
    title_only = [sample(i, 470, 48, 300, 1300) for i in range(3)]
    assert renderer.select_subtitle_cluster([], W, H, 24) is None
    assert renderer.select_subtitle_cluster(title_only, W, H, 24) is None


def test_cluster_counts_at_most_one_detection_per_sample_frame():
    # A noisy CV frame can contain both a subtitle-like component and a nearby
    # duplicate.  Stability is a frame property, so duplicates must not inflate it.
    samples = []
    for frame in range(12):
        samples.append(sample(frame, 904, 36))
        samples.append(sample(frame, 906, 34, 530, 860))
    cluster = renderer.select_subtitle_cluster(samples, W, H, 24)
    assert cluster and cluster["accepted_sample_count"] == 12, cluster
    assert 0.49 <= cluster["stability"] <= 0.51, cluster


def test_duplicate_boxes_in_too_few_frames_do_not_make_a_cluster_viable():
    samples = []
    for frame in range(3):
        samples.append(sample(frame, 904, 36))
        samples.append(sample(frame, 906, 34, 530, 860))
    assert renderer.select_subtitle_cluster(samples, W, H, 24) is None


def test_artifact_round_trip_and_renderer_only_contract():
    args = SimpleNamespace(
        band_region_top_ratio=0.55, band_region_bottom_ratio=1.0,
        band_height_ratio=0.10, band_min_height=64,
    )
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "fixture.mp4"
        video.write_bytes(b"synthetic-video")
        artifact = Path(tmp) / "subtitle_region.json"
        band = {"x": 0, "y": 886, "w": W, "h": 108, "source": "stable_band", "fallback": False,
                "reason": "ok", "sample_count": 24, "detected_sample_count": 20,
                "confidence": 0.92, "line_mode": "one_line", "stability": 0.91}
        renderer.write_subtitle_region(artifact, video, W, H, args, band)
        loaded = renderer.load_subtitle_region(artifact, video, W, H)
        assert loaded["y"] == 886 and loaded["h"] == 108
        artifact.write_text(artifact.read_text(encoding="utf-8").replace('"schema_version": 2', '"schema_version": 1'), encoding="utf-8")
        assert renderer.load_subtitle_region(artifact, video, W, H) is None
        renderer.write_subtitle_region(artifact, video, W, H, args, band)
        artifact.write_text(
            artifact.read_text(encoding="utf-8").replace(renderer.SUBTITLE_REGION_DETECTOR_VERSION, "old-detector"),
            encoding="utf-8",
        )
        assert renderer.load_subtitle_region(artifact, video, W, H) is None

def test_localized_fallback_uses_detected_horizontal_bounds():
    args = SimpleNamespace(
        fallback_mask_height_ratio=0.08,
        box_vertical_offset_ratio=0.02,
        max_chars_per_line=28,
        max_lines=2,
        font_size_ratio=0.03,
        dynamic_mask_min_width_ratio=0.12,
        fallback_mask_max_width_ratio=0.50,
    )
    band = {"x": 510, "y": 886, "w": 900, "h": 108}
    box = renderer.fallback_text_box(W, H, "Một câu phụ đề đủ dài", args, band=band)
    assert box["y"] == 886 and box["h"] == 108, box
    assert box["x"] >= 510 and box["x"] + box["w"] <= 1410, box
    assert box["w"] < W, box

def test_localized_blur_filter_uses_masked_merge_not_full_width_crop():
    filter_complex = renderer.build_localized_blur_filter(
        "ass='vi.ass'",
        "ass='mask.ass'",
        SimpleNamespace(band_blur=18, band_tint_opacity=0.18),
    )
    assert "maskedmerge" in filter_complex
    assert "crop=w=iw" not in filter_complex
    assert "ass='mask.ass'" in filter_complex

def test_pipeline_defaults_to_localized_blur():
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    assert 'SUBTITLE_MASK_STYLE="${SUBTITLE_MASK_STYLE:-localized_blur}"' in run_sh


def test_localized_blur_uses_stable_band_for_vietnamese_text_layout():
    source = (SKILL_DIR / "subtitle_mask_render.py").read_text(encoding="utf-8")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    assert 'text_box = {"x": band["x"], "y": band["y"], "w": band["w"], "h": band["h"]}' in source
    assert 'fit_vi_subtitle_text(event.get("text", ""), text_box,' in source
    assert 'VI_SUBTITLE_SAFE_HEIGHT_RATIO="${VI_SUBTITLE_SAFE_HEIGHT_RATIO:-1.0}"' in run_sh


def test_localized_blur_filter_renders_with_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source.mp4"
        output = root / "output.mp4"
        mask_ass = root / "mask.ass"
        subtitle_ass = root / "vi.ass"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        renderer.write_mask_ass(
            mask_ass, 320, 180,
            [{"start": 0.0, "end": 1.0, "x": 80, "y": 120, "w": 160, "h": 32}],
            SimpleNamespace(mask_alpha=1.0, mask_rounded=False, mask_radius=0),
            colour="white", opacity=1.0,
        )
        subtitle_ass.write_text(
            """[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 180

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,22,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,18,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Phu de Viet
""",
            encoding="utf-8",
        )
        graph = renderer.build_localized_blur_filter(
            f"ass='{renderer.ass_escape_path(subtitle_ass.resolve())}'",
            f"ass='{renderer.ass_escape_path(mask_ass.resolve())}'",
            SimpleNamespace(band_blur=8, band_tint_opacity=0.18),
        )
        subprocess.run([
            "ffmpeg", "-y", "-i", str(source), "-filter_complex", graph,
            "-map", "[vout]", "-map", "0:a?", "-c:v", "libx264", "-c:a", "copy", str(output),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        streams = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output),
        ], text=True).strip()
        assert output.stat().st_size > 0 and streams == "video"

if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"subtitle region tests passed: {len(tests)}")
