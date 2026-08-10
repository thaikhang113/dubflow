"""Kiểm thử năm hàm sửa cấu trúc câu thoại trong autodub/editor.py.

Điểm quan trọng nhất được kiểm tra ở đây: sau mỗi thao tác, số thứ tự câu
phải liền mạch từ 1 tới N và tệp giọng đọc phải được đổi tên theo. Nếu sai,
lần xuất video sau sẽ ghép giọng của câu này vào chỗ của câu khác.
"""
from __future__ import annotations

import json
import os

import pytest

from autodub.editor import (
    EditorError, add_segment, delete_segment, merge_segments, set_segment_time,
    split_segment,
)
from autodub.workdir import data_path

_TEXT_FIELD = "text_vi"


def _segments(count: int = 3) -> list[dict]:
    """Câu mẫu: mỗi câu dài 2 giây, cách nhau 1 giây, câu đầu bắt đầu ở giây 1."""
    out = []
    for i in range(1, count + 1):
        start = 1.0 + (i - 1) * 3.0
        out.append({
            "id": i,
            "start": start,
            "end": start + 2.0,
            "duration": 2.0,
            "text": f"nguyen ban cau {i}",
            _TEXT_FIELD: f"Câu thoại số {i} bằng tiếng Việt",
        })
    return out


@pytest.fixture()
def work_dir(tmp_path):
    """Thư mục dự án giả có bản dịch và tệp giọng đọc cho từng câu."""
    work = tmp_path / "20260804_vi"
    data = work / "data"
    seg_dir = data / "segments"
    seg_dir.mkdir(parents=True)
    (data / "transcript_vi.json").write_text(
        json.dumps(_segments(), ensure_ascii=False), encoding="utf-8")
    for i in range(1, 4):
        (seg_dir / f"seg_{i:05d}.wav").write_bytes(f"giong cau {i}".encode())
    (data / "audio_vi_full.wav").write_bytes(b"ban ghep cu")
    (work / "dubbed_video.mp4").write_bytes(b"video cu")
    (data / "segments_speed1_00").mkdir()
    return str(work)


def _read(work: str) -> list[dict]:
    with open(data_path(work, "transcript_vi.json"), encoding="utf-8") as f:
        return json.load(f)


def _wav_names(work: str) -> list[str]:
    seg_dir = data_path(work, "segments")
    return sorted(os.listdir(seg_dir)) if os.path.isdir(seg_dir) else []


def _wav_text(work: str, seg_id: int) -> str:
    path = os.path.join(data_path(work, "segments"), f"seg_{seg_id:05d}.wav")
    with open(path, "rb") as f:
        return f.read().decode()


# -- Thêm câu ----------------------------------------------------------

def test_add_segment_inserts_after_given_id(work_dir) -> None:
    new_id = add_segment(work_dir, 1, 3.2, 3.8, "Câu mới chèn vào")
    segments = _read(work_dir)
    assert new_id == 2
    assert len(segments) == 4
    assert segments[1][_TEXT_FIELD] == "Câu mới chèn vào"


def test_add_segment_at_beginning(work_dir) -> None:
    """Truyền 0 nghĩa là chèn lên đầu danh sách."""
    new_id = add_segment(work_dir, 0, 0.0, 0.5, "Câu mở đầu")
    assert new_id == 1
    assert _read(work_dir)[0][_TEXT_FIELD] == "Câu mở đầu"


def test_add_segment_renumbers_ids_continuously(work_dir) -> None:
    add_segment(work_dir, 1, 3.2, 3.8, "Chèn giữa")
    assert [s["id"] for s in _read(work_dir)] == [1, 2, 3, 4]


def test_add_segment_shifts_audio_files_correctly(work_dir) -> None:
    """Câu cũ số 2 và 3 phải dời thành 3 và 4, nội dung giọng đi theo."""
    add_segment(work_dir, 1, 3.2, 3.8, "Chèn giữa")
    assert _wav_text(work_dir, 1) == "giong cau 1"
    assert _wav_text(work_dir, 3) == "giong cau 2"
    assert _wav_text(work_dir, 4) == "giong cau 3"
    assert not os.path.exists(
        os.path.join(data_path(work_dir, "segments"), "seg_00002.wav"))


def test_add_segment_rejects_unknown_id(work_dir) -> None:
    with pytest.raises(EditorError, match="Không tìm thấy câu số 99"):
        add_segment(work_dir, 99, 1.0, 2.0, "x")


def test_add_segment_rejects_too_short_span(work_dir) -> None:
    with pytest.raises(EditorError, match="ít nhất"):
        add_segment(work_dir, 1, 3.2, 3.25, "quá ngắn")


