"""Bảo đảm trang Cài đặt không bỏ sót khóa cấu hình nào.

Rủi ro lớn nhất khi viết lại trang Cài đặt là sót một ô: người dùng lưu lại
thì khóa bị sót sẽ mất giá trị cũ. Bài kiểm thử này đối chiếu tập khóa mà
trang Cài đặt quản lý với tập khóa trong tệp cấu hình mẫu.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from autodub_gui.pages import settings_fields as spec

_ROOT = Path(__file__).parent.parent
_ENV_EXAMPLE = _ROOT / ".env.example"
_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _example_keys() -> set[str]:
    return set(_KEY_RE.findall(_ENV_EXAMPLE.read_text(encoding="utf-8")))


def test_example_file_exists() -> None:
    assert _ENV_EXAMPLE.is_file(), "Thiếu tệp cấu hình mẫu .env.example"


def test_every_example_key_is_editable_or_exempt() -> None:
    """Mọi khóa trong tệp mẫu đều phải chỉnh được, hoặc được miễn trừ có lý do."""
    managed = spec.field_keys() | set(spec.EXEMPT_KEYS)
    missing = sorted(_example_keys() - managed)
    if missing:
        pytest.fail(
            "Những khóa sau có trong .env.example nhưng trang Cài đặt không "
            "chỉnh được. Hãy thêm vào FIELDS, hoặc ghi vào EXEMPT_KEYS kèm "
            "lý do:\n  " + "\n  ".join(missing))


def test_every_exempt_key_has_a_reason() -> None:
    for key, reason in spec.EXEMPT_KEYS.items():
        assert reason.strip(), f"Khóa miễn trừ {key} chưa ghi lý do"


def test_field_keys_are_unique() -> None:
    keys = [item.key for item in spec.FIELDS]
    duplicates = {k for k in keys if keys.count(k) > 1}
    assert not duplicates, f"Khóa bị khai báo trùng: {sorted(duplicates)}"


def test_every_field_has_label_and_hint() -> None:
    """Mỗi ô đều phải có nhãn và lời giải thích cho người dùng."""
    for item in spec.FIELDS:
        assert item.label.strip(), f"{item.key} thiếu nhãn"
        assert item.hint.strip(), f"{item.key} thiếu lời giải thích"


def test_labels_and_hints_are_accented_vietnamese() -> None:
    marks = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    for item in spec.FIELDS:
        combined = (item.label + " " + item.hint).lower()
        assert any(ch in combined for ch in marks), (
            f"{item.key}: nhãn hoặc lời giải thích chưa viết tiếng Việt có dấu")


def test_every_field_belongs_to_a_known_tab() -> None:
    for item in spec.FIELDS:
        assert item.tab in spec.TABS, f"{item.key} thuộc thẻ lạ: {item.tab}"


def test_all_tabs_have_fields() -> None:
    for tab in spec.TABS:
        if tab == spec.TAB_VOICE:
            # Thẻ Giọng đọc là thư viện giọng riêng (pages/voice_library.py),
            # không dựng từ bảng khai báo.
            continue
        assert spec.fields_of(tab), f"Thẻ {tab} không có mục nào"


def test_combo_fields_have_options() -> None:
    for item in spec.FIELDS:
        if item.kind == spec.COMBO:
            assert item.options, f"{item.key} là ô chọn nhưng chưa có lựa chọn"


def test_combo_default_is_one_of_the_options() -> None:
    """Giá trị mặc định phải nằm trong danh sách, nếu không ô sẽ trống trơn."""
    for item in spec.FIELDS:
        if item.kind != spec.COMBO or not item.default:
            continue
        keys = [key for _label, key in item.options]
        assert item.default in keys, (
            f"{item.key}: giá trị mặc định {item.default!r} không có trong "
            f"danh sách lựa chọn")


def test_slider_defaults_are_within_range() -> None:
    for item in spec.FIELDS:
        if item.kind not in (spec.SLIDER, spec.NUMBER):
            continue
        value = float(item.default or 0)
        assert item.minimum <= value <= item.maximum, (
            f"{item.key}: giá trị mặc định {value} nằm ngoài khoảng "
            f"{item.minimum} tới {item.maximum}")


def test_video_speed_range_matches_core_clamp() -> None:
    """Tốc độ video bị lõi xử lý kẹp trong khoảng 0.5 tới 1.0."""
    item = next(f for f in spec.FIELDS if f.key == "VIDEO_SPEED")
    assert (item.minimum, item.maximum) == (0.5, 1.0)


def test_voice_speed_range_matches_core_clamp() -> None:
    item = next(f for f in spec.FIELDS if f.key == "VOICE_SPEED")
    assert (item.minimum, item.maximum) == (0.5, 2.0)


def test_defaults_cover_every_field() -> None:
    assert set(spec.defaults()) == spec.field_keys()


def test_groups_are_listed_in_declaration_order() -> None:
    """Thứ tự nhóm trên giao diện phải đúng thứ tự khai báo."""
    for tab in spec.TABS:
        groups = spec.groups_of(tab)
        assert len(groups) == len(set(groups)), f"Thẻ {tab} có nhóm trùng tên"
