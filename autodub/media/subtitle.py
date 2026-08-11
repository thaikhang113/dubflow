"""Kiểu phụ đề và bộ lọc ffmpeg cho phần ghi chữ / che chữ lên hình.

Đây là NGUỒN DUY NHẤT định nghĩa một "kiểu phụ đề" trong toàn ứng dụng: trang
Cài đặt, hộp thoại chỉnh kiểu chữ, pipeline và trình chỉnh sửa đều đọc cùng
các khóa ở đây, nên chữ xem trước và chữ ghi vào video luôn khớp nhau.

Hai việc, gộp trong đúng một lượt mã hóa lại (:func:`build_filter_complex`):

1. **Che chữ trên hình** — phụ đề cứng của video gốc. Người dùng khoanh vùng
   trong giao diện; tọa độ lưu dạng chuẩn hóa 0..1 nên đổi độ phân giải vẫn
   đúng chỗ.
2. **Ghi phụ đề vào hình** — vẽ phụ đề tiếng Việt đè lên vùng đã che, bằng
   libass, nên chữ cũ bị giấu và chữ mới nằm đúng chỗ của nó.

Chỗ khó nhất là thoát đường dẫn cho bộ lọc ``subtitles`` trên Windows: chuỗi
đi qua bộ đọc filtergraph của ffmpeg RỒI mới tới bộ đọc tùy chọn của bộ lọc,
nên ``C:\\out\\a.srt`` phải thành ``C\\:/out/a.srt``.
"""
from __future__ import annotations

import re

# Độ mờ của vùng che: boxblur luma_radius:luma_power. Bán kính 10 xóa sạch
# chữ mà vẫn nhẹ; vùng che là chữ đục nên không mất chi tiết gì.
MAX_BLUR_RADIUS = 10
BLUR_POWER = 2

#: Kiểu phụ đề đầy đủ — mọi khóa đều có mặt để không nơi nào phải đoán.
DEFAULT_STYLE: dict = {
    "preset": "clean",
    "position": "bottom",       # "bottom" | "middle" | "top"
    "font": "Arial",
    "font_size": 22,
    "margin_v": 40,
    "outline": 2,
    "shadow": 0,
    "bold": True,
    "color": "#FFFFFF",
    "outline_color": "#000000",
    "box": "none",              # "none" (chỉ viền) | "box" (khối nền đặc)
    "box_color": "#000000",
    "box_opacity": 60,          # 0–100, chỉ dùng khi box = "box"
    "line_words": 0,            # 0 = tự xuống dòng theo bề rộng
    "max_lines": 2,
    "all_caps": False,
    "display": "sentence",      # "sentence" | "karaoke"
    "words_per_cue": 3,
    "effect": "pop",            # "pop" | "fade" | "karaoke" | "none"
    "highlight_color": "#FFD54A",
}

#: Bộ kiểu dựng sẵn — (khóa, tên hiển thị, mô tả ngắn, phần ghi đè).
#: Người dùng chọn một bộ rồi tinh chỉnh; mọi khóa không nêu giữ mặc định.
PRESETS: tuple[tuple[str, str, str, dict], ...] = (
    ("clean", "Gọn gàng", "Chữ trắng viền đen, hợp mọi loại video", {
        "font_size": 22, "outline": 2, "shadow": 0, "bold": True,
        "color": "#FFFFFF", "outline_color": "#000000", "box": "none",
        "line_words": 0, "max_lines": 2, "display": "sentence",
    }),
    ("bold_yellow", "Nổi bật", "Chữ vàng viền dày, hợp video giải trí", {
        "font_size": 26, "outline": 3, "shadow": 1, "bold": True,
        "color": "#FFE24A", "outline_color": "#101010", "box": "none",
        "line_words": 0, "max_lines": 2, "display": "sentence",
    }),
    ("box", "Nền mờ", "Khối nền tối sau chữ, dễ đọc trên nền rối", {
        "font_size": 22, "outline": 4, "shadow": 0, "bold": False,
        "color": "#FFFFFF", "box": "box", "box_color": "#000000",
        "box_opacity": 65, "line_words": 0, "max_lines": 2,
        "display": "sentence",
    }),
    ("tiktok", "Video dọc", "Chữ to, ít chữ mỗi hàng, nằm cao hơn mép dưới", {
        "font_size": 30, "outline": 3, "shadow": 0, "bold": True,
        "color": "#FFFFFF", "outline_color": "#000000", "box": "none",
        "line_words": 5, "max_lines": 2, "margin_v": 70,
        "display": "sentence",
    }),
    ("karaoke", "Cụm chữ theo lời", "Từng cụm ngắn sáng lên đúng nhịp đọc", {
        "font_size": 30, "outline": 3, "shadow": 0, "bold": True,
        "color": "#FFFFFF", "outline_color": "#000000", "box": "none",
        "margin_v": 70, "display": "karaoke", "words_per_cue": 3,
        "effect": "karaoke", "highlight_color": "#FFD54A",
    }),
    ("cinema", "Điện ảnh", "Chữ nhỏ, viền mảnh, sát mép dưới", {
        "font_size": 18, "outline": 1, "shadow": 1, "bold": False,
        "color": "#F2F2F2", "outline_color": "#000000", "box": "none",
        "line_words": 0, "max_lines": 2, "margin_v": 24,
        "display": "sentence",
    }),
    ("custom", "Tự chỉnh", "Bạn tự quyết mọi thông số bên dưới", {}),
)

