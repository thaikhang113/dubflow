"""Đo và dọn dung lượng đĩa của các thư mục dự án.

Mỗi dự án đã xuất xong còn giữ nguyên thư mục ``data/`` chứa tệp trung gian
(WAV tách nhạc, từng đoạn giọng đọc, video làm chậm...) nặng gấp nhiều lần
video kết quả. Mô-đun này đo phần đó và dọn được một cách AN TOÀN: chỉ đụng
tới ``data/`` của dự án đã có video kết quả, không bao giờ chạm vào
``dubbed_video.mp4``, ``transcript_vi.srt`` hay thư mục ``youtube/``.

Không import Qt — GUI bọc lại trong worker riêng, pytest gọi thẳng.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from autodub.utils import setup_logging
from autodub.workdir import DATA_SUBDIR, is_legacy_layout

logger = setup_logging("autodub.diskspace")

#: Tên video kết quả — dự án có tệp này mới được coi là "đã xong".
OUTPUT_VIDEO = "dubbed_video.mp4"

#: Các tệp/thư mục trung gian ở bản cũ (layout phẳng) được phép dọn. Bản mới
#: gom hết vào ``data/`` nên chỉ cần xóa nguyên thư mục đó.
_LEGACY_INTERMEDIATES = (
    "original_audio.wav", "original_audio_hq.wav",
    "vocals.wav", "no_vocals.wav",
    "audio_vi_full.wav", "slowed_video.mp4", "slowed_background.wav",
    "segments",
)
_LEGACY_DIR_PREFIXES = ("segments_speed", "segments_slow", "segments_fit",
                        "segments_post", "segments_timed")


@dataclass
class ProjectUsage:
    """Dung lượng một thư mục dự án, tách phần giữ và phần dọn được."""

    work_dir: str
    total_bytes: int = 0
    cleanable_bytes: int = 0     # phần trung gian, dọn được khi đã có video
    has_output: bool = False     # đã có dubbed_video.mp4 chưa


@dataclass
class UsageReport:
    """Bức tranh dung lượng của cả thư mục kết quả."""

    output_dir: str
    total_bytes: int = 0
    cleanable_bytes: int = 0
    project_count: int = 0
    projects: list[ProjectUsage] = field(default_factory=list)


def dir_size(path: str) -> int:
    """Tổng dung lượng cả cây thư mục (byte); 0 nếu không tồn tại."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def _cleanable_paths(work_dir: str) -> list[str]:
    """Các đường dẫn trung gian dọn được của MỘT dự án.

    Bản mới: nguyên thư mục ``data/``. Bản cũ (layout phẳng): từng tệp và
    thư mục trung gian có tên biết trước — tuyệt đối không xóa theo kiểu
    "mọi thứ trừ video" vì bản cũ để lẫn tệp người dùng cần ngay ở gốc.
    """
    if not is_legacy_layout(work_dir):
        data = os.path.join(work_dir, DATA_SUBDIR)
        return [data] if os.path.isdir(data) else []
    paths: list[str] = []
    for name in _LEGACY_INTERMEDIATES:
        path = os.path.join(work_dir, name)
        if os.path.exists(path):
            paths.append(path)
    try:
        entries = os.listdir(work_dir)
    except OSError:
        entries = []
    paths.extend(os.path.join(work_dir, d) for d in entries
                 if d.startswith(_LEGACY_DIR_PREFIXES)
                 and os.path.isdir(os.path.join(work_dir, d)))
    return paths


def measure_project(work_dir: str) -> ProjectUsage:
    """Đo một thư mục dự án: tổng, phần dọn được, đã có video chưa."""
    usage = ProjectUsage(work_dir=work_dir)
    usage.total_bytes = dir_size(work_dir)
    usage.has_output = os.path.isfile(os.path.join(work_dir, OUTPUT_VIDEO))
    # Chỉ tính là "dọn được" khi video kết quả đã có mặt — dự án đang dở
    # cần giữ tệp trung gian để chạy tiếp từ chỗ dừng.
    if usage.has_output:
        for path in _cleanable_paths(work_dir):
            usage.cleanable_bytes += (dir_size(path) if os.path.isdir(path)
                                      else _file_size(path))
    return usage


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _iter_work_dirs(output_dir: str) -> list[str]:
    """Mọi thư mục dự án bên trong thư mục kết quả.

    Nhận diện bằng dấu vết của một lần chạy (video kết quả hoặc ``data/``
    hoặc dấu bản cũ) thay vì tin vào tên thư mục.
    """
    found: list[str] = []
    for root, dirs, files in os.walk(output_dir):
        if (OUTPUT_VIDEO in files or DATA_SUBDIR in dirs
                or is_legacy_layout(root)):
            found.append(root)
            dirs.clear()        # không đào sâu vào trong một dự án
    return found


def measure(output_dir: str) -> UsageReport:
    """Đo toàn bộ thư mục kết quả. Không bao giờ ném lỗi ra ngoài."""
    report = UsageReport(output_dir=output_dir)
    if not output_dir or not os.path.isdir(output_dir):
        return report
    for work_dir in _iter_work_dirs(output_dir):
        try:
            usage = measure_project(work_dir)
        except OSError:
            continue
        report.projects.append(usage)
        report.total_bytes += usage.total_bytes
        report.cleanable_bytes += usage.cleanable_bytes
    report.project_count = len(report.projects)
    return report


def clean_project(work_dir: str) -> int:
    """Dọn tệp trung gian của MỘT dự án đã xong. Trả về số byte giải phóng.

    Dự án chưa có video kết quả thì không đụng tới (trả về 0) — người dùng
    còn cần tệp trung gian để chạy tiếp.
    """
    if not os.path.isfile(os.path.join(work_dir, OUTPUT_VIDEO)):
        return 0
    freed = 0
    for path in _cleanable_paths(work_dir):
        size = dir_size(path) if os.path.isdir(path) else _file_size(path)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            freed += size
        except OSError as e:
            logger.warning(f"Không dọn được {path}: {e}")
    if freed:
        logger.info(f"Đã dọn tệp trung gian: {work_dir} "
                    f"({freed / (1024 ** 2):.0f} MB)")
    return freed


def clean_all(output_dir: str) -> tuple[int, int]:
    """Dọn tệp trung gian của mọi dự án đã xong trong thư mục kết quả.

    Trả về (số dự án được dọn, tổng số byte giải phóng).
    """
    cleaned = 0
    freed = 0
    report = measure(output_dir)
    for usage in report.projects:
        if not usage.cleanable_bytes:
            continue
        got = clean_project(usage.work_dir)
        if got:
            cleaned += 1
            freed += got
    return cleaned, freed
