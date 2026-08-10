import os
from autodub.text.srt import generate_srt


def test_generate_srt_original_text(tmp_path):
    segments = [
        {"id": 1, "text": "Hello everyone", "start": 0.5, "end": 3.2, "duration": 2.7},
        {"id": 2, "text": "Welcome to the lesson", "start": 3.5, "end": 6.8, "duration": 3.3},
    ]
    output_path = str(tmp_path / "test.srt")
    result = generate_srt(segments, output_path, text_field="text")

    assert os.path.exists(result)
    content = open(result, encoding="utf-8").read()
    assert "1\n00:00:00,500 --> 00:00:03,200\nHello everyone" in content
    assert "2\n00:00:03,500 --> 00:00:06,800\nWelcome to the lesson" in content


def test_generate_srt_unicode_text(tmp_path):
    segments = [
        {
            "id": 1,
            "text": "你好",
            "text_vi": "Xin chào các bạn",
            "start": 0.0,
            "end": 2.0,
            "duration": 2.0,
        },
    ]
    output_path = str(tmp_path / "test_vi.srt")
    result = generate_srt(segments, output_path, text_field="text_vi")

    content = open(result, encoding="utf-8").read()
    assert "Xin chào các bạn" in content


def test_generate_srt_empty_segments(tmp_path):
    output_path = str(tmp_path / "empty.srt")
    result = generate_srt([], output_path, text_field="text")
    content = open(result, encoding="utf-8").read()
    assert content.strip() == ""


# ----------------------- display splitting (merged segments) --------------- #

from autodub.text.srt import split_for_display, MAX_LINE_CHARS, MAX_LINES_PER_CUE


def test_short_segment_single_cue():
    seg = {"start": 0.0, "end": 2.0, "text_vi": "Xin chào các bạn."}
    cues = split_for_display(seg, "text_vi")
    assert len(cues) == 1
    assert cues[0]["text"] == "Xin chào các bạn."


def test_long_segment_splits_into_cues():
    text = ("Nhưng khi giải mã nội dung bức bích họa, các nhà khoa học phát "
            "hiện một điều kỳ lạ, loài này không giống các loài động vật "
            "khác mà chúng ta từng biết.")
    seg = {"start": 10.0, "end": 17.4, "text_vi": text}
    cues = split_for_display(seg, "text_vi")
    assert len(cues) >= 2
    # every line respects the width cap
    for c in cues:
        for line in c["text"].split("\n"):
            assert len(line) <= MAX_LINE_CHARS
        assert len(c["text"].split("\n")) <= MAX_LINES_PER_CUE
    # cues tile the segment: continuous, ordered, exact ends
    assert cues[0]["start"] == 10.0
    assert cues[-1]["end"] == 17.4
    for a, b in zip(cues, cues[1:]):
        assert a["end"] == b["start"]


def test_cue_time_proportional_to_text():
    text = "ngắn thôi, " + "còn vế sau này thì dài hơn hẳn so với vế trước đó nhiều lắm luôn nhé bạn ơi."
    seg = {"start": 0.0, "end": 10.0, "text_vi": text}
    cues = split_for_display(seg, "text_vi")
    if len(cues) >= 2:
        assert (cues[0]["end"] - cues[0]["start"]) < (cues[-1]["end"] - cues[-1]["start"])


def test_empty_text_no_cues():
    assert split_for_display({"start": 0, "end": 1, "text_vi": " "}, "text_vi") == []
