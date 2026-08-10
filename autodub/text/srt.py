"""Sinh tệp .srt, có ngắt dòng cho dễ đọc.

Phụ đề bám đúng mốc thời gian từng câu mà bước nghe-chép đã tách (khớp nhịp
video gốc). Phần lớn câu đều ngắn nên đi thẳng 1:1; câu nào quá dài mới bị
chia tiếp thành các dòng hiển thị ngắn (~42 ký tự mỗi hàng, tối đa 2 hàng),
thời gian chia theo số ký tự — đúng cách làm phụ đề chuyên nghiệp.

Chữ hiển thị lấy từ :func:`subtitle_text`: nếu câu có trường phụ đề riêng
(``sub_vi``) thì dùng nó, không thì dùng chính lời đọc. Nhờ vậy sửa một lỗi
chính tả trên phụ đề không bắt phải đọc lại giọng cho câu đó.
"""
from autodub.utils import format_timestamp, setup_logging

logger = setup_logging("autodub.srt_generator")

#: Trường chứa phụ đề riêng, khi người dùng muốn phụ đề khác lời đọc.
SUBTITLE_FIELD = "sub_vi"

# Giới hạn dễ đọc theo chuẩn phụ đề cho tiếng Việt.
MAX_LINE_CHARS = 42
MAX_LINES_PER_CUE = 2
MIN_CUE_SECONDS = 0.8


def subtitle_text(seg: dict, text_field: str = "text_vi") -> str:
    """Chữ sẽ hiện trên phụ đề của một câu.

    Ưu tiên phụ đề riêng ``sub_vi``; trống thì dùng chính lời đọc. Đây là
    hàm DUY NHẤT mọi nơi sinh phụ đề được phép dùng, để phụ đề trong video,
    tệp .srt và bản xem trước không bao giờ lệch nhau.
    """
    override = str(seg.get(SUBTITLE_FIELD, "") or "").strip()
    return override or str(seg.get(text_field, "") or "").strip()


def has_subtitle_override(seg: dict, text_field: str = "text_vi") -> bool:
    """Câu này có phụ đề viết riêng, khác với lời đọc, hay không."""
    override = str(seg.get(SUBTITLE_FIELD, "") or "").strip()
    return bool(override) and override != str(seg.get(text_field, "") or "").strip()


def _wrap_lines(text: str, width: int = MAX_LINE_CHARS,
                line_words: int = 0) -> list[str]:
    """Ngắt dòng: theo SỐ CHỮ mỗi hàng khi ``line_words`` > 0, không thì gói
    tham lam theo bề rộng ký tự (chuẩn 42) — không bao giờ cắt giữa một chữ."""
    if line_words > 0:
        words = text.split()
        return [" ".join(words[i:i + line_words])
                for i in range(0, len(words), line_words)] or []
    lines: list[str] = []
    cur = ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if len(cand) <= width or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def split_for_display(seg: dict, text_field: str, line_words: int = 0,
                      max_lines: int = MAX_LINES_PER_CUE,
                      all_caps: bool = False) -> list[dict]:
    """Chia một câu (có thể dài) thành các dòng hiển thị ngắn.

    Ranh giới ưu tiên dấu câu; thời gian chia đều cho các mảnh theo số ký tự.
    Câu đã vừa một dòng hiển thị (trường hợp phổ biến) đi thẳng, không đổi.

    ``line_words`` > 0: người dùng chốt số chữ mỗi hàng — sức chứa một dòng
    hiển thị tính theo CHỮ (line_words × số hàng) thay vì theo ký tự.
    """
    import re

    text = subtitle_text(seg, text_field)
    if not text:
        return []
    if all_caps:
        text = text.upper()

    max_lines = max(1, int(max_lines or MAX_LINES_PER_CUE))

    # Đơn vị đo theo chế độ: chữ (khi chỉnh tay) hoặc ký tự (khi tự động).
    if line_words > 0:
        def measure(s: str) -> int:
            return len(s.split())
        max_cue = line_words * max_lines
    else:
        measure = len
        max_cue = MAX_LINE_CHARS * max_lines

    def _wrapped(chunk: str) -> str:
        return "\n".join(_wrap_lines(chunk, line_words=line_words))

    if measure(text) <= max_cue:
        return [{"start": seg["start"], "end": seg["end"],
                 "text": _wrapped(text)}]

    # Cắt ở dấu ngắt mệnh đề trước, rồi dồn thành các mảnh vừa một dòng hiện.
    parts = [p.strip() for p in re.split(r"(?<=[,.!?;…])\s+", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for part in parts:
        # Một mệnh đề dài hơn cả một dòng hiển thị thì phải cắt tiếp.
        while measure(part) > max_cue:
            if line_words > 0:
                head = " ".join(part.split()[:max_cue])
            else:
                head = " ".join(_wrap_lines(part, max_cue)[:1])
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
            part = part[len(head):].strip()
        cand = f"{cur} {part}".strip()
        if measure(cand) <= max_cue or not cur:
            cur = cand
        else:
            chunks.append(cur)
            cur = part
    if cur:
        chunks.append(cur)

    # Chia thời gian của câu cho các mảnh theo số ký tự.
    total_chars = sum(len(c) for c in chunks) or 1
    duration = seg["end"] - seg["start"]
    cues = []
    t = seg["start"]
    for i, chunk in enumerate(chunks):
        share = duration * len(chunk) / total_chars
        share = max(share, MIN_CUE_SECONDS
                    if duration >= MIN_CUE_SECONDS * len(chunks) else share)
        end = seg["end"] if i == len(chunks) - 1 else min(t + share, seg["end"])
        cues.append({"start": round(t, 3), "end": round(end, 3),
                     "text": _wrapped(chunk)})
        t = end
    return cues


def generate_srt(segments: list[dict], output_path: str,
                 text_field: str = "text", line_words: int = 0,
                 max_lines: int = MAX_LINES_PER_CUE,
                 all_caps: bool = False) -> str:
    lines = []
    n = 0
    for seg in segments:
        for cue in split_for_display(seg, text_field, line_words=line_words,
                                     max_lines=max_lines, all_caps=all_caps):
            n += 1
            start_ts = format_timestamp(cue["start"])
            end_ts = format_timestamp(cue["end"])
            lines.append(f"{n}\n{start_ts} --> {end_ts}\n{cue['text']}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Đã ghi phụ đề: {output_path} ({n} dòng hiện từ "
                f"{len(segments)} câu)")
    return output_path


def generate_srt_styled(segments: list[dict], output_path: str,
                        text_field: str, style: dict | None) -> str:
    """Sinh .srt theo đúng kiểu phụ đề người dùng đã chọn.

    Gói lại ba tùy chọn ảnh hưởng tới NỘI DUNG dòng phụ đề (số chữ mỗi hàng,
    số hàng, viết hoa toàn bộ) để pipeline và trình chỉnh sửa không phải bóc
    tay từ dict kiểu — và không nơi nào quên mất một tùy chọn.
    """
    from autodub.media.subtitle import normalize_style

    s = normalize_style(style)
    return generate_srt(segments, output_path, text_field=text_field,
                        line_words=int(s["line_words"]),
                        max_lines=int(s["max_lines"]),
                        all_caps=bool(s["all_caps"]))
