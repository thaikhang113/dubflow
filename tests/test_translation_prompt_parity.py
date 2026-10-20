"""Đường dịch API và đường dịch tay phải dùng CÙNG một bộ hướng dẫn.

Trước đây mỗi đường có một prompt riêng: đường API là một khối ngắn ~28 dòng
không có style rules, không có luật max_chars/prosody, nên cùng một video
dịch qua API cho kết quả khác hẳn bản dịch tay. Các test dưới đây khoá lại
việc hai đường chia sẻ đúng một nguồn hướng dẫn.
"""
from autodub.languages import get_target
from autodub.providers.openai_compatible import build_translation_prompt
from autodub.text.translate_hint import (
    build_translation_prompt as build_shared_prompt,
)

SEGMENTS = [{"id": 1, "text": "你好", "duration": 2.0, "max_chars": 24}]
CONTEXT = {"pronouns": "mình - các bạn", "styleNotes": "tự nhiên"}
PREVIOUS = [{"id": 0, "text": "前一句"}]


def test_prompt_api_chua_nguyen_bo_huong_dan_cua_duong_dich_tay():
    shared = build_shared_prompt(
        get_target("vi"), "zh-CN", compact_output=True)
    api = build_translation_prompt(SEGMENTS, CONTEXT, PREVIOUS,
                                   source_lang="zh-CN")
    assert shared in api


def test_prompt_api_giu_du_luat_makinh_nghiem_trong_ban_dich_tay():
    api = build_translation_prompt(SEGMENTS, CONTEXT, PREVIOUS,
                                   source_lang="zh-CN")
    for rule in ("### FIDELITY TO THE ORIGINAL", "### PROSODY & EMPHASIS",
                 "### DURATION-AWARE LENGTH & PACING",
                 "### FINAL QUALITY CHECK", "HARD LIMIT", "max_chars"):
        assert rule in api, rule


def test_prompt_api_van_gui_kem_ngu_canh_va_cau_truoc():
    api = build_translation_prompt(SEGMENTS, CONTEXT, PREVIOUS,
                                   source_lang="zh-CN")
    assert "mình - các bạn" in api
    assert "tự nhiên" in api
    assert "前一句" in api


def test_prompt_api_khong_con_khoi_van_ban_cu():
    api = build_translation_prompt(SEGMENTS, CONTEXT, PREVIOUS,
                                   source_lang="zh-CN")
    assert "Các câu cần dịch" not in api
    assert "Ngữ cảnh:" not in api


def test_prompt_api_dung_schema_compact_de_translate_parse_duoc():
    api = build_translation_prompt(SEGMENTS, CONTEXT, PREVIOUS,
                                   source_lang="zh-CN")
    assert '{"segments": [...]}' in api
    format_block = api.split("### OUTPUT FORMAT")[1].split("### STYLE")[0]
    assert "EXACTLY two fields" in format_block
    # Bản dịch tay giữ nguyên timing; bản API thì không — đúng thứ
    # parse_response_segments() đọc được.
    manual = build_shared_prompt(
        get_target("vi"), "zh-CN", compact_output=False)
    assert "`start`, `end`, and `duration` (in seconds)" in manual
    assert "`start`, `end`, and `duration` (in seconds)" not in api


def test_prompt_api_theo_ngon_ngu_nguon_duoc_truyen_vao():
    api = build_translation_prompt(SEGMENTS, None, None, source_lang="en-US")
    assert "from en-US to Vietnamese" in api


def test_prompt_api_theo_cps_budget_duoc_truyen_vao():
    api = build_translation_prompt(SEGMENTS, None, None, cps_budget=9.5)
    assert "~9.5 chars/sec" in api
