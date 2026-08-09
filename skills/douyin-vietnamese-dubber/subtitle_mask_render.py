#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import subprocess
import textwrap
import statistics
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from PIL import Image, ImageFont
except Exception:  # pragma: no cover - runtime fallback when Pillow missing
    Image = None
    ImageFont = None

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - runtime fallback when cv2/numpy missing
    cv2 = None
    np = None

try:
    import nine_router_vision as _nrv
except Exception:
    _nrv = None

try:
    from fontTools.ttLib import TTFont as _TTFont
except Exception:  # pragma: no cover - fontTools optional, fallback PIL measure
    _TTFont = None


VI_SUBTITLE_GLYPH_PROBE = "Đặng Tiếng Việt: ă â ê ô ơ ư ế ệ ộ ử ỹ"
VI_SUBTITLE_GLYPH_CHARS = set(VI_SUBTITLE_GLYPH_PROBE) - {" ", ":"}


def ffprobe_dim(video: Path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(video)
    ], text=True).strip()
    w, h = out.split("x", 1)
    return int(w), int(h)

def ffprobe_duration(video: Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1", str(video)
        ], text=True).strip()
        return max(0.0, float(out))
    except Exception:
        return 0.0


def ass_escape_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

def ass_escape_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", r"\N")

def ass_alpha(opacity: float) -> str:
    opacity = max(0.0, min(1.0, opacity))
    alpha = int(round((1.0 - opacity) * 255))
    return f"{alpha:02X}"

def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default

def env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, str(default))))
    except Exception:
        return default

def enabled(value) -> bool:
    return str(value).lower() not in ("0", "false", "no", "off", "none")

def split_srt_blocks(text: str):
    return [block.strip() for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]

def parse_srt_events(source: Path):
    events = []
    for block in split_srt_blocks(source.read_text(encoding="utf-8", errors="replace")):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->", 1)]
        text = compact_text(lines[2:])
        if text:
            events.append({"start_raw": start_raw, "end_raw": end_raw, "text": text})
    return events

def compact_text(lines):
    return re.sub(r"\s+", " ", " ".join(line.strip() for line in lines if line.strip())).strip()

def srt_seconds(srt_time: str) -> float:
    hh, mm, rest = srt_time.strip().split(":")
    ss, ms = rest.split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0

def wrap_subtitle_text(text: str, max_chars: int, max_lines: int) -> str:
    """Wrap subtitle Việt: ưu tiên 1 dòng nếu text vừa; chỉ xuống dòng khi thật cần.

    Khác bản cũ (luôn wrap theo max_chars): bản này đo độ dài thật của text và chỉ
    tách 2 dòng khi VƯỢT max_chars, chia gần cân. Không co chữ quá nhỏ vì wrap không
    ép thêm dòng khi text đã nằm trong 1 dòng.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    max_lines = max(1, int(max_lines or 2))
    width = max(12, int(max_chars or 0))
    # Nếu không có max_chars hoặc text vừa trong 1 dòng -> giữ 1 dòng (chữ to nhất).
    if width <= 0 or len(text) <= width:
        return text
    # Quá dài: ưu tiên 2 dòng cân, cắt theo word-space tiếng Việt; không cắt giữa từ.
    if max_lines == 1:
        # Chỉ 1 dòng cho phép: rút gọn cuối, giữ font lớn thay vì xuống dòng nhỏ.
        room = max(8, width - 1)
        return textwrap.shorten(text, width=room, placeholder="…")
    half = max(1, width // 2)
    first = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    if len(first) <= max_lines:
        return "\n".join(first)
    # Cố gói vừa 2 dòng: chia gần cân tại điểm space gần giữa câu.
    words = text.split(" ")
    if len(words) >= 2:
        # Tìm điểm cắt sao cho dòng 1 <= width và dòng 2 <= width (nếu được).
        for cut in range(1, len(words)):
            line1 = " ".join(words[:cut])
            line2 = " ".join(words[cut:])
            if len(line1) <= width and len(line2) <= width:
                return line1 + "\n" + line2
        # Không tìm được điểm cắt gọn cả 2 dòng -> chia gần giữa rồi rút gọn dòng dài.
        mid = max(1, len(words) // 2)
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])
        if len(line1) > width:
            line1 = textwrap.shorten(line1, width=max(8, width - 1), placeholder="…")
        if len(line2) > width:
            line2 = textwrap.shorten(line2, width=max(8, width - 1), placeholder="…")
        return line1 + "\n" + line2
    return textwrap.shorten(text, width=max(8, width - 1), placeholder="…")

def write_wrapped_srt(source: Path, target: Path, max_chars: int, max_lines: int) -> int:
    blocks = split_srt_blocks(source.read_text(encoding="utf-8", errors="replace"))
    out = []
    count = 0
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        count += 1
        out.append(str(count))
        out.append(lines[1])
        wrapped = wrap_subtitle_text(compact_text(lines[2:]), max_chars=max_chars, max_lines=max_lines)
        if wrapped:
            out.extend(wrapped.splitlines())
        out.append("")
    target.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return count

def ass_time(srt_time: str) -> str:
    hh, mm, rest = srt_time.strip().split(":")
    ss, ms = rest.split(",")
    cs = int(round(int(ms) / 10.0))
    if cs >= 100:
        cs = 99
    return f"{int(hh)}:{int(mm):02d}:{int(ss):02d}.{cs:02d}"

def ffmpeg_filter_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")

def ass_colour(name: str) -> str:
    raw = (name or "white").strip()
    value = raw.lower()
    colours = {
        "white": "&H00FFFFFF",
        "yellow": "&H0000FFFF",
        "gold": "&H0000D7FF",
        "cyan": "&H00FFFF00",
    }
    if re.match(r"^&H[0-9A-Fa-f]{8}$", raw):
        return raw.upper()
    if re.match(r"^#[0-9A-Fa-f]{6}$", raw):
        rr, gg, bb = raw[1:3], raw[3:5], raw[5:7]
        return f"&H00{bb}{gg}{rr}".upper()
    return colours.get(value, colours["white"])

def _system_font_candidates() -> list:
    return [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def _font_dir_candidates(font_dir: str) -> list:
    base = Path(font_dir) if font_dir else Path("/home/haonguyen/.openclaw/assets/fonts")
    return [
        base / "BeVietnamPro-SemiBold.ttf",
        base / "BeVietnamPro-Bold.ttf",
        base / "NotoSans-Bold.ttf",
        base / "NotoSans-SemiBold.ttf",
        base / "NotoSans-Regular.ttf",
        base / "OpenSans-SemiBold.ttf",
        base / "OpenSans-Bold.ttf",
        base / "OpenSans-Regular.ttf",
        base / "WorkSans-SemiBold.ttf",
        base / "WorkSans-Bold.ttf",
    ]


def _tt_cmap_chars(path: Path) -> set:
    if _TTFont is None:
        return set()
    try:
        font = _TTFont(str(path), fontNumber=0, lazy=True)
        cmap = font.getBestCmap()
        chars = {chr(code) for code in (cmap.keys() if cmap else [])}
        font.close()
        return chars
    except Exception:
        return set()


def font_has_vietnamese_glyphs(path: Path) -> tuple:
    """Trả (ok: bool, missing: list, method: str)."""
    if not path or not path.exists():
        return False, list(VI_SUBTITLE_GLYPH_CHARS), "missing_file"
    needed = set(VI_SUBTITLE_GLYPH_CHARS)
    if _TTFont is not None:
        cmap = _tt_cmap_chars(path)
        if cmap:
            missing = sorted(ch for ch in needed if ch not in cmap)
            return (len(missing) == 0, missing, "fonttools_cmap")
    # Fallback PIL measure: glyph có width>0 xem như có mặt.
    if Image is None:
        return True, [], "no_measure_assume_ok"
    try:
        face = ImageFont.truetype(str(path), 64)
    except Exception as exc:
        return False, sorted(needed), f"pil_load_failed:{exc!r}"[:120]
    missing = []
    for ch in needed:
        try:
            mask = face.getmask(ch)
            if mask is None or mask.size[0] == 0 or mask.size[1] == 0:
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return (len(missing) == 0, missing, "pil_measure")


def _resolve_font_by_name(name: str, font_dir: str) -> Path:
    if not name:
        return None
    # Accept file path-like names.
    p = Path(name)
    if p.exists() and p.is_file():
        return p
    lower = name.lower().strip()
    # Strip common extension if provided.
    for ext in (".ttf", ".otf"):
        if lower.endswith(ext):
            lower = lower[: -len(ext)]
    name_map = {
        "bevietnampro-semibold": "BeVietnamPro-SemiBold.ttf",
        "bevietnampro-bold": "BeVietnamPro-Bold.ttf",
        "bevietnampro": "BeVietnamPro-Bold.ttf",
        "notosans-bold": "NotoSans-Bold.ttf",
        "notosans-semibold": "NotoSans-SemiBold.ttf",
        "notosans": "NotoSans-Bold.ttf",
        "opensans-semibold": "OpenSans-SemiBold.ttf",
        "opensans-bold": "OpenSans-Bold.ttf",
        "opensans": "OpenSans-Bold.ttf",
        "worksans-semibold": "WorkSans-SemiBold.ttf",
        "worksans-bold": "WorkSans-Bold.ttf",
        "worksans": "WorkSans-Bold.ttf",
    }
    target = name_map.get(lower)
    base = Path(font_dir) if font_dir else Path("/home/haonguyen/.openclaw/assets/fonts")
    if target:
        candidate = base / target
        if candidate.exists():
            return candidate
    # Try fuzzy match inside font dir.
    if base.exists():
        for f in base.glob("*.ttf"):
            stem = f.stem.lower().replace(" ", "")
            if lower in stem or stem.startswith(lower):
                return f
    return None


def resolve_vi_subtitle_font(explicit_file: str, preset: str, name: str, font_dir: str, legacy_font: str) -> dict:
    """Trả dict: path, font_name (libass fn), fontsdir, source, glyph_ok, glyph_missing, method, tried[], skipped[]."""
    tried = []
    skipped = []
    candidates = []
    if explicit_file:
        candidates.append(("explicit", Path(explicit_file)))
    if preset or name:
        resolved = _resolve_font_by_name(preset or name, font_dir)
        if resolved:
            candidates.append(("preset_name", resolved))
    candidates.extend([("font_dir", p) for p in _font_dir_candidates(font_dir)])
    if legacy_font:
        candidates.append(("legacy", Path(legacy_font)))
    candidates.extend([("system", Path(p)) for p in _system_font_candidates()])

    chosen = None
    for source, path in candidates:
        if not path or str(path) in tried:
            continue
        tried.append(str(path))
        if not path.exists():
            skipped.append({"path": str(path), "source": source, "reason": "missing"})
            continue
        ok, missing, method = font_has_vietnamese_glyphs(path)
        if ok:
            chosen = {"path": path, "source": source, "glyph_ok": True, "glyph_missing": [], "method": method}
            break
        skipped.append({"path": str(path), "source": source, "reason": f"missing_glyphs:{','.join(missing)}", "missing": missing})

    if chosen is None:
        # Last resort: first existing system font even if glyph check failed (render something).
        for source, path in candidates:
            if path and path.exists():
                ok, missing, method = font_has_vietnamese_glyphs(path)
                chosen = {"path": path, "source": f"{source}_last_resort", "glyph_ok": ok, "glyph_missing": missing, "method": method}
                break
    if chosen is None:
        chosen = {"path": None, "source": "none", "glyph_ok": False, "glyph_missing": sorted(VI_SUBTITLE_GLYPH_CHARS), "method": "no_font_found"}
    path = chosen["path"]
    font_name = path.stem if path else "Noto Sans"
    fontsdir = str(path.parent) if path and path.exists() else ""
    return {
        "path": str(path) if path else "",
        "font_name": font_name,
        "fontsdir": fontsdir,
        "source": chosen["source"],
        "glyph_ok": chosen["glyph_ok"],
        "glyph_missing": chosen["glyph_missing"],
        "method": chosen["method"],
        "tried": tried,
        "skipped": skipped,
    }


def _pil_font(path: Path, size: int):
    if Image is None or not path or not Path(path).exists():
        return None
    try:
        return ImageFont.truetype(str(path), max(6, int(size)))
    except Exception:
        return None


def measure_text_width(path: Path, size: int, text: str) -> int:
    """Trả width pixel của text ở size cho trước. Fallback estimate khi PIL/font thiếu."""
    face = _pil_font(path, size)
    if face is None:
        # Estimate: ~0.55 * size per char (Latin/Việt combining).
        return int(len(text) * size * 0.55)
    try:
        if hasattr(face, "getlength"):
            return int(face.getlength(text))
    except Exception:
        pass
    try:
        bbox = face.getbbox(text)
        if bbox:
            return max(0, int(bbox[2] - bbox[0]))
    except Exception:
        pass
    try:
        return int(face.getmask(text).size[0])
    except Exception:
        return int(len(text) * size * 0.55)


def measure_line_height(path: Path, size: int) -> int:
    face = _pil_font(path, size)
    if face is None:
        return int(size * 1.25)
    try:
        ascent, descent = face.getmetrics()
        return int(ascent + descent)
    except Exception:
        return int(size * 1.25)


def fit_vi_subtitle_text(text, band_box, video_w, video_h, font_path, options) -> dict:
    """Chọn font size + wrap 1/2 dòng sao cho vừa safe width/height và gần target fill nhất.

    options: {
      min_size, max_size, target_band_fill, safe_width_ratio, safe_height_ratio,
      max_lines, vertical_offset_ratio,
    }
    Trả dict: lines[], font_size, text_width, text_height, fill_ratio, status, reason.
    band_box: {x,y,w,h} hoặc None (khi none/MASK=0 -> dùng bottom-safe box).
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return {"lines": [], "font_size": 0, "text_width": 0, "text_height": 0, "fill_ratio": 0.0, "status": "empty", "reason": "empty_text"}

    min_size = max(8, int(options.get("min_size") or 48))
    max_size = max(min_size, int(options.get("max_size") or 62))
    target_fill = float(options.get("target_band_fill") or 0.70)
    safe_w_ratio = float(options.get("safe_width_ratio") or 0.88)
    safe_h_ratio = float(options.get("safe_height_ratio") or 0.72)
    max_lines = max(1, min(int(options.get("max_lines") or 2), 2))

    if band_box and band_box.get("w") and band_box.get("h"):
        band_w = int(band_box["w"])
        band_h = int(band_box["h"])
    else:
        # Bottom-safe full-width text box.
        band_w = int(video_w)
        band_h = int(video_h * 0.12)

    safe_w = max(20, int(band_w * safe_w_ratio))
    safe_h = max(20, int(band_h * safe_h_ratio))

    def split_words(t):
        return [w for w in re.split(r"\s+", t) if w]

    def try_wrap(size: int, lines_cap: int):
        """Trả (lines[], width, height) hoặc None nếu không vừa safe."""
        # 1 dòng.
        one_w = measure_text_width(font_path, size, text)
        one_h = measure_line_height(font_path, size)
        if one_w <= safe_w and one_h <= safe_h:
            return [text], one_w, one_h
        if lines_cap <= 1:
            return None
        # Wrap 2 dòng cân theo word-space; không cắt giữa từ.
        words = split_words(text)
        if len(words) < 2:
            return None
        best = None
        for cut in range(1, len(words)):
            l1 = " ".join(words[:cut])
            l2 = " ".join(words[cut:])
            w1 = measure_text_width(font_path, size, l1)
            w2 = measure_text_width(font_path, size, l2)
            w = max(w1, w2)
            h = measure_line_height(font_path, size) * 2 * 1.05
            if w <= safe_w and h <= safe_h:
                # Cân: prefer |len(l1)-len(l2)| nhỏ.
                balance = abs(len(l1) - len(l2))
                if best is None or balance < best[0]:
                    best = (balance, [l1, l2], w, h)
        if best is not None:
            return best[1], best[2], best[3]
        return None

    chosen = None
    # Ưu tiên 1 dòng: thử size từ max xuống min, chọn size lớn nhất vừa 1 dòng.
    for size in range(max_size, min_size - 1, -1):
        result = try_wrap(size, max_lines)
        if result is None:
            continue
        lines, w, h = result
        # fill = mức chiếm band: max của width-fill và height-fill, để cue ngắn
        # (font to trên band hẹp) không bị đánh giá "fill thấp" sai.
        fill = max(w / float(max(1, band_w)), h / float(max(1, band_h)))
        # Ưu tiên 1 dòng nếu fit; nếu 2 dòng thì vẫn chấp nhận.
        is_one_line = len(lines) == 1
        score = (1 if is_one_line else 0, size, -abs(fill - target_fill))
        if chosen is None or score > chosen[0]:
            chosen = (score, lines, size, w, h, fill)
    if chosen is not None:
        _, lines, size, w, h, fill = chosen
        status = "ok"
        reason = f"fit_{'1' if len(lines)==1 else '2'}line"
        return {"lines": lines, "font_size": size, "text_width": int(w), "text_height": int(h), "fill_ratio": round(fill, 4), "status": status, "reason": reason}

    # Không fit: lấy size min, wrap 2 dòng rút gọn (placeholder ellipsis) để vẫn render.
    size = min_size
    words = split_words(text)
    if len(words) >= 2 and max_lines >= 2:
        mid = max(1, len(words) // 2)
        l1 = " ".join(words[:mid])
        l2 = " ".join(words[mid:])
    else:
        l1 = text
        l2 = ""
    lines = [l1] + ([l2] if l2 else [])
    w = max(measure_text_width(font_path, size, l1), measure_text_width(font_path, size, l2) if l2 else 0)
    h = measure_line_height(font_path, size) * (len(lines)) * 1.05
    fill = max(w / float(max(1, band_w)), h / float(max(1, band_h)))
    return {"lines": lines, "font_size": size, "text_width": int(w), "text_height": int(h), "fill_ratio": round(fill, 4), "status": "overflow", "reason": "no_fit_used_min_size"}


def extract_frame(input_video: Path, timestamp: float, target: Path) -> bool:
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{max(0.0, timestamp):.3f}", "-i", str(input_video),
                "-frames:v", "1", str(target),
            ],
            check=True,
        )
        return target.exists() and target.stat().st_size > 0
    except Exception:
        return False