_PRESET_MAP = {key: overrides for key, _label, _hint, overrides in PRESETS}

#: Danh sách (nhãn, khóa) cho ô chọn của giao diện.
PRESET_CHOICES: list[tuple[str, str]] = [
    (label, key) for key, label, _hint, _o in PRESETS
]

# Alignment của libass (theo bàn phím số): 2 = dưới-giữa, 5 = giữa, 8 = trên.
_POSITION_ALIGN = {"bottom": 2, "middle": 5, "top": 8}


def preset_style(key: str) -> dict:
    """Kiểu đầy đủ của một bộ dựng sẵn."""
    return {**DEFAULT_STYLE, "preset": key, **_PRESET_MAP.get(key, {})}


def normalize_style(style: dict | None) -> dict:
    """Điền đủ mọi khóa còn thiếu của một kiểu phụ đề.

    Kiểu lưu trong dự án cũ chỉ có vài khóa; hàm này đắp phần còn lại từ bộ
    dựng sẵn tương ứng (nếu có) rồi tới giá trị mặc định, nên mọi nơi đọc
    kiểu đều thấy một dict hoàn chỉnh và không phải viết ``.get(..., mặc định)``.
    """
    style = dict(style or {})
    base = preset_style(str(style.get("preset", DEFAULT_STYLE["preset"])))
    base.update({k: v for k, v in style.items() if v is not None})
    return base


def blur_filter(width: int, height: int) -> str:
    """Bộ lọc boxblur có bán kính hợp lệ với kích thước vùng che.

    ffmpeg đòi bán kính nhỏ hơn nửa của MẶT PHẲNG đang làm mờ. Ở yuv420p hai
    mặt phẳng màu chỉ bằng một nửa độ phân giải, nên giới hạn thật là
    ``min(w, h) / 4`` — vùng 192x36 chỉ cho phép bán kính dưới 9. Vượt quá
    thì ffmpeg báo "Invalid chroma_param radius value".
    """
    limit = min(width, height) // 4
    radius = max(1, min(MAX_BLUR_RADIUS, limit - 1 if limit > 1 else 1))
    return f"boxblur={radius}:{BLUR_POWER}"


def hex_to_ass_color(hex_color: str, opacity: int = 100) -> str:
    """Đổi ``#RRGGBB`` sang màu ASS ``&HAABBGGRR&`` (thứ tự BGR).

    ``opacity`` tính theo phần trăm: 100 là đục hoàn toàn, 0 là trong suốt.
    Trong ASS thì kênh AA ngược lại — 00 mới là đục.
    """
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        r, g, b = 255, 255, 255
    alpha = max(0, min(255, round((100 - max(0, min(100, opacity))) * 255 / 100)))
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}&"


def safe_font_name(font: str) -> str:
    """Tên phông an toàn: bỏ ký tự phá cấu trúc chuỗi force_style/filtergraph."""
    return re.sub(r"[,'\"\\]", "", str(font or "")) or "Arial"


