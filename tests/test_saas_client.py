"""Máy khách SaaS: mã thiết bị, khóa idempotency, ghép bản dịch."""
from __future__ import annotations

import pytest

from autodub.device_id import get_fingerprint, short_id
from autodub.text.translate_common import TranslateError
from autodub.text.translate_saas import (
    _batch_job_id, _context_from_settings, _merge, _payload_segment,
    _prev_context, run_id_for,
)


class _Target:
    text_field = "text_vi"


TARGET = _Target()


def seg(i: int, text: str = "你好", duration: float = 2.0, slot: float = 2.5) -> dict:
    return {"id": i, "text": text, "start": 0.0, "end": duration,
            "duration": duration, "slot": slot}


# --------------------------------------------------------------- mã máy ----

def test_fingerprint_is_stable_within_a_session():
    assert get_fingerprint() == get_fingerprint()


def test_fingerprint_is_a_sha256_hex():
    fp = get_fingerprint()
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_short_id_matches_fingerprint_prefix():
    assert short_id() == get_fingerprint()[:8].upper()


# -------------------------------------------------------- khóa idempotency --

def test_run_id_stable_for_same_transcript():
    """Chạy lại cùng transcript phải ra cùng mã — nếu không thì các lô đã
    tính phí ở lượt trước bị tính lại từ đầu."""
    segments = [seg(1), seg(2, "再见")]
    assert run_id_for(segments, TARGET) == run_id_for(list(segments), TARGET)


def test_run_id_changes_when_source_text_changes():
    assert run_id_for([seg(1)], TARGET) != run_id_for([seg(1, "khác")], TARGET)


def test_run_id_changes_when_segment_added():
    assert run_id_for([seg(1)], TARGET) != run_id_for([seg(1), seg(2)], TARGET)


def test_batch_job_ids_follow_content_not_index():
    """Đổi translate_batch_size giữa hai lần chạy làm ranh giới lô xê dịch —
    khóa phải theo NỘI DUNG lô: cùng lô → cùng khóa, khác lô → khác khóa."""
    run = run_id_for([seg(1), seg(2, "再见")], TARGET)
    assert _batch_job_id(run, [seg(1)]) == _batch_job_id(run, [seg(1)])
    assert _batch_job_id(run, [seg(1)]) != _batch_job_id(run, [seg(2, "再见")])
    assert _batch_job_id(run, [seg(1)]) != _batch_job_id(run, [seg(1), seg(2, "再见")])


# ------------------------------------------------------------- payload -----

def test_payload_drops_timeline_fields():
    """start/end không giúp gì cho việc dịch mà nhân với hàng nghìn câu là
    hàng chục nghìn token vô ích."""
    out = _payload_segment(seg(1), 12.5)
    assert set(out) == {"id", "text", "duration", "max_chars"}


def test_payload_max_chars_follows_slot_not_duration():
    out = _payload_segment(seg(1, duration=2.0, slot=4.0), 10.0)
    assert out["max_chars"] == 40


def test_payload_max_chars_has_a_floor():
    """Câu cực ngắn vẫn phải dịch được — trần 12 ký tự là sàn cứng."""
    out = _payload_segment(seg(1, duration=0.1, slot=0.1), 10.0)
    assert out["max_chars"] == 12


def test_payload_without_timing_has_no_budget():
    out = _payload_segment({"id": 1, "text": "x"}, 12.5)
    assert "max_chars" not in out


# ------------------------------------------------------------- ngữ cảnh ----

class _Settings:
    translate_domain = "review công nghệ"
    translate_context = ""
    translate_pronouns = "mình – các bạn"
    translate_glossary = ""
    translate_style_notes = ""
    translate_video_title = "Đập hộp"


def test_context_skips_empty_fields():
    out = _context_from_settings(_Settings())
    assert out == {"videoTitle": "Đập hộp", "domain": "review công nghệ",
                   "pronouns": "mình – các bạn"}


def test_context_of_none_is_empty():
    assert _context_from_settings(None) == {}


def test_prev_context_takes_preceding_segments():
    segments = [seg(i) for i in range(1, 6)]
    ctx = _prev_context(segments, 3, TARGET, n=2)
    assert [c["id"] for c in ctx] == [2, 3]


def test_prev_context_at_start_is_empty():
    assert _prev_context([seg(1), seg(2)], 0, TARGET) == []


def test_prev_context_includes_existing_translation():
    segments = [{**seg(1), "text_vi": "Xin chào"}, seg(2)]
    ctx = _prev_context(segments, 1, TARGET)
    assert ctx[0]["text_vi"] == "Xin chào"


# ---------------------------------------------------------------- ghép -----

def test_merge_keeps_client_side_fields():
    """Máy chủ chỉ trả id + bản dịch; start/end/slot của máy khách phải còn
    nguyên, nếu không thì bước TTS mất hết mốc thời gian."""
    merged = _merge([seg(1)], [{"id": 1, "text_vi": "Xin chào."}], "text_vi")
    assert merged[0]["start"] == 0.0
    assert merged[0]["slot"] == 2.5
    assert merged[0]["text_vi"] == "Xin chào."


def test_merge_does_not_mutate_source():
    original = seg(1)
    _merge([original], [{"id": 1, "text_vi": "Xin chào."}], "text_vi")
    assert "text_vi" not in original


def test_merge_matches_by_id_not_position():
    merged = _merge(
        [seg(1), seg(2)],
        [{"id": 2, "text_vi": "Hai."}, {"id": 1, "text_vi": "Một."}],
        "text_vi")
    assert [m["text_vi"] for m in merged] == ["Một.", "Hai."]


def test_merge_keeps_original_for_missing_segment():
    """Máy chủ đã tính phí và cache lô theo job_id — raise là ngõ cụt (chạy
    lại nhận đúng kết quả thiếu đó). Câu thiếu giữ nguyên bản gốc, lượt rà
    soát sẽ bắt chữ nguồn còn sót."""
    merged = _merge([seg(1), seg(2)], [{"id": 1, "text_vi": "Một."}], "text_vi")
    assert [m["text_vi"] for m in merged] == ["Một.", seg(2)["text"]]


def test_merge_treats_blank_translation_as_missing():
    merged = _merge([seg(1)], [{"id": 1, "text_vi": "   "}], "text_vi")
    assert merged[0]["text_vi"] == seg(1)["text"]
