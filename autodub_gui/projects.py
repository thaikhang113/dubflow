"""Quét thư mục kết quả và mô tả từng dự án.

Đây là Python thuần, không dùng Qt, nên kiểm thử được bằng pytest và chạy
được trong luồng nền mà không đụng tới giao diện.

Lưu ý về một lỗi đã sửa: mã cũ đọc tệp `dub_report.json` ở gốc thư mục dự án,
nhưng tên thật do lõi xử lý ghi ra là `data/report.json`. Vì vậy tên, thời
lượng và ngày tháng trước đây không bao giờ hiện đúng. Hàm quét ở đây đọc
đúng tên mới trước, rồi mới thử tên cũ để những thư mục làm từ bản trước
vẫn dùng được.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from autodub.workdir import data_path

# Trạng thái một dự án có thể ở
STATUS_COMPLETED = "completed"
STATUS_PROCESSING = "processing"
STATUS_PENDING = "pending"
STATUS_LOCKED = "locked"          # đã lồng tiếng xong, chờ bấm Xuất video
STATUS_FAILED = "failed"
STATUS_QUEUED = "queued"

STATUS_LABELS: dict[str, str] = {
    STATUS_COMPLETED: "Hoàn thành",
    STATUS_PROCESSING: "Đang xử lý",
    STATUS_PENDING: "Chờ dịch",
    STATUS_LOCKED: "Chờ xuất video",
    STATUS_FAILED: "Lỗi",
    STATUS_QUEUED: "Đang chờ",
}

OUTPUT_VIDEO = "dubbed_video.mp4"
SUBTITLE_FILE = "transcript_vi.srt"
THUMB_FILE = "thumb.png"
INDEX_FILE = ".voxdub_index.json"
PENDING_MARKER = "TRANSLATE_PENDING.txt"

# Tiền tố của các tệp video do chính ứng dụng sinh ra, không phải video gốc
_DERIVED_PREFIXES = ("dubbed_", "retimed_", "slowed_")
_VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".avi", ".webm")
_WORK_DIR_SUFFIX = "*_vi"
_INDEX_VERSION = 3         # bump khi đổi cách suy trạng thái (thêm "locked")
_THUMB_WIDTH = 480
_THUMB_SEEK_S = 1
_FFMPEG_TIMEOUT_S = 20


@dataclass
class Project:
    """Mọi thứ giao diện cần biết về một dự án, đọc sẵn một lần."""

    work_dir: str
    key: str
    title: str
    status: str
    status_label: str
    duration_s: float = 0.0
    processing_s: float = 0.0
    segments: int = 0
    created_at: float = 0.0
    date_label: str = ""
    size_bytes: int = 0
    video_path: str = ""
    output_path: str = ""
    thumb_path: str = ""
    source_lang: str = ""
    voice: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def has_output(self) -> bool:
        return bool(self.output_path) and os.path.isfile(self.output_path)


def _read_json(path: str) -> dict:
    """Đọc một tệp JSON, trả về từ điển rỗng nếu tệp hỏng hoặc không có."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def read_report(work_dir: str) -> dict:
    """Đọc bản tóm tắt của lần chạy, ưu tiên vị trí mới rồi mới tới vị trí cũ."""
    report = _read_json(data_path(work_dir, "report.json"))
    if report:
        return report
    # Thư mục làm từ bản cũ vẫn để tệp này ở gốc với tên khác.
    return _read_json(os.path.join(work_dir, "dub_report.json"))


def _source_video(work_dir: str) -> str:
    """Đường dẫn video gốc, lấy từ ghi chú của lõi xử lý hoặc dò trong thư mục."""
    info = _read_json(data_path(work_dir, "source_video.json"))
    path = (info.get("file_path") or "").strip()
    if path:
        return path
    for name in sorted(os.listdir(work_dir)):
        lower = name.lower()
        if (lower.endswith(_VIDEO_EXTS)
                and not name.startswith(_DERIVED_PREFIXES)):
            return os.path.join(work_dir, name)
    return ""