def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))

def is_subtitle_like_pixel(rgb, args) -> bool:
    r, g, b = rgb
    lum = (r * 299 + g * 587 + b * 114) // 1000
    spread = max(r, g, b) - min(r, g, b)
    return lum >= args.detect_luma_threshold and spread <= args.detect_max_rgb_spread

def merge_boxes(boxes):
    min_x = min(box["x"] for box in boxes)
    min_y = min(box["y"] for box in boxes)
    max_x = max(box["x"] + box["w"] for box in boxes)
    max_y = max(box["y"] + box["h"] for box in boxes)
    return {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y}

def box_to_bbox(box):
    return [int(box["x"]), int(box["y"]), int(box["x"] + box["w"]), int(box["y"] + box["h"])]

def bbox_to_box(bbox):
    x1, y1, x2, y2 = [int(v) for v in bbox]
    return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}

def clamp_box(box, width: int, height: int):
    x1 = clamp_int(box["x"], 0, max(0, width - 1))
    y1 = clamp_int(box["y"], 0, max(0, height - 1))
    x2 = clamp_int(box["x"] + box["w"], x1 + 1, width)
    y2 = clamp_int(box["y"] + box["h"], y1 + 1, height)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}

def time_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))

def event_time(event):
    return srt_seconds(event["start_raw"]), srt_seconds(event["end_raw"])

def source_pad_values(width: int, height: int, args):
    pad_x = args.source_pad_x if args.source_pad_x >= 0 else int(width * args.dynamic_mask_pad_x_ratio)
    pad_y = args.source_pad_y if args.source_pad_y >= 0 else int(height * args.dynamic_mask_pad_y_ratio)
    return max(0, int(pad_x)), max(0, int(pad_y))

def pad_source_box(box, width: int, height: int, args):
    pad_x, pad_y = source_pad_values(width, height, args)
    wide_threshold = int(width * args.source_wide_width_ratio)
    raw_w = int(box["w"])
    if raw_w >= wide_threshold:
        pad_x = max(pad_x, int(width * 0.06))
    x1 = box["x"] - pad_x
    y1 = box["y"] - pad_y
    x2 = box["x"] + box["w"] + pad_x
    y2 = box["y"] + box["h"] + pad_y
    if raw_w >= wide_threshold:
        safe_margin = max(0, int(width * (1.0 - args.detect_max_width_ratio) / 2.0))
        x1 = min(x1, safe_margin)
        x2 = max(x2, width - safe_margin)
    return clamp_box({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}, width, height)

