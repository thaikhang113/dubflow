"""Kiểm thử việc quét thư mục kết quả và đọc thông tin dự án.

Có kiểm tra riêng cho lỗi cũ: mã trước đây đọc `dub_report.json` ở gốc thư
mục, trong khi lõi xử lý ghi ra `data/report.json`.
"""
from __future__ import annotations

import json
import os

import pytest

from autodub_gui import projects
from autodub_gui.projects import (
    STATUS_COMPLETED, STATUS_FAILED, STATUS_PENDING, STATUS_PROCESSING,
    STATUS_QUEUED, Project, filter_projects, load_project, read_report, scan,
    summarize,
)

_REPORT = {
    "session_id": "20260804112214",
    "source_language": "zh",
    "voice": "female",
    "total_segments": 57,
    "total_original_duration": 512.0,
    "processing_time_seconds": 240.0,
}


def _make_work_dir(base, name="20260804112214_vi", *, legacy=False,
                   report=None, source_name="video gốc.mp4"):
    """Dựng một thư mục dự án giả đủ tệp cần thiết."""
    work = base / name
    data = work if legacy else work / "data"
    data.mkdir(parents=True, exist_ok=True)
    payload = _REPORT if report is None else report
    if payload:
        report_name = "dub_report.json" if legacy else "report.json"
        target = work / report_name if legacy else data / report_name
        target.write_text(json.dumps(payload), encoding="utf-8")
    if source_name:
        (data / "source_video.json").write_text(
            json.dumps({"file_path": str(work / source_name)}), encoding="utf-8")
    return work


def _finish(work):
    (work / "dubbed_video.mp4").write_bytes(b"x" * 100)


# -- Đọc bản tóm tắt ---------------------------------------------------

def test_report_read_from_data_folder(tmp_path) -> None:
    """Tên tệp đúng là data/report.json — đây là lỗi cũ đã được sửa."""
    work = _make_work_dir(tmp_path)
    assert read_report(str(work))["total_segments"] == 57


def test_report_falls_back_to_legacy_name(tmp_path) -> None:
    """Thư mục làm từ bản cũ vẫn đọc được."""
    work = _make_work_dir(tmp_path, legacy=True)
    assert read_report(str(work))["session_id"] == "20260804112214"


def test_report_missing_is_not_an_error(tmp_path) -> None:
    work = _make_work_dir(tmp_path, report={})
    assert read_report(str(work)) == {}


def test_report_corrupted_json_is_ignored(tmp_path) -> None:
    """Tệp hỏng không được làm sập việc quét."""
    work = _make_work_dir(tmp_path)
    (work / "data" / "report.json").write_text("{ hỏng", encoding="utf-8")
    assert read_report(str(work)) == {}


# -- Thông tin từng dự án ----------------------------------------------

def test_title_from_source_video_name(tmp_path) -> None:
    work = _make_work_dir(tmp_path)
    assert load_project(str(work)).title == "video gốc"


def test_title_falls_back_to_session_id(tmp_path) -> None:
    """Không biết video gốc thì lấy mã phiên làm tên."""
    work = _make_work_dir(tmp_path, source_name="")
    assert load_project(str(work)).title == "20260804112214"


def test_title_falls_back_to_folder_name(tmp_path) -> None:
    work = _make_work_dir(tmp_path, report={}, source_name="")
    assert load_project(str(work)).title == "20260804112214_vi"


def test_duration_and_segments_read_from_report(tmp_path) -> None:
    work = _make_work_dir(tmp_path)
    project = load_project(str(work))
    assert project.duration_s == 512.0
    assert project.segments == 57
    assert project.processing_s == 240.0


def test_duration_falls_back_to_quality_report(tmp_path) -> None:
    work = _make_work_dir(tmp_path, report={})
    (work / "data" / "quality_report.json").write_text(
        json.dumps({"summary": {"video_duration_seconds": 99.5}}),
        encoding="utf-8")
    assert load_project(str(work)).duration_s == 99.5


def test_segments_counted_from_transcript_when_report_empty(tmp_path) -> None:
    work = _make_work_dir(tmp_path, report={})
    (work / "data" / "transcript_vi.json").write_text(
        json.dumps([{"id": 1}, {"id": 2}, {"id": 3}]), encoding="utf-8")
    assert load_project(str(work)).segments == 3


def test_size_counts_whole_tree(tmp_path) -> None:
    work = _make_work_dir(tmp_path)
    _finish(work)
    assert load_project(str(work)).size_bytes >= 100


# -- Năm trạng thái ----------------------------------------------------

def test_status_completed_when_output_exists(tmp_path) -> None:
    work = _make_work_dir(tmp_path)
    _finish(work)
    project = load_project(str(work))
    assert project.status == STATUS_COMPLETED
    assert project.status_label == "Hoàn thành"
    assert project.has_output


def test_status_pending_when_marker_present(tmp_path) -> None:
    work = _make_work_dir(tmp_path)
    (work / "TRANSLATE_PENDING.txt").write_text("chờ dịch", encoding="utf-8")
    project = load_project(str(work))
    assert project.status == STATUS_PENDING
    assert project.status_label == "Chờ dịch"


def test_status_failed_when_error_file_present(tmp_path) -> None:
    work = _make_work_dir(tmp_path)
    (work / "error.txt").write_text("hỏng", encoding="utf-8")
    assert load_project(str(work)).status == STATUS_FAILED


