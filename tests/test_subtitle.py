"""Tests for subtitle burning and region-blur filtergraph construction."""

from autodub.media.subtitle import (
    blur_filter,
    build_filter_complex,
    build_force_style,
    compact_blur_regions,
    escape_subtitles_path,
    hex_to_ass_color,
    mirror_blur_regions,
)

W, H = 1920, 1080
FULL_WIDTH_BAND = {"x": 0.0, "y": 0.85, "w": 1.0, "h": 0.12}


# --------------------------- path escaping --------------------------- #

def test_escape_windows_path():
    out = escape_subtitles_path(r"C:\Users\me\out\sub.srt")
    assert out == "C\\:/Users/me/out/sub.srt"
    assert "\\U" not in out          # no stray backslash escapes


def test_escape_posix_path_only_touches_colon():
    assert escape_subtitles_path("/home/me/sub.srt") == "/home/me/sub.srt"


def test_escape_single_quote():
    # Inside ffmpeg single quotes a backslash is literal, so ' must use the
    # close-escape-reopen splice ('\'') — \' would end the quoted token.
    assert escape_subtitles_path("/tmp/bo's.srt") == "/tmp/bo'\\''s.srt"


# --------------------------- style --------------------------- #

def test_force_style_defaults_and_override():
    assert "FontSize=22" in build_force_style()
    assert "FontSize=40" in build_force_style({"font_size": 40})
    assert "Alignment=2" in build_force_style()      # bottom-centre


def test_force_style_position_maps_to_alignment():
    assert "Alignment=2" in build_force_style({"position": "bottom"})
    assert "Alignment=5" in build_force_style({"position": "middle"})
    assert "Alignment=8" in build_force_style({"position": "top"})


def test_hex_to_ass_color_bgr_order():
    # pure red #FF0000 → &H000000FF& (BGR, opaque alpha 00)
    assert hex_to_ass_color("#FF0000") == "&H000000FF&"
    assert hex_to_ass_color("#FFFFFF") == "&H00FFFFFF&"
    assert hex_to_ass_color("#000000") == "&H00000000&"
    assert hex_to_ass_color("bad") == "&H00FFFFFF&"    # invalid → white


def test_force_style_custom_colors():
    style = build_force_style({"color": "#FF0000", "outline_color": "#00FF00"})
    assert "PrimaryColour=&H000000FF&" in style       # red text
    assert "OutlineColour=&H0000FF00&" in style       # green outline


# --------------------------- no-op --------------------------- #

def test_no_filter_when_nothing_requested():
    assert build_filter_complex(None, W, H) is None
    assert build_filter_complex([], W, H, None) is None


# --------------------------- subtitles only --------------------------- #

def test_subtitles_only_graph():
    graph = build_filter_complex(None, W, H, "/tmp/vi.srt")
    assert graph.startswith("[0:v]subtitles='/tmp/vi.srt'")
    assert graph.endswith("[vout]")
    assert "crop" not in graph and "boxblur" not in graph


# --------------------------- blur only --------------------------- #

def test_blur_only_ends_at_vout_via_null():
    graph = build_filter_complex([FULL_WIDTH_BAND], W, H)
    assert "boxblur" in graph
    assert graph.endswith("null[vout]")
    assert "subtitles" not in graph


def test_blur_region_converted_to_pixels():
    graph = build_filter_complex([FULL_WIDTH_BAND], W, H)
    # y=0.85*1080=918, h=0.12*1080=129.6→130 (even), w=1920
    assert "crop=1920:130:0:918" in graph
    assert "overlay=0:918" in graph


def test_blur_dimensions_are_even():
    """Odd crop sizes break yuv420p chroma subsampling."""
    graph = build_filter_complex([{"x": 0, "y": 0, "w": 0.333, "h": 0.111}], W, H)
    crop = [p for p in graph.split(";") if "crop=" in p][0]
    w, h = crop.split("crop=")[1].split(",")[0].split(":")[:2]
    assert int(w) % 2 == 0 and int(h) % 2 == 0


