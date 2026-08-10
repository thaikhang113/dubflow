"""Danh mục giọng đọc VieNeu — nguồn dữ liệu DUY NHẤT cho mọi nơi chọn giọng.

Ứng dụng chỉ còn một bộ giọng (VieNeu), nên người dùng không chọn "nam/nữ"
nữa mà chọn thẳng TÊN giọng. Giới tính, vùng miền và quốc gia chỉ còn là bộ
lọc để tìm giọng cho nhanh.

Nguồn giọng DUY NHẤT: ``models/vieneu/custom_voices.json``, do
:mod:`autodub.speech.tts.vieneu_worker` ghi ra sau khi enroll từ thư viện
``voices/preset_voices_vn/`` (tải về lần đầu chạy app qua voice_downloader).

Không còn giọng builtin hardcoded — catalog rỗng khi chưa tải voices.

Module này KHÔNG nạp model và không phụ thuộc venv riêng của VieNeu, nên
giao diện gọi thoải mái.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

# --- Từ vựng dùng chung cho bộ lọc ----------------------------------------

GENDERS: tuple[tuple[str, str], ...] = (
    ("Nam", "male"),
    ("Nữ", "female"),
)

REGIONS: tuple[tuple[str, str], ...] = (
    ("Miền Bắc", "bac"),
    ("Miền Trung", "trung"),
    ("Miền Nam", "nam"),
)

COUNTRIES: tuple[tuple[str, str], ...] = (
    ("Việt Nam", "vn"),
    # ("Mỹ", "us"),
    # ("Anh", "uk"),
    # ("Nhật Bản", "jp"),
    # ("Hàn Quốc", "kr"),
    # ("Trung Quốc", "cn"),
    # ("Khác", "other"),
)

STYLES: tuple[tuple[str, str], ...] = (
    ("Tự nhiên", "tu_nhien"),
    ("Tin tức", "tin_tuc"),
    ("Kể chuyện", "doc_truyen"),
)

_GENDER_LABEL = dict((k, v) for v, k in GENDERS)
_REGION_LABEL = dict((k, v) for v, k in REGIONS)
_COUNTRY_LABEL = dict((k, v) for v, k in COUNTRIES)
_STYLE_LABEL = dict((k, v) for v, k in STYLES)

# Nhãn giọng của VieNeu viết vùng miền bằng tiếng Việt có dấu.
_REGION_FROM_TEXT = {"bắc": "bac", "trung": "trung", "nam": "nam"}
_STYLE_FROM_TEXT = {
    "tin tức": "tin_tuc",
    "kể chuyện": "doc_truyen",
    "tự nhiên": "tu_nhien",
}


@dataclass(frozen=True)
class Voice:
    """Một giọng đọc: tên là định danh, phần còn lại chỉ để lọc và hiển thị."""

    name: str
    gender: str = ""          # "male" | "female" | ""
    region: str = ""          # "bac" | "trung" | "nam" | ""
    country: str = "vn"       # khóa trong COUNTRIES
    style: str = "tu_nhien"   # khóa trong STYLES
    description: str = ""
    #: "builtin" (đóng kèm model) | "library" (thư mục voices/) | "custom"
    #: (bạn tự học từ một đoạn ghi âm) | "capcut" (bộ giọng CapCut, chỉ có
    #: embedding — không có file âm thanh trên máy).
    source: str = "builtin"

    @property
    def custom(self) -> bool:
        """Giọng này do người dùng tự học hay không."""
        return self.source == "custom"

    @property
    def is_capcut(self) -> bool:
        """Giọng thuộc bộ CapCut hay không."""
        return self.source == "capcut"

    @property
    def label(self) -> str:
        """Dòng chữ hiện trong ô chọn giọng."""
        parts = [
            _GENDER_LABEL.get(self.gender, ""),
            _REGION_LABEL.get(self.region, ""),
            _COUNTRY_LABEL.get(self.country, "") if self.country != "vn" else "",
            _STYLE_LABEL.get(self.style, ""),
        ]
        detail = " · ".join(p for p in parts if p)
        prefix = ("CapCut · " if self.is_capcut
                  else "Giọng bạn thêm · " if self.custom else "")
        return f"{self.name} — {prefix}{detail}" if detail else self.name

    def matches(self, gender: str = "", region: str = "",
                country: str = "", style: str = "", query: str = "") -> bool:
        """Giọng này có lọt qua bộ lọc đang chọn không (ô rỗng = không lọc)."""
        if gender and self.gender != gender:
            return False
        if region and self.region != region:
            return False
        if country and self.country != country:
            return False
        if style and self.style != style:
            return False
        if query and query.strip().lower() not in self.label.lower():
            return False
        return True


# --- Không có giọng builtin — tất cả phải tải từ internet ---------------
# App tự động tải voices.zip từ GitHub lần đầu chạy (voice_downloader).
BUILTIN: tuple[Voice, ...] = ()


def source_group(voice: Voice) -> str:
    """Nhóm nguồn cho tab giao diện: "capcut" hoặc "offline" (mọi thứ khác).

    Điểm phân loại DUY NHẤT — Thư viện giọng và ô chọn giọng đều gọi hàm này
    để hai nơi không bao giờ chia tab khác nhau.
    """
    return "capcut" if voice.is_capcut else "offline"

#: Giọng fallback khi catalog trống (ví dụ chưa tải voices).
# Tên này sẽ trùng với một giọng trong thư viện sau khi tải.
DEFAULT_VOICE = "Trần Hải"


def _from_label(name: str, label: str) -> Voice:
    """Dựng một giọng từ nhãn kiểu «Nam · Bắc · Phong cách tin tức»."""
    text = (label or "").lower()
    gender = "female" if "nữ" in text else ("male" if "nam ·" in text
                                            or text.startswith("nam") else "")
    region = ""
    for word, key in _REGION_FROM_TEXT.items():
        # Vùng miền là mảnh GIỮA hai dấu chấm giữa, tránh nhầm với giới tính.
        if f"· {word}" in text:
            region = key
            break
    style = "tu_nhien"
    for word, key in _STYLE_FROM_TEXT.items():
        if word in text:
            style = key
            break
    return Voice(name, gender, region, style=style, description=label)


def _builtin_voices(model_dir: str) -> list[Voice]:
    """Không còn giọng builtin — mọi giọng đều đến từ custom_voices.json.

    Hàm giữ lại để không vỡ code gọi catalog(); luôn trả về danh sách rỗng.
    """
    return []


def _custom_voices(custom_path: str) -> list[Voice]:
    """Giọng người dùng tự học từ đoạn ghi âm."""
    if not custom_path or not os.path.isfile(custom_path):
        return []
    try:
        with open(custom_path, encoding="utf-8") as f:
            presets = json.load(f).get("presets", {})
    except (OSError, ValueError):
        return []
    voices: list[Voice] = []
    for name, entry in (presets or {}).items():
        if not isinstance(entry, dict) or not str(name).strip():
            continue
        source = str(entry.get("source", "") or "custom")
        # Bản cũ từng enroll 16 giọng clone source="capcut" vào file này.
        # Giờ giọng CapCut đến từ API (_capcut_voices) và trùng tên, nên bỏ
        # qua preset cũ để nó không chắn mất giọng API.
        if source == "capcut":
            continue
        voices.append(Voice(
            name=str(name),
            gender=str(entry.get("gender", "")),
            region=str(entry.get("region", "")),
            country=str(entry.get("country", "") or "vn"),
            style=str(entry.get("style", "") or "tu_nhien"),
            description=str(entry.get("description", "")),
            source=source,
        ))
    return voices


def _capcut_voices() -> list[Voice]:
    """Giọng CapCut gọi qua API — chỉ đọc JSON tĩnh trong gói, không mạng."""
    from autodub.speech.tts import capcut_catalog

    return [Voice(name=e["name"], gender=e["gender"], region="",
                  country="vn", style="tu_nhien",
                  description=e["description"], source="capcut")
            for e in capcut_catalog.entries()]


def is_capcut_voice(name: str) -> bool:
    """Tên giọng này thuộc bộ CapCut (gọi API) hay bộ offline (VieNeu)."""
    from autodub.speech.tts import capcut_catalog

    return (name or "").strip() in capcut_catalog.names()


#: Cache danh mục giọng — tránh đọc lại JSON mỗi lần gọi (A5 fix).
#: Khoá theo đường dẫn file, huỷ hiệu lực khi mtime đổi (enroll giọng mới).
_catalog_cache: dict[str, tuple[float, list[Voice]]] = {}


def catalog(settings) -> list[Voice]:
    """Toàn bộ giọng dùng được: giọng tự thêm, giọng có sẵn, rồi giọng CapCut.

    Kết quả được cache theo mtime của ``custom_voices.json`` — giao diện gọi
    hàm này rất nhiều lần (bộ lọc, ô chọn giọng, resolve) nên đọc đĩa mỗi lần
    là lãng phí. Enroll giọng mới đổi mtime nên cache tự huỷ hiệu lực. Giọng
    CapCut đọc từ file tĩnh trong gói nên không ảnh hưởng khoá cache.
    """
    custom_path = settings.vieneu_custom_voices_path()
    try:
        mtime = os.path.getmtime(custom_path) if custom_path else 0.0
    except OSError:
        mtime = 0.0

    cached = _catalog_cache.get(custom_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    custom = _custom_voices(custom_path)
    builtin = _builtin_voices(settings.vieneu_model_dir_path())
    taken = {v.name for v in custom}
    result = custom + [v for v in builtin if v.name not in taken]
    taken |= {v.name for v in result}
    result += [v for v in _capcut_voices() if v.name not in taken]
    _catalog_cache[custom_path] = (mtime, result)
    return result


def invalidate_catalog_cache() -> None:
    """Xoá cache danh mục — gọi sau khi enroll/xoá giọng để nạp lại ngay."""
    _catalog_cache.clear()


def resolve(settings, name: str | None = None) -> str:
    """Tên giọng dùng thật cho một lần chạy.

    Thứ tự ưu tiên: tên gọi truyền vào → giọng mặc định trong cấu hình →
    :data:`DEFAULT_VOICE` → giọng đầu tiên của danh mục. Luôn trả về một tên
    có trong danh mục để worker không chết vì «unknown voice»; máy chưa cài
    VieNeu vẫn có bộ giọng CapCut nên danh mục không bao giờ rỗng thật sự.
    """
    voices = catalog(settings)
    names = {v.name for v in voices}
    for candidate in (name, getattr(settings, "vieneu_voice", "")):
        candidate = (candidate or "").strip()
        if candidate in names:
            return candidate
    if DEFAULT_VOICE in names:
        return DEFAULT_VOICE
    if voices:
        return voices[0].name
    from autodub.speech.tts.capcut_catalog import DEFAULT_CAPCUT_VOICE

    return DEFAULT_CAPCUT_VOICE
