"""Sinh phụ đề karaoke .ass — cụm 2-3 chữ nhảy theo giọng đọc (kiểu CapCut).

Khác phụ đề SRT cả câu: mỗi câu dịch được chia thành các CỤM ``words_per_cue``
chữ, mỗi cụm là một Dialogue event với mốc thời gian riêng và hiệu ứng libass
(pop/fade/karaoke đổi màu). Chỉ dùng ở chế độ burn — libass render trong đúng
pass re-encode sẵn có, không thêm dependency.

Mốc thời gian từng chữ lấy từ 2 tầng:

1. **Alignment thật** (:mod:`autodub.speech.align`) — Whisper base nghe chính
   clip WAV tiếng Việt; chính xác như CapCut vì văn bản đã biết trước.
2. **Ước lượng âm tiết** (fallback) — tiếng Việt đơn âm tiết nhịp đều nên chia
   thời lượng clip theo số chữ + trọng số dấu câu là đủ sát; neo lại ở đầu
   mỗi câu nên sai số không tích luỹ.

Toạ độ style dùng canvas PlayResY=288 — cùng hệ với force_style của đường SRT
(style dialog đã hiển thị đúng cỡ này).
"""
from __future__ import annotations

import os

from autodub.utils import seg_wav_path, setup_logging

logger = setup_logging("autodub.ass_karaoke")

# Cùng canvas với đường SRT (ffmpeg convert SRT→ASS ở PlayResY=288).
PLAY_RES_X = 512
PLAY_RES_Y = 288

# Đuôi hiển thị sau chữ cuối của câu (giây) — caption không tắt phụt.
_TAIL_S = 0.15
# Cụm hiển thị tối thiểu — cụm 1 chữ quá nhanh sẽ không kịp đọc.
_MIN_CUE_S = 0.20

# Dấu kết thúc cụm sớm (ngắt theo nhịp đọc thay vì đếm chữ cứng nhắc).
_BREAK_PUNCT = ",.!?…;:"
# Trọng số nghỉ sau dấu — TTS ngân dài hơn ở các dấu này.
_PAUSE_WEIGHT = {",": 0.5, ";": 0.5, ":": 0.5,
                 ".": 0.9, "!": 0.9, "?": 0.9, "…": 0.9}

DEFAULT_KARAOKE = {
    "display": "sentence",        # "sentence" (SRT cũ) | "karaoke"
    "words_per_cue": 3,           # 1-5 chữ mỗi cụm
    "effect": "pop",              # "pop" | "fade" | "karaoke" | "none"
    "highlight_color": "#FFD54A", # màu chữ đang đọc (effect="karaoke")
}


# ------------------------------------------------------------- timing ------ #

def _pause_after(word: str) -> float:
    w = word.rstrip("\"'”’)»")
    return _PAUSE_WEIGHT.get(w[-1:], 0.0)


def estimate_word_times(text: str, start: float,
                        duration: float) -> list[tuple[str, float, float]]:
    """Ước lượng mốc từng chữ khi không có alignment thật.

    Mỗi chữ tiếng Việt ~1 âm tiết → chia ``duration`` theo số chữ, cộng
    trọng số nghỉ sau dấu câu (TTS ngân ở đó). Trả về mốc TUYỆT ĐỐI.
    """
    tokens = text.split()
    if not tokens or duration <= 0:
        return []
    weights = [1.0 + _pause_after(t) for t in tokens]
    weights[-1] = 1.0  # đuôi câu đã có _TAIL_S, không cần nghỉ ảo
    total = sum(weights)
    out: list[tuple[str, float, float]] = []
    t = start
    for tok, w in zip(tokens, weights):
        dur = duration * w / total
        out.append((tok, round(t, 3), round(t + dur, 3)))
        t += dur
    return out


