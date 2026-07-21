#!/usr/bin/env python3
import argparse
import json
import os
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageStat

# Style preset: "pro_youtube" (mặc định, v2) hoặc "legacy" (v1 cũ).
TEXT_STYLE = os.environ.get("THUMBNAIL_TEXT_STYLE", "pro_youtube").strip().lower()
if TEXT_STYLE not in ("pro_youtube", "legacy"):
    TEXT_STYLE = "pro_youtube"

FONT_FILE = os.environ.get("GOOGLE_FLOW_THUMBNAIL_FONT", "")
MAX_LINES = int(os.environ.get("THUMBNAIL_MAX_TEXT_LINES", "2"))

# v1 legacy style (giữ hành vi cũ khi THUMBNAIL_TEXT_STYLE=legacy).
LEGACY_FILL = (255, 222, 70, 255)        # #FFDE46
LEGACY_STROKE = (0, 0, 0, 255)
LEGACY_STROKE_WIDTH = 5
LEGACY_SHADOW = True
LEGACY_PANEL_ALPHA = 165

# v2 pro_youtube style defaults (override được qua text_plan).
PRO_FILL_TOP = (255, 235, 90, 255)       # gradient top (sáng)
PRO_FILL_BOTTOM = (255, 180, 30, 255)    # gradient bottom (đậm)
PRO_STROKE = (20, 12, 0, 255)
PRO_GLOW = True
PRO_EXTRUDE = True
PRO_SHADOW = True
PRO_PANEL_ALPHA = 120                     # chỉ dùng khi nền rối

# Thứ tự tìm font Việt bold/black (giống resolver subtitle_mask_render.py).
FONT_CANDIDATES = [
    "NotoSans-Black.ttf", "NotoSans-Bold.ttf", "NotoSansCJK-Black.ttc", "NotoSansCJK-Bold.ttc",
    "NotoSerif-Black.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
    "LiberationSerif-Bold.ttf", "FreeSans-Bold.ttf",
]
FONT_SEARCH_DIRS = [
    "/usr/share/fonts/truetype/noto", "/usr/share/fonts/opentype/noto",
    "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/liberation",
    "/usr/share/fonts/freefont", "/usr/share/fonts/truetype/liberation",
    os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts"),
]


def _resolve_font_path() -> str:
    """Tìm font Việt bold/black theo thứ tự env -> candidates -> system."""
    if FONT_FILE and Path(FONT_FILE).exists():
        return FONT_FILE
    for d in FONT_SEARCH_DIRS:
        if not Path(d).exists():
            continue
        for name in FONT_CANDIDATES:
            p = Path(d) / name
            if p.exists():
                return str(p)
        # Glob đuôi gần đúng trong dir.
        for cand in FONT_CANDIDATES:
            stem = cand.split(".")[0]
            for p in Path(d).glob(f"{stem}*"):
                if p.is_file():
                    return str(p)
    return "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"


RESOLVED_FONT_PATH = _resolve_font_path()


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    return title[:60] or "BIẾN CỐ BẤT NGỜ"


def load_font(size: int):
    try:
        return ImageFont.truetype(RESOLVED_FONT_PATH, size=size)
    except Exception:
        try:
            return ImageFont.truetype(FONT_FILE or "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", size=size)
        except Exception:
            return ImageFont.load_default()


def text_size(draw, text, font, stroke_width=4):
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        if text_size(draw, trial, font)[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) >= MAX_LINES - 1:
                break
    if current and len(lines) < MAX_LINES:
        rest = " ".join(words[sum(len(line.split()) for line in lines):])
        current = rest or current
        while text_size(draw, current, font)[0] > max_width and len(current) > 8:
            current = current[:-1].rstrip()
        lines.append(current)
    return lines[:MAX_LINES]


def box_pixels(box_norm, w, h):
    x1, y1, x2, y2 = box_norm
    return int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)


def parse_color(value, default):
    if not value:
        return default
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        return tuple(int(v) for v in value)
    s = str(value).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        r = int(s[0:2], 16); g = int(s[2:4], 16); b = int(s[4:6], 16)
        a = int(s[6:8], 16) if len(s) >= 8 else 255
        return (r, g, b, a)
    except Exception:
        return default


def draw_gradient_box(img, box, alpha=155):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    x1, y1, x2, y2 = box
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=(0, 0, 0, alpha))
    blurred = overlay.filter(ImageFilter.GaussianBlur(1.2))
    img.alpha_composite(blurred)