def _title_of(work_dir: str, report: dict) -> str:
    """Tên hiển thị của dự án, thử lần lượt các nguồn đáng tin nhất trước."""
    source = _source_video(work_dir)
    if source:
        return Path(source).stem
    session = (report.get("session_id") or "").strip()
    return session or os.path.basename(work_dir.rstrip("\\/"))


def _duration_of(work_dir: str, report: dict) -> float:
    """Thời lượng video gốc tính bằng giây."""
    value = report.get("total_original_duration")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    quality = _read_json(data_path(work_dir, "quality_report.json"))
    summary = quality.get("summary") or {}
    value = summary.get("video_duration_seconds")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return 0.0


def _segments_of(work_dir: str, report: dict) -> int:
    """Số câu thoại của dự án."""
    value = report.get("total_segments")
    if isinstance(value, int) and value > 0:
        return value
    try:
        with open(data_path(work_dir, "transcript_vi.json"), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            return len(data.get("segments") or [])
    except (OSError, ValueError):
        pass
    return 0


def _has_error_marker(work_dir: str) -> bool:
    """Thư mục có dấu vết của một lần chạy hỏng không."""
    try:
        for name in os.listdir(work_dir):
            lower = name.lower()
            if lower.endswith(".error") or (lower.startswith("error")
                                            and lower.endswith(".txt")):
                return True
    except OSError:
        return False
    return False


def _status_of(work_dir: str, running_dir: str) -> str:
    """Suy ra trạng thái hiện tại của dự án từ những tệp có trong thư mục."""
    if os.path.isfile(os.path.join(work_dir, OUTPUT_VIDEO)):
        return STATUS_COMPLETED
    if os.path.isfile(os.path.join(work_dir, PENDING_MARKER)):
        return STATUS_PENDING
    if running_dir and os.path.normpath(running_dir) == os.path.normpath(work_dir):
        return STATUS_PROCESSING
    if _has_error_marker(work_dir):
        return STATUS_FAILED
    # Đã lồng tiếng xong nhưng chưa bấm Xuất video — dữ liệu còn khóa.
    if os.path.isfile(data_path(work_dir, "voxdub_lock.json")):
        return STATUS_LOCKED
    segments_dir = data_path(work_dir, "segments")
    if os.path.isdir(segments_dir) and os.listdir(segments_dir):
        return STATUS_PROCESSING
    return STATUS_QUEUED


def _dir_size(path: str) -> int:
    """Tổng dung lượng của cả cây thư mục, tính bằng byte."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def _format_date(ts: float) -> str:
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
    except (OSError, OverflowError, ValueError):
        return ""


def load_project(work_dir: str, running_dir: str = "") -> Project:
    """Đọc mọi thông tin của một thư mục dự án."""
    report = read_report(work_dir)
    status = _status_of(work_dir, running_dir)
    try:
        created = os.path.getmtime(work_dir)
    except OSError:
        created = 0.0
    output = os.path.join(work_dir, OUTPUT_VIDEO)
    processing = report.get("processing_time_seconds")
    return Project(
        work_dir=work_dir,
        key=work_dir,
        title=_title_of(work_dir, report),
        status=status,
        status_label=STATUS_LABELS.get(status, status),
        duration_s=_duration_of(work_dir, report),
        processing_s=float(processing) if isinstance(processing, (int, float)) else 0.0,
        segments=_segments_of(work_dir, report),
        created_at=created,
        date_label=_format_date(created),
        size_bytes=_dir_size(work_dir),
        video_path=_source_video(work_dir),
        output_path=output if os.path.isfile(output) else "",
        thumb_path=data_path(work_dir, THUMB_FILE),
        source_lang=(report.get("source_language") or "").strip(),
        voice=(report.get("voice") or "").strip(),
    )


def _index_path(output_dir: str) -> str:
    return os.path.join(output_dir, INDEX_FILE)


def _load_index(output_dir: str) -> dict:
    data = _read_json(_index_path(output_dir))
    if data.get("version") != _INDEX_VERSION:
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def _save_index(output_dir: str, entries: dict) -> None:
    """Ghi bộ nhớ đệm; hỏng thì bỏ qua vì đây chỉ là thứ giúp chạy nhanh hơn."""
    try:
        with open(_index_path(output_dir), "w", encoding="utf-8") as f:
            json.dump({"version": _INDEX_VERSION, "entries": entries}, f,
                      ensure_ascii=False)
    except OSError:
        pass


def _to_dict(project: Project) -> dict:
    return {k: v for k, v in vars(project).items() if k != "extra"}


def scan(output_dir: str, running_dir: str = "",
         use_cache: bool = True) -> list[Project]:
    """Liệt kê mọi dự án trong thư mục kết quả, mới nhất đứng đầu.

    Kết quả được ghi đệm theo thời điểm sửa đổi của từng thư mục, nên lần
    quét thứ hai gần như không tốn thời gian dù có hàng trăm dự án.
    """
    base = Path(output_dir)
    if not base.is_dir():
        return []

    cached = _load_index(output_dir) if use_cache else {}
    fresh: dict[str, dict] = {}
    projects: list[Project] = []

    for path in base.rglob(_WORK_DIR_SUFFIX):
        if not path.is_dir():
            continue
        work_dir = str(path)
        try:
            mtime = os.path.getmtime(work_dir)
        except OSError:
            continue
        entry = cached.get(work_dir)
        # Thư mục đang chạy luôn phải đọc lại vì trạng thái đổi liên tục.
        is_running = bool(running_dir) and os.path.normpath(
            running_dir) == os.path.normpath(work_dir)
        if entry and entry.get("mtime") == mtime and not is_running:
            project = Project(**entry["project"])
        else:
            project = load_project(work_dir, running_dir)
        projects.append(project)
        fresh[work_dir] = {"mtime": mtime, "project": _to_dict(project)}

    projects.sort(key=lambda p: p.created_at, reverse=True)
    if use_cache:
        _save_index(output_dir, fresh)
    return projects


def summarize(projects: list[Project]) -> dict[str, str]:
    """Bốn con số cho ô thống kê nhanh ở Trang chủ."""
    from autodub_gui.formatting import format_hours, format_size

    completed = sum(1 for p in projects if p.status == STATUS_COMPLETED)
    failed = sum(1 for p in projects if p.status == STATUS_FAILED)
    total_time = sum(p.processing_s for p in projects)
    total_size = sum(p.size_bytes for p in projects)
    finished = completed + failed
    rate = f"{round(completed / finished * 100)}%" if finished else "—"
    return {
        "completed": str(completed),
        "time": format_hours(total_time),
        "size": format_size(total_size) if total_size else "0 KB",
        "rate": rate,
    }


def ensure_thumbnail(project: Project) -> str:
    """Tạo ảnh đại diện cho dự án nếu chưa có, trả về đường dẫn ảnh.

    Ảnh được lưu bền trong thư mục dự án chứ không nằm ở thư mục tạm, nhờ vậy
    lần mở ứng dụng sau không phải chạy lại ffmpeg.
    """
    import subprocess

    target = project.thumb_path
    if target and os.path.isfile(target) and os.path.getsize(target) > 0:
        return target
    source = project.output_path or project.video_path
    if not source or not os.path.isfile(source):
        return ""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    command = [
        "ffmpeg", "-v", "error", "-ss", str(_THUMB_SEEK_S), "-i", source,
        "-frames:v", "1", "-q:v", "3", "-y",
        "-vf", f"scale={_THUMB_WIDTH}:-1", target,
    ]
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(command, capture_output=True,
                       timeout=_FFMPEG_TIMEOUT_S, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return ""
    return target if os.path.isfile(target) else ""


def filter_projects(projects: list[Project], query: str = "",
                    status: str = "", sort_key: str = "newest") -> list[Project]:
    """Lọc theo chữ tìm kiếm và trạng thái, rồi sắp xếp theo yêu cầu."""
    result = list(projects)
    text = (query or "").strip().lower()
    if text:
        result = [p for p in result if text in p.title.lower()]
    if status:
        result = [p for p in result if p.status == status]
    sorters = {
        "newest": (lambda p: p.created_at, True),
        "oldest": (lambda p: p.created_at, False),
        "name": (lambda p: p.title.lower(), False),
        "duration": (lambda p: p.duration_s, True),
    }
    key, reverse = sorters.get(sort_key, sorters["newest"])
    result.sort(key=key, reverse=reverse)
    return result