def resolve_word_times(
    segments: list[dict],
    merge_dir: str,
    text_field: str,
    settings=None,
    cache_path: str | None = None,
) -> dict[int, list[tuple[str, float, float]]]:
    """Mốc từng chữ cho mọi segment: alignment thật trước, ước lượng bù sau.

    Trả về ``{seg_id: [(chữ, t0, t1), ...]}`` với thời gian TUYỆT ĐỐI trên
    timeline video. Không bao giờ raise — alignment hỏng thì toàn bộ rơi về
    ước lượng (non-fatal, video vẫn ra).
    """
    from autodub.media.audio import wav_duration_s
    from autodub.text.srt import has_subtitle_override, subtitle_text

    aligned: dict[int, list[tuple[str, float, float]]] = {}
    use_align = getattr(settings, "karaoke_alignment", True) if settings else True
    if use_align:
        try:
            from autodub.speech.align import align_segments
            aligned = align_segments(segments, merge_dir, text_field,
                                     cache_path=cache_path)
        except Exception as e:
            logger.warning(f"Không canh được phụ đề theo giọng đọc ({e}) — "
                           "chữ sẽ chia đều theo thời lượng câu")
            aligned = {}

    out: dict[int, list[tuple[str, float, float]]] = {}
    n_est = 0
    for seg in segments:
        sid = seg.get("id")
        text = subtitle_text(seg, text_field)
        if not text:
            continue
        # Mốc chữ từ alignment là mốc của LỜI ĐỌC. Câu nào có phụ đề viết
        # riêng thì chữ không còn khớp giọng nữa, phải chia đều theo thời
        # lượng — nếu không, chữ sẽ sáng lên sai nhịp.
        words = None if has_subtitle_override(seg, text_field) else aligned.get(sid)
        if not words:
            dur = (wav_duration_s(seg_wav_path(merge_dir, sid))
                   or float(seg.get("end", 0)) - float(seg.get("start", 0)))
            words = estimate_word_times(text, float(seg["start"]), dur)
            n_est += 1
        if words:
            out[sid] = words
    if n_est and use_align:
        logger.info(f"Phụ đề kiểu cụm chữ: {n_est}/{len(segments)} câu chia "
                    "đều theo thời lượng (không bắt được nhịp giọng đọc)")
    return out


# ------------------------------------------------------------- chunking ---- #

def chunk_words(words: list[tuple[str, float, float]],
                n: int) -> list[list[tuple[str, float, float]]]:
    """Gom mốc chữ thành cụm ≤ ``n`` chữ, ngắt sớm tại dấu câu."""
    n = max(1, min(5, int(n)))
    chunks: list[list[tuple[str, float, float]]] = []
    cur: list[tuple[str, float, float]] = []
    for wt in words:
        cur.append(wt)
        bare = wt[0].rstrip("\"'”’)»")
        if len(cur) >= n or (bare and bare[-1] in _BREAK_PUNCT):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


# ------------------------------------------------------------- ASS text ---- #