def ass_seconds(timestamp: float) -> str:
    timestamp = max(0.0, float(timestamp))
    hh = int(timestamp // 3600)
    timestamp -= hh * 3600
    mm = int(timestamp // 60)
    timestamp -= mm * 60
    ss = int(timestamp)
    cs = int(round((timestamp - ss) * 100))
    if cs >= 100:
        ss += 1
        cs = 0
    return f"{hh}:{mm:02d}:{ss:02d}.{cs:02d}"

def rounded_rect_ass_path(box, radius: int) -> str:
    x = int(box["x"])
    y = int(box["y"])
    w = int(box["w"])
    h = int(box["h"])
    r = clamp_int(radius, 0, max(0, min(w // 2, h // 2)))
    x2 = x + w
    y2 = y + h
    if r <= 0:
        return f"m {x} {y} l {x2} {y} l {x2} {y2} l {x} {y2} l {x} {y}"
    # Cubic bezier approximation with ASS drawing coordinates.
    k = max(1, int(round(r * 0.55228475)))
    return " ".join([
        f"m {x + r} {y}",
        f"l {x2 - r} {y}",
        f"b {x2 - r + k} {y} {x2} {y + r - k} {x2} {y + r}",
        f"l {x2} {y2 - r}",
        f"b {x2} {y2 - r + k} {x2 - r + k} {y2} {x2 - r} {y2}",
        f"l {x + r} {y2}",
        f"b {x + r - k} {y2} {x} {y2 - r + k} {x} {y2 - r}",
        f"l {x} {y + r}",
        f"b {x} {y + r - k} {x + r - k} {y} {x + r} {y}",
    ])

def write_mask_ass(target: Path, width: int, height: int, mask_segments, args, colour="black", opacity=None) -> int:
    alpha = ass_alpha(args.mask_alpha if opacity is None else opacity)
    colour_value = "FFFFFF" if str(colour).lower() == "white" else "000000"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Mask,Arial,20,&H{alpha}{colour_value},&H{alpha}{colour_value},&H{alpha}{colour_value},&H{alpha}{colour_value},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for segment in mask_segments:
        if float(segment.get("end", 0.0)) <= float(segment.get("start", 0.0)):
            continue
        radius = min(int(args.mask_radius), int(segment.get("w", 1)) // 2, int(segment.get("h", 1)) // 2)
        path = rounded_rect_ass_path(segment, radius)
        lines.append(
            f"Dialogue: 0,{ass_seconds(segment['start'])},{ass_seconds(segment['end'])},Mask,,0,0,0,,"
            f"{{\\p1\\bord0\\shad0\\alpha&H{alpha}&\\1c&H{colour_value}&}}{path}{{\\p0}}"
        )
    target.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)

def detect_connected_text_box(image_path: Path, width: int, height: int, args):
    if Image is None:
        return None
    try:
        image = Image.open(image_path).convert("RGB")
    except Exception:
        return None
    crop_top = max(0, min(height - 1, int(height * args.detect_region_top_ratio)))
    crop_bottom = max(crop_top + 1, min(height, int(height * args.detect_region_bottom_ratio)))
    step = max(1, env_int("SUBTITLE_DETECT_PIXEL_STEP", 2))
    bright = set()
    for y in range(crop_top, crop_bottom, step):
        for x in range(0, width, step):
            if is_subtitle_like_pixel(image.getpixel((x, y)), args):
                bright.add((x, y))
    if len(bright) < args.detect_min_pixels:
        return None

    visited = set()
    components = []
    neighbors = [
        (-step, -step), (0, -step), (step, -step),
        (-step, 0),                 (step, 0),
        (-step, step),  (0, step),  (step, step),
    ]
    min_component_pixels = max(3, env_int("SUBTITLE_COMPONENT_MIN_PIXELS", 4))
    max_component_w = max(12, int(width * env_float("SUBTITLE_COMPONENT_MAX_WIDTH_RATIO", 0.18)))
    max_component_h = max(8, int(height * env_float("SUBTITLE_COMPONENT_MAX_HEIGHT_RATIO", 0.09)))
    for point in bright:
        if point in visited:
            continue
        queue = deque([point])
        visited.add(point)
        count = 0
        min_x = max_x = point[0]
        min_y = max_y = point[1]
        while queue:
            x, y = queue.popleft()
            count += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for dx, dy in neighbors:
                neighbor = (x + dx, y + dy)
                if neighbor in bright and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        comp_w = max_x - min_x + step
        comp_h = max_y - min_y + step
        if count < min_component_pixels:
            continue
        if comp_w > max_component_w and comp_w > int(width * args.detect_max_width_ratio):
            continue
        if comp_h > max_component_h:
            continue
        if comp_w < 2 or comp_h < 2:
            continue
        density = count / max(1, (comp_w / step) * (comp_h / step))
        if density < env_float("SUBTITLE_COMPONENT_MIN_DENSITY", 0.10):
            continue
        components.append({"x": min_x, "y": min_y, "w": comp_w, "h": comp_h, "pixels": count})

    if not components:
        return None

    line_tolerance = max(8, int(height * env_float("SUBTITLE_LINE_CLUSTER_TOLERANCE_RATIO", 0.035)))
    best_line = []
    best_score = -1
    for seed in components:
        seed_center = seed["y"] + seed["h"] / 2
        line = [
            comp for comp in components
            if abs((comp["y"] + comp["h"] / 2) - seed_center) <= line_tolerance
        ]
        if not line:
            continue
        merged = merge_boxes(line)
        bottom_weight = 20 if getattr(args, "detect_prefer_bottom", False) else 0.01
        score = sum(comp["pixels"] for comp in line) + len(line) * 8 + int(merged["y"] * bottom_weight)
        if score > best_score:
            best_line = line
            best_score = score

    if not best_line:
        return None

    raw = merge_boxes(best_line)
    pad_x = max(4, int(width * args.dynamic_mask_pad_x_ratio))
    pad_y = max(4, int(height * args.dynamic_mask_pad_y_ratio))
    x1 = max(0, raw["x"] - pad_x)
    y1 = max(0, raw["y"] - pad_y)
    x2 = min(width, raw["x"] + raw["w"] + pad_x)
    y2 = min(height, raw["y"] + raw["h"] + pad_y)
    box = {
        "x": x1,
        "y": y1,
        "w": x2 - x1,
        "h": y2 - y1,
        "bright_count": sum(comp["pixels"] for comp in best_line),
        "components": len(best_line),
    }
    if box["w"] < int(width * args.detect_min_width_ratio) or box["h"] < int(height * args.detect_min_height_ratio):
        return None
    if box["w"] > int(width * args.detect_max_width_ratio) or box["h"] > int(height * args.detect_max_height_ratio):
        return None
    min_mask_w = int(width * args.dynamic_mask_min_width_ratio)
    if box["w"] < min_mask_w:
        center = box["x"] + box["w"] // 2
        box["x"] = max(0, min(width - min_mask_w, center - min_mask_w // 2))
        box["w"] = min_mask_w
    return box

def detect_cv2_text_box(image_path: Path, width: int, height: int, args):
    if cv2 is None or np is None:
        return None
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        return None
    crop_top = max(0, min(height - 1, int(height * args.detect_region_top_ratio)))
    crop_bottom = max(crop_top + 1, min(height, int(height * args.detect_region_bottom_ratio)))
    roi = image[crop_top:crop_bottom, 0:width]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    max_channel = roi.max(axis=2)
    min_channel = roi.min(axis=2)
    spread = max_channel - min_channel
    mask = ((gray >= args.detect_luma_threshold) & (spread <= args.detect_max_rgb_spread)).astype("uint8") * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    components = []
    min_component_pixels = max(3, env_int("SUBTITLE_COMPONENT_MIN_PIXELS", 4))
    max_component_w = max(12, int(width * env_float("SUBTITLE_COMPONENT_MAX_WIDTH_RATIO", 0.18)))
    max_component_h = max(8, int(height * env_float("SUBTITLE_COMPONENT_MAX_HEIGHT_RATIO", 0.09)))
    for label in range(1, count):
        x, y, w, h, area = [int(v) for v in stats[label]]
        if area < min_component_pixels or w < 2 or h < 2:
            continue
        if w > max_component_w and w > int(width * args.detect_max_width_ratio):
            continue
        if h > max_component_h:
            continue
        density = area / max(1, w * h)
        if density < env_float("SUBTITLE_COMPONENT_MIN_DENSITY", 0.10):
            continue
        components.append({"x": x, "y": y + crop_top, "w": w, "h": h, "pixels": area})
    if not components:
        return None
    line_tolerance = max(8, int(height * env_float("SUBTITLE_LINE_CLUSTER_TOLERANCE_RATIO", 0.035)))
    best_line = []
    best_score = -1
    for seed in components:
        seed_center = seed["y"] + seed["h"] / 2
        line = [comp for comp in components if abs((comp["y"] + comp["h"] / 2) - seed_center) <= line_tolerance]
        merged = merge_boxes(line) if line else None
        if not merged:
            continue
        bottom_weight = 20 if getattr(args, "detect_prefer_bottom", False) else 0.01
        score = sum(comp["pixels"] for comp in line) + len(line) * 8 + int(merged["y"] * bottom_weight)
        if score > best_score:
            best_line = line
            best_score = score
    if not best_line:
        return None
    box = merge_boxes(best_line)
    box["bright_count"] = sum(comp["pixels"] for comp in best_line)
    box["components"] = len(best_line)
    if box["w"] < int(width * args.detect_min_width_ratio) or box["h"] < int(height * args.detect_min_height_ratio):
        return None
    if box["w"] > int(width * args.detect_max_width_ratio) or box["h"] > int(height * args.detect_max_height_ratio):
        return None
    return clamp_box(box, width, height)

def detect_source_text_box(image_path: Path, width: int, height: int, args):
    box = detect_cv2_text_box(image_path, width, height, args)
    if box:
        box["method"] = "cv2"
        return box
    box = detect_connected_text_box(image_path, width, height, args)
    if box:
        box["method"] = "pillow"
        return box
    return None

def should_try_ocr(segment, width: int, height: int, args) -> bool:
    if not enabled(args.ocr_fallback):
        return False
    if args.source_detect_mode == "ocr":
        return True
    if args.source_detect_mode != "auto":
        return False
    bbox = segment.get("bbox") or [0, 0, 0, 0]
    box_w = max(0, int(bbox[2]) - int(bbox[0]))
    box_h = max(0, int(bbox[3]) - int(bbox[1]))
    duration = float(segment.get("end", 0.0)) - float(segment.get("start", 0.0))
    samples = segment.get("samples") or []
    jitter = 0.0
    if len(samples) >= 2:
        centers = [((s["bbox"][0] + s["bbox"][2]) / 2.0, (s["bbox"][1] + s["bbox"][3]) / 2.0) for s in samples if s.get("bbox")]
        if len(centers) >= 2:
            xs, ys = zip(*centers)
            jitter = (max(xs) - min(xs)) + (max(ys) - min(ys))
    return (
        float(segment.get("confidence", 0.0)) < args.source_track_min_confidence
        or duration < 0.25
        or box_w < width * 0.18
        or box_h < height * 0.012
        or jitter > width * 0.08
        or args.source_detect_mode == "ocr"
    )

def paddleocr_available():
    try:
        from paddleocr import PaddleOCR  # noqa: F401
        return True
    except Exception:
        return False

def create_paddle_ocr(args):
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import PaddleOCR
    attempts = [
        {"lang": args.ocr_lang, "use_textline_orientation": False},
        {"lang": args.ocr_lang, "use_angle_cls": False},
        {"lang": args.ocr_lang},
    ]
    errors = []
    for kwargs in attempts:
        try:
            return PaddleOCR(**kwargs), kwargs
        except Exception as exc:
            errors.append(f"{kwargs}: {exc!r}")
    raise RuntimeError("PaddleOCR init failed: " + " | ".join(errors))

def paddle_ocr_image(ocr, image_path: Path):
    if hasattr(ocr, "predict"):
        try:
            return ocr.predict(str(image_path))
        except Exception:
            pass
    try:
        return ocr.ocr(str(image_path), cls=False)
    except TypeError:
        return ocr.ocr(str(image_path))

def collect_ocr_boxes(result, min_confidence: float, offset_y: int):
    boxes = []
    confidences = []
    for page in result or []:
        if isinstance(page, dict):
            rec_boxes = page.get("rec_boxes")
            if rec_boxes is None:
                rec_boxes = page.get("dt_boxes")
            if rec_boxes is None:
                rec_boxes = []
            rec_scores = page.get("rec_scores")
            if rec_scores is None:
                rec_scores = page.get("scores")
            if rec_scores is None:
                rec_scores = []
            for index, raw_box in enumerate(rec_boxes):
                confidence = float(rec_scores[index]) if index < len(rec_scores) else 1.0
                if confidence < min_confidence:
                    continue
                values = raw_box.tolist() if hasattr(raw_box, "tolist") else raw_box
                if len(values) == 4 and not isinstance(values[0], (list, tuple)):
                    x1, y1, x2, y2 = [float(value) for value in values]
                    boxes.append({"x": int(x1), "y": int(y1 + offset_y), "w": int(x2 - x1), "h": int(y2 - y1)})
                    confidences.append(confidence)
            rec_polys = page.get("rec_polys")
            if rec_polys is None:
                rec_polys = page.get("dt_polys")
            if rec_polys is None:
                rec_polys = []
            for index, poly in enumerate(rec_polys):
                confidence = float(rec_scores[index]) if index < len(rec_scores) else 1.0
                if confidence < min_confidence:
                    continue
                points = poly.tolist() if hasattr(poly, "tolist") else poly
                if not points:
                    continue
                xs = [float(point[0]) for point in points]
                ys = [float(point[1]) + offset_y for point in points]
                boxes.append({"x": int(min(xs)), "y": int(min(ys)), "w": int(max(xs) - min(xs)), "h": int(max(ys) - min(ys))})
                confidences.append(confidence)
            continue
        for item in page or []:
            if not item or len(item) < 2:
                continue
            points = item[0]
            meta = item[1]
            confidence = float(meta[1]) if isinstance(meta, (list, tuple)) and len(meta) > 1 else 0.0
            if confidence < min_confidence:
                continue
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) + offset_y for point in points]
            boxes.append({"x": int(min(xs)), "y": int(min(ys)), "w": int(max(xs) - min(xs)), "h": int(max(ys) - min(ys))})
            confidences.append(confidence)
    return boxes, confidences

def run_paddleocr_on_image(image_path: Path, width: int, height: int, args):
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:
        return None, f"paddleocr_missing: {exc}"
    if Image is None:
        return None, "pillow_missing_for_roi_crop"
    try:
        image = Image.open(image_path).convert("RGB")
        offset_y = 0
        ocr_input = image_path
        temp_path = None
        if enabled(args.ocr_roi_only):
            crop_top = max(0, min(height - 1, int(height * args.detect_region_top_ratio)))
            crop_bottom = max(crop_top + 1, min(height, int(height * args.detect_region_bottom_ratio)))
            roi = image.crop((0, crop_top, width, crop_bottom))
            temp_path = image_path.with_suffix(".ocr_roi.jpg")
            roi.save(temp_path, quality=92)
            ocr_input = temp_path
            offset_y = crop_top
        ocr, _ = create_paddle_ocr(args)
        result = paddle_ocr_image(ocr, ocr_input)
        raw_boxes, confidences = collect_ocr_boxes(result, args.ocr_min_confidence, offset_y)
        boxes = [clamp_box(box, width, height) for box in raw_boxes if box["w"] > 2 and box["h"] > 2]
        if temp_path:
            try:
                temp_path.unlink()
            except Exception:
                pass
        if not boxes:
            return None, "paddleocr_no_boxes"
        merged = merge_boxes(boxes)
        return {
            "bbox": box_to_bbox(clamp_box(merged, width, height)),
            "confidence": sum(confidences) / max(1, len(confidences)),
            "engine": "paddleocr",
            "boxes": len(boxes),
        }, None
    except Exception as exc:
        return None, f"paddleocr_error: {exc}"

def refine_segments_with_ocr(input_video: Path, segments, width: int, height: int, args):
    if not enabled(args.ocr_fallback) or args.source_detect_mode == "cv":
        return segments, {"fallback_segments": 0, "skipped_segments": len(segments), "reason": "disabled_or_cv_mode"}
    if args.ocr_engine != "paddleocr":
        return segments, {"fallback_segments": 0, "skipped_segments": len(segments), "reason": f"unsupported_engine:{args.ocr_engine}"}
    if not paddleocr_available():
        print("WARN: PaddleOCR chưa khả dụng; bỏ OCR fallback và dùng CV source track.")
        return segments, {"fallback_segments": 0, "skipped_segments": len(segments), "reason": "paddleocr_missing"}
    refined = []
    fallback_count = 0
    skipped_count = 0
    with TemporaryDirectory(prefix="openclaw-sub-ocr-") as tmp:
        tmp_dir = Path(tmp)
        for index, segment in enumerate(segments, 1):
            current = dict(segment)
            if not should_try_ocr(current, width, height, args):
                current["detect_mode"] = args.source_detect_mode
                skipped_count += 1
                refined.append(current)
                continue
            timestamp = (float(current["start"]) + float(current["end"])) / 2.0
            frame_path = tmp_dir / f"ocr-{index:04d}.jpg"
            if not extract_frame(input_video, timestamp, frame_path):
                skipped_count += 1
                refined.append(current)
                continue
            ocr, error = run_paddleocr_on_image(frame_path, width, height, args)
            if not ocr:
                current["ocr_error"] = error
                current["detect_mode"] = args.source_detect_mode
                skipped_count += 1
                refined.append(current)
                continue
            current["cv_bbox"] = current.get("bbox")
            current["ocr_bbox"] = ocr["bbox"]
            current["ocr_confidence"] = round(float(ocr["confidence"]), 3)
            current["ocr_engine"] = ocr["engine"]
            current["bbox"] = ocr["bbox"]
            current["confidence"] = round(max(float(current.get("confidence", 0.0)), float(ocr["confidence"])), 3)
            current["method"] = f"{current.get('method', 'cv')}+ocr_fallback"
            current["detect_mode"] = args.source_detect_mode
            fallback_count += 1
            refined.append(current)
    return refined, {"fallback_segments": fallback_count, "skipped_segments": skipped_count, "reason": "ok"}

def detect_ocr_subtitle_track(input_video: Path, width: int, height: int, args):
    if args.ocr_engine != "paddleocr" or not enabled(args.ocr_fallback):
        return [], {"fallback_segments": 0, "skipped_segments": 0, "reason": "ocr_disabled"}
    if not paddleocr_available():
        print("WARN: PaddleOCR chưa khả dụng; không thể chạy OCR source track, fallback CV nếu có.")
        return [], {"fallback_segments": 0, "skipped_segments": 0, "reason": "paddleocr_missing"}
    fps = max(0.2, float(args.ocr_fps))
    frame_duration = 1.0 / fps
    raw_segments = []
    active = None
    skipped = 0
    with TemporaryDirectory(prefix="openclaw-ocr-sub-track-") as tmp:
        tmp_dir = Path(tmp)
        pattern = tmp_dir / "ocr-frame-%06d.jpg"
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(input_video), "-vf", f"fps={fps}", "-q:v", "3", str(pattern),
            ],
            check=True,
        )
        for frame_index, frame_path in enumerate(sorted(tmp_dir.glob("ocr-frame-*.jpg"))):
            timestamp = frame_index / fps
            ocr, error = run_paddleocr_on_image(frame_path, width, height, args)
            if ocr:
                sample = {"time": round(timestamp, 3), "bbox": ocr["bbox"], "confidence": round(float(ocr["confidence"]), 3)}
                if active is None:
                    active = {
                        "start": timestamp,
                        "end": timestamp + frame_duration,
                        "bbox": ocr["bbox"],
                        "confidence": float(ocr["confidence"]),
                        "method": "ocr",
                        "ocr_confidence": round(float(ocr["confidence"]), 3),
                        "ocr_engine": ocr["engine"],
                        "samples": [sample],
                    }
                else:
                    active["end"] = timestamp + frame_duration
                    active["samples"].append(sample)
                    active["bbox"] = box_to_bbox(merge_boxes([bbox_to_box(active["bbox"]), bbox_to_box(ocr["bbox"])]))
                    active["confidence"] = max(active["confidence"], float(ocr["confidence"]))
                    active["ocr_confidence"] = round(max(float(active.get("ocr_confidence", 0.0)), float(ocr["confidence"])), 3)
            else:
                skipped += 1
                if active is not None:
                    raw_segments.append(active)
                    active = None
        if active is not None:
            raw_segments.append(active)
    segments = smooth_source_segments(raw_segments, width, height, args)
    for segment in segments:
        segment["detect_mode"] = args.source_detect_mode
    return segments, {"fallback_segments": len(segments), "skipped_segments": skipped, "reason": "ocr_track"}

def smooth_source_segments(segments, width: int, height: int, args):
    if not segments:
        return []
    segments = sorted(segments, key=lambda item: item["start"])
    merged = []
    for segment in segments:
        current = dict(segment)
        current.setdefault("samples", [])
        if merged and current["start"] - merged[-1]["end"] <= args.source_merge_gap_sec:
            previous = merged[-1]
            previous["end"] = max(previous["end"], current["end"])
            previous["samples"].extend(current.get("samples", []))
            previous["confidence"] = max(previous.get("confidence", 0.0), current.get("confidence", 0.0))
            methods = {previous.get("method", "cv"), current.get("method", "cv")}
            previous["method"] = "+".join(sorted(methods))
        else:
            merged.append(current)
    smoothed = []
    for segment in merged:
        samples = segment.get("samples") or []
        sample_boxes = [sample["bbox"] for sample in samples if sample.get("bbox")]
        if sample_boxes:
            window = max(1, int(args.source_bbox_smooth_window))
            selected = sample_boxes[-window:] if len(sample_boxes) > window else sample_boxes
            bbox = [int(statistics.median(values)) for values in zip(*selected)]
        else:
            bbox = segment.get("bbox")
        box = clamp_box(bbox_to_box(bbox), width, height)
        start = max(0.0, float(segment["start"]) - args.source_lead_in_sec)
        end = max(start + 0.01, float(segment["end"]) + args.source_hold_out_sec)
        smoothed.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "bbox": box_to_bbox(box),
            "confidence": round(float(segment.get("confidence", 0.0)), 3),
            "method": segment.get("method", "cv"),
            "sample_count": len(samples),
        })
    return smoothed

def detect_source_subtitle_track(input_video: Path, width: int, height: int, args):
    fps = max(1.0, float(args.source_detect_fps))
    frame_duration = 1.0 / fps
    raw_segments = []
    active = None
    with TemporaryDirectory(prefix="openclaw-source-sub-track-") as tmp:
        tmp_dir = Path(tmp)
        pattern = tmp_dir / "frame-%06d.jpg"
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(input_video), "-vf", f"fps={fps}", "-q:v", "3", str(pattern),
            ],
            check=True,
        )
        frames = sorted(tmp_dir.glob("frame-*.jpg"))
        for frame_index, frame_path in enumerate(frames):
            timestamp = frame_index / fps
            box = detect_source_text_box(frame_path, width, height, args)
            if box:
                confidence = min(0.99, 0.40 + box.get("components", 1) * 0.035 + box.get("bright_count", 0) / 9000.0)
                sample = {"time": round(timestamp, 3), "bbox": box_to_bbox(box), "confidence": round(confidence, 3)}
                if active is None:
                    active = {
                        "start": timestamp,
                        "end": timestamp + frame_duration,
                        "bbox": box_to_bbox(box),
                        "confidence": confidence,
                        "method": box.get("method", "cv"),
                        "samples": [sample],
                    }
                else:
                    active["end"] = timestamp + frame_duration
                    active["samples"].append(sample)
                    active["bbox"] = box_to_bbox(merge_boxes([bbox_to_box(active["bbox"]), box]))
                    active["confidence"] = max(active["confidence"], confidence)
                    if box.get("method") and box.get("method") not in active["method"]:
                        active["method"] = f"{active['method']}+{box['method']}"
            elif active is not None:
                raw_segments.append(active)
                active = None
        if active is not None:
            raw_segments.append(active)
    return smooth_source_segments(raw_segments, width, height, args)

