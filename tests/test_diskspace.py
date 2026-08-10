"""Kiểm tra autodub.diskspace — logic thuần, không cần Qt."""
import os

from autodub.diskspace import (
    OUTPUT_VIDEO, clean_all, clean_project, dir_size, measure, measure_project,
)
from autodub.workdir import DATA_SUBDIR


def _write(path, size=100):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)


def _make_project(root, name, done=True, legacy=False, data_size=1000):
    """Dựng một thư mục dự án giả: bản mới (data/) hoặc bản cũ (phẳng)."""
    work = os.path.join(str(root), name)
    os.makedirs(work, exist_ok=True)
    if done:
        _write(os.path.join(work, OUTPUT_VIDEO), 500)
        _write(os.path.join(work, "transcript_vi.srt"), 50)
    if legacy:
        _write(os.path.join(work, "original_audio.wav"), data_size)
        _write(os.path.join(work, "segments", "seg_0001.wav"), data_size)
        _write(os.path.join(work, "segments_speed1.2", "seg_0001.wav"),
               data_size)
    else:
        _write(os.path.join(work, DATA_SUBDIR, "original_audio.wav"),
               data_size)
        _write(os.path.join(work, DATA_SUBDIR, "segments", "seg_0001.wav"),
               data_size)
    return work


def test_dir_size_missing_is_zero(tmp_path):
    assert dir_size(str(tmp_path / "khong_ton_tai")) == 0


def test_measure_project_done_counts_cleanable(tmp_path):
    work = _make_project(tmp_path, "p1", done=True)
    usage = measure_project(work)
    assert usage.has_output
    assert usage.cleanable_bytes == 2000          # data/ chứa 2 tệp 1000 byte
    assert usage.total_bytes > usage.cleanable_bytes


def test_measure_project_unfinished_not_cleanable(tmp_path):
    work = _make_project(tmp_path, "p1", done=False)
    usage = measure_project(work)
    assert not usage.has_output
    assert usage.cleanable_bytes == 0


def test_clean_project_new_layout_keeps_outputs(tmp_path):
    work = _make_project(tmp_path, "p1", done=True)
    freed = clean_project(work)
    assert freed == 2000
    assert os.path.isfile(os.path.join(work, OUTPUT_VIDEO))
    assert os.path.isfile(os.path.join(work, "transcript_vi.srt"))
    assert not os.path.exists(os.path.join(work, DATA_SUBDIR))


def test_clean_project_legacy_keeps_outputs(tmp_path):
    work = _make_project(tmp_path, "p1", done=True, legacy=True)
    _write(os.path.join(work, "transcript_vi.json"), 30)   # tệp cần giữ
    freed = clean_project(work)
    assert freed == 3000
    assert os.path.isfile(os.path.join(work, OUTPUT_VIDEO))
    assert os.path.isfile(os.path.join(work, "transcript_vi.srt"))
    assert os.path.isfile(os.path.join(work, "transcript_vi.json"))
    assert not os.path.exists(os.path.join(work, "original_audio.wav"))
    assert not os.path.exists(os.path.join(work, "segments"))
    assert not os.path.exists(os.path.join(work, "segments_speed1.2"))


def test_clean_project_unfinished_untouched(tmp_path):
    work = _make_project(tmp_path, "p1", done=False)
    assert clean_project(work) == 0
    assert os.path.isdir(os.path.join(work, DATA_SUBDIR))


def test_measure_and_clean_all(tmp_path):
    _make_project(tmp_path, "xong", done=True)
    _make_project(tmp_path, "dang_do", done=False)
    report = measure(str(tmp_path))
    assert report.project_count == 2
    assert report.cleanable_bytes == 2000
    cleaned, freed = clean_all(str(tmp_path))
    assert (cleaned, freed) == (1, 2000)
    # Đo lại: không còn gì dọn được nữa.
    assert measure(str(tmp_path)).cleanable_bytes == 0


def test_measure_missing_dir(tmp_path):
    report = measure(str(tmp_path / "chua_co"))
    assert report.project_count == 0
    assert report.total_bytes == 0
