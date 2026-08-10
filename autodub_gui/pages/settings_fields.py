"""Khai báo mọi mục trong trang Cài đặt.

Mỗi mục được mô tả một lần ở đây rồi dùng lại cho việc dựng ô nhập, nạp giá
trị, lưu lại và khôi phục mặc định. Nhờ vậy không bao giờ có chuyện thêm ô
mới mà quên lưu, hoặc đổi tên khóa ở một chỗ mà quên chỗ kia.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from autodub.media.subtitle import PRESET_CHOICES
from autodub_gui import dub_constants as consts
from autodub_gui import tokens

# Tên sáu thẻ của trang Cài đặt. TAB_BASIC phải luôn đứng đầu vì
# focus_display_name() nhảy thẳng về thẻ số 0.
TAB_BASIC = "Cơ bản"
TAB_VOICE = "Giọng đọc"
TAB_SUBTITLE = "Phụ đề"
TAB_PERF = "Hiệu suất"
#: Thẻ "Dịch thuật" — mọi API Key đã lên máy chủ, ở đây chỉ còn NGỮ CẢNH:
#: những gì người dùng biết về video mà máy chủ không thể tự đoán.
TAB_TRANSLATE = "Dịch thuật"
TAB_ADVANCED = "Nâng cao"

TABS = (TAB_BASIC, TAB_VOICE, TAB_SUBTITLE, TAB_PERF, TAB_TRANSLATE, TAB_ADVANCED)

# Ba thẻ Giọng đọc, Phụ đề và Dịch thuật đã tách thành trang Công cụ riêng
# trên thanh bên, nên trang Cài đặt chỉ còn giữ những thẻ dưới đây để khỏi trùng.
SETTINGS_TABS = (TAB_BASIC, TAB_PERF, TAB_ADVANCED)

# Kiểu ô nhập
COMBO = "combo"
TEXT = "text"
CHECK = "check"
SLIDER = "slider"
NUMBER = "number"
FOLDER = "folder"
FILE = "file"
MULTILINE = "multiline"
FONT = "font"
COLOR = "color"


@dataclass
class Field:
    """Một mục cấu hình: khóa trong tệp cấu hình và cách hiển thị của nó."""

    key: str
    kind: str
    label: str
    tab: str
    group: str
    default: str = ""
    hint: str = ""
    placeholder: str = ""
    suffix: str = ""
    minimum: float = 0.0
    maximum: float = 1.0
    step: float = 0.1
    decimals: int = 2
    options: list[tuple[str, str]] = field(default_factory=list)


_QUALITY_PRESETS = [
    ("Nhanh — ưu tiên tốc độ", "fast"),
    ("Cân bằng (khuyên dùng)", "balanced"),
    ("Chất lượng cao — chạy chậm hơn", "quality"),
]

_SUBTITLE_POSITIONS = [
    ("Dưới màn hình", "bottom"),
    ("Giữa màn hình", "middle"),
    ("Trên màn hình", "top"),
]

_SUBTITLE_DISPLAY = [
    ("Hiện cả câu", "sentence"),
    ("Hiện theo cụm chữ, sáng dần", "karaoke"),
]

_SUBTITLE_BOX = [
    ("Chỉ viền chữ", "none"),
    ("Khối nền mờ sau chữ", "box"),
]

_KARAOKE_EFFECTS = [
    ("Chữ bật lên", "pop"),
    ("Mờ dần", "fade"),
    ("Đổi màu theo lời đọc", "karaoke"),
    ("Không hiệu ứng", "none"),
]


# Toàn bộ các mục, xếp theo thẻ rồi theo nhóm.
FIELDS: tuple[Field, ...] = (
    # -- Thẻ Cơ bản ---------------------------------------------------
    Field("QUALITY_PRESET", COMBO, "Mức chất lượng", TAB_BASIC,
          "Chất lượng tổng thể", "balanced",
          "Chọn một mức là đủ, ứng dụng tự đặt các chi tiết bên dưới. "
          "Ô nào bạn tự chỉnh thì giá trị của bạn được ưu tiên.",
          options=_QUALITY_PRESETS),
    Field("ASR_ENGINE", COMBO, "Bộ nhận dạng", TAB_BASIC,
          "Nghe và chép lời video gốc", "whisper",
          "Whisper nghe được mọi ngôn ngữ. Paraformer chính xác hơn với "
          "video tiếng Trung nhưng phải cài thêm một lần.",
          options=consts.ASR_ENGINES),
    Field("WHISPER_MODEL", COMBO, "Độ chính xác", TAB_BASIC,
          "Nghe và chép lời video gốc", "auto",
          "Mức càng cao nghe càng đúng nhưng chạy lâu hơn và tải về nặng hơn.",
          options=consts.WHISPER_MODELS),
    Field("DEFAULT_SOURCE_LANG", COMBO, "Ngôn ngữ gốc mặc định", TAB_BASIC,
          "Nghe và chép lời video gốc", "zh-CN",
          "Ngôn ngữ được chọn sẵn mỗi khi bạn tạo dự án mới.",
          options=consts.SOURCE_LANGS),
    Field("VIDEO_SPEED", SLIDER, "Tốc độ video", TAB_BASIC,
          "Tốc độ", "1.00",
          "Làm chậm toàn bộ video để giọng tiếng Việt có đủ chỗ. "
          "0.82 nghĩa là video dài thêm khoảng 22 phần trăm. "
          "1.00 là giữ nguyên.",
          suffix="x", minimum=0.5, maximum=1.0, step=0.02),
    Field("VOICE_SPEED", SLIDER, "Tốc độ giọng đọc", TAB_BASIC,
          "Tốc độ", "1.00",
          "1.00 là tốc độ tự nhiên. Tăng lên khi câu tiếng Việt dài hơn câu "
          "gốc và bị chồng sang câu sau.",
          suffix="x", minimum=0.5, maximum=2.0, step=0.05),
    Field("OUTPUT_DIR", FOLDER, "Thư mục lưu video", TAB_BASIC,
          "Nơi lưu kết quả", "./output",
          "Mọi dự án sẽ được lưu vào thư mục này.",
          placeholder="./output"),
    Field("DISPLAY_NAME", TEXT, "Tên hiển thị", TAB_BASIC, "Hiển thị", "",
          "Tên này hiện ở lời chào trên Trang chủ. Để trống thì dùng tên "
          "đăng nhập của máy.",
          placeholder="ví dụ: Dylan"),

    # (Thẻ Giọng đọc không khai báo ô ở đây — toàn bộ thẻ là thư viện giọng
    #  riêng, xem pages/voice_library.py. VIENEU_STYLE render trong đó.)

    # -- Thẻ Phụ đề ---------------------------------------------------
    Field("SUBTITLE_MODE", COMBO, "Kiểu phụ đề mặc định", TAB_SUBTITLE,
          "Mặc định", "none",
          "Kiểu được chọn sẵn mỗi khi bạn tạo dự án mới.",
          options=consts.SUBTITLE_MODES),
    Field("SUBTITLE_PRESET", COMBO, "Bộ kiểu chữ", TAB_SUBTITLE,
          "Mặc định", "clean",
          "Chọn một bộ có sẵn là xong. Muốn tự quyết từng thông số thì chọn "
          "Tự chỉnh rồi sửa các ô bên dưới.",
          options=PRESET_CHOICES),
    Field("SUBTITLE_POSITION", COMBO, "Vị trí chữ", TAB_SUBTITLE,
          "Kiểu chữ", "bottom", "Chữ nằm ở đâu trên khung hình.",
          options=_SUBTITLE_POSITIONS),
    Field("SUBTITLE_FONT", FONT, "Phông chữ", TAB_SUBTITLE, "Kiểu chữ", "",
          "Chỉ liệt kê phông trong thư mục phông của dự án, vì chỉ những "
          "phông này mới chắc chắn hiện đúng trên mọi máy."),
    Field("SUBTITLE_FONT_SIZE", NUMBER, "Cỡ chữ", TAB_SUBTITLE, "Kiểu chữ",
          "22", "Cỡ chữ phụ đề trên video.",
          minimum=8, maximum=96, step=1, decimals=0),
    Field("SUBTITLE_BOLD", CHECK, "Chữ đậm", TAB_SUBTITLE, "Kiểu chữ", "true",
          "Chữ đậm dễ đọc hơn khi video được xem trên điện thoại."),
    Field("SUBTITLE_MARGIN_V", NUMBER, "Cách mép màn hình", TAB_SUBTITLE,
          "Kiểu chữ", "40", "Khoảng cách từ chữ tới mép trên hoặc mép dưới.",
          suffix=" điểm ảnh", minimum=0, maximum=400, step=5, decimals=0),
    Field("SUBTITLE_OUTLINE", NUMBER, "Độ dày viền chữ", TAB_SUBTITLE,
          "Kiểu chữ", "2",
          "Viền giúp chữ đọc được cả khi nền video sáng.",
          minimum=0, maximum=8, step=1, decimals=0),
    Field("SUBTITLE_SHADOW", NUMBER, "Độ đổ bóng", TAB_SUBTITLE, "Kiểu chữ",
          "0", "Bóng nhẹ phía sau chữ. Đặt 0 để tắt.",
          minimum=0, maximum=8, step=1, decimals=0),
    Field("SUBTITLE_COLOR", COLOR, "Màu chữ", TAB_SUBTITLE, "Kiểu chữ",
          tokens.SUBTITLE_TEXT_DEFAULT, "Màu của chữ phụ đề."),
    Field("SUBTITLE_OUTLINE_COLOR", COLOR, "Màu viền chữ", TAB_SUBTITLE,
          "Kiểu chữ", tokens.SUBTITLE_OUTLINE_DEFAULT,
          "Màu viền bao quanh chữ."),
    Field("SUBTITLE_BOX", COMBO, "Nền sau chữ", TAB_SUBTITLE, "Nền chữ",
          "none",
          "Khối nền mờ giúp chữ đọc được trên nền video nhiều chi tiết.",
          options=_SUBTITLE_BOX),
    Field("SUBTITLE_BOX_COLOR", COLOR, "Màu nền", TAB_SUBTITLE, "Nền chữ",
          tokens.SUBTITLE_BOXFILL_DEFAULT, "Màu của khối nền sau chữ."),
    Field("SUBTITLE_BOX_OPACITY", NUMBER, "Độ đục của nền", TAB_SUBTITLE,
          "Nền chữ", "60",
          "0 là trong suốt hẳn, 100 là che kín hoàn toàn.",
          suffix=" phần trăm", minimum=0, maximum=100, step=5, decimals=0),
    Field("SUBTITLE_LINE_WORDS", NUMBER, "Số chữ mỗi dòng", TAB_SUBTITLE,
          "Cách ngắt dòng", "0",
          "Đặt 0 để ứng dụng tự ngắt dòng theo độ dài câu. Video dọc nên đặt "
          "4 tới 6 chữ cho chữ khỏi tràn mép.",
          minimum=0, maximum=20, step=1, decimals=0),
    Field("SUBTITLE_MAX_LINES", NUMBER, "Số dòng tối đa", TAB_SUBTITLE,
          "Cách ngắt dòng", "2",
          "Mỗi lần hiện nhiều nhất bấy nhiêu dòng chữ.",
          minimum=1, maximum=4, step=1, decimals=0),
    Field("SUBTITLE_ALL_CAPS", CHECK, "Viết hoa toàn bộ", TAB_SUBTITLE,
          "Cách ngắt dòng", "false",
          "Chữ hoa hết nhìn mạnh hơn nhưng đọc chậm hơn, hợp video ngắn."),
    Field("SUBTITLE_DISPLAY", COMBO, "Cách hiện chữ", TAB_SUBTITLE,
          "Hiện theo cụm chữ", "sentence",
          "Hiện cả câu là kiểu phụ đề thường. Hiện theo cụm chữ giống lời "
          "bài hát, từng cụm sáng lên theo lời đọc.",
          options=_SUBTITLE_DISPLAY),
    Field("KARAOKE_WORDS_PER_CUE", NUMBER, "Số chữ mỗi cụm", TAB_SUBTITLE,
          "Hiện theo cụm chữ", "3",
          "Mỗi lần hiện bao nhiêu chữ khi dùng kiểu sáng dần.",
          minimum=1, maximum=5, step=1, decimals=0),
    Field("KARAOKE_EFFECT", COMBO, "Hiệu ứng", TAB_SUBTITLE,
          "Hiện theo cụm chữ", "pop", "Cách chữ xuất hiện.",
          options=_KARAOKE_EFFECTS),
    Field("KARAOKE_HIGHLIGHT_COLOR", COLOR, "Màu chữ đang đọc", TAB_SUBTITLE,
          "Hiện theo cụm chữ", tokens.SUBTITLE_HIGHLIGHT_DEFAULT,
          "Màu tô lên cụm chữ đang được đọc."),
    Field("KARAOKE_ALIGNMENT", CHECK, "Canh chữ theo lời đọc", TAB_SUBTITLE,
          "Hiện theo cụm chữ", "true",
          "Bật để từng chữ sáng lên đúng lúc được đọc."),

    # -- Thẻ Hiệu suất ------------------------------------------------
    Field("PARALLEL_WORKERS", NUMBER, "Số việc chạy cùng lúc", TAB_PERF,
          "Hiệu năng", "0",
          "Đặt 0 để ứng dụng tự chọn theo cấu hình máy. Chỉ đổi khi bạn biết "
          "rõ mình cần gì.", minimum=0, maximum=32, step=1, decimals=0),
    Field("VIENEU_MAX_WORKERS", NUMBER, "Số giọng chạy cùng lúc",
          TAB_PERF, "Hiệu năng", "0",
          "Đặt 0 để tự chọn. Mỗi luồng tốn khoảng 1,5 GB bộ nhớ.",
          minimum=0, maximum=8, step=1, decimals=0),
    Field("HQ_BACKGROUND", CHECK, "Giữ nhạc nền chất lượng cao",
          TAB_PERF, "Hiệu năng", "true",
          "Tắt đi thì chạy nhanh hơn nhưng nhạc nền kém hơn một chút."),

    # -- Thẻ Nâng cao -------------------------------------------------
    Field("TRANSLATE_ANALYSIS", CHECK, "Đọc hiểu video trước khi dịch",
          TAB_ADVANCED, "Chất lượng dịch", "true",
          "Ứng dụng đọc qua toàn bộ lời thoại để nắm bối cảnh, nhờ vậy xưng "
          "hô và thuật ngữ nhất quán hơn."),
    Field("TRANSLATE_REVIEW", CHECK, "Rà lại bản dịch một lượt nữa",
          TAB_ADVANCED, "Chất lượng dịch", "true",
          "Chạy thêm một lượt để sửa câu ngượng. Tốn thêm thời gian."),
    Field("TRANSLATE_CPS_BUDGET", SLIDER, "Số chữ mỗi giây", TAB_ADVANCED,
          "Chất lượng dịch", "12.5",
          "Giới hạn độ dài câu dịch để đọc kịp. Càng nhỏ thì câu càng ngắn "
          "gọn.", minimum=8.0, maximum=20.0, step=0.5, decimals=1),
    Field("VOICE_POSTPROCESS", CHECK, "Làm đều độ lớn giọng đọc",
          TAB_ADVANCED, "Xử lý âm thanh", "true",
          "Cân bằng để câu nào cũng nghe rõ như nhau, không câu to câu nhỏ."),
    Field("VOICE_TARGET_LUFS", SLIDER, "Độ lớn giọng đọc", TAB_ADVANCED,
          "Xử lý âm thanh", "-16.0",
          "Càng gần 0 thì giọng càng to. Mức thường dùng cho video là -16.",
          suffix=" dB", minimum=-24.0, maximum=-10.0, step=0.5, decimals=1),
    Field("BG_DUCK_VOICE_DB", SLIDER, "Giảm nhạc nền khi có lời",
          TAB_ADVANCED, "Xử lý âm thanh", "-8.0",
          "Nhạc nền tự nhỏ đi bấy nhiêu mỗi khi có lời thoại tiếng Việt.",
          suffix=" dB", minimum=-24.0, maximum=0.0, step=0.5, decimals=1),
    Field("SOFT_TIMING_FIT", CHECK, "Tự căn lại thời điểm từng câu",
          TAB_ADVANCED, "Căn thời gian", "true",
          "Dịch nhẹ thời điểm các câu để lời thoại không chồng lên nhau."),
    Field("TIMING_MAX_DRIFT_S", SLIDER, "Cho phép lệch tối đa", TAB_ADVANCED,
          "Căn thời gian", "1.5",
          "Mỗi câu được dịch đi nhiều nhất bấy nhiêu giây so với bản gốc.",
          suffix=" giây", minimum=0.0, maximum=5.0, step=0.1, decimals=1),
    Field("TIMING_MIN_GAP_S", SLIDER, "Khoảng nghỉ tối thiểu", TAB_ADVANCED,
          "Căn thời gian", "0.08",
          "Khoảng lặng ngắn giữa hai câu liền nhau cho dễ nghe.",
          suffix=" giây", minimum=0.0, maximum=1.0, step=0.01),
    Field("TIMING_MAX_ATEMPO", SLIDER, "Mức nén lời tối đa", TAB_ADVANCED,
          "Căn thời gian", "1.15",
          "Câu quá dài có thể được đọc nhanh hơn tối đa bấy nhiêu lần.",
          suffix="x", minimum=1.0, maximum=1.6, step=0.01),
    Field("AUTO_CLEAN_INTERMEDIATES", CHECK, "Tự dọn tệp trung gian sau khi xuất",
          TAB_ADVANCED, "Dung lượng đĩa", "false",
          "Xuất video xong là dọn ngay các tệp trung gian nặng. Tiết kiệm "
          "đĩa, nhưng dự án đó sẽ không sửa từng câu hay xuất lại được nữa."),

    # -- Thẻ Dịch thuật ------------------------------------------------
    # Mô hình, lời nhắc và API Key nằm trên máy chủ VoxDub. Người dùng không
    # chọn nơi dịch nữa — thứ họ đóng góp được là NGỮ CẢNH: video nói về gì,
    # xưng hô ra sao, thuật ngữ nào phải dịch cố định. Máy chủ tự phân tích
    # được phần lớn, nhưng người làm kênh biết rõ hơn máy.
    Field("TRANSLATE_ENABLED", CHECK, "Bật dịch tự động", TAB_TRANSLATE,
          "Dịch tự động", "true",
          "Bật: máy chủ dịch toàn bộ, 12 Vox mỗi câu thoại. Tắt: ứng dụng "
          "dừng ở bước dịch và hướng dẫn bạn dịch tay, còn 10 Vox mỗi câu."),
    Field("TRANSLATION_ENDPOINT", TEXT, "Endpoint dịch OpenAI-compatible",
          TAB_TRANSLATE, "Nhà cung cấp dịch", "",
          "Ví dụ Ollama: http://localhost:11434/v1. Có thể dùng endpoint riêng "
          "miễn có /models và /chat/completions.",
          placeholder="http://localhost:11434/v1"),
    Field("TRANSLATION_API_KEY", TEXT, "API key dịch", TAB_TRANSLATE,
          "Nhà cung cấp dịch", "",
          "Lưu cục bộ trong .env. Không hiển thị trong log.",
          placeholder="Để trống nếu endpoint local"),
    Field("TRANSLATION_MODEL", TEXT, "Model dịch", TAB_TRANSLATE,
          "Nhà cung cấp dịch", "",
          "Nhập đúng model server hỗ trợ, ví dụ qwen3:4b hoặc translategemma:4b.",
          placeholder="qwen3:4b"),
    Field("BILIBILI_COOKIES_FILE", TEXT, "Tệp cookie Bilibili",
          TAB_TRANSLATE, "Đăng nhập Bilibili", "",
          "Đường dẫn tệp Netscape cookies.txt. Không dán nội dung cookie vào đây.",
          placeholder="C:\\Users\\...\\bilibili-cookies.txt"),
    Field("TRANSLATE_BATCH_SIZE", NUMBER, "Số câu mỗi lượt gửi", TAB_TRANSLATE,
          "Dịch tự động", "40",
          "Lô nhỏ hơn thì chậm hơn một chút nhưng mạch dịch bám ngữ cảnh sát "
          "hơn. Không ảnh hưởng số Vox — tính theo câu, không theo lượt gửi.",
          minimum=1, maximum=100, step=5, decimals=0),

    Field("TRANSLATE_DOMAIN", TEXT, "Chủ đề video", TAB_TRANSLATE,
          "Ngữ cảnh video", "",
          "Càng cụ thể thì bản dịch càng đúng ngữ cảnh. Để trống thì máy chủ "
          "tự đoán từ lời thoại.",
          placeholder="ví dụ: review công nghệ, phim cổ trang, vlog ẩm thực"),
    Field("TRANSLATE_CONTEXT", MULTILINE, "Ngữ cảnh", TAB_TRANSLATE,
          "Ngữ cảnh video", "",
          "Mô tả kênh nói về gì, người xem là ai.",
          placeholder="ví dụ: Kênh đập hộp linh kiện máy tính giá rẻ, "
                      "người xem là dân tự lắp máy."),
    Field("TRANSLATE_PRONOUNS", TEXT, "Cách xưng hô", TAB_TRANSLATE,
          "Ngữ cảnh video", "",
          "Giúp bản dịch xưng hô nhất quán từ đầu tới cuối.",
          placeholder="ví dụ: mình – các bạn  |  tôi – anh em"),
    Field("TRANSLATE_GLOSSARY", MULTILINE, "Thuật ngữ cố định", TAB_TRANSLATE,
          "Ngữ cảnh video", "",
          "Mỗi dòng một cặp, viết dạng gốc = bản dịch.",
          placeholder="显卡 = card đồ họa\n翻车 = toang"),
    Field("TRANSLATE_STYLE_NOTES", TEXT, "Yêu cầu khác cho người dịch",
          TAB_TRANSLATE, "Ngữ cảnh video", "",
          "Ghi chú này được gửi kèm mỗi lần dịch.",
          placeholder="ví dụ: giọng hài hước, giữ tên nhân vật Hán Việt"),

    Field("GENERATE_METADATA", CHECK,
          "Tạo tiêu đề, mô tả và thẻ cho mạng xã hội", TAB_TRANSLATE,
          "Nội dung đăng bài", "true",
          "Kết quả lưu vào thư mục dự án, tệp youtube_post.txt. Thêm 20 Vox "
          "mỗi video — tắt đi nếu bạn tự viết."),
)

# Khóa do ứng dụng tự tính hoặc chỉ dùng nội bộ, không hiện thành ô nhập chữ.
# Mỗi khóa đều phải kèm lý do rõ ràng.
EXEMPT_KEYS: dict[str, str] = {
    "VIENEU_VOICE": "chọn ở thẻ Giọng đọc bằng thẻ giọng, không phải ô nhập chữ",
    "VIENEU_STYLE": "chọn ở cột phải của thẻ Giọng đọc",
    "VOICE_RECENT": "ứng dụng tự ghi lại các giọng dùng gần đây",
    "WHISPER_BEAM_SIZE": "nút vặn nâng cao cho người biết việc (đổi tốc độ "
                         "lấy độ chính xác); mặc định giữ nguyên chất lượng, "
                         "ai cần thì sửa thẳng trong .env",
    "UPDATE_REPO": "địa chỉ kho phát hành cố định của ứng dụng, người dùng "
                   "không cần đổi; ai cần thì sửa thẳng trong .env",
    "SUPPORT_URL": "đường dẫn biểu mẫu báo lỗi cố định, chỉ hiện ở nút Gửi "
                   "báo lỗi chứ không phải cấu hình của người dùng",
    "VOXDUB_API_URL": "địa chỉ máy chủ được nhúng cứng vào bản đóng gói; "
                      "chỉ đọc từ .env khi chạy từ mã nguồn (dev), người "
                      "dùng cuối không đổi được và không cần đổi",
}


def fields_of(tab: str) -> list[Field]:
    """Các mục thuộc một thẻ, giữ nguyên thứ tự khai báo."""
    return [f for f in FIELDS if f.tab == tab]


def groups_of(tab: str) -> list[str]:
    """Tên các nhóm trong một thẻ, không lặp lại."""
    seen: list[str] = []
    for item in fields_of(tab):
        if item.group not in seen:
            seen.append(item.group)
    return seen


def defaults() -> dict[str, str]:
    """Giá trị mặc định của mọi mục."""
    return {item.key: item.default for item in FIELDS}


def field_keys() -> set[str]:
    """Tập khóa mà trang Cài đặt quản lý."""
    return {item.key for item in FIELDS}