def _box_from_anchor(anchor: str, w: int, h: int) -> tuple[int, int, int, int]:
    """Default text box (pixels) from an anchor keyword when no explicit text_box."""
    if anchor == "bottom":
        return (0, int(h * 0.74), w, h)
    if anchor == "bottom_left":
        return (0, int(h * 0.64), int(w * 0.56), h)
    if anchor == "bottom_right":
        return (int(w * 0.44), int(h * 0.64), w, h)
    if anchor == "top_left":
        return (0, 0, int(w * 0.58), int(h * 0.26))
    if anchor == "top_right":
        return (int(w * 0.42), 0, w, int(h * 0.26))
    return (0, 0, w, int(h * 0.20))  # top


def _load_plan_or_layout(path: Path) -> tuple[dict, bool]:
    """Return (data, is_text_plan). is_text_plan=True if it has line_breaks/text_box."""
    if not path or not Path(path).exists():
        return {}, False
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    is_plan = isinstance(data.get("line_breaks"), list) or "text_box" in data
    return data, is_plan


def _image_clutter_score(img: Image.Image) -> float:
    """Edge density 0-1 của vùng text box -> quyết định có cần panel không."""
    try:
        gray = img.convert("L").resize((320, 180))
        edges = gray.filter(ImageFilter.FIND_EDGES)
        return float(ImageStat.Stat(edges).mean[0]) / 80.0
    except Exception:
        return 0.0


def _gradient_fill_mask(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    """Tạo mask gradient dọc top->bottom dùng cho fill chữ (multiply với text)."""
    w, h = size
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = grad.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        a = int(top[3] + (bottom[3] - top[3]) * t) if len(top) > 3 and len(bottom) > 3 else 255
        for x in range(w):
            px[x, y] = (r, g, b, a)
    return grad


def _render_pro_text(img, draw, mask_draw, x, y, text, font, fill_top, fill_bottom,
                     stroke, stroke_width, shadow, glow, extrude) -> int:
    """Pro renderer: vẽ extrude/shadow/glow/stroke(đen) riêng, rồi gradient fill fill-only mask.

    Sửa bug gradient phủ stroke: gradient fill chỉ tô phần glyph (stroke_width=0) nên
    stroke đen composited phía dưới vẫn hiện viền đen đúng. Trả về line height (có stroke).
    """
    tw, th = text_size(draw, text, font, stroke_width)
    if extrude:
        for off in range(1, 4):
            draw.text((x + off, y + off), text, font=font, fill=(0, 0, 0, 70), stroke_width=0)
    if shadow:
        draw.text((x + 4, y + 4), text, font=font, fill=(0, 0, 0, 210),
                  stroke_width=stroke_width, stroke_fill=(0, 0, 0, 230))
    if glow:
        glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        gd.text((x, y), text, font=font, fill=fill_top,
                stroke_width=stroke_width + 4, stroke_fill=fill_top)
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(3))
        img.alpha_composite(glow_layer)
    # Stroke đen (full shape) — composited phía dưới gradient fill.
    stroke_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(stroke_layer)
    sd.text((x, y), text, font=font, fill=stroke, stroke_width=stroke_width, stroke_fill=stroke)
    img.alpha_composite(stroke_layer)
    # Gradient fill (fill-only mask): chỉ glyph (stroke_width=0) -> stroke đen phía dưới vẫn hiện.
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=0)
    gw, gh = max(1, bbox[2] - bbox[0]), max(1, bbox[3] - bbox[1])
    grad = _gradient_fill_mask((gw, gh), fill_top, fill_bottom)
    fill_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(fill_layer)
    fd.text((x, y), text, font=font, fill=(255, 255, 255, 255), stroke_width=0)
    glyph_alpha = fill_layer.split()[3]
    fill_layer.paste(grad, (x + bbox[0], y + bbox[1]))
    fill_layer.putalpha(glyph_alpha)
    img.alpha_composite(fill_layer)
    # Mask preview: full text shape (glyph + stroke).
    mask_draw.text((x, y), text, font=font, fill=255, stroke_width=stroke_width, stroke_fill=255)
    return th