def _ass_time(seconds: float) -> str:
    """ASS timestamp ``H:MM:SS.cc`` (centi-giây, không âm)."""
    cs_total = max(0, int(round(seconds * 100)))
    s_total, cs = divmod(cs_total, 100)
    h, rem = divmod(s_total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_text(text: str) -> str:
    """Chữ hiển thị an toàn trong Dialogue: bỏ ngoặc override + xuống dòng."""
    return (text.replace("{", "(").replace("}", ")")
            .replace("\r", " ").replace("\n", " "))


def _effect_prefix(effect: str) -> str:
    """Thẻ override mở đầu event theo hiệu ứng đã chọn."""
    if effect == "pop":
        # Nảy nhẹ kiểu CapCut: hiện ở 82% cỡ chữ rồi phóng lên 100% trong
        # 110 ms, kèm fade ngắn hai đầu.
        return (r"{\fad(60,40)\fscx82\fscy82"
                r"\t(0,110,\fscx100\fscy100)}")
    if effect == "fade":
        return r"{\fad(90,70)}"
    if effect == "karaoke":
        return r"{\fad(40,30)}"
    return ""


def _karaoke_body(chunk: list[tuple[str, float, float]],
                  all_caps: bool = False) -> str:
    """Nội dung dòng kiểu \\k: từng chữ đổi màu đúng lúc được đọc."""
    parts = []
    for word, t0, t1 in chunk:
        cs = max(1, int(round((t1 - t0) * 100)))
        parts.append(rf"{{\k{cs}}}{_escape_text(word.upper() if all_caps else word)}")
    return " ".join(parts)


def _style_line(style: dict) -> str:
    """Dòng Style ASS, dựng từ đúng dict kiểu mà đường SRT cũng dùng."""
    from autodub.media.subtitle import (_POSITION_ALIGN, hex_to_ass_color,
                                        normalize_style, safe_font_name)

    s = normalize_style(style)
    align = _POSITION_ALIGN.get(str(s["position"]), 2)
    font = safe_font_name(s["font"])
    primary = hex_to_ass_color(s["color"])
    highlight = hex_to_ass_color(s["highlight_color"])
    boxed = str(s["box"]) == "box"
    # BorderStyle 3 = khối nền đặc, vẽ bằng chính OutlineColour.
    border_style = 3 if boxed else 1
    outline_c = (hex_to_ass_color(s["box_color"], int(s["box_opacity"]))
                 if boxed else hex_to_ass_color(s["outline_color"]))
    if str(s["effect"]) == "karaoke":
        # Với thẻ \k: chữ CHƯA đọc mang SecondaryColour, chữ ĐÃ đọc chuyển
        # sang PrimaryColour — nên primary là màu nhấn, secondary là màu chữ.
        primary, secondary = highlight, primary
    else:
        secondary = highlight
    bold = -1 if s["bold"] else 0
    return (
        f"Style: Kara,{font},{int(s['font_size'])},"
        f"{primary},{secondary},{outline_c},{hex_to_ass_color('#000000', 40)},"
        f"{bold},0,0,0,100,100,0,0,{border_style},{int(s['outline'])},"
        f"{int(s['shadow'])},{align},20,20,{int(s['margin_v'])},163"
    )


def build_karaoke_ass(
    segments: list[dict],
    merge_dir: str,
    out_path: str,
    style: dict | None,
    text_field: str = "text_vi",
    settings=None,
    cache_path: str | None = None,
) -> str:
    """Sinh file .ass hoàn chỉnh cho toàn video. Trả về ``out_path``.

    ``merge_dir`` là thư mục clip CUỐI CÙNG (đã hậu kỳ + voice speed +
    timing mềm) — mốc chữ tính trên đúng audio người nghe sẽ nghe.
    """
    from autodub.media.subtitle import normalize_style

    s = normalize_style(style)
    effect = str(s["effect"])
    n_words = int(s["words_per_cue"])
    all_caps = bool(s["all_caps"])

    word_times = resolve_word_times(segments, merge_dir, text_field,
                                    settings=settings, cache_path=cache_path)

    events: list[str] = []
    for seg in segments:
        words = word_times.get(seg.get("id"))
        if not words:
            continue
        chunks = chunk_words(words, n_words)
        for i, chunk in enumerate(chunks):
            t0 = chunk[0][1]
            # Cụm hiển thị liền mạch tới cụm sau (không nháy tắt/bật);
            # cụm cuối câu giữ thêm _TAIL_S.
            t1 = (chunks[i + 1][0][1] if i + 1 < len(chunks)
                  else chunk[-1][2] + _TAIL_S)
            t1 = max(t1, t0 + _MIN_CUE_S)
            if effect == "karaoke":
                body = _karaoke_body(chunk, all_caps)
            else:
                words_text = " ".join(w for w, _, _ in chunk)
                body = _escape_text(words_text.upper() if all_caps
                                    else words_text)
            events.append(
                f"Dialogue: 0,{_ass_time(t0)},{_ass_time(t1)},Kara,,0,0,0,,"
                f"{_effect_prefix(effect)}{body}"
            )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {PLAY_RES_X}\n"
        f"PlayResY: {PLAY_RES_Y}\n"
        "ScaledBorderAndShadow: yes\n"
        "WrapStyle: 2\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{_style_line(s)}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write(header)
        f.write("\n".join(events))
        f.write("\n")
    logger.info(f"Phụ đề kiểu cụm chữ: {len(events)} cụm đã sẵn sàng "
                f"({n_words} chữ mỗi lần hiện)")
    return out_path