def escape_subtitles_path(path: str) -> str:
    """Thoát đường dẫn để dùng làm giá trị của bộ lọc ``subtitles=``.

    Trên Windows cần ba phép đổi: dấu ``\\`` thành ``/`` (ffmpeg chấp nhận và
    chúng không còn là ký tự thoát), dấu hai chấm của ổ đĩa được thoát để bộ
    đọc bộ lọc không hiểu nhầm là dấu ngăn tùy chọn, và dấu nháy đơn dùng
    cách nối ``'\\''`` (đóng nháy, nháy đã thoát, mở lại) vì bên trong nháy
    đơn của ffmpeg thì dấu ``\\`` là ký tự thường — viết ``\\'`` sẽ KHÔNG
    thoát được dấu nháy và đường dẫn kiểu ``O'Brien`` làm hỏng cả filtergraph.
    """
    escaped = path.replace("\\", "/")
    escaped = escaped.replace(":", "\\:")
    escaped = escaped.replace("'", r"'\''")
    return escaped


def build_force_style(style: dict | None = None) -> str:
    """Chuỗi ``force_style`` của libass cho phụ đề ghi vào hình.

    Theo đúng vị trí, phông, cỡ chữ, lề dọc, độ dày viền, đổ bóng, in đậm,
    màu chữ / màu viền và khối nền. Màu ASS là ``&HAABBGGRR&`` (thứ tự BGR).
    """
    s = normalize_style(style)
    align = _POSITION_ALIGN.get(str(s["position"]), 2)
    boxed = str(s["box"]) == "box"
    # BorderStyle 3 = khối nền đặc, vẽ bằng chính OutlineColour; lúc đó
    # Outline đóng vai trò khoảng đệm quanh chữ.
    border_style = 3 if boxed else 1
    outline_colour = (hex_to_ass_color(s["box_color"], int(s["box_opacity"]))
                      if boxed else hex_to_ass_color(s["outline_color"]))
    return (
        f"FontName={safe_font_name(s['font'])},"
        f"FontSize={int(s['font_size'])},"
        f"Bold={1 if s['bold'] else 0},"
        f"BorderStyle={border_style},"
        f"Outline={int(s['outline'])},"
        f"Shadow={int(s['shadow'])},"
        f"Alignment={align},"
        f"MarginV={int(s['margin_v'])},"
        f"PrimaryColour={hex_to_ass_color(s['color'])},"
        f"OutlineColour={outline_colour},"
        f"BackColour={hex_to_ass_color('#000000', 40)}"
    )


def _to_pixels(region: dict, video_w: int, video_h: int) -> tuple[int, int, int, int]:
    """Đổi một vùng chuẩn hóa thành số điểm ảnh chẵn, nằm gọn trong khung.

    Chiều rộng và cao chẵn để phép cắt còn hợp lệ với yuv420p.
    """
    x = int(round(float(region["x"]) * video_w))
    y = int(round(float(region["y"]) * video_h))
    w = int(round(float(region["w"]) * video_w))
    h = int(round(float(region["h"]) * video_h))

    x = max(0, min(x, video_w - 2))
    y = max(0, min(y, video_h - 2))
    w = max(2, min(w, video_w - x))
    h = max(2, min(h, video_h - y))
    return x, y, w - (w % 2), h - (h % 2)


def _region_iou(a: dict, b: dict) -> float:
    ax1, ay1 = float(a["x"]), float(a["y"])
    ax2, ay2 = ax1 + float(a["w"]), ay1 + float(a["h"])
    bx1, by1 = float(b["x"]), float(b["y"])
    bx2, by2 = bx1 + float(b["w"]), by1 + float(b["h"])
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = float(a["w"]) * float(a["h"]) + float(b["w"]) * float(b["h"]) - inter
    return inter / union if union > 0 else 0.0


