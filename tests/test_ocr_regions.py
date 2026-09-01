import json

from autodub.media.ocr_regions import (
    detections_to_logo_regions,
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
        "x": round(96 / 1920, 6),
        "y": round(796 / 1080, 6),
        "w": round(808 / 1920, 6),
        "h": round(68 / 1080, 6),
        "t_start": 2.5,
        "t_end": 3.5,
        "source": "ocr",
        "text": "中文字幕",
        "confidence": 0.95,
    }]


def test_ocr_accepts_two_line_subtitle_in_lower_35_percent():
    detections = [
        _det(box=[[100, 700], [900, 700], [900, 755], [100, 755]]),
        _det(box=[[100, 760], [900, 760], [900, 815], [100, 815]]),
    ]

    regions = detections_to_regions(
        detections, video_w=1920, video_h=1080, min_confidence=0.8
    )

    assert len(regions) == 2
    assert all(region["y"] + region["h"] > 0.65 for region in regions)

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


def test_ocr_rejects_vertical_or_tall_screen_text_in_subtitle_band():
    detections = [
        _det(box=[[100, 700], [220, 700], [220, 1040], [100, 1040]]),
        _det(box=[[300, 700], [1500, 700], [1500, 760], [300, 760]]),
    ]

    regions = detections_to_regions(
        detections, video_w=1920, video_h=1080, min_confidence=0.8
    )

    assert len(regions) == 1
    assert regions[0]["w"] > regions[0]["h"]

def test_ocr_can_promote_stable_upper_text_to_source_logo_region():
    detections = [
        _det(box=[[100, 80], [420, 80], [420, 130], [100, 130]], t=1.0),
        _det(box=[[104, 82], [424, 82], [424, 132], [104, 132]], t=2.0),
        _det(box=[[100, 800], [900, 800], [900, 860], [100, 860]], t=2.0),
    ]

    regions = detections_to_logo_regions(
        detections, video_w=1920, video_h=1080, min_confidence=0.8
    )

    assert len(regions) == 1
    assert regions[0]["source"] == "logo"
    assert regions[0]["x"] < 0.1
    assert regions[0]["y"] < 0.2


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
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 3

def test_logo_source_region_survives_blur_compaction():
    from autodub.media.subtitle import compact_blur_regions

    logo = {"x": 0.7, "y": 0.05, "w": 0.2, "h": 0.1, "source": "logo"}
    ocr = {"x": 0.2, "y": 0.8, "w": 0.3, "h": 0.1, "source": "ocr"}

    assert compact_blur_regions([logo, ocr]) == [logo, ocr]