def test_add_segment_rejects_overlap(work_dir) -> None:
    """Chèn đè lên câu liền trước phải bị chặn."""
    with pytest.raises(EditorError, match="câu liền trước"):
        add_segment(work_dir, 1, 2.0, 3.5, "đè lên câu trước")


# -- Xóa câu -----------------------------------------------------------

def test_delete_segment_removes_entry(work_dir) -> None:
    delete_segment(work_dir, 2)
    segments = _read(work_dir)
    assert len(segments) == 2
    assert [s["id"] for s in segments] == [1, 2]


def test_delete_segment_removes_its_audio_and_shifts_rest(work_dir) -> None:
    delete_segment(work_dir, 2)
    assert _wav_names(work_dir) == ["seg_00001.wav", "seg_00002.wav"]
    assert _wav_text(work_dir, 1) == "giong cau 1"
    assert _wav_text(work_dir, 2) == "giong cau 3"


def test_delete_segment_rejects_unknown_id(work_dir) -> None:
    with pytest.raises(EditorError, match="Không tìm thấy câu số 42"):
        delete_segment(work_dir, 42)


def test_delete_last_remaining_segment_is_refused(tmp_path) -> None:
    """Dự án phải còn ít nhất một câu."""
    work = tmp_path / "solo_vi"
    (work / "data").mkdir(parents=True)
    (work / "data" / "transcript_vi.json").write_text(
        json.dumps(_segments(1), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(EditorError, match="ít nhất một câu"):
        delete_segment(str(work), 1)


# -- Tách câu ----------------------------------------------------------

def test_split_segment_creates_two_parts(work_dir) -> None:
    left, right = split_segment(work_dir, 2, 5.0)
    segments = _read(work_dir)
    assert (left, right) == (2, 3)
    assert len(segments) == 4
    assert segments[1]["end"] == 5.0
    assert segments[2]["start"] == 5.0


def test_split_segment_divides_text_at_word_boundary(work_dir) -> None:
    """Chữ được chia theo tỉ lệ nhưng không cắt đứt đôi một chữ."""
    split_segment(work_dir, 2, 5.0)
    segments = _read(work_dir)
    left_text = segments[1][_TEXT_FIELD]
    right_text = segments[2][_TEXT_FIELD]
    assert left_text and right_text
    assert " ".join((left_text, right_text)).split() == (
        "Câu thoại số 2 bằng tiếng Việt".split())


def test_split_segment_renumbers_and_moves_audio(work_dir) -> None:
    split_segment(work_dir, 2, 5.0)
    assert [s["id"] for s in _read(work_dir)] == [1, 2, 3, 4]
    # Câu 3 cũ dời thành câu 4, giọng đi theo; hai nửa vừa tách chưa có giọng.
    assert _wav_text(work_dir, 4) == "giong cau 3"
    assert not os.path.exists(
        os.path.join(data_path(work_dir, "segments"), "seg_00002.wav"))
    assert not os.path.exists(
        os.path.join(data_path(work_dir, "segments"), "seg_00003.wav"))


def test_split_segment_rejects_time_outside_segment(work_dir) -> None:
    with pytest.raises(EditorError, match="quá sát đầu hoặc cuối"):
        split_segment(work_dir, 2, 10.0)


def test_split_segment_rejects_time_too_close_to_edge(work_dir) -> None:
    with pytest.raises(EditorError, match="quá sát đầu hoặc cuối"):
        split_segment(work_dir, 2, 4.05)


def test_split_segment_rejects_unknown_id(work_dir) -> None:
    with pytest.raises(EditorError, match="Không tìm thấy câu số 7"):
        split_segment(work_dir, 7, 1.0)


# -- Gộp câu -----------------------------------------------------------

def test_merge_segments_joins_range(work_dir) -> None:
    kept = merge_segments(work_dir, [1, 2])
    segments = _read(work_dir)
    assert kept == 1
    assert len(segments) == 2
    assert segments[0]["start"] == 1.0
    assert segments[0]["end"] == 6.0


def test_merge_segments_concatenates_text(work_dir) -> None:
    merge_segments(work_dir, [1, 2])
    merged = _read(work_dir)[0]
    assert merged[_TEXT_FIELD] == (
        "Câu thoại số 1 bằng tiếng Việt Câu thoại số 2 bằng tiếng Việt")


def test_merge_segments_renumbers_and_drops_old_audio(work_dir) -> None:
    merge_segments(work_dir, [1, 2])
    assert [s["id"] for s in _read(work_dir)] == [1, 2]
    # Câu gộp phải được đọc lại nên không còn giọng cũ ở vị trí 1.
    assert not os.path.exists(
        os.path.join(data_path(work_dir, "segments"), "seg_00001.wav"))
    assert _wav_text(work_dir, 2) == "giong cau 3"


def test_merge_segments_requires_two_or_more(work_dir) -> None:
    with pytest.raises(EditorError, match="ít nhất hai câu"):
        merge_segments(work_dir, [1])


def test_merge_segments_refuses_non_adjacent(work_dir) -> None:
    with pytest.raises(EditorError, match="liền nhau"):
        merge_segments(work_dir, [1, 3])


def test_merge_segments_rejects_unknown_id(work_dir) -> None:
    with pytest.raises(EditorError, match="Không tìm thấy câu số 9"):
        merge_segments(work_dir, [1, 9])


# -- Đổi mốc thời gian -------------------------------------------------

def test_set_segment_time_updates_span(work_dir) -> None:
    set_segment_time(work_dir, 2, 3.5, 4.5)
    segment = _read(work_dir)[1]
    assert segment["start"] == 3.5
    assert segment["end"] == 4.5
    assert segment["duration"] == 1.0


def test_set_segment_time_keeps_ids_unchanged(work_dir) -> None:
    """Đổi mốc thời gian không làm xáo trộn thứ tự câu."""
    set_segment_time(work_dir, 2, 3.5, 4.5)
    assert [s["id"] for s in _read(work_dir)] == [1, 2, 3]
    assert _wav_text(work_dir, 2) == "giong cau 2"


def test_set_segment_time_rejects_overlap_with_previous(work_dir) -> None:
    with pytest.raises(EditorError, match="câu liền trước"):
        set_segment_time(work_dir, 2, 2.0, 5.0)


def test_set_segment_time_rejects_overlap_with_next(work_dir) -> None:
    with pytest.raises(EditorError, match="câu liền sau"):
        set_segment_time(work_dir, 2, 4.0, 8.0)


def test_set_segment_time_rejects_reversed_span(work_dir) -> None:
    with pytest.raises(EditorError, match="ít nhất"):
        set_segment_time(work_dir, 2, 6.0, 5.0)


def test_set_segment_time_rejects_negative_start(work_dir) -> None:
    with pytest.raises(EditorError, match="số âm"):
        set_segment_time(work_dir, 1, -1.0, 2.0)


# -- Dọn tệp dẫn xuất --------------------------------------------------

@pytest.mark.parametrize("action", [
    lambda w: add_segment(w, 1, 3.2, 3.8, "x"),
    lambda w: delete_segment(w, 2),
    lambda w: split_segment(w, 2, 5.0),
    lambda w: merge_segments(w, [1, 2]),
    lambda w: set_segment_time(w, 2, 3.5, 4.5),
])
def test_every_structural_change_invalidates_derived_files(work_dir, action) -> None:
    """Bản ghép và video cũ phải bị xóa, nếu không sẽ ghép nhầm giọng."""
    action(work_dir)
    assert not os.path.exists(data_path(work_dir, "audio_vi_full.wav"))
    assert not os.path.exists(os.path.join(work_dir, "dubbed_video.mp4"))


def test_structural_change_removes_processed_segment_dirs(work_dir) -> None:
    delete_segment(work_dir, 2)
    assert not os.path.isdir(data_path(work_dir, "segments_speed1_00"))


# -- Tính toàn vẹn của tệp --------------------------------------------

def test_transcript_stays_valid_after_a_rejected_operation(work_dir) -> None:
    """Thao tác bị từ chối không được làm hỏng tệp bản dịch."""
    before = _read(work_dir)
    with pytest.raises(EditorError):
        merge_segments(work_dir, [1, 3])
    assert _read(work_dir) == before


def test_audio_files_untouched_after_a_rejected_operation(work_dir) -> None:
    before = _wav_names(work_dir)
    with pytest.raises(EditorError):
        split_segment(work_dir, 2, 99.0)
    assert _wav_names(work_dir) == before


def test_missing_transcript_reports_friendly_message(tmp_path) -> None:
    work = tmp_path / "trong_vi"
    work.mkdir()
    with pytest.raises(EditorError, match="Chưa có bản dịch"):
        delete_segment(str(work), 1)


def test_all_error_messages_are_accented_vietnamese(work_dir) -> None:
    """Mọi thông điệp lỗi phải viết tiếng Việt có dấu."""
    marks = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    cases = (
        lambda: merge_segments(work_dir, [1]),
        lambda: split_segment(work_dir, 2, 99.0),
        lambda: delete_segment(work_dir, 99),
        lambda: set_segment_time(work_dir, 1, -1.0, 2.0),
    )
    for case in cases:
        with pytest.raises(EditorError) as info:
            case()
        assert any(ch in str(info.value).lower() for ch in marks), info.value