def test_region_clamped_to_frame():
    """An oversized region must not crop outside the video."""
    graph = build_filter_complex([{"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5}], W, H)
    crop = [p for p in graph.split(";") if "crop=" in p][0]
    w, h, x, y = (int(v) for v in crop.split("crop=")[1].split(",")[0].split(":"))
    assert x + w <= W and y + h <= H


def test_multiple_regions_chain_sequentially():
    graph = build_filter_complex(
        [FULL_WIDTH_BAND, {"x": 0.0, "y": 0.0, "w": 0.3, "h": 0.1}], W, H)
    assert graph.count("boxblur") == 2
    assert "[v1]split[b1][b1c]" in graph      # second region consumes the first's output
    assert graph.endswith("[vout]")


def test_blur_radius_capped_for_small_regions():
    """ffmpeg rejects a radius >= plane/2; chroma is half-size in yuv420p.

    Regression: boxblur=10 on a 192x36 band failed with
    "Invalid chroma_param radius value 10, must be >= 0 and < 9".
    """
    assert blur_filter(1920, 130) == "boxblur=10:2"     # large: full strength
    assert blur_filter(192, 36) == "boxblur=8:2"        # 36//4-1 = 8
    assert blur_filter(20, 4) == "boxblur=1:2"          # tiny: floor at 1
    assert blur_filter(2, 2) == "boxblur=1:2"           # never 0


def test_small_region_graph_uses_reduced_radius():
    graph = build_filter_complex([{"x": 0, "y": 0, "w": 0.1, "h": 0.03}], W, H)
    assert "boxblur=7:2" in graph                       # 32//4-1 = 7


def test_time_window_adds_enable_expression():
    region = {**FULL_WIDTH_BAND, "t_start": 1.5, "t_end": 4.0}
    graph = build_filter_complex([region], W, H)
    assert "enable='between(t,1.5,4.0)'" in graph


def test_no_enable_without_full_time_window():
    graph = build_filter_complex([{**FULL_WIDTH_BAND, "t_start": 1.0}], W, H)
    assert "enable" not in graph


# --------------------------- OCR compaction --------------------------- #

def test_compact_blur_regions_merges_repeated_ocr_box():
    regions = [
        {"x": 0.01, "y": 0.04, "w": 0.10, "h": 0.05,
         "t_start": 0.0, "t_end": 1.0, "source": "ocr"},
        {"x": 0.012, "y": 0.041, "w": 0.099, "h": 0.049,
         "t_start": 1.0, "t_end": 3.0, "source": "ocr"},
    ]
    compacted = compact_blur_regions(regions)
    assert len(compacted) == 1
    assert compacted[0]["t_start"] == 0.0
    assert compacted[0]["t_end"] == 3.0


def test_compact_blur_regions_keeps_separate_positions():
    regions = [
        {**FULL_WIDTH_BAND, "t_start": 0.0, "t_end": 1.0, "source": "ocr"},
        {"x": 0.0, "y": 0.05, "w": 0.2, "h": 0.1,
         "t_start": 0.0, "t_end": 1.0, "source": "ocr"},
    ]
    assert len(compact_blur_regions(regions)) == 2


def test_compact_blur_regions_bounds_large_ocr_graph():
    regions = [
        {"x": 0.01 + (i % 10) * 0.09, "y": 0.88, "w": 0.05,
         "h": 0.06, "t_start": float(i * 2), "t_end": float(i * 2 + 1),
         "source": "ocr"}
        for i in range(100)
    ]
    compacted = compact_blur_regions(regions, max_regions=24)
    graph = build_filter_complex(compacted, W, H)
    assert len(compacted) == 100
    assert max(float(region["w"]) for region in compacted) <= 0.05
    assert max(float(region["h"]) for region in compacted) <= 0.06
    assert graph.count("delogo") == len(compacted)
    assert "boxblur" not in graph


def test_compact_blur_regions_does_not_force_distant_ocr_boxes_into_large_regions():
    regions = [
        {"x": 0.01 + (i % 8) * 0.12, "y": 0.04 + (i % 4) * 0.05,
         "w": 0.08, "h": 0.04, "t_start": float(i),
         "t_end": float(i + 1), "source": "ocr"}
        for i in range(32)
    ]
    compacted = compact_blur_regions(regions, max_regions=4)
    assert max(float(region["w"]) for region in compacted) <= 0.16
    assert max(float(region["h"]) for region in compacted) <= 0.08

def test_compact_blur_regions_drops_malformed_regions():
    assert compact_blur_regions([{"x": 0.1}, {"x": "bad"}]) == []

def test_mirror_blur_region_moves_x_only():
    region = {"x": 0.2, "y": 0.3, "w": 0.25, "h": 0.1}
    mirrored = mirror_blur_regions([region])[0]
    assert mirrored["x"] == 0.55
    assert mirrored["y"] == region["y"]
    assert mirrored["w"] == region["w"]


# --------------------------- combined --------------------------- #

def test_blur_then_subtitles_order():
    """Subtitles must draw on top of the blur, not underneath it."""
    graph = build_filter_complex([FULL_WIDTH_BAND], W, H, "/tmp/vi.srt")
    assert graph.index("boxblur") < graph.index("subtitles")
    assert graph.endswith("[vout]")
    assert "null[vout]" not in graph
