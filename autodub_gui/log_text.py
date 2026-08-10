"""Chữ nghĩa cho khung Nhật ký: kể lại tiến trình bằng lời thường.

Chỉ có HAI nguồn được lên Nhật ký của giao diện:

1. ``ProgressEvent`` của lõi — xương sống, bảo đảm mọi giai đoạn đều có dòng
   "đang làm" rồi "đã xong" theo thời gian thực (:class:`Narrator`).
2. Bảng thông báo soạn sẵn :data:`NOTICES` — những việc lõi ghi log mà người
   dùng cần biết (dùng lại kết quả cũ, số câu, chất lượng, nguyên nhân lỗi),
   đã viết lại bằng lời thường.

Mọi dòng log khác của lõi bị bỏ hẳn khỏi giao diện: tên model, đường dẫn,
tham số, id, cache, backend, vết lỗi... chỉ còn ra console và tệp log cho
người phát triển.

Thuần Python (không nạp Qt) nên kiểm thử được bằng pytest.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable

#: Mức riêng cho dòng "đã xong" — chỉ dùng để tô màu trong khung Nhật ký,
#: không bao giờ dùng để ghi log.
SUCCESS = 25


# --- Xương sống: kể lại từng bước của quá trình xử lý ------------------------

_STEP_START = {
    "acquire": "Đang lấy video",
    "extract": "Đang lấy âm thanh từ video",
    "separate": "Đang tách giọng nói khỏi nhạc nền",
    "asr": "Đang nghe và ghi lại lời thoại gốc",
    "translate": "Đang dịch sang tiếng Việt",
    "tts": "Đang tạo giọng đọc tiếng Việt",
    "merge_audio": "Đang ghép giọng đọc với nhạc nền",
    "merge_video": "Đang xuất video hoàn chỉnh",
    "content": "Đang viết tiêu đề, mô tả và hashtag",
}

_STEP_DONE = {
    "acquire": "Đã có video",
    "extract": "Đã lấy xong âm thanh",
    "separate": "Đã tách xong nhạc nền",
    "asr": "Đã ghi lại xong lời thoại gốc",
    "translate": "Đã dịch xong sang tiếng Việt",
    "tts": "Đã tạo xong giọng đọc",
    "merge_audio": "Đã ghép xong âm thanh",
    "merge_video": "Đã xuất xong video",
    "content": "Đã viết xong tiêu đề và mô tả",
}

_STEP_SKIP = {
    "extract": "Dùng lại âm thanh của lần chạy trước",
    "separate": "Không tách nhạc nền (theo lựa chọn của bạn)",
    "asr": "Dùng lại lời thoại đã ghi ở lần chạy trước",
    "translate": "Dùng lại bản dịch của lần chạy trước",
    "content": "Không viết tiêu đề và mô tả (theo lựa chọn của bạn)",
}

_STEP_ERROR = {
    "separate": "Không tách được nhạc nền — video sẽ chỉ còn giọng đọc",
    "translate": "Không dịch tự động được — cần bản dịch tay",
    "content": "Không viết được tiêu đề và mô tả (không ảnh hưởng video)",
}

#: Bước nào có đếm số thì hiện luôn số đã làm. Dòng tiến độ được ghi ĐÈ tại
#: chỗ trong khung Nhật ký nên video nghìn câu cũng chỉ chiếm một dòng —
#: người dùng luôn thấy đang ở câu thứ mấy trên tổng bao nhiêu.
_STEP_PROGRESS = {
    "translate": "Đang dịch: {current}/{total} câu",
    "tts": "Đang tạo giọng đọc: {current}/{total} câu",
    "merge_audio": "Đang cân âm lượng: {current}/{total} câu",
}


class Narrator:
    """Đổi ``ProgressEvent`` thành từng dòng Nhật ký, không nói lặp.

    Trả về ``(chữ, mức, là_dòng_tiến_độ)``. Dòng tiến độ được khung Nhật ký
    ghi đè tại chỗ nên video nghìn câu cũng không làm ngập Nhật ký.
    """

    def __init__(self) -> None:
        self._said: set[tuple[str, str]] = set()

    def reset(self) -> None:
        self._said.clear()

    def narrate(self, event) -> tuple[str, int, bool] | None:
        step = getattr(event, "step", "")
        status = getattr(event, "status", "")
        if step == "done":
            return None            # dòng tổng kết đã có trong NOTICES
        if status == "progress":
            template = _STEP_PROGRESS.get(step)
            total = getattr(event, "total", 0)
            if not template or not total:
                return None
            text = template.format(current=getattr(event, "current", 0),
                                   total=total)
            return text, logging.INFO, True

        table, level = {
            "start": (_STEP_START, logging.INFO),
            "done": (_STEP_DONE, SUCCESS),
            "skip": (_STEP_SKIP, logging.INFO),
            "error": (_STEP_ERROR, logging.WARNING),
        }.get(status, (None, logging.INFO))
        if table is None:
            return None
        text = table.get(step)
        if text is None:
            return None
        key = (step, status)
        if key in self._said:
            return None
        self._said.add(key)
        # Bước xong rồi thì cho phép nói lại "đang chạy" ở lần sau (trình
        # chỉnh sửa xuất video nhiều lượt trên cùng một khung Nhật ký).
        if status in ("done", "error", "skip"):
            self._said.discard((step, "start"))
        return text, level, False


# --- Bảng thông báo soạn sẵn -------------------------------------------------
# Thứ tự có ý nghĩa: khớp dòng nào trước thì dùng dòng đó. ``None`` = biết rõ
# đây là log kỹ thuật, bỏ luôn (kể cả khi là cảnh báo). Chỗ nào cần tính toán
# (đổi giây thành phút:giây) thì đặt một hàm nhận ``re.Match`` thay cho chuỗi.


def _clock(seconds: str) -> str:
    """``"131.4"`` → ``"2:11"`` — mốc thời gian đọc được như trên trình phát."""
    total = int(float(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _asr_segment_line(match: re.Match) -> str:
    """Một câu vừa nghe được: số câu, mốc trong video, và lời thoại gốc.

    Đây là dòng chạy realtime trong lúc nghe — người dùng thấy máy đang nghe
    tới đâu và nghe ra chữ gì, thay vì một khung Nhật ký im lặng vài phút.
    """
    sid, start, _end, text = match.groups()
    text = text.strip().rstrip(".…").strip()
    return f"Câu {sid} · {_clock(start)} — {text}"


_Template = str | None | Callable[[re.Match], str]

_RAW_NOTICES: list[tuple[str, _Template, int]] = [
    # -- Lấy video ---------------------------------------------------------
    (r"Đang tải video về máy",
     "Đang tải video từ đường dẫn bạn nhập", logging.INFO),
    (r"Tải trước video kế tiếp",
     "Đang tải trước video kế tiếp trong hàng chờ", logging.INFO),
    (r"Tải trước quá lâu",
     "Tải trước lâu hơn bình thường — video sẽ được tải lại", logging.WARNING),
    (r"Tải trước thất bại",
     "Không tải trước được video kế tiếp — sẽ tải lại khi tới lượt",
     logging.WARNING),

    # -- Nghe lời thoại ----------------------------------------------------
    # Bản chép lời chạy realtime: mỗi câu nghe được là một dòng, người dùng
    # nhìn thấy máy đang nghe tới đâu và nghe ra chữ gì (giữ nguyên tiếng gốc
    # — đó chính là thứ cần nhìn để biết máy nghe đúng hay sai ngôn ngữ).
    (r"^Segment (\d+): \[([\d.]+)s-([\d.]+)s\] (.+)$",
     _asr_segment_line, logging.INFO),
    (r"Dùng lại lời thoại đã nghe từ lần chạy trước \((\d+) câu",
     "Dùng lại {0} câu thoại đã nghe ở lần chạy trước", logging.INFO),
    (r"Nghe xong: video có (\d+) câu",
     "Đã nghe xong: video có {0} câu thoại", SUCCESS),
    (r"Transcript cũ hỏng",
     "Bản ghi lời thoại cũ không dùng được — nghe lại từ đầu", logging.WARNING),
    (r"Ngôn ngữ tự nhận dạng", None, logging.INFO),
    (r"Không nhận dạng được lời nói nào",
     "Không nghe thấy lời nói nào trong video — hãy kiểm tra lại ngôn ngữ gốc",
     logging.ERROR),

    # -- Dịch ---------------------------------------------------------------
    (r"Dùng lại bản dịch đã có",
     "Dùng lại bản dịch của lần chạy trước", logging.INFO),
    (r"Dùng lại phân tích ngữ cảnh video",
     "Dùng lại phần tìm hiểu nội dung video của lần chạy trước", logging.INFO),
    (r"Đang dịch (\d+) câu sang tiếng Việt",
     "Đang dịch {0} câu sang tiếng Việt", logging.INFO),
    (r"Đã dịch \d+/\d+ câu", None, logging.INFO),      # thanh tiến độ đã có
    (r"Không đủ Vox|INSUFFICIENT_CREDIT",
     "Hết Vox — mở trang Tài khoản để nạp thêm rồi chạy tiếp",
     logging.WARNING),
    (r"Không kết nối được máy chủ",
     "Mất kết nối tới máy chủ dịch — kiểm tra mạng rồi chạy tiếp",
     logging.WARNING),
    (r"Máy chủ đang bận",
     "Máy chủ đang quá tải, chờ một chút rồi thử lại", logging.WARNING),
    (r"Lượt dịch này tốn ([\d.,]+) Vox",
     "Lượt dịch này tốn {0} Vox", logging.INFO),
    (r"câu dịch còn lẫn tiếng Trung — dịch lại",
     "Đang dịch lại vài câu còn lẫn tiếng Trung", logging.INFO),
    (r"(\d+) câu vẫn còn lẫn tiếng Trung",
     "Còn {0} câu chưa dịch sạch tiếng Trung — nên sửa tay trong Chỉnh sửa",
     logging.WARNING),
    (r"[Dd]ịch tự động lỗi .* chuyển sang dịch tay",
     "Dịch tự động gặp lỗi — chuyển sang chờ bạn dịch tay", logging.WARNING),
    (r"Rà soát bản dịch lỗi|Soát lại câu .* lỗi", None, logging.INFO),
    (r"Soát lại bản dịch: mọi câu đều đạt",
     "Đã soát lại bản dịch: mọi câu đều đạt", SUCCESS),
    (r"Soát lại bản dịch: (\d+) câu cần sửa",
     "Đang soát lại {0} câu dịch chưa ổn", logging.INFO),
    (r"Soát lại bản dịch: đã sửa xong (\d+)/(\d+)",
     "Đã soát và sửa {0}/{1} câu dịch", SUCCESS),
    (r"Soát lại bản dịch: bản dịch lại không tốt hơn", None, logging.INFO),
    (r"Video đang chờ bản dịch",
     "Video đang chờ bản dịch — làm theo hướng dẫn ba bước hiện trên màn hình",
     logging.WARNING),
    (r"Lượt dịch dùng .* token", None, logging.INFO),

    # -- Nhạc nền ----------------------------------------------------------
    (r"Đang tách giọng nói gốc ra khỏi nhạc nền",
     "Đang tách giọng nói khỏi nhạc nền — video dài sẽ mất vài phút",
     logging.INFO),
    (r"Vocal separation unavailable",
     "Không tách được nhạc nền — video sẽ chỉ còn giọng đọc", logging.WARNING),

    # -- Giọng đọc ----------------------------------------------------------
    (r"Bắt đầu tạo giọng đọc cho (\d+) câu",
     "Đang tạo giọng đọc cho {0} câu — đây là bước lâu nhất", logging.INFO),
    (r"Giọng đọc: (\S+) \+ (\d+) giọng riêng.*?— (\d+)/(\d+) câu cần đọc"
     r".*?chạy (\d+) luồng",
     "Giọng «{0}» và {1} giọng riêng, {2}/{3} câu cần đọc, {4} luồng cùng lúc",
     logging.INFO),
    (r"Giọng đọc: (\S+) — (\d+)/(\d+) câu cần đọc.*?chạy (\d+) luồng",
     "Giọng «{0}», {1}/{2} câu cần đọc, {3} luồng cùng lúc", logging.INFO),
    (r"Chỉnh tốc độ giọng đọc ([\d.]+)x",
     "Đang chỉnh tốc độ giọng đọc thành {0}x cho cả video", logging.INFO),
    (r"Cache giọng đọc cũ",
     "Giọng đọc của lần chạy trước không dùng lại được — sẽ đọc lại từ đầu",
     logging.WARNING),
    (r"Đã lưu (\d+) câu vào",
     "Đã lưu {0} câu vừa sửa", SUCCESS),
    (r"Câu (\d+): giọng riêng",
     "Đã đổi giọng riêng cho câu {0}", logging.INFO),

    # -- Âm thanh và hình --------------------------------------------------
    (r"Đang cân chỉnh âm lượng",
     "Đang cân âm lượng các câu cho đều nhau", logging.INFO),
    (r"Sắp xếp thời gian các câu",
     "Đang sắp lại thời gian các câu cho khớp hình", logging.INFO),
    (r"Đang ghép giọng đọc với nhạc nền",
     "Đang ghép giọng đọc với nhạc nền", logging.INFO),
    (r"Xuất video bằng: CPU",
     "Máy này xuất video bằng CPU — chậm hơn, hãy chờ thêm một chút",
     logging.INFO),
    (r"Xuất video bằng: (NVIDIA|Intel|AMD)\S*\s*(\S*)",
     "Máy này xuất video bằng card đồ họa {0} — nhanh hơn nhiều", logging.INFO),
    (r"Đang xuất video hoàn chỉnh",
     "Đang xuất video hoàn chỉnh — bước này chạy lâu", logging.INFO),
    (r"Làm chậm video .* thất bại|Không dùng được bản video đã làm chậm",
     "Không làm chậm được video — giữ nguyên tốc độ gốc", logging.WARNING),
    (r"Đã xuất xong video",
     "Đã xuất xong video", SUCCESS),
    (r"Đã ghi lại phụ đề vào video",
     "Đã ghi xong phụ đề vào video", SUCCESS),
    (r"Đã dựng đoạn xem thử câu (\d+)",
     "Đã dựng xong đoạn xem thử câu {0}", SUCCESS),

    # -- Phụ đề -------------------------------------------------------------
    (r"Đang canh phụ đề",
     "Đang canh phụ đề chạy khớp giọng đọc", logging.INFO),
    (r"Canh phụ đề xong: (\d+)/(\d+)",
     "Đã canh phụ đề: {0}/{1} câu khớp chính xác", SUCCESS),
    (r"Không canh được phụ đề|Không tạo được phụ đề kiểu cụm chữ",
     "Không canh được phụ đề theo giọng đọc — dùng phụ đề cả câu",
     logging.WARNING),
    (r"Phụ đề kiểu cụm chữ", None, logging.INFO),
    (r"Đã ghi phụ đề", None, logging.INFO),

    # -- Tiêu đề, mô tả, ảnh bìa -------------------------------------------
    (r"Đang viết tiêu đề, mô tả và hashtag",
     "Đang viết tiêu đề, mô tả và hashtag để đăng bài", logging.INFO),
    (r"Đã viết xong phần đăng bài",
     "Đã viết xong tiêu đề, mô tả và hashtag", SUCCESS),
    (r"Bỏ qua tạo tiêu đề và mô tả|Bỏ qua nội dung đăng bài",
     "Không viết tiêu đề và mô tả (theo lựa chọn của bạn)", logging.INFO),
    (r"Đang vẽ ảnh bìa",
     "Đang vẽ ảnh bìa", logging.INFO),
    (r"Đã tạo ảnh bìa (\S+)",
     "Đã vẽ xong ảnh bìa {0}", SUCCESS),
    (r"Bỏ qua vẽ ảnh bìa",
     "Không vẽ ảnh bìa (chưa bật trong Cài đặt)", logging.INFO),
    (r"Tạo ảnh bìa .* lỗi|Ảnh bìa .* không trả về ảnh",
     "Không vẽ được ảnh bìa (không ảnh hưởng video)", logging.WARNING),
    (r"Tạo nội dung đăng bài lỗi|Viết nội dung bằng .* lỗi"
     r"|Không đọc được nội dung đăng bài",
     "Không viết được tiêu đề và mô tả (không ảnh hưởng video)",
     logging.WARNING),
    (r"Đã tải ảnh bìa gốc|Đã lấy khung hình tham chiếu", None, logging.INFO),

    # -- Kiểm tra chất lượng và tổng kết -----------------------------------
    (r"Kiểm tra chất lượng: (\d+)/(\d+) câu ổn — còn (\d+) câu chồng tiếng",
     "Kiểm tra chất lượng: {0}/{1} câu tốt, {2} câu bị chồng tiếng nhẹ — "
     "nghe thử trước khi đăng", logging.WARNING),
    (r"Kiểm tra chất lượng: (\d+)/(\d+) câu chuẩn",
     "Kiểm tra chất lượng: {0}/{1} câu chuẩn, số còn lại chỉ lệch nhẹ",
     logging.INFO),
    (r"Kiểm tra chất lượng: tất cả các câu đều khớp",
     "Kiểm tra chất lượng: mọi câu đều khớp đẹp", SUCCESS),
    (r"Hoàn tất! Lồng tiếng xong (\d+) câu trong (.+?) —",
     "Hoàn tất: đã lồng tiếng {0} câu trong {1}", SUCCESS),
    (r"Đã tự dọn tệp trung gian, giải phóng ([\d.]+) MB",
     "Đã dọn tệp tạm, giải phóng {0} MB", logging.INFO),
]

NOTICES: list[tuple[re.Pattern, _Template, int]] = [
    (re.compile(pattern, re.IGNORECASE), template, level)
    for pattern, template, level in _RAW_NOTICES
]


# --- Dọn chữ và chặn log kỹ thuật -------------------------------------------

#: Dấu hiệu của log dành cho lập trình viên. Một dòng cảnh báo lạ có chứa bất
#: kỳ dấu hiệu nào trong đây thì không được lên Nhật ký của người dùng.
_TECH_RE = re.compile(
    r"""(
      [A-Za-z]:[\\/]                                  # C:\ đường dẫn
    | [\\/][\w.-]+[\\/]                               # /thư/mục/
    | \.(?:json|wav|mp3|mp4|mkv|webm|srt|ass|txt|log|py|exe|zip|onnx|pt|jpg|png)\b
    | traceback | exc_info | errno | winerror | 0x[0-9a-f]{4}
    | \b(?:vram|gpu|cpu|cuda|cublas|cudnn|onnx|nvenc|dll|venv|api|http|url
        |json|sdk|ram|id|uuid|regex|stdout|stderr|subprocess|timeout)\b
    | ffmpeg | ffprobe | yt-dlp | ytdlp | demucs | whisper | paraformer
    | vieneu | sherpa | playwright | pydub | torch | pyinstaller
    | gemini | openai | openrouter | anthropic | deepseek | claude | gpt-
    | fingerprint | idempotency | jobid | saas | bearer
    | atempo | loudnorm | highpass | filtergraph | setpts | force_style
    | fontsdir | playres | lufs | \bcps\b | kv\s?cache | keep.?alive
    | \bcache\b | \bdebug\b | \bworker\b | \bthread\b | \bluồng\b
    | \bmodel\b | \bmô\s?hình\b | \btoken\b | \bendpoint\b | \bembedding\b
    | \benroll\b | \bprompt\b | \bschema\b | \bbatch\b | \blô\b
    | \bstep\s*\d | \bsegment\b | \bcheckpoint\b
    | [{}\[\]<>]                                      # bãi dữ liệu thô
    )""",
    re.IGNORECASE | re.VERBOSE)

_PARENS = re.compile(r"\s*\([^()]*\)")
_PATHS = re.compile(r"[A-Za-z]:[\\/][^\s,;]*|(?:[\w.-]+[\\/])+[\w.-]+")


def _tidy(text: str) -> str:
    """Bỏ chú thích trong ngoặc và đường dẫn, gộp khoảng trắng."""
    text = _PARENS.sub("", text)
    text = _PATHS.sub("", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return " ".join(text.split()).strip(" .,;:-—")


def notice_for(message: str, levelno: int) -> tuple[str, int] | None:
    """Dòng Nhật ký cho một bản ghi log của lõi, hoặc ``None`` nếu nên bỏ.

    Chỉ những gì có trong :data:`NOTICES` được đi qua. Cảnh báo và lỗi lạ
    (chưa kịp soạn lời) vẫn được giữ nếu dọn xong còn đọc hiểu được — thà
    một dòng hơi khô còn hơn ẩn mất một cảnh báo thật.
    """
    text = " ".join(str(message).split())
    if not text or set(text) <= {"=", "-", " "}:
        return None
    for pattern, template, level in NOTICES:
        match = pattern.search(text)
        if match is None:
            continue
        if template is None:
            return None
        if callable(template):
            return template(match), level
        groups = [g for g in match.groups() if g is not None]
        try:
            return template.format(*groups), level
        except (IndexError, KeyError):
            return template, level
    if levelno < logging.WARNING:
        return None
    tidied = _tidy(text)
    if not tidied or len(tidied) < 12 or _TECH_RE.search(tidied):
        return None
    return tidied, levelno


def error_line(message: str) -> tuple[str, int]:
    """Một dòng lỗi cho Nhật ký khi cả lượt chạy phải dừng.

    Ưu tiên lời khuyên đã soạn trong ``dub_constants``; không khớp thì dọn
    sạch thông báo gốc rồi kèm chỉ dẫn xem chi tiết ở hộp thoại.
    """
    from autodub_gui.dub_constants import friendly_error

    friendly = friendly_error(message or "")
    if friendly is not None:
        title, advice = friendly
        return f"Dừng lại: {title}. {advice}", logging.ERROR
    notice = notice_for(message or "", logging.ERROR)
    if notice is not None:
        return f"Dừng lại: {notice[0]}", logging.ERROR
    return ("Dừng lại vì một lỗi ngoài dự tính — xem chi tiết ở hộp thoại "
            "vừa hiện. Tiến độ đã lưu vẫn còn, bạn có thể chạy tiếp.",
            logging.ERROR)
