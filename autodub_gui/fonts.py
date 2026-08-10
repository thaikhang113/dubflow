"""Nạp phông chữ kèm ứng dụng và liệt kê cho phần chọn phông phụ đề.

Phông phụ đề CHỈ được lấy từ thư mục `fonts/` của dự án, tuyệt đối không
liệt kê phông có sẵn trong máy. Lý do: chữ phụ đề được ghi thẳng lên video
bằng libass, mà libass chỉ đọc phông từ thư mục này. Nếu cho chọn phông của
máy, video xuất ra trên máy khác sẽ hiện sai phông hoặc mất dấu tiếng Việt.

Phông giao diện thì vẫn dùng phông hệ thống bình thường — quy tắc trên chỉ áp
cho phông ghi lên video.

Phông được nạp theo từng tệp và ghi nhớ tệp đã nạp, nên gọi lại bao nhiêu lần
cũng không tạo bản trùng. Người dùng thả tệp phông mới vào thư mục rồi mở lại
cửa sổ là thấy ngay, không cần khởi động lại ứng dụng.
"""
from __future__ import annotations

import os

from PySide6.QtGui import QFontDatabase

from autodub.utils import app_root, bundled_font_files

FONTS_DIRNAME = "fonts"

# Hậu tố cảnh báo gắn sau tên phông thiếu dấu tiếng Việt
NO_VIETNAMESE_SUFFIX = "  (không hiển thị được dấu tiếng Việt)"

# Phông dự phòng khi thư mục phông trống
FALLBACK_FONT = "Arial"

# đường dẫn tệp -> các họ phông trong tệp đó, rỗng nếu tệp hỏng
_loaded: dict[str, list[str]] = {}


def fonts_dir() -> str:
    """Thư mục chứa phông chữ dùng cho phụ đề."""
    return os.path.join(app_root(), FONTS_DIRNAME)


def load_app_fonts() -> list[str]:
    """Nạp mọi phông trong thư mục dự án và trả về danh sách họ phông."""
    families: list[str] = []
    for path in bundled_font_files():
        if path not in _loaded:
            font_id = QFontDatabase.addApplicationFont(path)
            _loaded[path] = (list(QFontDatabase.applicationFontFamilies(font_id))
                             if font_id >= 0 else [])
        families.extend(_loaded[path])
    seen: set[str] = set()
    unique: list[str] = []
    for family in families:
        if family not in seen:
            seen.add(family)
            unique.append(family)
    return unique


def supports_vietnamese(family: str) -> bool:
    """Phông này có đủ chữ tiếng Việt không.

    Thiếu thì chữ sẽ hiện thành ô vuông trên video.
    """
    try:
        return QFontDatabase.Vietnamese in QFontDatabase.writingSystems(family)
    except Exception:  # noqa: BLE001 — không xác định được thì đừng dọa người dùng
        return True


def app_font_families() -> list[str]:
    """Danh sách phông của dự án, đã sắp xếp, phông đủ dấu đứng trước."""
    families = load_app_fonts()
    with_marks = sorted(f for f in families if supports_vietnamese(f))
    without_marks = sorted(f for f in families if not supports_vietnamese(f))
    return with_marks + without_marks


def font_choices() -> list[tuple[str, str]]:
    """Cặp (nhãn hiển thị, tên phông) cho ô chọn phông.

    Phông thiếu dấu tiếng Việt vẫn được liệt kê nhưng có gắn cảnh báo, và
    không bao giờ được chọn làm mặc định.
    """
    choices: list[tuple[str, str]] = []
    for family in app_font_families():
        label = (family if supports_vietnamese(family)
                 else family + NO_VIETNAMESE_SUFFIX)
        choices.append((label, family))
    return choices


def default_subtitle_font() -> str:
    """Phông phụ đề mặc định: phông đầu tiên của dự án có đủ dấu tiếng Việt."""
    for family in app_font_families():
        if supports_vietnamese(family):
            return family
    return FALLBACK_FONT


def has_app_fonts() -> bool:
    """Thư mục phông của dự án có tệp nào dùng được không."""
    return bool(load_app_fonts())