def _normalize_blur_region(region: dict) -> dict | None:
    try:
        x = max(0.0, min(1.0, float(region["x"])))
        y = max(0.0, min(1.0, float(region["y"])))
        w = max(0.0, min(1.0 - x, float(region["w"])))
        h = max(0.0, min(1.0 - y, float(region["h"])))
    except (KeyError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    out = dict(region)
    out.update({"x": x, "y": y, "w": w, "h": h})
    if region.get("t_start") is not None and region.get("t_end") is not None:
        try:
            start = max(0.0, float(region["t_start"]))
            end = max(start, float(region["t_end"]))
        except (TypeError, ValueError):
            return None
        out.update({"t_start": start, "t_end": end})
    elif region.get("t_start") is not None:
        try:
            out["t_start"] = max(0.0, float(region["t_start"]))
        except (TypeError, ValueError):
            return None
    elif region.get("t_end") is not None:
        try:
            out["t_end"] = max(0.0, float(region["t_end"]))
        except (TypeError, ValueError):
            return None
    return out


def _union_blur_regions(a: dict, b: dict) -> dict:
    out = dict(a)
    x1 = min(float(a["x"]), float(b["x"]))
    y1 = min(float(a["y"]), float(b["y"]))
    x2 = max(float(a["x"]) + float(a["w"]),
             float(b["x"]) + float(b["w"]))
    y2 = max(float(a["y"]) + float(a["h"]),
             float(b["y"]) + float(b["h"]))
    out.update({"x": x1, "y": y1, "w": min(1.0 - x1, x2 - x1),
                "h": min(1.0 - y1, y2 - y1)})
    if a.get("t_start") is not None and b.get("t_start") is not None:
        out["t_start"] = min(float(a["t_start"]), float(b["t_start"]))
        out["t_end"] = max(float(a["t_end"]), float(b["t_end"]))
    if len(str(b.get("text", ""))) > len(str(a.get("text", ""))):
        out["text"] = b["text"]
    if "confidence" in a or "confidence" in b:
        out["confidence"] = max(float(a.get("confidence", 0)),
                                float(b.get("confidence", 0)))
    return out


def _union_geometry(a: dict, b: dict) -> tuple[float, float, float]:
    x1 = min(float(a["x"]), float(b["x"]))
    y1 = min(float(a["y"]), float(b["y"]))
    x2 = max(float(a["x"]) + float(a["w"]),
             float(b["x"]) + float(b["w"]))
    y2 = max(float(a["y"]) + float(a["h"]),
             float(b["y"]) + float(b["h"]))
    return x2 - x1, y2 - y1, (x2 - x1) * (y2 - y1)


def _can_merge_blur_regions(
    a: dict,
    b: dict,
    *,
    max_gap: float,
    iou_threshold: float,
) -> bool:
    if a.get("source") != b.get("source"):
        return False
    if _region_iou(a, b) < iou_threshold:
        return False
    if a.get("t_start") is not None and b.get("t_start") is not None:
        gap = float(b["t_start"]) - float(a["t_end"])
        if gap > max_gap:
            return False
    union_w, union_h, union_area = _union_geometry(a, b)
    max_w = max(float(a["w"]), float(b["w"]))
    max_h = max(float(a["h"]), float(b["h"]))
    max_area = max(float(a["w"]) * float(a["h"]),
                   float(b["w"]) * float(b["h"]))
    return (
        union_w <= max_w * 1.5
        and union_h <= max_h * 1.5
        and union_area <= max_area * 2.25
    )


def compact_blur_regions(
    blur_regions: list[dict] | None,
    *,
    max_regions: int = 24,
    max_gap: float = 1.5,
    iou_threshold: float = 0.45,
) -> list[dict]:
    """Bound OCR blur work without dropping manually selected regions."""
    normalized = []
    for region in blur_regions or []:
        item = _normalize_blur_region(region)
        if item is not None:
            normalized.append(item)

    merged: list[dict] = []
    for region in sorted(
        normalized,
        key=lambda r: (float(r.get("t_start", 0.0)), float(r["y"]), float(r["x"])),
    ):
        match = None
        for candidate in reversed(merged):
            if _can_merge_blur_regions(
                candidate,
                region,
                max_gap=max_gap,
                iou_threshold=iou_threshold,
            ):
                match = candidate
                break
            if (
                candidate.get("source") == region.get("source")
                and candidate.get("t_start") is not None
                and region.get("t_start") is not None
                and float(region["t_start"]) - float(candidate["t_end"]) > max_gap
            ):
                break
        if match is None:
            merged.append(dict(region))
        else:
            merged[merged.index(match)] = _union_blur_regions(match, region)

    if len(merged) <= max_regions:
        return merged

    manual = [r for r in merged if r.get("source") != "ocr"]
    ocr = [r for r in merged if r.get("source") == "ocr"]
    budget = max(1, max_regions - len(manual))
    while len(ocr) > budget:
        best_index = None
        best_score = None
        for i, left in enumerate(ocr):
            for j in range(i + 1, len(ocr)):
                right = ocr[j]
                if not _can_merge_blur_regions(
                    left,
                    right,
                    max_gap=max_gap,
                    iou_threshold=iou_threshold,
                ):
                    continue
                score = abs(
                    float(right.get("t_start", 0.0))
                    - float(left.get("t_end", left.get("t_start", 0.0)))
                )
                if best_score is None or score < best_score:
                    best_index, best_score = (i, j), score
        if best_index is None:
            break
        i, j = best_index
        ocr[i] = _union_blur_regions(ocr[i], ocr[j])
        del ocr[j]
    return manual + ocr


def mirror_blur_regions(blur_regions: list[dict] | None) -> list[dict]:
    """Return blur regions moved to their horizontal mirror positions."""
    mirrored = []
    for region in blur_regions or []:
        item = dict(region)
        try:
            item["x"] = round(
                max(0.0, min(1.0, 1.0 - float(region["x"]) - float(region["w"]))),
                6,
            )
        except (KeyError, TypeError, ValueError):
            pass
        mirrored.append(item)
    return mirrored


def build_filter_complex(
    blur_regions: list[dict] | None,
    video_w: int,
    video_h: int,
    srt_path: str | None = None,
    style: dict | None = None,
) -> str | None:
    """Dựng chuỗi ``-filter_complex``, hoặc None khi không cần lọc gì.

    Mỗi vùng che được cắt khỏi khung hình, làm mờ rồi dán trở lại đúng chỗ.
    Vùng có ``t_start``/``t_end`` chỉ được dán trong đúng khoảng đó. Phụ đề
    vẽ sau cùng nên luôn nằm trên vùng đã che. Chuỗi luôn kết ở ``[vout]``.
    """
    regions = compact_blur_regions(blur_regions)
    if not regions and not srt_path:
        return None

    parts: list[str] = []
    current = "0:v"

    if len(regions) > 4:
        # crop+boxblur evaluates a separate full filter chain per OCR box.
        # delogo is much cheaper for dense OCR regions and still smudges the
        # hardcoded text before subtitles are burned on top.
        for i, region in enumerate(regions):
            x, y, w, h = _to_pixels(region, video_w, video_h)
            x = max(1, min(x, video_w - 3))
            y = max(1, min(y, video_h - 3))
            w = max(2, min(w, video_w - x - 1))
            h = max(2, min(h, video_h - y - 1))
            filt = f"delogo=x={x}:y={y}:w={w}:h={h}:show=0"
            t_start, t_end = region.get("t_start"), region.get("t_end")
            if t_start is not None and t_end is not None:
                filt += f":enable='between(t,{float(t_start)},{float(t_end)})'"
            nxt = f"v{i + 1}"
            parts.append(f"[{current}]{filt}[{nxt}]")
            current = nxt
    else:
        for i, region in enumerate(regions):
            x, y, w, h = _to_pixels(region, video_w, video_h)
            base, blurred = f"b{i}", f"bl{i}"
            nxt = f"v{i + 1}"

            # Tách luồng để cùng một khung vừa làm nền dán vừa làm nguồn cắt.
            parts.append(f"[{current}]split[{base}][{base}c]")
            parts.append(
                f"[{base}c]crop={w}:{h}:{x}:{y},{blur_filter(w, h)}[{blurred}]"
            )

            overlay = f"overlay={x}:{y}"
            t_start, t_end = region.get("t_start"), region.get("t_end")
            if t_start is not None and t_end is not None:
                overlay += f":enable='between(t,{float(t_start)},{float(t_end)})'"
            parts.append(f"[{base}][{blurred}]{overlay}[{nxt}]")
            current = nxt

    if srt_path:
        # Tệp .ass đã mang sẵn kiểu chữ và hiệu ứng của từng dòng bên trong —
        # force_style sẽ đè mất, nên chỉ áp cho tệp .srt.
        subs = f"subtitles='{escape_subtitles_path(srt_path)}'"
        # Phông đi kèm ứng dụng (<app>/fonts): libass tra thư mục này TRƯỚC
        # phông hệ thống, nên phông người dùng thả vào fonts/ hiện đúng trên
        # mọi máy mà không cần cài vào Windows.
        from autodub.utils import bundled_font_files, fonts_dir
        if bundled_font_files():
            subs += f":fontsdir='{escape_subtitles_path(fonts_dir())}'"
        if not srt_path.lower().endswith(".ass"):
            subs += f":force_style='{build_force_style(style)}'"
        parts.append(f"[{current}]{subs}[vout]")
    else:
        # Không còn gì để vẽ — đặt tên đầu ra cho bước làm mờ cuối cùng.
        parts.append(f"[{current}]null[vout]")

    return ";".join(parts)
