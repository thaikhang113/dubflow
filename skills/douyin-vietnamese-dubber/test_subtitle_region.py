#!/usr/bin/env python3
"""Small, synthetic regression tests for the fixed subtitle-region artifact."""
import importlib.util
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
        artifact.write_text(artifact.read_text(encoding="utf-8").replace('"schema_version": 1', '"schema_version": 0'), encoding="utf-8")
        assert renderer.load_subtitle_region(artifact, video, W, H) is None
        renderer.write_subtitle_region(artifact, video, W, H, args, band)
        artifact.write_text(
            artifact.read_text(encoding="utf-8").replace(renderer.SUBTITLE_REGION_DETECTOR_VERSION, "old-detector"),
            encoding="utf-8",
        )
        assert renderer.load_subtitle_region(artifact, video, W, H) is None


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"subtitle region tests passed: {len(tests)}")
