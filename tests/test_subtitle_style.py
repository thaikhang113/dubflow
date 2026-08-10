"""Kiểu phụ đề: bộ dựng sẵn, điền đủ khóa và dựng chuỗi cho ffmpeg.

Kiểu phụ đề đi qua rất nhiều chặng (Cài đặt → pipeline → render_opts.json →
trình chỉnh sửa → ffmpeg). Chỉ cần một chặng đánh rơi một khóa là chữ trên
video khác chữ xem trước, nên chuẩn hóa và dựng chuỗi phải được khóa chặt.
"""
from __future__ import annotations

import pytest

from autodub.media.subtitle import (
    DEFAULT_STYLE, PRESETS, build_force_style, hex_to_ass_color,
    normalize_style, preset_style,
)


# ------------------------------------------------------------ chuẩn hóa --- #

def test_normalize_fills_every_key():
    assert set(normalize_style({})) == set(DEFAULT_STYLE)
    assert set(normalize_style(None)) == set(DEFAULT_STYLE)


def test_normalize_keeps_what_the_user_chose():
    style = normalize_style({"font_size": 44, "position": "top"})
    assert style["font_size"] == 44
    assert style["position"] == "top"


def test_normalize_starts_from_the_named_preset():
    """Kiểu cũ chỉ lưu vài khóa — phần còn lại phải lấy từ đúng bộ đã chọn."""
    style = normalize_style({"preset": "tiktok", "color": "#FF0000"})
    assert style["color"] == "#FF0000"          # người dùng thắng
    assert style["line_words"] == 5             # phần còn lại theo bộ tiktok
    assert style["margin_v"] == 70


def test_unknown_preset_falls_back_to_defaults():
    style = normalize_style({"preset": "khong-co-that"})
    assert style["font_size"] == DEFAULT_STYLE["font_size"]


@pytest.mark.parametrize("key", [k for k, _l, _h, _o in PRESETS])
def test_every_preset_is_complete_and_valid(key):
    style = preset_style(key)
    assert set(style) == set(DEFAULT_STYLE)
    assert style["position"] in ("bottom", "middle", "top")
    assert style["display"] in ("sentence", "karaoke")
    assert style["box"] in ("none", "box")
    assert 0 <= style["box_opacity"] <= 100
    assert style["font_size"] > 0


# -------------------------------------------------------------- màu ASS --- #

def test_hex_to_ass_is_bgr_and_opaque_by_default():
    assert hex_to_ass_color("#FF0000") == "&H000000FF&"   # đỏ → BGR
    assert hex_to_ass_color("#00FF00") == "&H0000FF00&"


def test_opacity_maps_to_the_inverted_alpha_channel():
    assert hex_to_ass_color("#000000", 100).startswith("&H00")   # đục hẳn
    assert hex_to_ass_color("#000000", 0).startswith("&HFF")     # trong hẳn


def test_bad_hex_falls_back_to_white():
    assert hex_to_ass_color("khong-phai-mau") == "&H00FFFFFF&"


# ---------------------------------------------------------- force_style --- #

def test_force_style_carries_every_visible_choice():
    out = build_force_style({"font": "Arial", "font_size": 30, "bold": True,
                             "outline": 3, "shadow": 2, "position": "top",
                             "margin_v": 55})
    assert "FontSize=30" in out
    assert "Bold=1" in out
    assert "Outline=3" in out and "Shadow=2" in out
    assert "Alignment=8" in out      # 8 = trên, theo bàn phím số của libass
    assert "MarginV=55" in out


def test_box_mode_switches_border_style():
    plain = build_force_style({"box": "none"})
    boxed = build_force_style({"box": "box", "box_color": "#123456",
                               "box_opacity": 50})
    assert "BorderStyle=1" in plain
    assert "BorderStyle=3" in boxed      # 3 = khối nền đặc
    assert hex_to_ass_color("#123456", 50) in boxed


def test_font_name_cannot_break_the_filter_string():
    """Dấu phẩy hay nháy trong tên phông sẽ phá cả chuỗi bộ lọc của ffmpeg."""
    out = build_force_style({"font": "Ba'd, Font\\"})
    assert out.startswith("FontName=Bad Font,")
    assert out.count("FontName") == 1


def test_bold_off_is_written_explicitly():
    assert "Bold=0" in build_force_style({"bold": False})