def source_track_payload(input_video: Path, width: int, height: int, args, segments):
    return {
        "input_video": str(input_video),
        "width": width,
        "height": height,
        "config": {
            "source_detect_mode": args.source_detect_mode,
            "source_detect_fps": args.source_detect_fps,
            "detect_region_top_ratio": args.detect_region_top_ratio,
            "detect_region_bottom_ratio": args.detect_region_bottom_ratio,
            "detect_luma_threshold": args.detect_luma_threshold,
            "detect_max_rgb_spread": args.detect_max_rgb_spread,
            "source_merge_gap_sec": args.source_merge_gap_sec,
            "source_lead_in_sec": args.source_lead_in_sec,
            "source_hold_out_sec": args.source_hold_out_sec,
            "source_bbox_smooth_window": args.source_bbox_smooth_window,
            "ocr_fallback": args.ocr_fallback,
            "ocr_engine": args.ocr_engine,
            "ocr_lang": args.ocr_lang,
            "ocr_fps": args.ocr_fps,
            "ocr_roi_only": args.ocr_roi_only,
        },
        "segments": segments,
    }

def load_or_build_source_track(input_video: Path, output_video: Path, width: int, height: int, args):
    track_path = output_video.with_suffix(".source_subtitle_track.json")
    if not enabled(args.source_track):
        return [], track_path, "disabled"
    if track_path.exists() and not enabled(args.source_track_rebuild) and not enabled(args.ocr_rebuild):
        try:
            data = json.loads(track_path.read_text(encoding="utf-8"))
            segments = data.get("segments", data if isinstance(data, list) else [])
            print(f"source_track_cache_used path={track_path} segments={len(segments)}")
            return segments, track_path, "cache"
        except Exception as exc:
            print(f"WARN: không đọc được source subtitle track cache {track_path}: {exc}; detect lại.")
    try:
        if args.source_detect_mode == "ocr":
            segments, ocr_stats = detect_ocr_subtitle_track(input_video, width, height, args)
            cv_segment_count = 0
        else:
            segments = detect_source_subtitle_track(input_video, width, height, args)
            cv_segment_count = len(segments)
            if not segments and args.source_detect_mode == "auto" and enabled(args.ocr_fallback):
                segments, ocr_stats = detect_ocr_subtitle_track(input_video, width, height, args)
            else:
                segments, ocr_stats = refine_segments_with_ocr(input_video, segments, width, height, args)
        track_path.write_text(json.dumps(source_track_payload(input_video, width, height, args, segments), ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"source_track_built input={input_video} path={track_path} source_detect_mode={args.source_detect_mode} "
            f"cv_segments={cv_segment_count} segments={len(segments)} "
            f"ocr_fallback_segments={ocr_stats.get('fallback_segments', 0)} "
            f"ocr_skipped_segments={ocr_stats.get('skipped_segments', 0)} "
            f"ocr_reason={ocr_stats.get('reason', 'unknown')}"
        )
        return segments, track_path, "built"
    except Exception as exc:
        print(f"WARN: source subtitle detector lỗi trên input gốc {input_video}: {exc}; dùng fallback dynamic/cue masks.")
        return [], track_path, "error"

def fallback_text_box(width: int, height: int, event_text: str, args, band=None):
    fallback_h = int((band or {}).get("h") or max(28, int(height * args.fallback_mask_height_ratio)))
    safe_y = int((band or {}).get("y") or max(0, min(height - fallback_h, height - fallback_h - int(height * args.box_vertical_offset_ratio))))
    text_len = max(8, min(len(event_text), args.max_chars_per_line * max(1, args.max_lines)))
    estimated_w = int(width * 0.12 + text_len * max(5, int(height * args.font_size_ratio * 0.32)))
    min_w = int(width * args.dynamic_mask_min_width_ratio)
    max_w = int(width * args.fallback_mask_max_width_ratio)
    if band:
        max_w = min(max_w, int(band.get("w") or max_w))
    box_w = clamp_int(estimated_w, min_w, max_w)
    center_x = int((band or {}).get("x", 0)) + int((band or {}).get("w", width)) // 2
    box_x = clamp_int(center_x - box_w // 2, int((band or {}).get("x", 0)), max(0, int((band or {}).get("x", 0)) + int((band or {}).get("w", width)) - box_w))
    return {"x": box_x, "y": safe_y, "w": box_w, "h": fallback_h, "source": "fallback"}

def detect_dynamic_masks(input_video: Path, events, width: int, height: int, args):
    if str(args.dynamic_mask).lower() in ("0", "false", "no", "off"):
        return []
    if Image is None:
        print("WARN: PIL/Pillow không khả dụng; bỏ dynamic subtitle mask, dùng mask cố định.")
        return []
    masks = []
    with TemporaryDirectory(prefix="openclaw-sub-mask-") as tmp:
        tmp_dir = Path(tmp)
        for index, event in enumerate(events, 1):
            start = srt_seconds(event["start_raw"])
            end = srt_seconds(event["end_raw"])
            if end <= start:
                continue
            timestamp = start + min(max(0.05, (end - start) * 0.45), max(0.05, end - start - 0.03))
            frame_path = tmp_dir / f"event-{index:04d}.jpg"
            if not extract_frame(input_video, timestamp, frame_path):
                continue
            box = detect_connected_text_box(frame_path, width, height, args)
            if not box:
                continue
            box.update({"start": start, "end": end, "event_index": index, "source": "dynamic"})
            masks.append(box)
    return masks

def build_event_masks(input_video: Path, events, width: int, height: int, args, band=None):
    dynamic_by_index = {box["event_index"]: box for box in detect_dynamic_masks(input_video, events, width, height, args)}
    masks = []
    for index, event in enumerate(events, 1):
        start = srt_seconds(event["start_raw"])
        end = srt_seconds(event["end_raw"])
        if end <= start:
            continue
        box = dynamic_by_index.get(index)
        if box is None:
            box = fallback_text_box(width, height, event.get("text", ""), args, band=band)
            box.update({"start": start, "end": end, "event_index": index})
        masks.append(box)
    return masks

def best_source_for_event(start: float, end: float, source_segments, args):
    best = None
    best_overlap = 0.0
    for index, segment in enumerate(source_segments, 1):
        if float(segment.get("confidence", 0.0)) < args.source_track_min_confidence:
            continue
        overlap = time_overlap(start, end, float(segment["start"]), float(segment["end"]))
        if overlap > best_overlap:
            best = (index, segment)
            best_overlap = overlap
    return best, best_overlap

def build_source_event_and_mask_segments(input_video: Path, events, width: int, height: int, args, source_segments, band=None):
    mask_segments = []
    event_masks = []
    used_source_indexes = set()
    if enabled(args.render_mask_from_source):
        for index, segment in enumerate(source_segments, 1):
            if float(segment.get("confidence", 0.0)) < args.source_track_min_confidence:
                continue
            box = pad_source_box(bbox_to_box(segment["bbox"]), width, height, args)
            box.update({
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "source": "source_track",
                "track_index": index,
                "source_confidence": float(segment.get("confidence", 0.0)),
                "source_method": segment.get("method", "cv"),
            })
            mask_segments.append(box)
    fallback_masks = build_event_masks(input_video, events, width, height, args, band=band) if enabled(args.dynamic_mask) else []
    fallback_by_index = {box.get("event_index"): box for box in fallback_masks}
    for event_index, event in enumerate(events, 1):
        start, end = event_time(event)
        if end <= start:
            continue
        source_match, overlap = best_source_for_event(start, end, source_segments, args)
        if source_match:
            track_index, segment = source_match
            used_source_indexes.add(track_index)
            box = pad_source_box(bbox_to_box(segment["bbox"]), width, height, args)
            box.update({
                "start": start,
                "end": end,
                "event_index": event_index,
                "source": "source_track_text_anchor",
                "track_index": track_index,
                "source_confidence": float(segment.get("confidence", 0.0)),
                "source_time_overlap": round(overlap, 3),
                "source_method": segment.get("method", "cv"),
            })
            event_masks.append(box)
            continue
        box = fallback_by_index.get(event_index)
        if box is None:
            box = fallback_text_box(width, height, event.get("text", ""), args, band=band)
            box.update({"start": start, "end": end, "event_index": event_index})
        box["source_time_overlap"] = 0.0
        event_masks.append(box)
        mask_segments.append(dict(box))
    for box in mask_segments:
        if box.get("source") == "source_track" and box.get("track_index") not in used_source_indexes:
            box["no_vietnamese_cue_overlap"] = True
    return event_masks, mask_segments

def write_wrapped_ass(
    source: Path,
    target: Path,
    width: int,
    height: int,
    font_name: str,
    font_size: int,
    outline: int,
    box_mode: str,
    box_opacity: float,
    box_margin_x: int,
    box_margin_y: int,
    margin_v: int,
    max_chars: int,
    max_lines: int,
    event_masks=None,
    fixed_text_box=None,
    text_color="white",
) -> int:
    blocks = split_srt_blocks(source.read_text(encoding="utf-8", errors="replace"))
    compact_box = box_mode.lower() not in ("0", "false", "no", "off", "none")
    border_style = 3 if compact_box else 1
    style_outline = max(1, box_margin_x if compact_box else outline)
    shadow = 0 if compact_box else 1
    back_colour = f"&H{ass_alpha(box_opacity)}000000"
    outline_colour = "&H00000000"
    primary_colour = ass_colour(text_color)
    margin_l = max(12, int(width * 0.02))
    margin_r = margin_l
    margin_v = max(4, margin_v + (box_margin_y if compact_box else 0))
    mask_by_index = {box.get("event_index"): box for box in (event_masks or [])}
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_colour},&H000000FF,{outline_colour},{back_colour},-1,0,0,0,100,100,0,0,{border_style},{style_outline},{shadow},2,{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    count = 0
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->", 1)]
        wrapped = wrap_subtitle_text(compact_text(lines[2:]), max_chars=max_chars, max_lines=max_lines)
        if not wrapped:
            continue
        count += 1
        override = ""
        box = fixed_text_box or mask_by_index.get(count)
        if box:
            center_x = clamp_int(box["x"] + box["w"] // 2, margin_l, width - margin_r)
            center_y = clamp_int(box["y"] + box["h"] // 2, 8, height - 8)
            override = f"{{\\an5\\pos({center_x},{center_y})}}"
        events.append(f"Dialogue: 0,{ass_time(start_raw)},{ass_time(end_raw)},Default,,0,0,0,,{override}{ass_escape_text(wrapped)}")
    target.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return count


def _ass_fontsdir_option(fontsdir: str) -> list:
    """libass thật sự load font custom qua fontsdir=..., không chỉ dựa Path.stem."""
    if not fontsdir:
        return []
    p = Path(fontsdir)
    if not p.exists() or not p.is_dir():
        return []
    escaped = str(p).replace("\\", "/").replace(":", "\\:")
    return [f"fontsdir={escaped}"]


def ass_filter_string(ass_path: str, fontsdir: str) -> str:
    """Build ass filter option: ass=<path>[:fontsdir=<dir>]. libass load font custom qua fontsdir."""
    fonts_opts = _ass_fontsdir_option(fontsdir)
    if not fonts_opts:
        return f"ass='{ass_path}'"
    return "ass=" + ass_path + "".join([":" + o for o in fonts_opts])


def write_fitted_ass(
    source: Path,
    target: Path,
    width: int,
    height: int,
    font_name: str,
    default_font_size: int,
    outline: int,
    box_mode: str,
    box_opacity: float,
    box_margin_x: int,
    box_margin_y: int,
    margin_v: int,
    text_color="white",
    layouts=None,
) -> int:
    """Ghi ASS với per-cue layout (override \\fn \\fs \\an5 \\pos + \\N line break).

    layouts: list[dict] cùng thứ tự cue parse được từ SRT, mỗi dict có:
      start_raw, end_raw, lines[], font_size, pos_x, pos_y (tâm), use_pos(bool).
    Khi không có pos -> dùng style alignment bottom (an2) + margin_v.
    """
    compact_box = box_mode.lower() not in ("0", "false", "no", "off", "none")
    border_style = 3 if compact_box else 1
    style_outline = max(1, box_margin_x if compact_box else outline)
    shadow = 0 if compact_box else 1
    back_colour = f"&H{ass_alpha(box_opacity)}000000"
    outline_colour = "&H00000000"
    primary_colour = ass_colour(text_color)
    margin_l = max(12, int(width * 0.02))
    margin_r = margin_l
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{default_font_size},{primary_colour},&H000000FF,{outline_colour},{back_colour},-1,0,0,0,100,100,0,0,{border_style},{style_outline},{shadow},2,{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    count = 0
    layout_by_index = {i + 1: lay for i, lay in enumerate(layouts or [])}
    blocks = split_srt_blocks(source.read_text(encoding="utf-8", errors="replace"))
    cue_index = 0
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        cue_index += 1
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->", 1)]
        lay = layout_by_index.get(cue_index)
        if not lay or not lay.get("lines"):
            continue
        count += 1
        size = int(lay.get("font_size") or default_font_size)
        text = "\\N".join(ass_escape_text(l) for l in lay["lines"])
        override = f"{{\\fn{font_name}\\fs{size}"
        if lay.get("use_pos") and lay.get("pos_x") is not None and lay.get("pos_y") is not None:
            override += f"\\an5\\pos({int(lay['pos_x'])},{int(lay['pos_y'])})"
        override += "}"
        events.append(f"Dialogue: 0,{ass_time(start_raw)},{ass_time(end_raw)},Default,,0,0,0,,{override}{text}")
    target.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return count


def write_fitted_srt(source: Path, target: Path, layouts=None) -> int:
    """wrapped.srt debug phải được tạo từ chính lines đã fit, tránh lệch với ASS."""
    blocks = split_srt_blocks(source.read_text(encoding="utf-8", errors="replace"))
    layout_by_index = {i + 1: lay for i, lay in enumerate(layouts or [])}
    out = []
    count = 0
    cue_index = 0
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        cue_index += 1
        lay = layout_by_index.get(cue_index)
        if not lay or not lay.get("lines"):
            continue
        count += 1
        out.append(str(count))
        out.append(lines[1])
        out.extend(lay["lines"])
        out.append("")
    target.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return count


def bottom_safe_text_box(width: int, height: int, args) -> dict:
    """Box an toàn dưới đáy để render sub Việt khi không có band/mask (none/MASK=0)."""
    band_h = max(60, int(height * 0.14))
    vertical_offset = int(height * getattr(args, "vi_vertical_offset_ratio", 0.02))
    y = max(0, min(height - band_h, height - band_h - vertical_offset))
    return {"x": 0, "y": int(y), "w": int(width), "h": int(band_h), "source": "bottom_safe"}


def compute_cue_pos(box: dict, line_count: int, video_h: int, vertical_offset_ratio: float) -> tuple:
    """Tính tâm cố định (x,y) cho \\an5\\pos trong subtitle band."""
    if not box:
        return None, None, False
    cx = int(box["x"] + box["w"] / 2)
    cy = int(box["y"] + box["h"] / 2)
    return cx, cy, True


def build_layouts(events, band_box, font_path, width, height, args, fit_options) -> list:
    """Tính layout per-cue cho toàn bộ events. band_box có thể None."""
    layouts = []
    for event in events:
        start, end = event_time(event)
        text = event.get("text", "")
        fit = fit_vi_subtitle_text(text, band_box, width, height, font_path, fit_options)
        cx, cy, use_pos = compute_cue_pos(band_box, len(fit.get("lines", [])), height, fit_options.get("vertical_offset_ratio", 0.0))
        layouts.append({
            "start_raw": event["start_raw"],
            "end_raw": event["end_raw"],
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "lines": fit["lines"],
            "line_count": len(fit["lines"]),
            "font_size": fit["font_size"],
            "text_width": fit["text_width"],
            "text_height": fit["text_height"],
            "fill_ratio": fit["fill_ratio"],
            "fit_status": fit["status"],
            "fit_reason": fit["reason"],
            "pos_x": cx,
            "pos_y": cy,
            "use_pos": use_pos,
            "band_box": band_box,
        })
    return layouts


def write_layout_report(path: Path, layouts, band_box, width, height, args, fit_min_size=0) -> None:
    fills = [l["fill_ratio"] for l in layouts if l.get("fill_ratio", 0) > 0]
    median_fill = round(float(statistics.median(fills)), 4) if fills else 0.0
    small_threshold = int(fit_min_size or getattr(args, "vi_min_font_size", 0) or 0)
    # "Small cue": cue bị ép xuống đúng min_size (không fit ở size lớn hơn) hoặc overflow.
    small_cues = sum(
        1 for l in layouts
        if (small_threshold and int(l["font_size"]) <= small_threshold) or l.get("fit_status") == "overflow"
    )
    small_cue_ratio = round(small_cues / max(1, len(layouts)), 4) if layouts else 0.0
    payload = {
        "width": width,
        "height": height,
        "band_box": band_box,
        "config": {
            "min_font_size": getattr(args, "vi_min_font_size", None),
            "max_font_size": getattr(args, "vi_max_font_size", None),
            "target_band_fill": getattr(args, "vi_target_band_fill", None),
            "safe_width_ratio": getattr(args, "vi_safe_width_ratio", None),
            "safe_height_ratio": getattr(args, "vi_safe_height_ratio", None),
            "max_lines": getattr(args, "vi_max_lines", None),
            "max_small_cue_ratio": getattr(args, "vi_max_small_cue_ratio", None),
        },
        "summary": {
            "cue_count": len(layouts),
            "median_fill": median_fill,
            "small_cue_ratio": small_cue_ratio,
            "min_fill": round(min(fills), 4) if fills else 0.0,
            "max_fill": round(max(fills), 4) if fills else 0.0,
        },
        "cues": [
            {
                "index": i + 1,
                "start": l["start_raw"],
                "end": l["end_raw"],
                "text": l["text"],
                "line_count": l["line_count"],
                "font_size": l["font_size"],
                "text_width": l["text_width"],
                "text_height": l["text_height"],
                "fill_ratio": l["fill_ratio"],
                "fit_status": l["fit_status"],
                "fit_reason": l["fit_reason"],
            }
            for i, l in enumerate(layouts)
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return median_fill, small_cue_ratio


def write_font_report(path: Path, resolved: dict, width: int, height: int) -> None:
    payload = {
        "width": width,
        "height": height,
        "resolved": resolved,
        "glyph_probe": VI_SUBTITLE_GLYPH_PROBE,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_readability_report(path: Path, status: str, median_fill: float, small_cue_ratio: float, gate_mode: str, reasons: list, median_fs=None, fs_samples=None) -> None:
    payload = {
        "status": status,
        "gate_mode": gate_mode,
        "median_fill": median_fill,
        "small_cue_ratio": small_cue_ratio,
        "reasons": reasons,
    }
    if median_fs is not None:
        payload["ass_median_fs"] = median_fs
        payload["ass_fs_samples"] = fs_samples or []
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_back_ass_fs(ass_path: Path):
    """Đọc lại .wrapped.ass đã ghi, parse tất cả \\fs override -> (median_fs, samples[]).

    Trả (None, []) nếu file không có hoặc không có override \fs.
    """
    import statistics as _st
    try:
        content = Path(ass_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None, []
    sizes = [int(m) for m in re.findall(r"\\fs(\d+)", content)]
    if not sizes:
        return None, []
    return float(_st.median(sizes)), sizes


def evaluate_layout_gate(median_fill: float, small_cue_ratio: float, args, ass_path=None, height=1080) -> tuple:
    """Trả (status, reasons[]). status in ok|skipped|warn|fail.

    Ngoài median_fill/small_cue_ratio, đọc lại .wrapped.ass để verify median \\fs >= gate
    (scale theo height/1080) — bắt đúng bug ASS ghi Fontsize=32 nhỏ li ti trong band 108px.
    """
    reasons = []
    min_fill_warn = float(getattr(args, "vi_min_band_fill_warn", 0.32) or 0.32)
    target_fill = float(getattr(args, "vi_target_band_fill", 0.55) or 0.55)
    max_small = float(getattr(args, "vi_max_small_cue_ratio", 0.25) or 0.25)
    gate_mode = (getattr(args, "vi_layout_gate", "fail") or "fail").lower()
    status = "ok"
    if median_fill < min_fill_warn:
        reasons.append(f"median_fill_too_low:{median_fill}<{min_fill_warn}")
    if small_cue_ratio > max_small:
        reasons.append(f"small_cue_ratio_too_high:{small_cue_ratio}>{max_small}")
    if median_fill > 0 and median_fill < target_fill * 0.7 and not reasons:
        reasons.append(f"median_fill_below_target:{median_fill}<{round(target_fill*0.7,3)}")
    # ASS read-back: median \fs phải >= gate (scale theo height/1080).
    if ass_path is not None:
        median_fs, fs_samples = read_back_ass_fs(ass_path)
        if median_fs is not None:
            scale = float(height) / 1080.0 if height else 1.0
            fs_gate = float(getattr(args, "vi_min_font_size_gate", 48) or 48) * scale
            if median_fs < fs_gate:
                reasons.append(f"ass_median_fs_too_small:{int(median_fs)}<{int(round(fs_gate))}")
        else:
            reasons.append("ass_no_fs_override")
    if reasons:
        status = "fail" if gate_mode == "fail" else "warn"
    return status, reasons


def detect_band_text_box(image_path: Path, width: int, height: int, args):
    old_top = args.detect_region_top_ratio
    old_bottom = args.detect_region_bottom_ratio
    old_prefer_bottom = getattr(args, "detect_prefer_bottom", False)
    try:
        args.detect_region_top_ratio = args.band_region_top_ratio
        args.detect_region_bottom_ratio = args.band_region_bottom_ratio
        args.detect_prefer_bottom = True
        return detect_source_text_box(image_path, width, height, args)
    finally:
        args.detect_region_top_ratio = old_top
        args.detect_region_bottom_ratio = old_bottom
        args.detect_prefer_bottom = old_prefer_bottom

def subtitle_band_fallback(width: int, height: int, args, reason: str, duration: float):
    band_h = max(int(args.band_min_height), int(height * args.band_height_ratio))
    # A fallback is deliberately conservative: uncertainty must not erase a quarter of a frame.
    band_h = min(max(1, band_h), max(1, int(height * 0.12)))
    vertical_offset = int(height * args.box_vertical_offset_ratio)
    y = max(0, min(height - band_h, height - band_h - vertical_offset))
    return {
        "x": 0,
        "y": int(y),
        "w": int(width),
        "h": int(band_h),
        "source": "fallback",
        "fallback": True,
        "reason": reason,
        "duration": round(duration, 3),
        "detected_sample_count": 0,
        "sample_count": 0,
        "samples": [],
    }


SUBTITLE_REGION_SCHEMA_VERSION = 2
SUBTITLE_REGION_DETECTOR_VERSION = "stable-cluster-v3"


def source_fingerprint(video: Path) -> str:
    """Cheap, deterministic cache key without reading the whole source video."""
    stat = video.stat()
    digest = hashlib.sha256()
    digest.update(f"{video.name}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8"))
    with video.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
    return digest.hexdigest()


def write_subtitle_region(path: Path, video: Path, width: int, height: int, args, band: dict) -> None:
    payload = {
        "schema_version": SUBTITLE_REGION_SCHEMA_VERSION,
        "source_fingerprint": source_fingerprint(video),
        "detector_version": SUBTITLE_REGION_DETECTOR_VERSION,
        "frame_width": width,
        "frame_height": height,
        "search_area": {"top_ratio": args.band_region_top_ratio, "bottom_ratio": args.band_region_bottom_ratio},
        "band": {"y_ratio": round(band["y"] / float(height), 6), "height_ratio": round(band["h"] / float(height), 6)},
        "line_mode": band.get("line_mode", "unknown"),
        "confidence": round(float(band.get("confidence", 0.0)), 4),
        "sample_count": int(band.get("sample_count", 0)),
        "accepted_sample_count": int(band.get("detected_sample_count", 0)),
        "fallback_used": bool(band.get("fallback", False)),
        "needs_attention": bool(band.get("needs_attention", False)),
        "reason": band.get("reason", "unknown"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_subtitle_region(path: Path, video: Path, width: int, height: int):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != SUBTITLE_REGION_SCHEMA_VERSION:
            return None
        if payload.get("detector_version") != SUBTITLE_REGION_DETECTOR_VERSION:
            return None
        if payload.get("source_fingerprint") != source_fingerprint(video):
            return None
        if payload.get("frame_width") != width or payload.get("frame_height") != height:
            return None
        raw = payload["band"]
        y = clamp_int(round(float(raw["y_ratio"]) * height), 0, height - 1)
        h = clamp_int(round(float(raw["height_ratio"]) * height), 1, height - y)
        return {"x": 0, "y": y, "w": width, "h": h, "source": "subtitle_region_artifact",
                "fallback": bool(payload.get("fallback_used")), "reason": payload.get("reason", "artifact"),
                "sample_count": int(payload.get("sample_count", 0)),
                "detected_sample_count": int(payload.get("accepted_sample_count", 0)),
                "confidence": float(payload.get("confidence", 0.0)), "line_mode": payload.get("line_mode", "unknown"),
                "needs_attention": bool(payload.get("needs_attention", False))}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def select_subtitle_cluster(samples, width: int, height: int, sample_count: int):
    """Pick one stable, near-bottom geometry cluster; never min/max unrelated text."""
    if not samples:
        return None
    min_center = height * 0.68
    max_box_h = height * 0.16
    candidates = []
    for sample in samples:
        box = bbox_to_box(sample["bbox"])
        center_y = box["y"] + box["h"] / 2.0
        if center_y < min_center or box["h"] > max_box_h or box["w"] < width * 0.08:
            continue
        candidates.append((sample, box, center_y))
    if not candidates:
        return None
    y_tol = max(24, int(height * 0.045))
    h_tol = max(14, int(height * 0.035))
    x_tol = int(width * 0.18)
    clusters = []
    for item in candidates:
        _, box, center_y = item
        center_x = box["x"] + box["w"] / 2.0
        for cluster in clusters:
            if (abs(center_y - cluster["cy"]) <= y_tol and abs(box["h"] - cluster["h"]) <= h_tol
                    and abs(center_x - cluster["cx"]) <= x_tol):
                cluster["items"].append(item)
                values = cluster["items"]
                cluster["cy"] = statistics.median(v[2] for v in values)
                cluster["h"] = statistics.median(v[1]["h"] for v in values)
                cluster["cx"] = statistics.median(v[1]["x"] + v[1]["w"] / 2.0 for v in values)
                break
        else:
            clusters.append({"cy": center_y, "h": box["h"], "cx": center_x, "items": [item]})
    min_hits = max(3, int(round(sample_count * 0.20)))

    def observed_frames(cluster):
        """Count stable observations, not duplicate CV boxes in one frame."""
        return {
            item[0].get("frame", item[0].get("time"))
            for item in cluster["items"]
        }

    viable = [c for c in clusters if len(observed_frames(c)) >= min_hits]
    if not viable:
        return None
    def score(cluster):
        hits = len(cluster["items"])
        stability = hits / float(max(1, sample_count))
        # Stability is primary; bottom position resolves otherwise-equal title-like clusters.
        return stability * 1000 + cluster["cy"] / float(height) * 100
    selected = max(viable, key=score)
    # Geometry stability is measured across frames, not detected components.  A
    # noisy frame may contribute several overlapping candidates, but it still
    # represents one observation and must not inflate confidence.
    per_frame = {}
    for item in selected["items"]:
        sample = item[0]
        frame_key = sample.get("frame", sample.get("time"))
        if frame_key not in per_frame:
            per_frame[frame_key] = item
    items = list(per_frame.values())
    boxes = [item[1] for item in items]
    tops = sorted(box["y"] for box in boxes)
    bottoms = sorted(box["y"] + box["h"] for box in boxes)
    # Trim a single unstable detection at either edge, then pad only 8-16 px at 1080p.
    trim = max(0, int(len(boxes) * 0.10))
    top, bottom = tops[trim], bottoms[-1 - trim]
    padding = clamp_int(round(height * 0.011), 8, 16)
    source_h = max(1, bottom - top)
    target_h = max(int(height * 0.08), int(source_h + padding * 2))
    max_h = int(height * 0.15)
    if target_h > max_h:
        return None
    center = statistics.median(box["y"] + box["h"] / 2.0 for box in boxes)
    y = clamp_int(round(center - target_h / 2.0), 0, height - target_h)
    stability = len(items) / float(max(1, sample_count))
    median_h = statistics.median(box["h"] for box in boxes)
    return {"band": {"x": 0, "y": y, "w": width, "h": target_h}, "accepted_samples": [item[0] for item in items],
            "accepted_sample_count": len(items), "median_center_y": center, "median_source_height": median_h,
            "stability": stability, "line_mode": "two_line" if median_h > height * 0.05 else "one_line",
            "confidence": min(0.99, 0.45 + stability * 0.5 + (center / height - 0.68) * 0.15)}

def detect_stable_subtitle_band(input_video: Path, width: int, height: int, args):
    duration = ffprobe_duration(input_video)
    sample_count = max(1, int(args.band_sample_count))
    if duration <= 0:
        times = [0.5]
    else:
        start = min(duration * 0.08, 2.0)
        end = max(start + 0.01, duration - min(duration * 0.08, 2.0))
        if sample_count == 1:
            times = [(start + end) / 2.0]
        else:
            span = max(0.01, end - start)
            times = [start + span * (idx + 0.5) / sample_count for idx in range(sample_count)]

    band_engine = getattr(args, "band_detect_engine", "cv")
    vision_gate_ok = False
    vision_gate_reason = None
    samples = []
    with TemporaryDirectory(prefix="openclaw-sub-band-") as tmp:
        tmp_dir = Path(tmp)
        # Extract tất cả frame trước.
        frame_paths = []
        for index, timestamp in enumerate(times, 1):
            frame_path = tmp_dir / f"band-{index:04d}.jpg"
            if extract_frame(input_video, timestamp, frame_path):
                frame_paths.append((index, round(timestamp, 3), frame_path))

        if band_engine == "9router_vision" and _nrv is not None:
            # AI gate: chỉ giữ frame AI xác nhận CÓ subtitle, rồi CV khoanh bbox trên đó.
            try:
                gate = _nrv.detect_subtitle_frames([fp for (_, _, fp) in frame_paths],
                                                     timeout=getattr(args, "band_vision_timeout", 60))
            except Exception as exc:
                gate = {"confirmed": [], "reason": f"vision_exception:{exc!r}"[:200], "detail": None}
            if gate.get("reason") == "vision_payload_unsupported":
                vision_gate_reason = "vision_payload_unsupported"
                # Fallback sang CV trên tất cả frame (như engine=cv).
            elif gate.get("confirmed"):
                vision_gate_ok = True
                confirmed_paths = {c["frame"] for c in gate["confirmed"]}
                confirmed_set = [(i, ts, fp) for (i, ts, fp) in frame_paths if fp in confirmed_paths]
                samples = _cv_band_samples(confirmed_set, width, height, args, method_tag="ai_gate_cv")
            else:
                vision_gate_reason = gate.get("reason") or "vision_no_confirmed"
                # Fallback CV trên tất cả frame.
        if not samples:
            # CV thuần (engine=cv, hoặc vision fail/empty -> fallback).
            samples = _cv_band_samples(frame_paths, width, height, args, method_tag="cv")

    min_samples = max(1, min(3, sample_count // 4))
    if len(samples) < min_samples:
        reason = "insufficient_detected_samples"
        if band_engine == "9router_vision" and not vision_gate_ok:
            reason = vision_gate_reason or "vision_fallback_insufficient"
        fallback = subtitle_band_fallback(width, height, args, reason, duration)
        fallback["sample_count"] = sample_count
        fallback["detected_sample_count"] = len(samples)
        fallback["samples"] = samples[:20]
        fallback["band_detect_engine"] = band_engine
        fallback["vision_gate_ok"] = vision_gate_ok
        return fallback

    cluster = select_subtitle_cluster(samples, width, height, sample_count)
    if cluster is None:
        fallback = subtitle_band_fallback(width, height, args, "no_stable_near_bottom_cluster", duration)
        fallback.update({"sample_count": sample_count, "detected_sample_count": len(samples), "samples": samples[:20],
                         "band_detect_engine": band_engine, "vision_gate_ok": vision_gate_ok,
                         "vision_gate_reason": vision_gate_reason, "needs_attention": True,
                         "confidence": 0.0, "line_mode": "unknown"})
        return fallback
    band = cluster["band"]
    return {
        **band,
        "source": "stable_band",
        "fallback": False,
        "reason": "ok",
        "duration": round(duration, 3),
        "sample_count": sample_count,
        "detected_sample_count": cluster["accepted_sample_count"],
        "median_center_y": round(cluster["median_center_y"], 2),
        "median_source_height": round(cluster["median_source_height"], 2),
        "stability": round(cluster["stability"], 4),
        "confidence": round(cluster["confidence"], 4),
        "line_mode": cluster["line_mode"],
        "needs_attention": False,
        "samples": cluster["accepted_samples"][:40],
        "band_detect_engine": band_engine,
        "vision_gate_ok": vision_gate_ok,
        "vision_gate_reason": vision_gate_reason,
    }


def _cv_band_samples(frame_paths, width, height, args, *, method_tag):
    """Chạy CV detector trên list (index, time, frame_path), trả list sample dict."""
    samples = []
    for index, timestamp, frame_path in frame_paths:
        box = detect_band_text_box(frame_path, width, height, args)
        if not box:
            continue
        samples.append({
            "time": timestamp,
            "bbox": box_to_bbox(clamp_box(box, width, height)),
            "method": method_tag,
            "bright_count": int(box.get("bright_count", 0)),
            "components": int(box.get("components", 0)),
        })
    return samples

def write_subtitle_band_report(path: Path, band, width: int, height: int, args):
    payload = {
        "width": width,
        "height": height,
        "band": band,
        "config": {
            "mask_style": args.mask_style,
            "sample_count": args.band_sample_count,
            "region_top_ratio": args.band_region_top_ratio,
            "region_bottom_ratio": args.band_region_bottom_ratio,
            "height_ratio": args.band_height_ratio,
            "min_height": args.band_min_height,
            "blur": args.band_blur,
            "tint_opacity": args.band_tint_opacity,
            "text_color": args.text_color,
            "text_align": args.text_align,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def build_blur_band_filter(ass_filter: str, band, args) -> str:
    blur = max(1, int(args.band_blur))
    chroma_blur = max(1, blur // 2)
    y = int(band["y"])
    h = int(band["h"])
    tint_opacity = max(0.0, min(1.0, float(args.band_tint_opacity)))
    filters = [
        f"[0:v]split=2[base][blur_src]",
        f"[blur_src]crop=w=iw:h={h}:x=0:y={y},boxblur=luma_radius={blur}:luma_power=1:chroma_radius={chroma_blur}:chroma_power=1[blur_band]",
        f"[base][blur_band]overlay=x=0:y={y}[blurred]",
    ]
    if tint_opacity > 0:
        filters.append(f"[blurred]drawbox=x=0:y={y}:w=iw:h={h}:color=black@{tint_opacity:.3f}:t=fill[tinted]")
        input_label = "tinted"
    else:
        input_label = "blurred"
    filters.append(f"[{input_label}]{ass_filter}[vout]")
    return ";".join(filters)

def build_localized_blur_filter(ass_filter: str, mask_filter: str, args) -> str:
    blur = max(1, int(args.band_blur))
    chroma_blur = max(1, blur // 2)
    tint_opacity = max(0.0, min(1.0, float(args.band_tint_opacity)))
    filters = [
        "[0:v]split=3[base][blur_src][mask_src]",
        f"[blur_src]boxblur=luma_radius={blur}:luma_power=1:chroma_radius={chroma_blur}:chroma_power=1[blurred]",
    ]
    if tint_opacity > 0:
        filters.append(f"[blurred]drawbox=color=black@{tint_opacity:.3f}:t=fill[blurred_tint]")
        blur_label = "blurred_tint"
    else:
        blur_label = "blurred"
    filters.extend([
        f"[mask_src]lutrgb=r=0:g=0:b=0,{mask_filter},format=gray[mask]",
        f"[base][{blur_label}][mask]maskedmerge[localized]",
        f"[localized]{ass_filter}[vout]",
    ])
    return ";".join(filters)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-video", required=True)
    parser.add_argument("--srt", required=True)
    parser.add_argument("--output-video", required=True)
    parser.add_argument("--subtitle-region", default=os.environ.get("SUBTITLE_REGION_ARTIFACT", ""))
    parser.add_argument("--detect-subtitle-region-only", action="store_true")
    parser.add_argument("--validate-subtitle-region-only", action="store_true")
    parser.add_argument("--font", default=os.environ.get("SUBTITLE_FONT", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"))
    parser.add_argument("--mask", default=os.environ.get("MASK_ORIGINAL_SUBTITLE", "1"))
    parser.add_argument("--mask-height-ratio", type=float, default=env_float("SUBTITLE_MASK_HEIGHT_RATIO", 0.12))
    parser.add_argument("--mask-opacity", type=float, default=env_float("SUBTITLE_MASK_OPACITY", 0.95))
    parser.add_argument("--bottom-margin-ratio", type=float, default=env_float("SUBTITLE_BOTTOM_MARGIN_RATIO", 0.035))
    parser.add_argument("--font-size-ratio", type=float, default=env_float("SUBTITLE_FONT_SIZE_RATIO", 0.026))
    parser.add_argument("--outline", type=int, default=env_int("SUBTITLE_OUTLINE", 2))
    parser.add_argument("--max-lines", type=int, default=env_int("SUBTITLE_MAX_LINES", 2))
    parser.add_argument("--max-chars-per-line", type=int, default=env_int("SUBTITLE_MAX_CHARS_PER_LINE", 0))
    parser.add_argument("--box-vertical-align", default=os.environ.get("SUBTITLE_BOX_VERTICAL_ALIGN", "center"))
    parser.add_argument("--box-mode", default=os.environ.get("SUBTITLE_BOX_MODE", "compact"))
    parser.add_argument("--box-opacity", type=float, default=env_float("SUBTITLE_BOX_OPACITY", 0.92))
    parser.add_argument("--box-margin-x", type=int, default=env_int("SUBTITLE_BOX_MARGIN_X", 8))
    parser.add_argument("--box-margin-y", type=int, default=env_int("SUBTITLE_BOX_MARGIN_Y", 3))
    parser.add_argument("--box-vertical-offset-ratio", type=float, default=env_float("SUBTITLE_BOX_VERTICAL_OFFSET_RATIO", 0.02))
    parser.add_argument("--dynamic-mask", default=os.environ.get("SUBTITLE_DYNAMIC_MASK", "1"))
    parser.add_argument("--detect-region-top-ratio", type=float, default=env_float("SUBTITLE_DETECT_REGION_TOP_RATIO", 0.82))
    parser.add_argument("--detect-region-bottom-ratio", type=float, default=env_float("SUBTITLE_DETECT_REGION_BOTTOM_RATIO", 0.96))
    parser.add_argument("--detect-luma-threshold", type=int, default=env_int("SUBTITLE_DETECT_LUMA_THRESHOLD", 185))
    parser.add_argument("--detect-max-rgb-spread", type=int, default=env_int("SUBTITLE_DETECT_MAX_RGB_SPREAD", 62))
    parser.add_argument("--detect-min-pixels", type=int, default=env_int("SUBTITLE_DETECT_MIN_PIXELS", 80))
    parser.add_argument("--detect-min-width-ratio", type=float, default=env_float("SUBTITLE_DETECT_MIN_WIDTH_RATIO", 0.08))
    parser.add_argument("--detect-min-height-ratio", type=float, default=env_float("SUBTITLE_DETECT_MIN_HEIGHT_RATIO", 0.018))
    parser.add_argument("--detect-max-width-ratio", type=float, default=env_float("SUBTITLE_DETECT_MAX_WIDTH_RATIO", 0.86))
    parser.add_argument("--detect-max-height-ratio", type=float, default=env_float("SUBTITLE_DETECT_MAX_HEIGHT_RATIO", 0.22))
    parser.add_argument("--dynamic-mask-pad-x-ratio", type=float, default=env_float("SUBTITLE_DYNAMIC_MASK_PAD_X_RATIO", 0.018))
    parser.add_argument("--dynamic-mask-pad-y-ratio", type=float, default=env_float("SUBTITLE_DYNAMIC_MASK_PAD_Y_RATIO", 0.012))
    parser.add_argument("--dynamic-mask-min-width-ratio", type=float, default=env_float("SUBTITLE_DYNAMIC_MASK_MIN_WIDTH_RATIO", 0.12))
    parser.add_argument("--fallback-mask-height-ratio", type=float, default=env_float("SUBTITLE_FALLBACK_MASK_HEIGHT_RATIO", 0.08))
    parser.add_argument("--fallback-mask-max-width-ratio", type=float, default=env_float("SUBTITLE_FALLBACK_MASK_MAX_WIDTH_RATIO", 0.50))
    parser.add_argument("--dynamic-mask-debug", default=os.environ.get("SUBTITLE_DYNAMIC_MASK_DEBUG", "0"))
    parser.add_argument("--source-track", default=os.environ.get("SUBTITLE_SOURCE_TRACK", "1"))
    parser.add_argument("--render-mask-from-source", default=os.environ.get("SUBTITLE_RENDER_MASK_FROM_SOURCE", "1"))
    parser.add_argument("--source-detect-fps", type=float, default=env_float("SUBTITLE_SOURCE_DETECT_FPS", 8.0))
    parser.add_argument("--source-track-rebuild", default=os.environ.get("SUBTITLE_SOURCE_TRACK_REBUILD", "0"))
    parser.add_argument("--source-track-min-confidence", type=float, default=env_float("SUBTITLE_SOURCE_TRACK_MIN_CONFIDENCE", 0.45))
    parser.add_argument("--source-merge-gap-sec", type=float, default=env_float("SUBTITLE_SOURCE_MERGE_GAP_SEC", 0.22))
    parser.add_argument("--source-hold-out-sec", type=float, default=env_float("SUBTITLE_SOURCE_HOLD_OUT_SEC", 0.16))
    parser.add_argument("--source-lead-in-sec", type=float, default=env_float("SUBTITLE_SOURCE_LEAD_IN_SEC", 0.08))
    parser.add_argument("--source-bbox-smooth-window", type=int, default=env_int("SUBTITLE_SOURCE_BBOX_SMOOTH_WINDOW", 3))
    parser.add_argument("--source-pad-x", type=int, default=env_int("SUBTITLE_SOURCE_PAD_X", 64))
    parser.add_argument("--source-pad-y", type=int, default=env_int("SUBTITLE_SOURCE_PAD_Y", 28))
    parser.add_argument("--source-wide-width-ratio", type=float, default=env_float("SUBTITLE_SOURCE_WIDE_WIDTH_RATIO", 0.55))
    parser.add_argument("--source-track-debug", default=os.environ.get("SUBTITLE_SOURCE_TRACK_DEBUG", "1"))
    parser.add_argument("--source-detect-mode", choices=("auto", "cv", "ocr"), default=os.environ.get("SUBTITLE_SOURCE_DETECT_MODE", "auto"))
    parser.add_argument("--ocr-fallback", default=os.environ.get("SUBTITLE_OCR_FALLBACK", "1"))
    parser.add_argument("--ocr-engine", default=os.environ.get("SUBTITLE_OCR_ENGINE", "paddleocr"))
    parser.add_argument("--ocr-lang", default=os.environ.get("SUBTITLE_OCR_LANG", "ch"))
    parser.add_argument("--ocr-fps", type=float, default=env_float("SUBTITLE_OCR_FPS", 2.0))
    parser.add_argument("--ocr-roi-only", default=os.environ.get("SUBTITLE_OCR_ROI_ONLY", "1"))
    parser.add_argument("--ocr-batch-size", type=int, default=env_int("SUBTITLE_OCR_BATCH_SIZE", 1))
    parser.add_argument("--ocr-min-confidence", type=float, default=env_float("SUBTITLE_OCR_MIN_CONFIDENCE", 0.45))
    parser.add_argument("--ocr-rebuild", default=os.environ.get("SUBTITLE_OCR_REBUILD", "0"))
    parser.add_argument("--mask-rounded", default=os.environ.get("SUBTITLE_MASK_ROUNDED", "1"))
    parser.add_argument("--mask-radius", type=int, default=env_int("SUBTITLE_MASK_RADIUS", 18))
    parser.add_argument("--mask-alpha", type=float, default=env_float("SUBTITLE_MASK_ALPHA", env_float("SUBTITLE_MASK_OPACITY", 0.82)))
    parser.add_argument("--mask-style", choices=("localized_blur", "blur_band", "legacy_box", "none"), default=os.environ.get("SUBTITLE_MASK_STYLE", "localized_blur"))
    parser.add_argument("--band-sample-count", type=int, default=env_int("SUBTITLE_BAND_SAMPLE_COUNT", 24))
    parser.add_argument("--band-region-top-ratio", type=float, default=env_float("SUBTITLE_BAND_REGION_TOP_RATIO", 0.55))
    parser.add_argument("--band-region-bottom-ratio", type=float, default=env_float("SUBTITLE_BAND_REGION_BOTTOM_RATIO", 0.98))
    parser.add_argument("--band-height-ratio", type=float, default=env_float("SUBTITLE_BAND_HEIGHT_RATIO", 0.12))
    parser.add_argument("--band-min-height", type=int, default=env_int("SUBTITLE_BAND_MIN_HEIGHT", 64))
    parser.add_argument("--band-blur", type=int, default=env_int("SUBTITLE_BAND_BLUR", 18))
    parser.add_argument("--band-tint-opacity", type=float, default=env_float("SUBTITLE_BAND_TINT_OPACITY", 0.18))
    parser.add_argument("--band-detect-engine", choices=("cv", "9router_vision"), default=os.environ.get("SUBTITLE_BAND_DETECT_ENGINE", os.environ.get("SUBTITLE_MASK_DETECT_ENGINE", "cv")))
    parser.add_argument("--band-vision-timeout", type=int, default=env_int("SUBTITLE_BAND_VISION_TIMEOUT", 60))
    parser.add_argument("--band-min-center-y-ratio", type=float, default=env_float("SUBTITLE_BAND_MIN_CENTER_Y_RATIO", 0.72))
    parser.add_argument("--band-outlier-consistency", type=int, default=env_int("SUBTITLE_BAND_OUTLIER_CONSISTENCY", 5))
    parser.add_argument("--band-outlier-mad-k", type=float, default=env_float("SUBTITLE_BAND_OUTLIER_MAD_K", 3.0))
    parser.add_argument("--text-color", default=os.environ.get("SUBTITLE_TEXT_COLOR", "yellow"))
    parser.add_argument("--text-align", default=os.environ.get("SUBTITLE_TEXT_ALIGN", "band_center"))
    # Subtitle Việt: kiểm soát wrap/font để chữ to, dễ đọc trên mobile.
    parser.add_argument("--vi-min-font-size", type=int, default=env_int("VI_SUBTITLE_MIN_FONT_SIZE", env_int("SUBTITLE_VI_MIN_FONT_SIZE", 0)))
    parser.add_argument("--vi-max-lines", type=int, default=env_int("VI_SUBTITLE_MAX_LINES", env_int("SUBTITLE_MAX_LINES", 2)))
    parser.add_argument("--vi-wrap-chars", type=int, default=env_int("VI_SUBTITLE_WRAP_CHARS", env_int("SUBTITLE_MAX_CHARS_PER_LINE", 0)))
    parser.add_argument("--vi-bottom-margin-ratio", type=float, default=env_float("VI_SUBTITLE_BOTTOM_MARGIN_RATIO", env_float("SUBTITLE_BOTTOM_MARGIN_RATIO", 0.035)))
    parser.add_argument("--vi-vertical-offset-ratio", type=float, default=env_float("VI_SUBTITLE_VERTICAL_OFFSET_RATIO", env_float("SUBTITLE_BOX_VERTICAL_OFFSET_RATIO", 0.02)))
    # Per-cue fitted layout: font resolve + measure + gate.
    parser.add_argument("--vi-subtitle-font-file", default=os.environ.get("VI_SUBTITLE_FONT_FILE", ""))
    parser.add_argument("--vi-subtitle-font-name", default=os.environ.get("VI_SUBTITLE_FONT_NAME", ""))
    parser.add_argument("--vi-subtitle-font-preset", default=os.environ.get("VI_SUBTITLE_FONT_PRESET", ""))
    parser.add_argument("--vi-subtitle-font-dir", default=os.environ.get("VI_SUBTITLE_FONT_DIR", "/home/haonguyen/.openclaw/assets/fonts"))
    parser.add_argument("--vi-max-font-size", type=int, default=env_int("VI_SUBTITLE_MAX_FONT_SIZE", 72))
    parser.add_argument("--vi-target-band-fill", type=float, default=env_float("VI_SUBTITLE_TARGET_BAND_FILL", 0.70))
    parser.add_argument("--vi-safe-width-ratio", type=float, default=env_float("VI_SUBTITLE_SAFE_WIDTH_RATIO", 0.88))
    parser.add_argument("--vi-safe-height-ratio", type=float, default=env_float("VI_SUBTITLE_SAFE_HEIGHT_RATIO", 0.72))
    parser.add_argument("--vi-min-band-fill-warn", type=float, default=env_float("VI_SUBTITLE_MIN_BAND_FILL_WARN", 0.32))
    parser.add_argument("--vi-layout-gate", choices=("fail", "warn", "off"), default=os.environ.get("VI_SUBTITLE_LAYOUT_GATE", "fail"))
    parser.add_argument("--vi-max-small-cue-ratio", type=float, default=env_float("VI_SUBTITLE_MAX_SMALL_CUE_RATIO", 0.25))
    parser.add_argument("--vi-min-font-size-gate", type=int, default=env_int("VI_SUBTITLE_MIN_FONT_SIZE_GATE", 48))
    args = parser.parse_args()

    input_video = Path(args.input_video)
    srt = Path(args.srt)
    output_video = Path(args.output_video)
    if not input_video.exists():
        raise SystemExit(f"input video missing: {input_video}")
    if not srt.exists() or srt.stat().st_size == 0:
        raise SystemExit(f"srt missing/empty: {srt}")

    width, height = ffprobe_dim(input_video)
    region_path = Path(args.subtitle_region) if args.subtitle_region else output_video.with_suffix(".subtitle_region.json")
    if args.validate_subtitle_region_only:
        if load_subtitle_region(region_path, input_video, width, height) is None:
            raise SystemExit(f"subtitle region artifact missing, stale, or invalid: {region_path}")
        print(f"subtitle_region_valid artifact={region_path}")
        return
    if args.detect_subtitle_region_only:
        band = detect_stable_subtitle_band(input_video, width, height, args)
        write_subtitle_region(region_path, input_video, width, height, args, band)
        write_subtitle_band_report(output_video.with_suffix(".subtitle_band.json"), band, width, height, args)
        print(f"subtitle_region_detected artifact={region_path} y={band['y']} height={band['h']} "
              f"confidence={band.get('confidence', 0.0)} fallback={band.get('fallback', False)}")
        return
    events = parse_srt_events(srt)
    mask_h = max(40, int(height * args.mask_height_ratio))
    vertical_offset = int(height * args.box_vertical_offset_ratio)
    mask_y = max(0, min(height - 1, height - mask_h - vertical_offset))
    mask_bottom_margin = max(0, height - (mask_y + mask_h))
    line_height = max(18, int(height * args.font_size_ratio))
    if args.box_vertical_align.lower() == "bottom":
        margin_v = max(10, mask_bottom_margin + int(height * args.bottom_margin_ratio))
    else:
        text_block_h = line_height * min(max(1, args.max_lines), 2) * 1.15
        margin_v = max(8, mask_bottom_margin + int((mask_h - text_block_h) / 2))
    font_size = max(16, int(height * args.font_size_ratio))
    # Subtitle Việt: cho phép font lớn hơn khi ưu tiên 1 dòng; floor từ vi_min_font_size.
    if args.vi_min_font_size and args.vi_min_font_size > 0:
        font_size = max(font_size, int(args.vi_min_font_size))
    max_chars = args.vi_wrap_chars if args.vi_wrap_chars and args.vi_wrap_chars > 0 else args.max_chars_per_line
    if max_chars <= 0:
        max_chars = 34 if width >= height else 28
    max_lines = max(1, min(args.vi_max_lines if args.vi_max_lines and args.vi_max_lines > 0 else args.max_lines, 2))

    # ---- Resolve font Việt có glyph, ghi font report ----
    resolved = resolve_vi_subtitle_font(
        explicit_file=args.vi_subtitle_font_file,
        preset=args.vi_subtitle_font_preset,
        name=args.vi_subtitle_font_name,
        font_dir=args.vi_subtitle_font_dir,
        legacy_font=args.font,
    )
    font_path = Path(resolved["path"]) if resolved["path"] else Path(args.font)
    font_name = resolved["font_name"] or (font_path.stem if font_path else "Noto Sans")
    fontsdir = resolved["fontsdir"]
    font_report_path = output_video.with_suffix(".subtitle_font_report.json")
    write_font_report(font_report_path, resolved, width, height)
    print(
        f"vi_subtitle_font_resolved path={resolved['path']} font_name={font_name} "
        f"source={resolved['source']} glyph_ok={resolved['glyph_ok']} "
        f"method={resolved['method']} missing={resolved['glyph_missing']} "
        f"fontsdir={fontsdir} report={font_report_path}"
    )

    layout_report_path = output_video.with_suffix(".subtitle_layout_report.json")
    readability_report_path = output_video.with_suffix(".subtitle_readability_report.json")
    wrapped_srt = output_video.with_suffix(".wrapped.srt")
    wrapped_ass = output_video.with_suffix(".wrapped.ass")
    mask_ass = output_video.with_suffix(".mask.ass")
    mask_enabled = enabled(args.mask)
    if args.mask_style == "none":
        mask_enabled = False

    # Layout 1080p baseline, scale theo video_height/1080.
    scale = height / 1080.0
    fit_options = {
        "min_size": max(8, int(round(args.vi_min_font_size * scale))) if args.vi_min_font_size and args.vi_min_font_size > 0 else max(8, int(round(48 * scale))),
        "max_size": max(8, int(round(args.vi_max_font_size * scale))),
        "target_band_fill": float(args.vi_target_band_fill),
        "safe_width_ratio": float(args.vi_safe_width_ratio),
        "safe_height_ratio": float(args.vi_safe_height_ratio),
        "max_lines": max_lines,
        "vertical_offset_ratio": float(args.vi_vertical_offset_ratio),
    }

    def run_render(cmd, label):
        output_video.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(cmd, check=True)

    def emit_gate(median_fill, small_cue_ratio, layouts, ass_path=None):
        status, reasons = evaluate_layout_gate(median_fill, small_cue_ratio, args, ass_path=ass_path, height=height)
        median_fs, fs_samples = (None, [])
        if ass_path is not None:
            median_fs, fs_samples = read_back_ass_fs(ass_path)
        write_readability_report(readability_report_path, status, median_fill, small_cue_ratio, args.vi_layout_gate, reasons, median_fs=median_fs, fs_samples=fs_samples)
        print(
            f"vi_subtitle_readability status={status} gate={args.vi_layout_gate} "
            f"median_fill={median_fill} small_cue_ratio={small_cue_ratio} "
            f"ass_median_fs={median_fs} reasons={reasons} report={readability_report_path}"
        )
        if status == "fail" and args.vi_layout_gate == "fail":
            return 8
        return 0

    if args.mask_style == "localized_blur" and mask_enabled:
        band = load_subtitle_region(region_path, input_video, width, height)
        if band is None:
            if args.subtitle_region:
                raise SystemExit(f"subtitle region artifact missing, stale, or invalid: {region_path}")
            band = detect_stable_subtitle_band(input_video, width, height, args)
            write_subtitle_region(region_path, input_video, width, height, args, band)
        source_segments, source_track_path, source_track_status = load_or_build_source_track(
            input_video, output_video, width, height, args
        )
        if source_segments:
            event_masks, mask_segments = build_source_event_and_mask_segments(
                input_video, events, width, height, args, source_segments, band=band
            )
        else:
            event_masks = build_event_masks(input_video, events, width, height, args, band=band)
            mask_segments = list(event_masks)
        mask_count = write_mask_ass(mask_ass, width, height, mask_segments, args, colour="white", opacity=1.0)
        mask_by_index = {box.get("event_index"): box for box in event_masks}
        text_box = {"x": band["x"], "y": band["y"], "w": band["w"], "h": band["h"]}
        layouts = []
        for idx, event in enumerate(events, 1):
            start, end = event_time(event)
            cue_box = mask_by_index.get(idx) or fallback_text_box(width, height, event.get("text", ""), args, band=band)
            fit = fit_vi_subtitle_text(event.get("text", ""), text_box, width, height, font_path, fit_options)
            cx, cy, use_pos = compute_cue_pos(text_box, len(fit.get("lines", [])), height, fit_options.get("vertical_offset_ratio", 0.0))
            layouts.append({
                "start_raw": event["start_raw"], "end_raw": event["end_raw"],
                "start": round(start, 3), "end": round(end, 3), "text": event.get("text", ""),
                "lines": fit["lines"], "line_count": len(fit["lines"]),
                "font_size": fit["font_size"], "text_width": fit["text_width"],
                "text_height": fit["text_height"], "fill_ratio": fit["fill_ratio"],
                "fit_status": fit["status"], "fit_reason": fit["reason"],
                "pos_x": cx, "pos_y": cy, "use_pos": use_pos, "band_box": text_box,
            })
        median_fill, small_cue_ratio = write_layout_report(
            layout_report_path, layouts, None, width, height, args, fit_options["min_size"]
        )
        subtitle_count = write_fitted_srt(srt, wrapped_srt, layouts=layouts)
        write_fitted_ass(
            srt, wrapped_ass, width=width, height=height, font_name=font_name,
            default_font_size=font_size, outline=args.outline, box_mode="none",
            box_opacity=args.box_opacity, box_margin_x=max(1, args.box_margin_x),
            box_margin_y=max(0, args.box_margin_y), margin_v=margin_v,
            text_color=args.text_color, layouts=layouts,
        )
        ass_filter = ass_filter_string(ass_escape_path(wrapped_ass.resolve()), fontsdir)
        mask_filter = f"ass='{ass_escape_path(mask_ass.resolve())}'"
        filter_complex = build_localized_blur_filter(ass_filter, mask_filter, args)
        run_render([
            "ffmpeg", "-y", "-i", str(input_video),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", os.environ.get("SUBTITLE_RENDER_PRESET", "veryfast"),
            "-crf", os.environ.get("SUBTITLE_RENDER_CRF", "20"),
            "-c:a", "copy", str(output_video),
        ], "localized_blur")
        source_count = sum(1 for box in event_masks if str(box.get("source", "")).startswith("source_track"))
        dynamic_count = sum(1 for box in event_masks if box.get("source") == "dynamic")
        fallback_count = sum(1 for box in event_masks if box.get("source") == "fallback")
        fallback_ratio = fallback_count / max(1, len(event_masks))
        mask_report_path = output_video.with_suffix(".subtitle_mask_report.json")
        mask_report_path.write_text(json.dumps({
            "status": "warning" if fallback_ratio > 0.25 else "ok",
            "mask_style": "localized_blur",
            "event_count": len(event_masks),
            "mask_segment_count": mask_count,
            "source_track_events": source_count,
            "dynamic_events": dynamic_count,
            "fallback_events": fallback_count,
            "fallback_ratio": round(fallback_ratio, 4),
            "source_track_status": source_track_status,
            "source_track_path": str(source_track_path),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        gate_rc = emit_gate(median_fill, small_cue_ratio, layouts, ass_path=wrapped_ass)
        print(
            "subtitle_render_ok "
            f"output={output_video} mask_style=localized_blur source={source_count} "
            f"dynamic={dynamic_count} fallback={fallback_count} fallback_ratio={fallback_ratio:.3f} "
            f"mask_report={mask_report_path} subtitle_count={subtitle_count}"
        )
        if gate_rc:
            raise SystemExit(gate_rc)
        return

    if args.mask_style == "blur_band" and mask_enabled:
        # Pipeline callers pass a fingerprinted artifact.  The old direct CLI remains
        # compatible by creating it here once, but rendering from an explicit artifact
        # never invokes the detector.
        band = load_subtitle_region(region_path, input_video, width, height)
        if band is None:
            if args.subtitle_region:
                raise SystemExit(f"subtitle region artifact missing, stale, or invalid: {region_path}")
            detected = detect_stable_subtitle_band(input_video, width, height, args)
            write_subtitle_region(region_path, input_video, width, height, args, detected)
            band = detected
        band_report_path = output_video.with_suffix(".subtitle_band.json")
        write_subtitle_band_report(band_report_path, band, width, height, args)
        band_box = {"x": band["x"], "y": band["y"], "w": band["w"], "h": band["h"]}
        layouts = build_layouts(events, band_box, font_path, width, height, args, fit_options)
        median_fill, small_cue_ratio = write_layout_report(layout_report_path, layouts, band_box, width, height, args, fit_options["min_size"])
        subtitle_count = write_fitted_srt(srt, wrapped_srt, layouts=layouts)
        write_fitted_ass(
            srt, wrapped_ass, width=width, height=height, font_name=font_name,
            default_font_size=font_size, outline=args.outline, box_mode="none",
            box_opacity=args.box_opacity, box_margin_x=max(1, args.box_margin_x),
            box_margin_y=max(0, args.box_margin_y), margin_v=margin_v,
            text_color=args.text_color, layouts=layouts,
        )
        ass_path = ass_escape_path(wrapped_ass.resolve())
        ass_filter = ass_filter_string(ass_path, fontsdir)
        filter_complex = build_blur_band_filter(ass_filter, band, args)
        run_render([
            "ffmpeg", "-y", "-i", str(input_video),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", os.environ.get("SUBTITLE_RENDER_PRESET", "veryfast"),
            "-crf", os.environ.get("SUBTITLE_RENDER_CRF", "20"),
            "-c:a", "copy", str(output_video)
        ], "blur_band")
        gate_rc = emit_gate(median_fill, small_cue_ratio, layouts, ass_path=wrapped_ass)
        print(
            "subtitle_render_ok "
            f"output={output_video} width={width} height={height} mask_style=blur_band "
            f"band_y={band['y']} band_h={band['h']} band_fallback={band.get('fallback')} "
            f"band_detected_samples={band.get('detected_sample_count', 0)}/{band.get('sample_count', 0)} "
            f"band_report={band_report_path} blur={args.band_blur} tint_opacity={args.band_tint_opacity} "
            f"text_color={args.text_color} text_align={args.text_align} font={resolved['path']} font_name={font_name} "
            f"fontsdir={fontsdir} median_fill={median_fill} small_cue_ratio={small_cue_ratio} "
            f"wrapped_srt={wrapped_srt} wrapped_ass={wrapped_ass} subtitle_count={subtitle_count}"
        )
        if gate_rc:
            raise SystemExit(gate_rc)
        return

    if not mask_enabled:
        # none hoặc MASK_ORIGINAL_SUBTITLE=0: dùng bottom-safe full-width text box để vẫn render sub Việt.
        band_box = bottom_safe_text_box(width, height, args)
        layouts = build_layouts(events, band_box, font_path, width, height, args, fit_options)
        median_fill, small_cue_ratio = write_layout_report(layout_report_path, layouts, band_box, width, height, args, fit_options["min_size"])
        subtitle_count = write_fitted_srt(srt, wrapped_srt, layouts=layouts)
        write_fitted_ass(
            srt, wrapped_ass, width=width, height=height, font_name=font_name,
            default_font_size=font_size, outline=args.outline, box_mode=args.box_mode,
            box_opacity=args.box_opacity, box_margin_x=max(1, args.box_margin_x),
            box_margin_y=max(0, args.box_margin_y), margin_v=margin_v,
            text_color=args.text_color, layouts=layouts,
        )
        ass_path = ass_escape_path(wrapped_ass.resolve())
        ass_filter = ass_filter_string(ass_path, fontsdir)
        run_render([
            "ffmpeg", "-y", "-i", str(input_video), "-vf", ass_filter,
            "-c:v", "libx264", "-preset", os.environ.get("SUBTITLE_RENDER_PRESET", "veryfast"),
            "-crf", os.environ.get("SUBTITLE_RENDER_CRF", "20"),
            "-c:a", "copy", str(output_video)
        ], "none")
        gate_rc = emit_gate(median_fill, small_cue_ratio, layouts, ass_path=wrapped_ass)
        print(
            "subtitle_render_ok "
            f"output={output_video} width={width} height={height} mask_style=none "
            f"text_color={args.text_color} font={resolved['path']} font_name={font_name} "
            f"fontsdir={fontsdir} median_fill={median_fill} small_cue_ratio={small_cue_ratio} "
            f"wrapped_srt={wrapped_srt} wrapped_ass={wrapped_ass} subtitle_count={subtitle_count}"
        )
        if gate_rc:
            raise SystemExit(gate_rc)
        return

    # ---- legacy_box: mask per-cue + chữ Việt fit theo event_masks ----
    event_masks = []
    mask_segments = []
    source_segments = []
    source_track_path = output_video.with_suffix(".source_subtitle_track.json")
    source_track_status = "disabled"
    if mask_enabled:
        if enabled(args.source_track) and enabled(args.render_mask_from_source):
            source_segments, source_track_path, source_track_status = load_or_build_source_track(input_video, output_video, width, height, args)
            if source_segments:
                event_masks, mask_segments = build_source_event_and_mask_segments(input_video, events, width, height, args, source_segments)
            else:
                event_masks = build_event_masks(input_video, events, width, height, args)
                mask_segments = list(event_masks)
        else:
            event_masks = build_event_masks(input_video, events, width, height, args)
            mask_segments = list(event_masks)
    # Với legacy_box, dùng event_masks làm text box cho từng cue.
    mask_by_index = {box.get("event_index"): box for box in event_masks}
    layouts = []
    for idx, event in enumerate(events, 1):
        start, end = event_time(event)
        text = event.get("text", "")
        cue_box = mask_by_index.get(idx)
        if not cue_box:
            cue_box = bottom_safe_text_box(width, height, args)
        fit = fit_vi_subtitle_text(text, cue_box, width, height, font_path, fit_options)
        cx, cy, use_pos = compute_cue_pos(cue_box, len(fit.get("lines", [])), height, fit_options.get("vertical_offset_ratio", 0.0))
        layouts.append({
            "start_raw": event["start_raw"], "end_raw": event["end_raw"],
            "start": round(start, 3), "end": round(end, 3), "text": text,
            "lines": fit["lines"], "line_count": len(fit["lines"]),
            "font_size": fit["font_size"], "text_width": fit["text_width"],
            "text_height": fit["text_height"], "fill_ratio": fit["fill_ratio"],
            "fit_status": fit["status"], "fit_reason": fit["reason"],
            "pos_x": cx, "pos_y": cy, "use_pos": use_pos, "band_box": cue_box,
        })
    band_box = None
    median_fill, small_cue_ratio = write_layout_report(layout_report_path, layouts, band_box, width, height, args, fit_options["min_size"])
    subtitle_count = write_fitted_srt(srt, wrapped_srt, layouts=layouts)
    write_fitted_ass(
        srt, wrapped_ass, width=width, height=height, font_name=font_name,
        default_font_size=font_size, outline=args.outline, box_mode=args.box_mode,
        box_opacity=args.box_opacity, box_margin_x=max(1, args.box_margin_x),
        box_margin_y=max(0, args.box_margin_y), margin_v=margin_v,
        text_color=args.text_color, layouts=layouts,
    )
    ass_path = ass_escape_path(wrapped_ass.resolve())
    subtitle_filter = ass_filter_string(ass_path, fontsdir)
    filters = []
    rounded_mask_events = 0
    if mask_enabled:
        opacity = max(0.0, min(1.0, args.mask_opacity))
        if mask_segments and enabled(args.mask_rounded):
            rounded_mask_events = write_mask_ass(mask_ass, width, height, mask_segments, args)
            mask_ass_path = ass_escape_path(mask_ass.resolve())
            filters.append(f"ass='{mask_ass_path}'")
        elif mask_segments:
            for box in mask_segments:
                filters.append(
                    "drawbox="
                    f"x={box['x']}:y={box['y']}:w={box['w']}:h={box['h']}:"
                    f"color=black@{opacity:.2f}:t=fill:"
                    f"enable='between(t\\,{box['start']:.3f}\\,{box['end']:.3f})'"
                )
        else:
            filters.append(f"drawbox=x=0:y={mask_y}:w=iw:h={mask_h}:color=black@{opacity:.2f}:t=fill")
    else:
        event_masks = []
        mask_segments = []
    source_masks = [box for box in mask_segments if box.get("source") == "source_track"]
    dynamic_masks = [box for box in mask_segments if box.get("source") == "dynamic"]
    fallback_masks = [box for box in mask_segments if box.get("source") == "fallback"]
    boxes_path = output_video.with_suffix(".subtitle_boxes.json")
    mask_segments_path = output_video.with_suffix(".mask_segments.json")
    if enabled(args.dynamic_mask_debug) or enabled(args.source_track_debug):
        boxes_path.write_text(json.dumps({"width": width, "height": height, "boxes": event_masks}, ensure_ascii=False, indent=2), encoding="utf-8")
        mask_segments_path.write_text(json.dumps({"width": width, "height": height, "mask_segments": mask_segments}, ensure_ascii=False, indent=2), encoding="utf-8")
    box_summary = ";".join(
        f"#{box.get('event_index')}:{box.get('source')}@{box.get('x')},{box.get('y')},{box.get('w')}x{box.get('h')}"
        for box in event_masks[:12]
    )
    filters.append(subtitle_filter)
    vf = ",".join(filters)
    run_render([
        "ffmpeg", "-y", "-i", str(input_video), "-vf", vf,
        "-c:v", "libx264", "-preset", os.environ.get("SUBTITLE_RENDER_PRESET", "veryfast"),
        "-crf", os.environ.get("SUBTITLE_RENDER_CRF", "20"),
        "-c:a", "copy", str(output_video)
    ], "legacy_box")
    gate_rc = emit_gate(median_fill, small_cue_ratio, layouts, ass_path=wrapped_ass)
    print(
        "subtitle_render_ok "
        f"output={output_video} width={width} height={height} mask_style=legacy_box mask_h={mask_h} mask_y={mask_y} "
        f"mask_opacity={max(0.0, min(1.0, args.mask_opacity)):.2f} box_mode={args.box_mode} "
        f"box_opacity={max(0.0, min(1.0, args.box_opacity)):.2f} font={resolved['path']} font_name={font_name} "
        f"fontsdir={fontsdir} median_fill={median_fill} small_cue_ratio={small_cue_ratio} "
        f"margin_v={margin_v} max_lines={max_lines} max_chars={max_chars} source_track_status={source_track_status} "
        f"source_track={source_track_path} source_track_segments={len(source_segments)} source_masks={len(source_masks)} "
        f"mask_segments={len(mask_segments)} mask_segments_path={mask_segments_path} dynamic_masks={len(dynamic_masks)} "
        f"fallback_masks={len(fallback_masks)} rounded_mask={enabled(args.mask_rounded)} rounded_mask_events={rounded_mask_events} "
        f"mask_ass={mask_ass if rounded_mask_events else ''} source_detect_mode={args.source_detect_mode} boxes={boxes_path} "
        f"box_summary={box_summary} "
        f"wrapped_srt={wrapped_srt} wrapped_ass={wrapped_ass} subtitle_count={subtitle_count}"
    )
    if gate_rc:
        raise SystemExit(gate_rc)


if __name__ == "__main__":
    main()
