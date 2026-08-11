import json

from autodub.media.ocr_regions import (
    detections_to_regions,
    load_regions,
    merge_regions,
    save_regions,
)


def _det(text="中文字幕", confidence=0.95, box=None, t=1.0):
    return {
        "text": text,
        "confidence": confidence,
        "box": box or [[100, 800], [900, 800], [900, 860], [100, 860]],
        "time": t,
    }


def test_ocr_rejects_low_confidence_and_unsafe_boxes():
    detections = [
        _det(confidence=0.5),
        _det(box=[[0, 0], [1920, 0], [1920, 1080], [0, 1080]]),
        _det(text="English only"),
    ]

    regions = detections_to_regions(
        detections, video_w=1920, video_h=1080, min_confidence=0.8
    )

    assert regions == []


def test_ocr_converts_pixel_box_to_normalized_timed_region():
    regions = detections_to_regions(
        [_det(t=2.5)],
        video_w=1920,
        video_h=1080,
        min_confidence=0.8,
    )

    assert regions == [{
        "x": round(100 / 1920, 6),
        "y": round(800 / 1080, 6),
        "w": round(800 / 1920, 6),
        "h": round(60 / 1080, 6),
        "t_start": 2.5,
        "t_end": 3.5,
        "source": "ocr",
        "text": "中文字幕",
        "confidence": 0.95,
    }]


def test_ocr_ignores_chinese_text_outside_subtitle_band():
    detections = [
        _det(box=[[100, 100], [900, 100], [900, 160], [100, 160]]),
        _det(box=[[100, 800], [900, 800], [900, 860], [100, 860]]),
    ]

    regions = detections_to_regions(
        detections, video_w=1920, video_h=1080, min_confidence=0.8
    )

    assert len(regions) == 1
    assert regions[0]["y"] > 0.7


def test_ocr_regions_merge_across_adjacent_samples():
    regions = detections_to_regions(
        [_det(t=1.0), _det(t=2.0)],
        video_w=1920,
        video_h=1080,
        min_confidence=0.8,
        sample_interval=1.0,
    )

    merged = merge_regions(regions, max_gap=1.1)

    assert len(merged) == 1
    assert merged[0]["t_start"] == 1.0
    assert merged[0]["t_end"] == 3.0


def test_ocr_artifact_round_trip(tmp_path):
    path = tmp_path / "ocr_regions.json"
    regions = [{"x": 0.1, "y": 0.8, "w": 0.4, "h": 0.1,
                "t_start": 0.0, "t_end": 2.0, "source": "ocr"}]

    save_regions(str(path), regions)

    assert load_regions(str(path)) == regions
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2
