"""Chặn hồi quy mã hóa: tiếng Việt trong kho phải lưu đúng UTF-8 một lượt.

Bài học từ autodub/batch.py và .env.example: có một thời điểm nào đó toàn bộ
chú thích của chúng bị encode UTF-8 rồi đọc lại như CP1252 và encode lần nữa,
nên "Tải trước" thành "T\xe1\xba\xa3i tr\xc6\xb0...". Chuỗi đó vẫn chạy được, pytest
vẫn xanh, nhưng người dùng thấy chữ vỡ trong Nhật ký và trong tệp .env mẫu.

Kiểm tra dùng ftfy nếu có, và không bao giờ yêu cầu thư viện đó lúc chạy test:
thiếu ftfy thì bỏ qua (bài kiểm tra này là lưới chắn thêm, không phải cổng).
"""
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path

import pytest

_ftfy = pytest.importorskip("ftfy", reason="ftfy không có trong môi trường test")
fix_text = _ftfy.fix_text

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / ".env.example",
    ROOT / "autodub" / "batch.py",
    ROOT / "autodub_gui" / "pages" / "projects_page.py",
    ROOT / "autodub_gui" / "pages" / "settings_fields.py",
    ROOT / "autodub" / "pipeline.py",
]
# Dấu hiệu thô của văn bản bị encode hai lượt (á»/, â€/ , Æ°). Chỉ dùng để
# đọc nhanh khi có lỗi; phần kết luận thuộc về _is_double_encoded().
MOJIBAKE = re.compile(r"á»|â€|Æ°|Ã©|Ã\xa0|Ä\u2018")

def _cp1252_high_bytes() -> set[str]:
    chars = set()
    for value in range(128, 256):
        try:
            chars.add(bytes([value]).decode("cp1252"))
        except UnicodeDecodeError:
            pass
    chars |= {chr(code) for code in range(0x80, 0xA0)}
    return chars


HIGH = _cp1252_high_bytes()


def _is_double_encoded(line: str) -> bool:
    """True khi ftfy sửa dòng này CHỈ bằng cách gỡ một lượt mã hóa CP1252."""
    fixed = fix_text(line)
    if fixed == line:
        return False
    removed = {ch for ch in set(line) if ch not in set(fixed)}
    added = {ch for ch in set(fixed) if ch not in set(line)}
    if not removed <= HIGH:
        return False        # mất ký tự thật (vd dấu câu toàn góc) -> không phải lỗi
    return all(
        ord(ch) >= 0x80 and unicodedata.category(ch).startswith("L")
        for ch in added)


@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
def test_no_double_encoded_vietnamese(path: Path) -> None:
    assert path.is_file(), f"Thiếu tệp {path.name} - cập nhật danh sách kiểm tra"
    text = io.open(path, encoding="utf-8-sig").read()
    bad = [index for index, line in enumerate(text.splitlines(), 1)
           if not all(ord(ch) < 128 for ch in line) and _is_double_encoded(line)]
    assert not bad, (
        f"{path.name}:{bad[:8]} chứa tiếng Việt bị mã hóa hai lần. "
        "Chạy ftfy.fix_text cho các dòng đó rồi kiểm tra lại.")


def test_fullwidth_punctuation_in_batch_is_deliberate() -> None:
    """Bộ dấu câu Trung Quốc trong batch.py KHÔNG phải lỗi mã hóa.

    Nếu ai đó "sửa" nó thành dấu nửa rộng, lời nhắc này giữ lại lý do để
    kiểm tra thủ công không bị tự động hóa nuốt mất.
    """
    text = io.open(ROOT / "autodub" / "batch.py", encoding="utf-8-sig").read()
    assert "\uff0c" in text and "\u3002" in text, (
        "Bộ ký tự rstrip dấu câu Trung Quốc đã bị thay bằng dấu nửa rộng - "
        "đây là hành vi thật, liên quan tới link dán từ app Douyin/Bilibili.")