def test_status_processing_when_running(tmp_path) -> None:
    """Thư mục trùng với việc đang chạy thì báo là đang xử lý."""
    work = _make_work_dir(tmp_path)
    assert load_project(str(work), str(work)).status == STATUS_PROCESSING


def test_status_processing_when_segments_started(tmp_path) -> None:
    work = _make_work_dir(tmp_path)
    seg = work / "data" / "segments"
    seg.mkdir()
    (seg / "0001.wav").write_bytes(b"x")
    assert load_project(str(work)).status == STATUS_PROCESSING


def test_status_queued_when_nothing_started(tmp_path) -> None:
    work = _make_work_dir(tmp_path)
    assert load_project(str(work)).status == STATUS_QUEUED


# -- Quét cả thư mục ---------------------------------------------------

def test_scan_finds_projects_newest_first(tmp_path) -> None:
    first = _make_work_dir(tmp_path, "20260101000000_vi")
    second = _make_work_dir(tmp_path, "20260804112214_vi")
    os.utime(first, (1_000_000, 1_000_000))
    os.utime(second, (2_000_000, 2_000_000))
    found = scan(str(tmp_path))
    assert [p.work_dir for p in found] == [str(second), str(first)]


def test_scan_ignores_non_project_folders(tmp_path) -> None:
    _make_work_dir(tmp_path)
    (tmp_path / "downloads").mkdir()
    (tmp_path / "ghi chú.txt").write_text("x", encoding="utf-8")
    assert len(scan(str(tmp_path))) == 1


def test_scan_missing_directory_returns_empty(tmp_path) -> None:
    assert scan(str(tmp_path / "không có")) == []


def test_scan_writes_and_reuses_cache(tmp_path) -> None:
    """Lần quét thứ hai đọc từ bộ nhớ đệm chứ không đọc lại toàn bộ tệp."""
    work = _make_work_dir(tmp_path)
    first = scan(str(tmp_path))
    assert (tmp_path / projects.INDEX_FILE).is_file()
    # Xóa bản tóm tắt: nếu vẫn ra đúng tên thì tức là đã dùng bộ nhớ đệm.
    (work / "data" / "report.json").unlink()
    second = scan(str(tmp_path))
    assert second[0].segments == first[0].segments == 57


def test_scan_cache_invalidated_when_folder_changes(tmp_path) -> None:
    work = _make_work_dir(tmp_path)
    scan(str(tmp_path))
    _finish(work)
    os.utime(work, (3_000_000, 3_000_000))
    assert scan(str(tmp_path))[0].status == STATUS_COMPLETED


def test_scan_legacy_layout_still_works(tmp_path) -> None:
    work = _make_work_dir(tmp_path, legacy=True)
    _finish(work)
    found = scan(str(tmp_path))
    assert len(found) == 1
    assert found[0].status == STATUS_COMPLETED


# -- Thống kê và lọc ---------------------------------------------------

def test_summarize_counts_and_rate() -> None:
    items = [
        Project("a", "a", "A", STATUS_COMPLETED, "Hoàn thành",
                processing_s=3600, size_bytes=1024 ** 3),
        Project("b", "b", "B", STATUS_COMPLETED, "Hoàn thành",
                processing_s=1800),
        Project("c", "c", "C", STATUS_FAILED, "Lỗi"),
    ]
    stats = summarize(items)
    assert stats["completed"] == "2"
    assert stats["rate"] == "67%"
    assert "giờ" in stats["time"]
    assert "GB" in stats["size"]


def test_summarize_empty_shows_placeholder() -> None:
    stats = summarize([])
    assert stats["completed"] == "0"
    assert stats["rate"] == "—"


def test_filter_by_query_and_status() -> None:
    items = [
        Project("a", "a", "Phim hài", STATUS_COMPLETED, "Hoàn thành"),
        Project("b", "b", "Phim buồn", STATUS_FAILED, "Lỗi"),
        Project("c", "c", "Nhạc", STATUS_COMPLETED, "Hoàn thành"),
    ]
    assert len(filter_projects(items, query="phim")) == 2
    assert len(filter_projects(items, status=STATUS_COMPLETED)) == 2
    assert len(filter_projects(items, query="phim",
                               status=STATUS_COMPLETED)) == 1


def test_filter_sorts_by_requested_key() -> None:
    items = [
        Project("a", "a", "B", STATUS_COMPLETED, "Hoàn thành",
                created_at=1, duration_s=10),
        Project("b", "b", "A", STATUS_COMPLETED, "Hoàn thành",
                created_at=2, duration_s=99),
    ]
    assert [p.title for p in filter_projects(items, sort_key="newest")] == ["A", "B"]
    assert [p.title for p in filter_projects(items, sort_key="oldest")] == ["B", "A"]
    assert [p.title for p in filter_projects(items, sort_key="name")] == ["A", "B"]
    assert [p.title for p in filter_projects(items, sort_key="duration")] == ["A", "B"]


def test_every_status_has_vietnamese_label() -> None:
    """Mọi trạng thái đều phải có nhãn tiếng Việt có dấu cho người dùng đọc."""
    for status, label in projects.STATUS_LABELS.items():
        assert label.strip(), status
        assert label[0].isupper()
