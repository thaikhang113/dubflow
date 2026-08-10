"""Phụ đề viết riêng, khác lời đọc.

Đây là thứ làm cho việc "sửa phụ đề trực tiếp" thành thật: sửa chữ trên màn
hình không được kéo theo việc phải đọc lại giọng, và chữ đã sửa phải đi thẳng
vào tệp phụ đề dùng để ghi vào video.
"""
from __future__ import annotations

import json
import os

import pytest

from autodub.editor import (EditorError, save_segment_texts,
                            save_subtitle_texts)
from autodub.text.srt import (SUBTITLE_FIELD, generate_srt,
                              has_subtitle_override, split_for_display,
                              subtitle_text)


def seg(**kw) -> dict:
    base = {"id": 1, "start": 0.0, "end": 2.0, "duration": 2.0,
            "text": "原文", "text_vi": "Lời đọc."}
    base.update(kw)
    return base


# ------------------------------------------------------------ chọn chữ --- #

def test_falls_back_to_the_spoken_line():
    assert subtitle_text(seg()) == "Lời đọc."


def test_override_wins():
    assert subtitle_text(seg(**{SUBTITLE_FIELD: "Chữ riêng."})) == "Chữ riêng."


def test_blank_override_is_ignored():
    assert subtitle_text(seg(**{SUBTITLE_FIELD: "   "})) == "Lời đọc."


def test_override_equal_to_the_spoken_line_is_not_an_override():
    assert not has_subtitle_override(seg(**{SUBTITLE_FIELD: "Lời đọc."}))
    assert has_subtitle_override(seg(**{SUBTITLE_FIELD: "Khác."}))


def test_display_lines_use_the_override():
    cues = split_for_display(seg(**{SUBTITLE_FIELD: "Chữ riêng."}), "text_vi")
    assert cues[0]["text"] == "Chữ riêng."


def test_all_caps_applies_to_the_displayed_text():
    cues = split_for_display(seg(), "text_vi", all_caps=True)
    assert cues[0]["text"] == "LỜI ĐỌC."


def test_line_words_controls_wrapping():
    long = seg(text_vi="một hai ba bốn năm sáu bảy tám", end=8.0, duration=8.0)
    cues = split_for_display(long, "text_vi", line_words=2, max_lines=2)
    assert all(len(line.split()) <= 2
               for cue in cues for line in cue["text"].splitlines())


def test_generated_srt_contains_the_override(tmp_path):
    out = str(tmp_path / "a.srt")
    generate_srt([seg(**{SUBTITLE_FIELD: "Chữ riêng."})], out,
                 text_field="text_vi")
    assert "Chữ riêng." in open(out, encoding="utf-8").read()


# --------------------------------------------------------------- lưu ---- #

@pytest.fixture
def work_dir(tmp_path):
    from autodub.workdir import data_path

    path = data_path(str(tmp_path), "transcript_vi.json", create_dir=True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([seg(id=1), seg(id=2, text_vi="Câu hai.")], f,
                  ensure_ascii=False)
    return str(tmp_path), path


def read(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_saving_a_subtitle_leaves_the_spoken_line_alone(work_dir):
    wd, path = work_dir
    changed = save_subtitle_texts(wd, {1: "Chữ riêng."})
    assert changed == [1]
    rows = read(path)
    assert rows[0][SUBTITLE_FIELD] == "Chữ riêng."
    assert rows[0]["text_vi"] == "Lời đọc."      # giọng đọc không đổi


def test_subtitle_equal_to_the_spoken_line_is_dropped(work_dir):
    wd, path = work_dir
    save_subtitle_texts(wd, {1: "Chữ riêng."})
    save_subtitle_texts(wd, {1: "Lời đọc."})
    assert SUBTITLE_FIELD not in read(path)[0]


def test_clearing_a_subtitle_removes_the_field(work_dir):
    wd, path = work_dir
    save_subtitle_texts(wd, {1: "Chữ riêng."})
    changed = save_subtitle_texts(wd, {1: "  "})
    assert changed == [1]
    assert SUBTITLE_FIELD not in read(path)[0]


def test_unchanged_subtitle_reports_nothing_to_do(work_dir):
    wd, _path = work_dir
    save_subtitle_texts(wd, {1: "Chữ riêng."})
    assert save_subtitle_texts(wd, {1: "Chữ riêng."}) == []


def test_spoken_line_still_cannot_be_emptied(work_dir):
    wd, _path = work_dir
    with pytest.raises(EditorError, match="không được để trống"):
        save_segment_texts(wd, {1: "   "})


def test_unknown_id_is_reported(work_dir):
    wd, _path = work_dir
    with pytest.raises(EditorError, match="Không tìm thấy câu"):
        save_subtitle_texts(wd, {99: "x"})