def compose(image_path, title, layout_or_plan_path, output_path, debug_dir) -> dict:
    image_path = Path(image_path)
    layout_or_plan_path = Path(layout_or_plan_path)
    output_path = Path(output_path)
    debug_dir = Path(debug_dir)
    img = Image.open(image_path).convert("RGBA").resize((1280, 720))
    debug_dir.mkdir(parents=True, exist_ok=True)
    raw_debug = debug_dir / "thumbnail_before_safe_text.jpg"
    img.convert("RGB").save(raw_debug, "JPEG", quality=92)

    data, is_plan = _load_plan_or_layout(layout_or_plan_path)
    title = clean_title(title)
    style = str(data.get("style") or TEXT_STYLE).strip().lower()
    if style not in ("pro_youtube", "legacy"):
        style = TEXT_STYLE

    # Style-dependent defaults (text_plan keys override).
    if style == "legacy":
        fill = parse_color(data.get("fill"), LEGACY_FILL)
        fill_top = fill
        fill_bottom = fill
        stroke = parse_color(data.get("stroke"), LEGACY_STROKE)
        stroke_width = int(data.get("stroke_width", LEGACY_STROKE_WIDTH))
        shadow = bool(data.get("shadow", LEGACY_SHADOW))
        panel = data.get("background_panel", True)
        if isinstance(panel, dict):
            panel_alpha = int(panel.get("alpha", LEGACY_PANEL_ALPHA))
            panel = bool(panel.get("enabled", True))
        else:
            panel = bool(panel)
            panel_alpha = LEGACY_PANEL_ALPHA
        glow = False
        extrude = False
    else:  # pro_youtube
        fill_top = parse_color(data.get("fill_top"), PRO_FILL_TOP)
        fill_bottom = parse_color(data.get("fill_bottom"), PRO_FILL_BOTTOM)
        fill = fill_top  # compat key
        stroke = parse_color(data.get("stroke"), PRO_STROKE)
        # stroke_width pro: dùng plan nếu có, nếu không recompute theo font.size sau (init=7).
        stroke_width = int(data.get("stroke_width", 7))
        glow = bool(data.get("glow", PRO_GLOW))
        extrude = bool(data.get("extrude", PRO_EXTRUDE))
        shadow = bool(data.get("shadow", PRO_SHADOW))
        panel = data.get("background_panel", "auto")
        if isinstance(panel, dict):
            panel_alpha = int(panel.get("alpha", PRO_PANEL_ALPHA))
            panel_mode = str(panel.get("mode", "auto")).lower()
            panel = bool(panel.get("enabled", True)) if panel_mode != "auto" else "auto"
        else:
            panel_alpha = PRO_PANEL_ALPHA
            panel = "auto" if panel in (True, "auto", None) else bool(panel)
    emphasis_word = str(data.get("emphasis_word") or "").strip()
    emphasis_scale = float(data.get("emphasis_scale", 1.2) or 1.2)

    # Resolve text box (pixels).
    if is_plan and "text_box" in data and len(data["text_box"]) == 4:
        x1, y1, x2, y2 = box_pixels(data["text_box"], img.width, img.height)
    elif is_plan and data.get("anchor"):
        x1, y1, x2, y2 = _box_from_anchor(data["anchor"], img.width, img.height)
    else:
        region = data.get("safe_text_box_norm") or [0.0, 0.0, 1.0, 0.20]
        x1, y1, x2, y2 = box_pixels(region, img.width, img.height)

    pad_x = 34
    pad_y = 18
    max_w = max(200, x2 - x1 - pad_x * 2)
    max_h = max(90, y2 - y1 - pad_y * 2)
    draw = ImageDraw.Draw(img)

    # Initial stroke width cho font-fitting (pro_youtube recompute lại theo font.size sau).
    init_stroke = stroke_width

    # Determine lines: text_plan.line_breaks wins; otherwise wrap.
    if is_plan and isinstance(data.get("line_breaks"), list) and data["line_breaks"]:
        lines = [clean_title(ln) for ln in data["line_breaks"] if clean_title(ln)]
        lines = lines[:MAX_LINES] or [title]
        font = None
        for size in range(86, 42, -4):
            font = load_font(size)
            ok = all(text_size(draw, ln, font, init_stroke)[0] <= max_w for ln in lines)
            line_heights = [text_size(draw, ln, font, init_stroke)[1] for ln in lines]
            total_h = sum(line_heights) + max(0, len(lines) - 1) * int(size * 0.12)
            if ok and total_h <= max_h:
                break
    else:
        font_size = 82 if (y2 - y1) >= 150 else 68
        for size in range(font_size, 42, -4):
            font = load_font(size)
            lines = wrap_text(draw, title, font, max_w)
            line_heights = [text_size(draw, line, font, init_stroke)[1] for line in lines]
            total_h = sum(line_heights) + max(0, len(lines) - 1) * int(size * 0.12)
            if total_h <= max_h:
                break
        else:
            font = load_font(44)
            lines = wrap_text(draw, title, font, max_w)
            total_h = sum(text_size(draw, line, font, init_stroke)[1] for line in lines)

    # pro_youtube: stroke dày theo tỉ lệ font thực tế.
    if style == "pro_youtube" and "stroke_width" not in data:
        stroke_width = max(3, int(font.size // 11))
    else:
        stroke_width = int(data.get("stroke_width", stroke_width))

    # Emphasis: enlarge the chosen word in any line that contains it.
    emphasis_font = None
    if emphasis_word:
        try:
            emphasis_font = load_font(int(font.size * emphasis_scale))
        except Exception:
            emphasis_font = None

    text_width = max(text_size(draw, line, font, stroke_width)[0] for line in lines)
    box_w = min(x2 - x1, text_width + pad_x * 2)
    box_h = min(y2 - y1, max(int(total_h), sum(text_size(draw, ln, font, stroke_width)[1] for ln in lines)) + pad_y * 2)
    if x1 > img.width * 0.3:
        bx1 = x2 - box_w - 18
    elif x2 < img.width * 0.7:
        bx1 = x1 + 18
    else:
        bx1 = x1 + (x2 - x1 - box_w) // 2
    by1 = y1 + max(8, (y2 - y1 - box_h) // 2)
    bx2, by2 = bx1 + box_w, by1 + box_h

    # Panel quyết định: pro_youtube auto -> chỉ panel khi nền rối.
    panel_used = False
    if isinstance(panel, str) and panel == "auto":
        clutter = _image_clutter_score(img.crop((bx1, by1, bx2, by2)) if bx2 > bx1 and by2 > by1 else img)
        panel_used = clutter > 0.45
    else:
        panel_used = bool(panel)
    if panel_used:
        draw_gradient_box(img, (bx1, by1, bx2, by2), alpha=panel_alpha)

    # Text mask (cho debug + gradient fill pro).
    text_mask = Image.new("L", img.size, 0)
    mask_draw = ImageDraw.Draw(text_mask)

    def _draw_line(line, font_used, y):
        tw, th = text_size(draw, line, font_used, stroke_width)
        tx = bx1 + (box_w - tw) // 2
        if style == "pro_youtube":
            return _render_pro_text(img, draw, mask_draw, tx, y, line, font_used,
                                    fill_top, fill_bottom, stroke, stroke_width,
                                    shadow, glow, extrude)
        # legacy: fill đơn sắc + shadow.
        if shadow:
            draw.text((tx + 4, y + 4), line, font=font_used, fill=(0, 0, 0, 210),
                      stroke_width=stroke_width, stroke_fill=(0, 0, 0, 230))
        draw.text((tx, y), line, font=font_used, fill=fill,
                  stroke_width=stroke_width, stroke_fill=stroke)
        mask_draw.text((tx, y), line, font=font_used, fill=255)
        return th

    y = by1 + pad_y
    for line in lines:
        if emphasis_word and emphasis_font and emphasis_word.upper() in line.upper():
            th = _draw_emphasis_line(img, draw, mask_draw, line, emphasis_word, font,
                                     emphasis_font, bx1, box_w, y, style, fill, fill_top,
                                     fill_bottom, stroke, stroke_width, shadow, glow, extrude)
        else:
            th = _draw_line(line, font, y)
        y += th + int(font.size * 0.12)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(output_path, "JPEG", quality=92)

    # Preview: chỉ text layer trên nền trong suốt.
    preview = Image.new("RGBA", img.size, (0, 0, 0, 0))
    # Render lại text lên preview (đơn giản: copy text layer qua mask).
    try:
        text_only = Image.new("RGBA", img.size, (0, 0, 0, 0))
        img.alpha_composite(text_only)  # noop, giữ preview sạch
        preview_path = output_path.parent / "thumbnail_text_preview.jpg"
        # Preview = text mask tô màu fill trên nền xám nhạt để thấy rõ.
        pv = Image.new("RGBA", img.size, (40, 40, 40, 255))
        colored = Image.new("RGBA", img.size, fill_top + (255,) if len(fill_top) == 3 else fill_top)
        pv.paste(colored, (0, 0), text_mask)
        pv.convert("RGB").save(preview_path, "JPEG", quality=92)
    except Exception:
        pass

    # Mask debug (optional).
    try:
        mask_path = debug_dir / "thumbnail_text_mask_debug.png"
        text_mask.save(mask_path)
    except Exception:
        mask_path = None

    report = {
        "title": title,
        "style": style,
        "font_path": RESOLVED_FONT_PATH,
        "font_size": int(font.size),
        "lines": lines,
        "safe_region": data.get("safe_text_region", data.get("anchor", "top")),
        "text_box": [bx1, by1, bx2, by2],
        "fill_top": list(fill_top),
        "fill_bottom": list(fill_bottom) if style == "pro_youtube" else list(fill_top),
        "stroke": list(stroke),
        "stroke_width": stroke_width,
        "shadow": shadow,
        "glow": glow,
        "extrude": extrude,
        "background_panel": panel_used,
        "panel_alpha": panel_alpha if panel_used else 0,
        "emphasis_word": emphasis_word,
        "emphasis_scale": emphasis_scale,
        "plan_mode": is_plan,
        "raw_debug": str(raw_debug),
        "text_preview": str(output_path.parent / "thumbnail_text_preview.jpg"),
        "text_mask_debug": str(mask_path) if mask_path else "",
    }
    report_path = output_path.parent / "thumbnail_composer_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Compat: giữ tên meta cũ cho code đọc tên cũ.
    (debug_dir / "thumbnail_composer_meta.json").write_text(
        json.dumps({k: v for k, v in report.items() if k in
                    ("title", "lines", "safe_region", "text_box", "fill_top", "stroke",
                     "stroke_width", "shadow", "background_panel", "emphasis_word",
                     "emphasis_scale", "plan_mode", "raw_debug")}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return report


def _draw_emphasis_line(img, draw, mask_draw, line, emphasis_word, font, emphasis_font,
                         bx1, box_w, y, style, fill, fill_top, fill_bottom,
                         stroke, stroke_width, shadow, glow, extrude) -> int:
    """Vẽ dòng có emphasis_word phóng to, phần còn lại font thường.

    Pro_youtube: dùng _render_pro_text cho từng đoạn (pre/emph/post) -> gradient fill,
    stroke đen, glow, extrude đồng bộ với dòng thường. Legacy: fill đơn sắc + shadow.
    Trả về line height (theo emphasis_font, có stroke).
    """
    ew = emphasis_word.upper()
    up = line.upper()
    idx = up.find(ew)
    emph_h = text_size(draw, emph := (line[idx:idx + len(emphasis_word)] if idx >= 0 else line),
                       emphasis_font, stroke_width)[1]
    if idx < 0:
        tw, _ = text_size(draw, line, font, stroke_width)
        tx = bx1 + (box_w - tw) // 2
        if style == "pro_youtube":
            _render_pro_text(img, draw, mask_draw, tx, y, line, font, fill_top, fill_bottom,
                             stroke, stroke_width, shadow, glow, extrude)
        else:
            if shadow:
                draw.text((tx + 4, y + 4), line, font=font, fill=(0, 0, 0, 210),
                          stroke_width=stroke_width, stroke_fill=(0, 0, 0, 230))
            draw.text((tx, y), line, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke)
            mask_draw.text((tx, y), line, font=font, fill=255)
        return emph_h
    pre = line[:idx]
    post = line[idx + len(emphasis_word):]
    pre_w = text_size(draw, pre, font, stroke_width)[0]
    emph_w = text_size(draw, emph, emphasis_font, stroke_width)[0]
    post_w = text_size(draw, post, font, stroke_width)[0]
    total_w = pre_w + emph_w + post_w
    tx = bx1 + (box_w - total_w) // 2
    # Căn baseline: emphasis (font lớn) nudge lên trên để canh giữa với font thường.
    normal_h = text_size(draw, "Ay", font, stroke_width)[1]
    yoff = max(0, (emph_h - normal_h) // 2) * -1

    def _render(seg, font_used, sx, sy):
        if not seg:
            return
        if style == "pro_youtube":
            _render_pro_text(img, draw, mask_draw, sx, sy, seg, font_used, fill_top,
                             fill_bottom, stroke, stroke_width, shadow, glow, extrude)
        else:
            if shadow:
                draw.text((sx + 4, sy + 4), seg, font=font_used, fill=(0, 0, 0, 210),
                          stroke_width=stroke_width, stroke_fill=(0, 0, 0, 230))
            draw.text((sx, sy), seg, font=font_used, fill=fill, stroke_width=stroke_width, stroke_fill=stroke)
            mask_draw.text((sx, sy), seg, font=font_used, fill=255)

    _render(pre, font, tx, y)
    _render(emph, emphasis_font, tx + pre_w, y + yoff)
    _render(post, font, tx + pre_w + emph_w, y)
    return emph_h


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("title")
    parser.add_argument("layout")  # path to thumbnail_text_plan.json OR thumbnail_layout.json
    parser.add_argument("output")
    parser.add_argument("debug_dir")
    args = parser.parse_args()
    meta = compose(Path(args.image), args.title, Path(args.layout), Path(args.output), Path(args.debug_dir))
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())