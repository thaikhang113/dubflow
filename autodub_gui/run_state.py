"""Sổ đăng ký việc đang chạy và nhật ký hoạt động của ứng dụng.

Đây là nguồn sự thật duy nhất cho thẻ "Dự án đang xử lý" ở Trang chủ và cho
chuông thông báo trên thanh tiêu đề. Mọi trang đều đọc từ đây thay vì tự giữ
trạng thái riêng, nhờ vậy Trang chủ vẫn thấy tiến độ của việc chạy từ trang
Tạo dự án.

Phần tính phần trăm và quản lý nhật ký là Python thuần nên kiểm thử được
bằng pytest mà không cần dựng cửa sổ.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

# Trọng số từng bước, tổng đúng 100. Bước nào lâu thì chiếm phần lớn hơn để
# thanh tiến trình không đứng im rồi nhảy vọt.
STEP_WEIGHTS: dict[str, int] = {
    "acquire": 6,
    "extract": 4,
    "separate": 14,
    "asr": 18,
    "translate": 14,
    "tts": 30,
    "merge_audio": 6,
    "merge_video": 6,
    "content": 2,
}

# Nhãn tiếng Việt cho từng bước, viết theo lời thường (không dùng thuật ngữ).
STEP_LABELS: dict[str, str] = {
    "acquire": "Đang tải video…",
    "extract": "Đang tách âm thanh…",
    "separate": "Đang tách nhạc nền…",
    "asr": "Đang nghe lời thoại gốc…",
    "translate": "Đang dịch sang tiếng Việt…",
    "tts": "Đang tạo giọng đọc…",
    "merge_audio": "Đang ghép âm thanh…",
    "merge_video": "Đang xuất video…",
    "content": "Đang tạo tiêu đề và mô tả…",
    "done": "Đã xong",
}

# Thứ tự chạy, dùng để cộng dồn trọng số các bước đã qua.
STEP_ORDER: tuple[str, ...] = tuple(STEP_WEIGHTS)

MAX_ACTIVITIES = 200          # giữ trong bộ nhớ
DEFAULT_FEED_LIMIT = 20       # số dòng hiện trong cửa sổ chuông
_MIN_SAMPLES_FOR_ETA = 3      # dưới ngưỡng này thì ước lượng còn quá nhiễu

LEVEL_INFO = "info"
LEVEL_SUCCESS = "success"
LEVEL_WARNING = "warning"
LEVEL_ERROR = "error"


def step_percent(done_steps, current_step: str = "",
                 current: int = 0, total: int = 0) -> int:
    """Phần trăm hoàn thành của cả quá trình.

    Bằng tổng trọng số các bước đã xong, cộng thêm phần đã chạy được của
    bước hiện tại. Kết quả luôn nằm trong khoảng 0 đến 100.
    """
    percent = sum(STEP_WEIGHTS.get(s, 0) for s in done_steps)
    weight = STEP_WEIGHTS.get(current_step, 0)
    if weight and total > 0:
        ratio = max(0.0, min(1.0, current / total))
        percent += weight * ratio
    return max(0, min(100, int(round(percent))))


def estimate_eta(elapsed: float, current: int, total: int) -> float:
    """Thời gian còn lại của bước hiện tại, tính theo tốc độ đã đo được.

    Trả về 0 khi chưa đủ mẫu để ước lượng cho ra con số đáng tin.
    """
    if current < _MIN_SAMPLES_FOR_ETA or total <= current or elapsed <= 0:
        return 0.0
    return elapsed / current * (total - current)


@dataclass
class ActiveJob:
    """Một việc đang chạy: lồng tiếng, xử lý hàng loạt, xuất lại hoặc tải về."""

    kind: str                      # "dub" | "batch" | "rebuild" | "download"
    title: str
    work_dir: str = ""
    step: str = ""
    step_label: str = ""
    percent: int = 0
    eta_s: float = 0.0
    thumbnail: object | None = None    # QPixmap, để nguyên kiểu tự do
    started_at: float = 0.0
    done_steps: set[str] = field(default_factory=set)
    step_started_at: float = 0.0


@dataclass
class Activity:
    """Một dòng trong nhật ký hoạt động."""

    ts: float
    level: str
    text: str
    work_dir: str = ""
    read: bool = False


class RunRegistry(QObject):
    """Sổ đăng ký dùng chung. Chỉ tạo một thể hiện duy nhất cho cả ứng dụng."""

    job_changed = Signal()            # việc đang chạy thay đổi, hoặc đã kết thúc
    activity_added = Signal(object)   # một Activity mới
    unread_changed = Signal(int)      # số thông báo chưa đọc

    def __init__(self) -> None:
        super().__init__()
        self._job: ActiveJob | None = None
        self._activities: list[Activity] = []
        self._cancel_callback = None

    # -- Việc đang chạy ------------------------------------------------
    def start_job(self, job: ActiveJob, on_cancel=None) -> None:
        """Ghi nhận một việc vừa bắt đầu, kèm hàm dừng để Trang chủ gọi lại."""
        if self._job is not None:
            # Không được đè việc đang chạy — mất luôn nút Dừng của nó.
            # Các trang phải kiểm tra is_busy() trước; đây là lưới an toàn.
            self.add_activity(
                LEVEL_WARNING,
                f"Bắt đầu «{job.title}» khi «{self._job.title}» chưa xong")
        job.started_at = job.started_at or time.time()
        job.step_started_at = time.monotonic()
        job.done_steps = set()
        self._job = job
        self._cancel_callback = on_cancel
        self.job_changed.emit()

    def update_job(self, event) -> None:
        """Cập nhật tiến độ từ một ProgressEvent của lõi xử lý."""
        job = self._job
        if job is None:
            return
        step = getattr(event, "step", "") or ""
        status = getattr(event, "status", "") or ""
        if step == "done":
            job.percent = 100
            job.step_label = STEP_LABELS["done"]
            self.job_changed.emit()
            return
        if step != job.step:
            job.step = step
            job.step_started_at = time.monotonic()
        if status in ("done", "skip"):
            job.done_steps.add(step)
            job.eta_s = 0.0
        current = int(getattr(event, "current", 0) or 0)
        total = int(getattr(event, "total", 0) or 0)
        job.step_label = STEP_LABELS.get(step, step)
        job.percent = step_percent(job.done_steps, step, current, total)
        if status == "progress":
            elapsed = time.monotonic() - job.step_started_at
            job.eta_s = estimate_eta(elapsed, current, total)
        self.job_changed.emit()

    def finish_job(self, ok: bool, detail: str = "") -> None:
        """Kết thúc việc đang chạy và ghi một dòng vào nhật ký hoạt động."""
        job = self._job
        if job is not None:
            level = LEVEL_SUCCESS if ok else LEVEL_ERROR
            prefix = "Đã xong" if ok else "Không hoàn thành"
            text = f"{prefix}: {job.title}"
            if detail:
                text = f"{text} — {detail}"
            self.add_activity(level, text, job.work_dir)
        self._job = None
        self._cancel_callback = None
        self.job_changed.emit()

    def current(self) -> ActiveJob | None:
        """Việc đang chạy, hoặc None nếu máy đang rảnh."""
        return self._job

    def is_busy(self) -> bool:
        return self._job is not None

    def request_cancel(self) -> bool:
        """Yêu cầu dừng việc đang chạy. Trả về True nếu có chỗ nhận yêu cầu."""
        if self._cancel_callback is None:
            return False
        self._cancel_callback()
        return True

    # -- Nhật ký hoạt động ---------------------------------------------
    def add_activity(self, level: str, text: str, work_dir: str = "") -> Activity:
        """Thêm một dòng vào nhật ký và báo cho chuông thông báo."""
        activity = Activity(ts=time.time(), level=level, text=text,
                            work_dir=work_dir)
        self._activities.append(activity)
        if len(self._activities) > MAX_ACTIVITIES:
            del self._activities[:-MAX_ACTIVITIES]
        self.activity_added.emit(activity)
        self.unread_changed.emit(self.unread())
        return activity

    def activities(self, limit: int = DEFAULT_FEED_LIMIT) -> list[Activity]:
        """Các dòng gần đây nhất, mới nhất đứng đầu."""
        if limit <= 0:
            return []
        return list(reversed(self._activities[-limit:]))

    def mark_all_read(self) -> None:
        """Đánh dấu mọi thông báo là đã đọc và tắt chấm đỏ."""
        for activity in self._activities:
            activity.read = True
        self.unread_changed.emit(0)

    def unread(self) -> int:
        """Số thông báo người dùng chưa xem."""
        return sum(1 for a in self._activities if not a.read)

    def clear(self) -> None:
        """Xóa sạch nhật ký, dùng khi kiểm thử."""
        self._activities.clear()
        self._job = None
        self._cancel_callback = None
        self.unread_changed.emit(0)


REGISTRY = RunRegistry()
