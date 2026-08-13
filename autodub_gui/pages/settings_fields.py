"""Khai bÃ¡o má»i má»¥c trong trang CÃ i Ä‘áº·t.

Má»—i má»¥c Ä‘Æ°á»£c mÃ´ táº£ má»™t láº§n á»Ÿ Ä‘Ã¢y rá»“i dÃ¹ng láº¡i cho viá»‡c dá»±ng Ã´ nháº­p, náº¡p giÃ¡
trá»‹, lÆ°u láº¡i vÃ  khÃ´i phá»¥c máº·c Ä‘á»‹nh. Nhá» váº­y khÃ´ng bao giá» cÃ³ chuyá»‡n thÃªm Ã´
má»›i mÃ  quÃªn lÆ°u, hoáº·c Ä‘á»•i tÃªn khÃ³a á»Ÿ má»™t chá»— mÃ  quÃªn chá»— kia.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from autodub.media.subtitle import PRESET_CHOICES
from autodub_gui import dub_constants as consts
from autodub_gui import tokens

# TÃªn sÃ¡u tháº» cá»§a trang CÃ i Ä‘áº·t. TAB_BASIC pháº£i luÃ´n Ä‘á»©ng Ä‘áº§u vÃ¬
# focus_display_name() nháº£y tháº³ng vá» tháº» sá»‘ 0.
TAB_BASIC = "CÆ¡ báº£n"
TAB_VOICE = "Giá»ng Ä‘á»c"
TAB_SUBTITLE = "Phá»¥ Ä‘á»"
TAB_PERF = "Hiá»‡u suáº¥t"
#: Tháº» "Dá»‹ch thuáº­t" â€” má»i API Key Ä‘Ã£ lÃªn mÃ¡y chá»§, á»Ÿ Ä‘Ã¢y chá»‰ cÃ²n NGá»® Cáº¢NH:
#: nhá»¯ng gÃ¬ ngÆ°á»i dÃ¹ng biáº¿t vá» video mÃ  mÃ¡y chá»§ khÃ´ng thá»ƒ tá»± Ä‘oÃ¡n.
TAB_TRANSLATE = "Dá»‹ch thuáº­t"
TAB_ADVANCED = "NÃ¢ng cao"

TABS = (TAB_BASIC, TAB_VOICE, TAB_SUBTITLE, TAB_PERF, TAB_TRANSLATE, TAB_ADVANCED)

# Ba tháº» Giá»ng Ä‘á»c, Phá»¥ Ä‘á» vÃ  Dá»‹ch thuáº­t Ä‘Ã£ tÃ¡ch thÃ nh trang CÃ´ng cá»¥ riÃªng
# trÃªn thanh bÃªn, nÃªn trang CÃ i Ä‘áº·t chá»‰ cÃ²n giá»¯ nhá»¯ng tháº» dÆ°á»›i Ä‘Ã¢y Ä‘á»ƒ khá»i trÃ¹ng.
SETTINGS_TABS = (TAB_BASIC, TAB_PERF, TAB_ADVANCED)

# Kiá»ƒu Ã´ nháº­p
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
    """Má»™t má»¥c cáº¥u hÃ¬nh: khÃ³a trong tá»‡p cáº¥u hÃ¬nh vÃ  cÃ¡ch hiá»ƒn thá»‹ cá»§a nÃ³."""

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
    ("Nhanh â€” Æ°u tiÃªn tá»‘c Ä‘á»™", "fast"),
    ("CÃ¢n báº±ng (khuyÃªn dÃ¹ng)", "balanced"),
    ("Cháº¥t lÆ°á»£ng cao â€” cháº¡y cháº­m hÆ¡n", "quality"),
]

_SUBTITLE_POSITIONS = [
    ("DÆ°á»›i mÃ n hÃ¬nh", "bottom"),
    ("Giá»¯a mÃ n hÃ¬nh", "middle"),
    ("TrÃªn mÃ n hÃ¬nh", "top"),
]

_SUBTITLE_DISPLAY = [
    ("Hiá»‡n cáº£ cÃ¢u", "sentence"),
    ("Hiá»‡n theo cá»¥m chá»¯, sÃ¡ng dáº§n", "karaoke"),
]

_SUBTITLE_BOX = [
    ("Chá»‰ viá»n chá»¯", "none"),
    ("Khá»‘i ná»n má» sau chá»¯", "box"),
]

_KARAOKE_EFFECTS = [
    ("Chá»¯ báº­t lÃªn", "pop"),
    ("Má» dáº§n", "fade"),
    ("Äá»•i mÃ u theo lá»i Ä‘á»c", "karaoke"),
    ("KhÃ´ng hiá»‡u á»©ng", "none"),
]


# ToÃ n bá»™ cÃ¡c má»¥c, xáº¿p theo tháº» rá»“i theo nhÃ³m.
FIELDS: tuple[Field, ...] = (
    # -- Tháº» CÆ¡ báº£n ---------------------------------------------------
    Field("QUALITY_PRESET", COMBO, "Má»©c cháº¥t lÆ°á»£ng", TAB_BASIC,
          "Cháº¥t lÆ°á»£ng tá»•ng thá»ƒ", "balanced",
          "Chá»n má»™t má»©c lÃ  Ä‘á»§, á»©ng dá»¥ng tá»± Ä‘áº·t cÃ¡c chi tiáº¿t bÃªn dÆ°á»›i. "
          "Ã” nÃ o báº¡n tá»± chá»‰nh thÃ¬ giÃ¡ trá»‹ cá»§a báº¡n Ä‘Æ°á»£c Æ°u tiÃªn.",
          options=_QUALITY_PRESETS),
    Field("ASR_ENGINE", COMBO, "Bá»™ nháº­n dáº¡ng", TAB_BASIC,
          "Nghe vÃ  chÃ©p lá»i video gá»‘c", "whisper",
          "Whisper nghe Ä‘Æ°á»£c má»i ngÃ´n ngá»¯. Paraformer chÃ­nh xÃ¡c hÆ¡n vá»›i "
          "video tiáº¿ng Trung nhÆ°ng pháº£i cÃ i thÃªm má»™t láº§n.",
          options=consts.ASR_ENGINES),
    Field("WHISPER_MODEL", COMBO, "Äá»™ chÃ­nh xÃ¡c", TAB_BASIC,
          "Nghe vÃ  chÃ©p lá»i video gá»‘c", "auto",
          "Má»©c cÃ ng cao nghe cÃ ng Ä‘Ãºng nhÆ°ng cháº¡y lÃ¢u hÆ¡n vÃ  táº£i vá» náº·ng hÆ¡n.",
          options=consts.WHISPER_MODELS),
    Field("DEFAULT_SOURCE_LANG", COMBO, "NgÃ´n ngá»¯ gá»‘c máº·c Ä‘á»‹nh", TAB_BASIC,
          "Nghe vÃ  chÃ©p lá»i video gá»‘c", "zh-CN",
          "NgÃ´n ngá»¯ Ä‘Æ°á»£c chá»n sáºµn má»—i khi báº¡n táº¡o dá»± Ã¡n má»›i.",
          options=consts.SOURCE_LANGS),
    Field("VIDEO_SPEED", SLIDER, "Tá»‘c Ä‘á»™ video", TAB_BASIC,
          "Tá»‘c Ä‘á»™", "1.00",
          "LÃ m cháº­m toÃ n bá»™ video Ä‘á»ƒ giá»ng tiáº¿ng Viá»‡t cÃ³ Ä‘á»§ chá»—. "
          "0.82 nghÄ©a lÃ  video dÃ i thÃªm khoáº£ng 22 pháº§n trÄƒm. "
          "1.00 lÃ  giá»¯ nguyÃªn.",
          suffix="x", minimum=0.5, maximum=1.0, step=0.02),
    Field("VOICE_SPEED", SLIDER, "Tá»‘c Ä‘á»™ giá»ng Ä‘á»c", TAB_BASIC,
          "Tá»‘c Ä‘á»™", "1.00",
          "1.00 lÃ  tá»‘c Ä‘á»™ tá»± nhiÃªn. TÄƒng lÃªn khi cÃ¢u tiáº¿ng Viá»‡t dÃ i hÆ¡n cÃ¢u "
          "gá»‘c vÃ  bá»‹ chá»“ng sang cÃ¢u sau.",
          suffix="x", minimum=0.5, maximum=2.0, step=0.05),
    Field("OUTPUT_DIR", FOLDER, "ThÆ° má»¥c lÆ°u video", TAB_BASIC,
          "NÆ¡i lÆ°u káº¿t quáº£", "./output",
          "Má»i dá»± Ã¡n sáº½ Ä‘Æ°á»£c lÆ°u vÃ o thÆ° má»¥c nÃ y.",
          placeholder="./output"),
    Field("DISPLAY_NAME", TEXT, "TÃªn hiá»ƒn thá»‹", TAB_BASIC, "Hiá»ƒn thá»‹", "",
          "TÃªn nÃ y hiá»‡n á»Ÿ lá»i chÃ o trÃªn Trang chá»§. Äá»ƒ trá»‘ng thÃ¬ dÃ¹ng tÃªn "
          "Ä‘Äƒng nháº­p cá»§a mÃ¡y.",
          placeholder="vÃ­ dá»¥: Dylan"),

    # (Tháº» Giá»ng Ä‘á»c khÃ´ng khai bÃ¡o Ã´ á»Ÿ Ä‘Ã¢y â€” toÃ n bá»™ tháº» lÃ  thÆ° viá»‡n giá»ng
    #  riÃªng, xem pages/voice_library.py. VIENEU_STYLE render trong Ä‘Ã³.)

    # -- Tháº» Phá»¥ Ä‘á» ---------------------------------------------------
    Field("SUBTITLE_MODE", COMBO, "Kiá»ƒu phá»¥ Ä‘á» máº·c Ä‘á»‹nh", TAB_SUBTITLE,
          "Máº·c Ä‘á»‹nh", "none",
          "Kiá»ƒu Ä‘Æ°á»£c chá»n sáºµn má»—i khi báº¡n táº¡o dá»± Ã¡n má»›i.",
          options=consts.SUBTITLE_MODES),
    Field("SUBTITLE_PRESET", COMBO, "Bá»™ kiá»ƒu chá»¯", TAB_SUBTITLE,
          "Máº·c Ä‘á»‹nh", "clean",
          "Chá»n má»™t bá»™ cÃ³ sáºµn lÃ  xong. Muá»‘n tá»± quyáº¿t tá»«ng thÃ´ng sá»‘ thÃ¬ chá»n "
          "Tá»± chá»‰nh rá»“i sá»­a cÃ¡c Ã´ bÃªn dÆ°á»›i.",
          options=PRESET_CHOICES),
    Field("SUBTITLE_POSITION", COMBO, "Vá»‹ trÃ­ chá»¯", TAB_SUBTITLE,
          "Kiá»ƒu chá»¯", "bottom", "Chá»¯ náº±m á»Ÿ Ä‘Ã¢u trÃªn khung hÃ¬nh.",
          options=_SUBTITLE_POSITIONS),
    Field("SUBTITLE_FONT", FONT, "PhÃ´ng chá»¯", TAB_SUBTITLE, "Kiá»ƒu chá»¯", "",
          "Chá»‰ liá»‡t kÃª phÃ´ng trong thÆ° má»¥c phÃ´ng cá»§a dá»± Ã¡n, vÃ¬ chá»‰ nhá»¯ng "
          "phÃ´ng nÃ y má»›i cháº¯c cháº¯n hiá»‡n Ä‘Ãºng trÃªn má»i mÃ¡y."),
    Field("SUBTITLE_FONT_SIZE", NUMBER, "Cá»¡ chá»¯", TAB_SUBTITLE, "Kiá»ƒu chá»¯",
          "22", "Cá»¡ chá»¯ phá»¥ Ä‘á» trÃªn video.",
          minimum=8, maximum=96, step=1, decimals=0),
    Field("SUBTITLE_BOLD", CHECK, "Chá»¯ Ä‘áº­m", TAB_SUBTITLE, "Kiá»ƒu chá»¯", "true",
          "Chá»¯ Ä‘áº­m dá»… Ä‘á»c hÆ¡n khi video Ä‘Æ°á»£c xem trÃªn Ä‘iá»‡n thoáº¡i."),
    Field("SUBTITLE_MARGIN_V", NUMBER, "CÃ¡ch mÃ©p mÃ n hÃ¬nh", TAB_SUBTITLE,
          "Kiá»ƒu chá»¯", "40", "Khoáº£ng cÃ¡ch tá»« chá»¯ tá»›i mÃ©p trÃªn hoáº·c mÃ©p dÆ°á»›i.",
          suffix=" Ä‘iá»ƒm áº£nh", minimum=0, maximum=400, step=5, decimals=0),
    Field("SUBTITLE_OUTLINE", NUMBER, "Äá»™ dÃ y viá»n chá»¯", TAB_SUBTITLE,
          "Kiá»ƒu chá»¯", "2",
          "Viá»n giÃºp chá»¯ Ä‘á»c Ä‘Æ°á»£c cáº£ khi ná»n video sÃ¡ng.",
          minimum=0, maximum=8, step=1, decimals=0),
    Field("SUBTITLE_SHADOW", NUMBER, "Äá»™ Ä‘á»• bÃ³ng", TAB_SUBTITLE, "Kiá»ƒu chá»¯",
          "0", "BÃ³ng nháº¹ phÃ­a sau chá»¯. Äáº·t 0 Ä‘á»ƒ táº¯t.",
          minimum=0, maximum=8, step=1, decimals=0),
    Field("SUBTITLE_COLOR", COLOR, "MÃ u chá»¯", TAB_SUBTITLE, "Kiá»ƒu chá»¯",
          tokens.SUBTITLE_TEXT_DEFAULT, "MÃ u cá»§a chá»¯ phá»¥ Ä‘á»."),
    Field("SUBTITLE_OUTLINE_COLOR", COLOR, "MÃ u viá»n chá»¯", TAB_SUBTITLE,
          "Kiá»ƒu chá»¯", tokens.SUBTITLE_OUTLINE_DEFAULT,
          "MÃ u viá»n bao quanh chá»¯."),
    Field("SUBTITLE_BOX", COMBO, "Ná»n sau chá»¯", TAB_SUBTITLE, "Ná»n chá»¯",
          "none",
          "Khá»‘i ná»n má» giÃºp chá»¯ Ä‘á»c Ä‘Æ°á»£c trÃªn ná»n video nhiá»u chi tiáº¿t.",
          options=_SUBTITLE_BOX),
    Field("SUBTITLE_BOX_COLOR", COLOR, "MÃ u ná»n", TAB_SUBTITLE, "Ná»n chá»¯",
          tokens.SUBTITLE_BOXFILL_DEFAULT, "MÃ u cá»§a khá»‘i ná»n sau chá»¯."),
    Field("SUBTITLE_BOX_OPACITY", NUMBER, "Äá»™ Ä‘á»¥c cá»§a ná»n", TAB_SUBTITLE,
          "Ná»n chá»¯", "60",
          "0 lÃ  trong suá»‘t háº³n, 100 lÃ  che kÃ­n hoÃ n toÃ n.",
          suffix=" pháº§n trÄƒm", minimum=0, maximum=100, step=5, decimals=0),
    Field("SUBTITLE_LINE_WORDS", NUMBER, "Sá»‘ chá»¯ má»—i dÃ²ng", TAB_SUBTITLE,
          "CÃ¡ch ngáº¯t dÃ²ng", "0",
          "Äáº·t 0 Ä‘á»ƒ á»©ng dá»¥ng tá»± ngáº¯t dÃ²ng theo Ä‘á»™ dÃ i cÃ¢u. Video dá»c nÃªn Ä‘áº·t "
          "4 tá»›i 6 chá»¯ cho chá»¯ khá»i trÃ n mÃ©p.",
          minimum=0, maximum=20, step=1, decimals=0),
    Field("SUBTITLE_MAX_LINES", NUMBER, "Sá»‘ dÃ²ng tá»‘i Ä‘a", TAB_SUBTITLE,
          "CÃ¡ch ngáº¯t dÃ²ng", "2",
          "Má»—i láº§n hiá»‡n nhiá»u nháº¥t báº¥y nhiÃªu dÃ²ng chá»¯.",
          minimum=1, maximum=4, step=1, decimals=0),
    Field("SUBTITLE_ALL_CAPS", CHECK, "Viáº¿t hoa toÃ n bá»™", TAB_SUBTITLE,
          "CÃ¡ch ngáº¯t dÃ²ng", "false",
          "Chá»¯ hoa háº¿t nhÃ¬n máº¡nh hÆ¡n nhÆ°ng Ä‘á»c cháº­m hÆ¡n, há»£p video ngáº¯n."),
    Field("SUBTITLE_DISPLAY", COMBO, "CÃ¡ch hiá»‡n chá»¯", TAB_SUBTITLE,
          "Hiá»‡n theo cá»¥m chá»¯", "sentence",
          "Hiá»‡n cáº£ cÃ¢u lÃ  kiá»ƒu phá»¥ Ä‘á» thÆ°á»ng. Hiá»‡n theo cá»¥m chá»¯ giá»‘ng lá»i "
          "bÃ i hÃ¡t, tá»«ng cá»¥m sÃ¡ng lÃªn theo lá»i Ä‘á»c.",
          options=_SUBTITLE_DISPLAY),
    Field("KARAOKE_WORDS_PER_CUE", NUMBER, "Sá»‘ chá»¯ má»—i cá»¥m", TAB_SUBTITLE,
          "Hiá»‡n theo cá»¥m chá»¯", "3",
          "Má»—i láº§n hiá»‡n bao nhiÃªu chá»¯ khi dÃ¹ng kiá»ƒu sÃ¡ng dáº§n.",
          minimum=1, maximum=5, step=1, decimals=0),
    Field("KARAOKE_EFFECT", COMBO, "Hiá»‡u á»©ng", TAB_SUBTITLE,
          "Hiá»‡n theo cá»¥m chá»¯", "pop", "CÃ¡ch chá»¯ xuáº¥t hiá»‡n.",
          options=_KARAOKE_EFFECTS),
    Field("KARAOKE_HIGHLIGHT_COLOR", COLOR, "MÃ u chá»¯ Ä‘ang Ä‘á»c", TAB_SUBTITLE,
          "Hiá»‡n theo cá»¥m chá»¯", tokens.SUBTITLE_HIGHLIGHT_DEFAULT,
          "MÃ u tÃ´ lÃªn cá»¥m chá»¯ Ä‘ang Ä‘Æ°á»£c Ä‘á»c."),
    Field("KARAOKE_ALIGNMENT", CHECK, "Canh chá»¯ theo lá»i Ä‘á»c", TAB_SUBTITLE,
          "Hiá»‡n theo cá»¥m chá»¯", "true",
          "Báº­t Ä‘á»ƒ tá»«ng chá»¯ sÃ¡ng lÃªn Ä‘Ãºng lÃºc Ä‘Æ°á»£c Ä‘á»c."),

    # -- Tháº» Hiá»‡u suáº¥t ------------------------------------------------
    Field("WORKER_MODE", COMBO, "CÃ¡ch cháº¡y worker", TAB_PERF,
          "Hiá»‡u nÄƒng", "auto",
          "Tá»± Ä‘á»™ng tÃ­nh theo CPU/RAM/GPU. Thá»§ cÃ´ng váº«n chá»‹u tráº§n an toÃ n.",
          options=[("Tá»± Ä‘á»™ng", "auto"), ("Thá»§ cÃ´ng", "manual")]),
    Field("PARALLEL_WORKERS", NUMBER, "Sá»‘ viá»‡c cháº¡y cÃ¹ng lÃºc", TAB_PERF,
          "Hiá»‡u nÄƒng", "0",
          "Äáº·t 0 Ä‘á»ƒ á»©ng dá»¥ng tá»± chá»n theo cáº¥u hÃ¬nh mÃ¡y. Chá»‰ Ä‘á»•i khi báº¡n biáº¿t "
          "rÃµ mÃ¬nh cáº§n gÃ¬.", minimum=0, maximum=32, step=1, decimals=0),
    Field("VIENEU_MAX_WORKERS", NUMBER, "Sá»‘ giá»ng cháº¡y cÃ¹ng lÃºc",
          TAB_PERF, "Hiá»‡u nÄƒng", "0",
          "Äáº·t 0 Ä‘á»ƒ tá»± chá»n. Má»—i luá»“ng tá»‘n khoáº£ng 1,5 GB bá»™ nhá»›.",
          minimum=0, maximum=8, step=1, decimals=0),
    Field("HQ_BACKGROUND", CHECK, "Giá»¯ nháº¡c ná»n cháº¥t lÆ°á»£ng cao",
          TAB_PERF, "Hiá»‡u nÄƒng", "true",
          "Táº¯t Ä‘i thÃ¬ cháº¡y nhanh hÆ¡n nhÆ°ng nháº¡c ná»n kÃ©m hÆ¡n má»™t chÃºt."),
    Field("OCR_ENABLED", CHECK, "Tá»± Ä‘á»™ng lÃ m má» phá»¥ Ä‘á» Trung",
          TAB_PERF, "Che phá»¥ Ä‘á» cá»©ng", "true",
          "DÃ¹ng PaddleOCR local Ä‘á»ƒ tÃ¬m Ä‘Ãºng vÃ¹ng chá»¯ Trung. VÃ¹ng Ä‘á»™ tin cáº­y tháº¥p "
          "hoáº·c quÃ¡ lá»›n sáº½ tá»± Ä‘á»™ng bá» qua; vÃ¹ng khoanh thá»§ cÃ´ng váº«n Ä‘Æ°á»£c giá»¯."),
    Field("OCR_MIN_CONFIDENCE", SLIDER, "Äá»™ tin cáº­y OCR tá»‘i thiá»ƒu",
          TAB_PERF, "Che phá»¥ Ä‘á» cá»©ng", "0.80",
          "TÄƒng lÃªn náº¿u OCR nháº­n nháº§m. Chá»‰ vÃ¹ng Ä‘áº¡t ngÆ°á»¡ng má»›i Ä‘Æ°á»£c lÃ m má».",
          minimum=0.5, maximum=0.99, step=0.05, decimals=2),
    Field("OCR_MAX_REGION_AREA", SLIDER, "Diá»‡n tÃ­ch vÃ¹ng OCR tá»‘i Ä‘a",
          TAB_PERF, "Che phá»¥ Ä‘á» cá»©ng", "0.25",
          "Bá» qua vÃ¹ng nháº­n diá»‡n chiáº¿m quÃ¡ nhiá»u khung hÃ¬nh Ä‘á»ƒ trÃ¡nh lÃ m má» nháº§m.",
          suffix=" pháº§n khung", minimum=0.02, maximum=0.8, step=0.05, decimals=2),
    Field("OCR_SUBTITLE_Y_MIN", SLIDER, "Vá»‹ trÃ­ báº¯t Ä‘áº§u vÃ¹ng phá»¥ Ä‘á» OCR",
          TAB_PERF, "Che phá»¥ Ä‘á» cá»©ng", "0.65",
          "Chá»‰ nháº­n chá»¯ Trung náº±m tá»« vá»‹ trÃ­ nÃ y xuá»‘ng dÆ°á»›i khung hÃ¬nh. "
          "0.65 phÃ¹ há»£p phá»¥ Ä‘á» má»™t hoáº·c hai dÃ²ng á»Ÿ cuá»‘i video.",
          suffix=" chiá»u cao khung", minimum=0.0, maximum=0.95, step=0.05,
          decimals=2),
    Field("OCR_SAMPLE_INTERVAL", SLIDER, "Khoáº£ng quÃ©t OCR",
          TAB_PERF, "Che phá»¥ Ä‘á» cá»©ng", "1.00",
          "QuÃ©t má»—i bao nhiÃªu giÃ¢y. Sá»‘ nhá» báº¯t chá»¯ ngáº¯n tá»‘t hÆ¡n nhÆ°ng cháº¡y lÃ¢u hÆ¡n.",
          suffix=" giÃ¢y", minimum=0.5, maximum=5.0, step=0.5, decimals=1),
    Field("BRANDING_LOGO_PATH", TEXT, "Logo cáº£ nhÃ¢n",
          TAB_PERF, "Branding video", "", "ÄÆ°á»ng dáº«n logo PNG/JPG."),
    Field("BRANDING_INTRO_PATH", TEXT, "Video intro",
          TAB_PERF, "Branding video", "", "Video ghÃ©p trÆ°á»›c video chÃ­nh."),
    Field("BRANDING_OUTRO_PATH", TEXT, "Video outro",
          TAB_PERF, "Branding video", "", "Video ghÃ©p sau video chÃ­nh."),
    Field("BRANDING_LOGO_REGION", MULTILINE, "VÃ¹ng logo nguá»“n",
          TAB_PERF, "Branding video", "",
          "JSON x/y/w/h; Ä‘á»ƒ trá»‘ng thÃ¬ dÃ¹ng Vision hoáº·c gÃ³c pháº£i trÃªn."),
    Field("BRANDING_LOGO_OPACITY", SLIDER, "Äá»™ trong logo",
          TAB_PERF, "Branding video", "1.0", "Äá»™ trong suá»‘t logo.",
          minimum=0.0, maximum=1.0, step=0.05, decimals=2),
    Field("BRANDING_LOGO_SCALE", SLIDER, "KÃ­ch thÆ°á»›c logo",
          TAB_PERF, "Branding video", "0.2", "Tá»· lá»‡ logo máº·c Ä‘á»‹nh.",
          minimum=0.01, maximum=1.0, step=0.01, decimals=2),
    Field("BRANDING_VISION_ENABLED", CHECK, "Tá»± dÃ² logo báº±ng Vision",
          TAB_PERF, "Branding video", "true",
          "DÃ¹ng Ollama náº¿u cÃ³; lá»—i thÃ¬ bá» qua."),
    Field("BRANDING_VISION_MODEL", TEXT, "Model Vision Ollama",
          TAB_PERF, "Branding video", "deepseek-vl",
          "TÃªn model Ä‘Ã£ cÃ i trong Ollama."),

    # -- Tháº» NÃ¢ng cao -------------------------------------------------
    Field("TRANSLATE_CPS_BUDGET", SLIDER, "Sá»‘ chá»¯ má»—i giÃ¢y", TAB_ADVANCED,
          "Cháº¥t lÆ°á»£ng dá»‹ch", "12.5",
          "Giá»›i háº¡n Ä‘á»™ dÃ i cÃ¢u dá»‹ch Ä‘á»ƒ Ä‘á»c ká»‹p. CÃ ng nhá» thÃ¬ cÃ¢u cÃ ng ngáº¯n "
          "gá»n.", minimum=8.0, maximum=20.0, step=0.5, decimals=1),
    Field("VOICE_POSTPROCESS", CHECK, "LÃ m Ä‘á»u Ä‘á»™ lá»›n giá»ng Ä‘á»c",
          TAB_ADVANCED, "Xá»­ lÃ½ Ã¢m thanh", "true",
          "CÃ¢n báº±ng Ä‘á»ƒ cÃ¢u nÃ o cÅ©ng nghe rÃµ nhÆ° nhau, khÃ´ng cÃ¢u to cÃ¢u nhá»."),
    Field("VOICE_TARGET_LUFS", SLIDER, "Äá»™ lá»›n giá»ng Ä‘á»c", TAB_ADVANCED,
          "Xá»­ lÃ½ Ã¢m thanh", "-16.0",
          "CÃ ng gáº§n 0 thÃ¬ giá»ng cÃ ng to. Má»©c thÆ°á»ng dÃ¹ng cho video lÃ  -16.",
          suffix=" dB", minimum=-24.0, maximum=-10.0, step=0.5, decimals=1),
    Field("BG_DUCK_VOICE_DB", SLIDER, "Giáº£m nháº¡c ná»n khi cÃ³ lá»i",
          TAB_ADVANCED, "Xá»­ lÃ½ Ã¢m thanh", "-8.0",
          "Nháº¡c ná»n tá»± nhá» Ä‘i báº¥y nhiÃªu má»—i khi cÃ³ lá»i thoáº¡i tiáº¿ng Viá»‡t.",
          suffix=" dB", minimum=-24.0, maximum=0.0, step=0.5, decimals=1),
    Field("SOFT_TIMING_FIT", CHECK, "Tá»± cÄƒn láº¡i thá»i Ä‘iá»ƒm tá»«ng cÃ¢u",
          TAB_ADVANCED, "CÄƒn thá»i gian", "true",
          "Dá»‹ch nháº¹ thá»i Ä‘iá»ƒm cÃ¡c cÃ¢u Ä‘á»ƒ lá»i thoáº¡i khÃ´ng chá»“ng lÃªn nhau."),
    Field("TIMING_MAX_DRIFT_S", SLIDER, "Cho phÃ©p lá»‡ch tá»‘i Ä‘a", TAB_ADVANCED,
          "CÄƒn thá»i gian", "1.5",
          "Má»—i cÃ¢u Ä‘Æ°á»£c dá»‹ch Ä‘i nhiá»u nháº¥t báº¥y nhiÃªu giÃ¢y so vá»›i báº£n gá»‘c.",
          suffix=" giÃ¢y", minimum=0.0, maximum=5.0, step=0.1, decimals=1),
    Field("TIMING_MIN_GAP_S", SLIDER, "Khoáº£ng nghá»‰ tá»‘i thiá»ƒu", TAB_ADVANCED,
          "CÄƒn thá»i gian", "0.08",
          "Khoáº£ng láº·ng ngáº¯n giá»¯a hai cÃ¢u liá»n nhau cho dá»… nghe.",
          suffix=" giÃ¢y", minimum=0.0, maximum=1.0, step=0.01),
    Field("TIMING_MAX_ATEMPO", SLIDER, "Má»©c nÃ©n lá»i tá»‘i Ä‘a", TAB_ADVANCED,
          "CÄƒn thá»i gian", "1.15",
          "CÃ¢u quÃ¡ dÃ i cÃ³ thá»ƒ Ä‘Æ°á»£c Ä‘á»c nhanh hÆ¡n tá»‘i Ä‘a báº¥y nhiÃªu láº§n.",
          suffix="x", minimum=1.0, maximum=1.6, step=0.01),
    Field("AUTO_CLEAN_INTERMEDIATES", CHECK, "Tá»± dá»n tá»‡p trung gian sau khi xuáº¥t",
          TAB_ADVANCED, "Dung lÆ°á»£ng Ä‘Ä©a", "false",
          "Xuáº¥t video xong lÃ  dá»n ngay cÃ¡c tá»‡p trung gian náº·ng. Tiáº¿t kiá»‡m "
          "Ä‘Ä©a, nhÆ°ng dá»± Ã¡n Ä‘Ã³ sáº½ khÃ´ng sá»­a tá»«ng cÃ¢u hay xuáº¥t láº¡i Ä‘Æ°á»£c ná»¯a."),

    # -- Tháº» Dá»‹ch thuáº­t ------------------------------------------------
    # Dá»‹ch qua endpoint OpenAI-compatible do ngÆ°á»i dÃ¹ng chá»n.
    Field("TRANSLATE_ENABLED", CHECK, "Báº­t dá»‹ch tá»± Ä‘á»™ng", TAB_TRANSLATE,
          "Dá»‹ch tá»± Ä‘á»™ng", "true",
          "Báº­t: mÃ¡y chá»§ dá»‹ch toÃ n bá»™, 12 Vox má»—i cÃ¢u thoáº¡i. Táº¯t: á»©ng dá»¥ng "
          "dá»«ng á»Ÿ bÆ°á»›c dá»‹ch vÃ  hÆ°á»›ng dáº«n báº¡n dá»‹ch tay, cÃ²n 10 Vox má»—i cÃ¢u."),
    Field("TRANSLATION_ENDPOINT", TEXT, "Endpoint dá»‹ch OpenAI-compatible",
          TAB_TRANSLATE, "NhÃ  cung cáº¥p dá»‹ch", "",
          "Endpoint pháº£i cÃ³ /models vÃ  /chat/completions. DÃ¹ng endpoint do "
          "nhÃ  cung cáº¥p API cáº¥p.",
          placeholder="https://api.example.com/v1"),
    Field("TRANSLATION_API_KEY", TEXT, "API key dá»‹ch", TAB_TRANSLATE,
          "NhÃ  cung cáº¥p dá»‹ch", "",
          "LÆ°u cá»¥c bá»™ trong .env. KhÃ´ng hiá»ƒn thá»‹ trong log.",
          placeholder="DÃ¡n API key"),
    Field("TRANSLATION_MODEL", TEXT, "Model dá»‹ch", TAB_TRANSLATE,
          "NhÃ  cung cáº¥p dá»‹ch", "",
          "GÃµ tÃªn model hoáº·c báº¥m Táº£i model Ä‘á»ƒ chá»n tá»« danh sÃ¡ch endpoint.",
          placeholder="TÃªn model, vÃ­ dá»¥: qwen3:4b"),
    Field("BILIBILI_COOKIES_FILE", TEXT, "Tá»‡p cookie Bilibili",
          TAB_TRANSLATE, "ÄÄƒng nháº­p Bilibili", "",
          "ÄÆ°á»ng dáº«n tá»‡p Netscape cookies.txt. KhÃ´ng dÃ¡n ná»™i dung cookie vÃ o Ä‘Ã¢y.",
          placeholder="C:\\Users\\...\\bilibili-cookies.txt"),
    Field("TRANSLATE_BATCH_SIZE", NUMBER, "Sá»‘ cÃ¢u má»—i lÆ°á»£t gá»­i", TAB_TRANSLATE,
          "Dá»‹ch tá»± Ä‘á»™ng", "10",
          "LÃ´ nhá» hÆ¡n thÃ¬ cháº­m hÆ¡n má»™t chÃºt nhÆ°ng máº¡ch dá»‹ch bÃ¡m ngá»¯ cáº£nh sÃ¡t "
          "hÆ¡n. KhÃ´ng áº£nh hÆ°á»Ÿng sá»‘ Vox â€” tÃ­nh theo cÃ¢u, khÃ´ng theo lÆ°á»£t gá»­i.",
          minimum=1, maximum=10, step=1, decimals=0),

    Field("TRANSLATE_DOMAIN", TEXT, "Chá»§ Ä‘á» video", TAB_TRANSLATE,
          "Ngá»¯ cáº£nh video", "",
          "CÃ ng cá»¥ thá»ƒ thÃ¬ báº£n dá»‹ch cÃ ng Ä‘Ãºng ngá»¯ cáº£nh. Äá»ƒ trá»‘ng thÃ¬ mÃ¡y chá»§ "
          "tá»± Ä‘oÃ¡n tá»« lá»i thoáº¡i.",
          placeholder="vÃ­ dá»¥: review cÃ´ng nghá»‡, phim cá»• trang, vlog áº©m thá»±c"),
    Field("TRANSLATE_CONTEXT", MULTILINE, "Ngá»¯ cáº£nh", TAB_TRANSLATE,
          "Ngá»¯ cáº£nh video", "",
          "MÃ´ táº£ kÃªnh nÃ³i vá» gÃ¬, ngÆ°á»i xem lÃ  ai.",
          placeholder="vÃ­ dá»¥: KÃªnh Ä‘áº­p há»™p linh kiá»‡n mÃ¡y tÃ­nh giÃ¡ ráº», "
                      "ngÆ°á»i xem lÃ  dÃ¢n tá»± láº¯p mÃ¡y."),
    Field("TRANSLATE_PRONOUNS", TEXT, "CÃ¡ch xÆ°ng hÃ´", TAB_TRANSLATE,
          "Ngá»¯ cáº£nh video", "",
          "GiÃºp báº£n dá»‹ch xÆ°ng hÃ´ nháº¥t quÃ¡n tá»« Ä‘áº§u tá»›i cuá»‘i.",
          placeholder="vÃ­ dá»¥: mÃ¬nh â€“ cÃ¡c báº¡n  |  tÃ´i â€“ anh em"),
    Field("TRANSLATE_GLOSSARY", MULTILINE, "Thuáº­t ngá»¯ cá»‘ Ä‘á»‹nh", TAB_TRANSLATE,
          "Ngá»¯ cáº£nh video", "",
          "Má»—i dÃ²ng má»™t cáº·p, viáº¿t dáº¡ng gá»‘c = báº£n dá»‹ch.",
          placeholder="æ˜¾å¡ = card Ä‘á»“ há»a\nç¿»è½¦ = toang"),
    Field("TRANSLATE_STYLE_NOTES", TEXT, "YÃªu cáº§u khÃ¡c cho ngÆ°á»i dá»‹ch",
          TAB_TRANSLATE, "Ngá»¯ cáº£nh video", "",
          "Ghi chÃº nÃ y Ä‘Æ°á»£c gá»­i kÃ¨m má»—i láº§n dá»‹ch.",
          placeholder="vÃ­ dá»¥: giá»ng hÃ i hÆ°á»›c, giá»¯ tÃªn nhÃ¢n váº­t HÃ¡n Viá»‡t"),

    Field("GENERATE_METADATA", CHECK,
          "Táº¡o tiÃªu Ä‘á», mÃ´ táº£ vÃ  tháº» cho máº¡ng xÃ£ há»™i", TAB_TRANSLATE,
          "Ná»™i dung Ä‘Äƒng bÃ i", "true",
          "Káº¿t quáº£ lÆ°u vÃ o thÆ° má»¥c dá»± Ã¡n, tá»‡p youtube_post.txt. ThÃªm 20 Vox "
          "má»—i video â€” táº¯t Ä‘i náº¿u báº¡n tá»± viáº¿t."),
)

# KhÃ³a do á»©ng dá»¥ng tá»± tÃ­nh hoáº·c chá»‰ dÃ¹ng ná»™i bá»™, khÃ´ng hiá»‡n thÃ nh Ã´ nháº­p chá»¯.
# Má»—i khÃ³a Ä‘á»u pháº£i kÃ¨m lÃ½ do rÃµ rÃ ng.
EXEMPT_KEYS: dict[str, str] = {
    "VIENEU_VOICE": "chá»n á»Ÿ tháº» Giá»ng Ä‘á»c báº±ng tháº» giá»ng, khÃ´ng pháº£i Ã´ nháº­p chá»¯",
    "VIENEU_STYLE": "chá»n á»Ÿ cá»™t pháº£i cá»§a tháº» Giá»ng Ä‘á»c",
    "VIENEU_CLONE_ENABLED": "clone lÃ  tÃ¹y chá»n theo tá»«ng job trong wizard, khÃ´ng cáº§n cáº¥u hÃ¬nh chung",
    "VIENEU_CLONE_SOURCE": "clone lÃ  tÃ¹y chá»n theo tá»«ng job trong wizard, khÃ´ng cáº§n cáº¥u hÃ¬nh chung",
    "VIENEU_CLONE_REFERENCE_AUDIO": "clone lÃ  tÃ¹y chá»n theo tá»«ng job trong wizard, khÃ´ng cáº§n cáº¥u hÃ¬nh chung",
    "VIENEU_CLONE_MIN_SECONDS": "ngÆ°á»¡ng ná»™i bá»™ cá»§a enrollment VieNeu, khÃ´ng cáº§n chá»‰nh trong giao diá»‡n",
    "VIENEU_CLONE_MAX_SECONDS": "ngÆ°á»¡ng ná»™i bá»™ cá»§a enrollment VieNeu, khÃ´ng cáº§n chá»‰nh trong giao diá»‡n",
    "OCR_DEVICE": "tá»± Ä‘á»™ng dÃ¹ng GPU NVIDIA náº¿u PaddlePaddle GPU Ä‘Ã£ cÃ i, náº¿u khÃ´ng thÃ¬ dÃ¹ng CPU",
    "VOICE_RECENT": "á»©ng dá»¥ng tá»± ghi láº¡i cÃ¡c giá»ng dÃ¹ng gáº§n Ä‘Ã¢y",
    "WHISPER_BEAM_SIZE": "nÃºt váº·n nÃ¢ng cao cho ngÆ°á»i biáº¿t viá»‡c (Ä‘á»•i tá»‘c Ä‘á»™ "
                         "láº¥y Ä‘á»™ chÃ­nh xÃ¡c); máº·c Ä‘á»‹nh giá»¯ nguyÃªn cháº¥t lÆ°á»£ng, "
                         "ai cáº§n thÃ¬ sá»­a tháº³ng trong .env",
    "UPDATE_REPO": "Ä‘á»‹a chá»‰ kho phÃ¡t hÃ nh cá»‘ Ä‘á»‹nh cá»§a á»©ng dá»¥ng, ngÆ°á»i dÃ¹ng "
                   "khÃ´ng cáº§n Ä‘á»•i; ai cáº§n thÃ¬ sá»­a tháº³ng trong .env",
    "SUPPORT_URL": "Ä‘Æ°á»ng dáº«n biá»ƒu máº«u bÃ¡o lá»—i cá»‘ Ä‘á»‹nh, chá»‰ hiá»‡n á»Ÿ nÃºt Gá»­i "
                   "bÃ¡o lá»—i chá»© khÃ´ng pháº£i cáº¥u hÃ¬nh cá»§a ngÆ°á»i dÃ¹ng",
}


def fields_of(tab: str) -> list[Field]:
    """CÃ¡c má»¥c thuá»™c má»™t tháº», giá»¯ nguyÃªn thá»© tá»± khai bÃ¡o."""
    return [f for f in FIELDS if f.tab == tab]


def groups_of(tab: str) -> list[str]:
    """TÃªn cÃ¡c nhÃ³m trong má»™t tháº», khÃ´ng láº·p láº¡i."""
    seen: list[str] = []
    for item in fields_of(tab):
        if item.group not in seen:
            seen.append(item.group)
    return seen


def defaults() -> dict[str, str]:
    """GiÃ¡ trá»‹ máº·c Ä‘á»‹nh cá»§a má»i má»¥c."""
    return {item.key: item.default for item in FIELDS}


def field_keys() -> set[str]:
    """Táº­p khÃ³a mÃ  trang CÃ i Ä‘áº·t quáº£n lÃ½."""
    return {item.key for item in FIELDS}
