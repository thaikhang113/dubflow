"""Tests for slot annotation, character budgets, and terminal punctuation.

These three pieces implement the strict 1:1 dub contract: one translated
segment = one spoken clip that fits its real time window and ends on a
full-stop-class mark.
"""
import pytest

from autodub.text.translate_hint import (
    annotate_slots,
    ensure_terminal_punct,
    payload_segment,
)


def seg(i, start, end):
    return {"id": i, "text": f"t{i}", "start": start, "end": end,
            "duration": round(end - start, 3)}


# --------------------------- annotate_slots --------------------------- #

def test_slot_is_gap_to_next_start():
    segs = annotate_slots([seg(1, 0.0, 2.0), seg(2, 3.5, 5.0)])
    # Own duration (2.0) + trailing silence (1.5) = 3.5
    assert segs[0]["slot"] == 3.5


def test_last_segment_gets_tail_slack():
    segs = annotate_slots([seg(1, 0.0, 2.0)], tail_slack=2.0)
    assert segs[0]["slot"] == 4.0


def test_slot_clamped_on_broken_timestamps():
    # Next segment starts BEFORE this one (bad ASR data) → floor, not negative.
    segs = annotate_slots([seg(1, 5.0, 6.0), seg(2, 4.0, 7.0)])
    assert segs[0]["slot"] == 0.3


def test_slot_back_to_back():
    segs = annotate_slots([seg(1, 0.0, 2.0), seg(2, 2.0, 4.0)])
    assert segs[0]["slot"] == 2.0


def test_annotate_empty():
    assert annotate_slots([]) == []


# --------------------------- payload_segment --------------------------- #

def test_max_chars_follows_slot():
    s = {**seg(1, 0.0, 2.0), "slot": 3.5}
    from autodub.text.translate_hint import CHARS_PER_SECOND_BUDGET
    assert payload_segment(s)["max_chars"] == int(3.5 * CHARS_PER_SECOND_BUDGET)


def test_max_chars_follows_custom_cps_budget():
    s = {**seg(1, 0.0, 2.0), "slot": 4.0}
    assert payload_segment(s, cps_budget=10.0)["max_chars"] == 40
    assert payload_segment(s, cps_budget=14.0)["max_chars"] == 56


def test_max_chars_falls_back_to_duration():
    # Pre-slot transcripts (manual path) still get a budget.
    from autodub.text.translate_hint import CHARS_PER_SECOND_BUDGET
    assert (payload_segment(seg(1, 0.0, 3.0))["max_chars"]
            == int(3.0 * CHARS_PER_SECOND_BUDGET))


def test_max_chars_floor_is_12():
    s = {**seg(1, 0.0, 0.4), "slot": 0.3}
    assert payload_segment(s)["max_chars"] == 12


def test_payload_has_no_slot_field():
    # slot is internal; the model only needs duration + max_chars.
    s = {**seg(1, 0.0, 2.0), "slot": 2.0}
    assert "slot" not in payload_segment(s)


# --------------------------- ensure_terminal_punct --------------------------- #

@pytest.mark.parametrize("raw,expected", [
    ("xin chào", "xin chào."),
    ("xin chào.", "xin chào."),
    ("thật á?", "thật á?"),
    ("tuyệt vời!", "tuyệt vời!"),
    ("rồi sao nữa…", "rồi sao nữa…"),
    ("và rồi,", "và rồi."),           # trailing comma → full stop
    ("đợi chút -", "đợi chút."),      # trailing dash → full stop
    ("nhiều   khoảng  trắng", "nhiều khoảng trắng."),
    ("  có  đệm  hai đầu  ", "có đệm hai đầu."),
    ("", ""),
])
def test_terminal_punct(raw, expected):
    assert ensure_terminal_punct(raw) == expected
