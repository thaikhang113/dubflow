"""Hằng số dùng chung cho luồng lồng tiếng.

Gom về một chỗ để trang Tạo dự án, trang Xử lý hàng loạt và trang Trợ giúp
đều đọc cùng một nguồn, không ai chép lại của ai.
"""
from __future__ import annotations

SOURCE_LANGS: list[tuple[str, str]] = [
    ("Tiếng Trung (zh-CN)", "zh-CN"),
    ("Tiếng Anh (en-US)", "en-US"),
    ("Tiếng Trung - Hồng Kông (zh-HK)", "zh-HK"),
    ("Tiếng Trung - Đài Loan (zh-TW)", "zh-TW"),
]

ASR_ENGINES: list[tuple[str, str]] = [
    ("Whisper — nghe được mọi ngôn ngữ", "whisper"),
    ("Paraformer — chuyên tiếng Trung", "paraformer"),
]

WHISPER_MODELS: list[tuple[str, str]] = [
    ("Tự chọn (khuyên dùng)", "auto"),
    ("Nhanh nhất (tiny)", "tiny"),
    ("Nhanh (base)", "base"),
    ("Khá (small)", "small"),
    ("Chính xác (medium)", "medium"),
    ("Chính xác nhất (large-v3)", "large-v3"),
]

BG_MODES: list[tuple[str, str]] = [
    ("Tách giọng gốc, giữ nguyên nhạc nền", "demucs"),
    ("Giảm nhỏ tiếng gốc khi có lời thoại", "duck"),
    ("Bỏ hết âm thanh gốc", "none"),
]

SUBTITLE_MODES: list[tuple[str, str]] = [
    ("Không gắn phụ đề", "none"),
    ("Phụ đề rời, người xem tự bật", "soft"),
    ("Ghi thẳng vào hình", "burn"),
]

# Sáu phong cách dịch. Chuỗi ghi chú được nối thêm vào phần hướng dẫn dịch
# mà lõi xử lý đã đọc sẵn, nên không phải sửa gì trong lõi.
TRANSLATE_STYLES: list[tuple[str, str, str]] = [
    ("Tự nhiên, gần gũi (mặc định)", "natural", ""),
    ("Trang trọng", "formal",
     "Dịch trang trọng, lịch sự, dùng từ chuẩn mực; tránh tiếng lóng."),
    ("Sát nghĩa", "literal",
     "Bám sát nghĩa gốc, giữ nguyên cấu trúc câu khi tiếng Việt vẫn xuôi."),
    ("Sáng tạo", "creative",
     "Dịch thoáng, ưu tiên câu chữ mượt và hấp dẫn hơn là bám từng chữ."),
    ("Hài hước", "humorous",
     "Giữ giọng vui, dí dỏm; dùng cách nói đời thường của giới trẻ Việt."),
    ("Hợp mạng xã hội", "social",
     "Câu ngắn, nhịp nhanh, dễ nghe khi lướt; tránh câu dài lê thê."),
]

# Dung lượng thật của từng phần cần tải thêm, hiện trong Cài đặt và Trợ giúp.
MODEL_SIZES: dict[str, str] = {
    "tiny": "khoảng 75 MB",
    "base": "khoảng 145 MB",
    "small": "khoảng 480 MB",
    "medium": "khoảng 1.5 GB",
    "large-v3": "khoảng 3.1 GB",
    "paraformer": "khoảng 1.2 GB",
    "vieneu": "khoảng 0.9 GB",
}

# Bảng dịch lỗi kỹ thuật sang lời khuyên cho người dùng.
# Mỗi mục gồm: chuỗi nhận dạng, tiêu đề ngắn, việc cần làm.
FRIENDLY_ERRORS: list[tuple[str, str, str]] = [
    ("Thiếu cấu hình bắt buộc", "Thiếu cấu hình",
     "Mở trang Cài đặt và điền các mục còn trống, rồi chạy lại."),
    ("Không đủ Vox", "Hết Vox",
     "Mở trang Tài khoản để nạp thêm, rồi chạy tiếp thư mục dự án đang dở. "
     "Phần đã dịch xong vẫn được giữ nguyên, không phải trả tiền lần nữa."),
    ("Không kết nối được máy chủ", "Mất kết nối máy chủ",
     "Kiểm tra mạng rồi chạy tiếp thư mục dự án đang dở. Phần đã dịch xong "
     "vẫn được giữ nguyên."),
    ("đang bảo trì", "Máy chủ đang bảo trì",
     "Thử lại sau ít phút. Các bước chạy trên máy (nghe chép, giọng đọc, "
     "xuất video) vẫn dùng bình thường."),
    ("Thiết bị này đã bị khóa", "Thiết bị bị khóa",
     "Liên hệ hỗ trợ kèm mã máy hiện ở trang Tài khoản."),
    ("Máy chủ đang bận", "Máy chủ đang quá tải",
     "Chờ một chút rồi chạy tiếp thư mục dự án đang dở."),
    ("CUDA out of memory", "Card đồ họa không đủ bộ nhớ",
     "Đóng bớt ứng dụng đang dùng card đồ họa như trò chơi hoặc trình duyệt "
     "mở nhiều video, hoặc đổi Nhạc nền sang Giảm nhỏ tiếng gốc cho nhẹ hơn, "
     "rồi chạy tiếp thư mục dự án đang dở."),
    ("ffmpeg", "Máy chưa có FFmpeg",
     "Cài FFmpeg rồi thêm vào đường dẫn hệ thống, sau đó mở lại ứng dụng."),
    ("VieNeu worker", "Bộ giọng đọc gặp sự cố",
     "Chọn chạy tiếp thư mục dự án đang dở để tiếp tục từ chỗ dừng. Nếu vẫn "
     "lỗi, cài lại một lần: py scripts/setup_vieneu.py"),
    ("Chưa cài bộ giọng VieNeu", "Chưa cài bộ giọng",
     "Chạy một lần: py scripts/setup_vieneu.py — sau đó mở lại ứng dụng."),
    ("Không tìm thấy video gốc", "Không tìm thấy video gốc",
     "Thư mục này không còn video gốc, có thể video nằm ở nơi khác hoặc đã bị "
     "xóa. Chọn lại tệp video rồi bấm chạy — ứng dụng sẽ tiếp tục từ chỗ dừng "
     "và ghi nhớ vị trí video cho lần sau."),
    ("chưa có bản âm thanh đã ghép", "Chưa xuất video lần nào",
     "Bấm Xuất video một lần để tạo bản âm thanh, sau đó mới ghi riêng phụ "
     "đề được."),
]


def style_note(key: str) -> str:
    """Ghi chú phong cách dịch ứng với một mã, không có thì trả về chuỗi rỗng."""
    for _label, style_key, note in TRANSLATE_STYLES:
        if style_key == key:
            return note
    return ""


def friendly_error(message: str) -> tuple[str, str] | None:
    """Đổi thông báo lỗi kỹ thuật thành cặp (tiêu đề, việc cần làm)."""
    lowered = (message or "").lower()
    for needle, title, advice in FRIENDLY_ERRORS:
        if needle.lower() in lowered:
            return title, advice
    return None
