"""Kiểm thử sổ đăng ký việc đang chạy và nhật ký hoạt động."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from autodub_gui.run_state import (
    DEFAULT_FEED_LIMIT, LEVEL_ERROR, LEVEL_INFO, MAX_ACTIVITIES, STEP_LABELS,
    STEP_WEIGHTS, ActiveJob, RunRegistry, estimate_eta, step_percent,
)


@dataclass
class FakeEvent:
    """Bản sao tối giản của ProgressEvent để khỏi phải chạy cả lõi xử lý."""

    step: str
    status: str = "progress"
    detail: str = ""
    current: int = 0
    total: int = 0


@pytest.fixture()
def registry() -> RunRegistry:
    reg = RunRegistry()
    yield reg
    reg.clear()


# -- Bảng trọng số -----------------------------------------------------

def test_weights_sum_to_one_hundred() -> None:
    """Tổng trọng số các bước phải đúng 100 để phần trăm không lệch."""
    assert sum(STEP_WEIGHTS.values()) == 100


def test_every_step_has_vietnamese_label() -> None:
    """Mỗi bước đều phải có nhãn tiếng Việt cho người dùng đọc."""
    for step in STEP_WEIGHTS:
        assert step in STEP_LABELS
        assert STEP_LABELS[step].strip()


def test_step_labels_match_core_pipeline_steps() -> None:
    """Bảng nhãn phải phủ hết các bước mà lõi xử lý thực sự phát ra."""
    from autodub.progress import STEPS

    for step in STEPS:
        assert step in STEP_LABELS, f"thiếu nhãn cho bước {step}"


# -- Tính phần trăm ----------------------------------------------------

def test_percent_zero_at_start() -> None:
    assert step_percent(set()) == 0


def test_percent_counts_finished_steps() -> None:
    """Xong hai bước đầu thì phần trăm bằng đúng tổng trọng số của chúng."""
    done = {"acquire", "extract"}
    assert step_percent(done) == STEP_WEIGHTS["acquire"] + STEP_WEIGHTS["extract"]


def test_percent_adds_partial_progress_of_current_step() -> None:
    """Bước hiện tại chạy được nửa chừng thì cộng thêm nửa trọng số."""
    done = {"acquire"}
    got = step_percent(done, "tts", current=50, total=100)
    assert got == STEP_WEIGHTS["acquire"] + STEP_WEIGHTS["tts"] // 2


def test_percent_never_exceeds_one_hundred() -> None:
    """Dù dữ liệu bất thường, phần trăm vẫn bị kẹp trong khoảng hợp lệ."""
    assert step_percent(set(STEP_WEIGHTS), "tts", current=999, total=10) == 100
    assert step_percent(set(), "tts", current=-5, total=10) == 0


def test_percent_ignores_unknown_step() -> None:
    """Bước lạ không làm hỏng phép tính."""
    assert step_percent({"khong_ton_tai"}) == 0


# -- Ước lượng thời gian còn lại ---------------------------------------

def test_eta_needs_enough_samples() -> None:
    """Mới chạy được một hai câu thì chưa ước lượng, tránh báo số sai lệch."""
    assert estimate_eta(elapsed=10.0, current=1, total=100) == 0.0
    assert estimate_eta(elapsed=10.0, current=2, total=100) == 0.0


def test_eta_scales_with_measured_speed() -> None:
    """Chạy 10 câu mất 10 giây thì 90 câu còn lại mất khoảng 90 giây."""
    assert estimate_eta(elapsed=10.0, current=10, total=100) == pytest.approx(90.0)


def test_eta_is_zero_when_finished() -> None:
    assert estimate_eta(elapsed=10.0, current=100, total=100) == 0.0


# -- Vòng đời của việc đang chạy ---------------------------------------

def test_registry_starts_idle(registry: RunRegistry) -> None:
    assert registry.current() is None
    assert not registry.is_busy()


def test_start_and_update_job(registry: RunRegistry) -> None:
    """Cập nhật tiến độ làm đổi nhãn bước và phần trăm."""
    registry.start_job(ActiveJob(kind="dub", title="video thử"))
    registry.update_job(FakeEvent("acquire", "done"))
    registry.update_job(FakeEvent("tts", "progress", current=15, total=30))
    job = registry.current()
    assert job is not None
    assert job.step == "tts"
    assert job.step_label == STEP_LABELS["tts"]
    assert job.percent == STEP_WEIGHTS["acquire"] + STEP_WEIGHTS["tts"] // 2


def test_done_event_sets_full_percent(registry: RunRegistry) -> None:
    registry.start_job(ActiveJob(kind="dub", title="video thử"))
    registry.update_job(FakeEvent("done", "done"))
    assert registry.current().percent == 100


def test_update_without_job_is_harmless(registry: RunRegistry) -> None:
    """Sự kiện đến muộn sau khi việc đã kết thúc thì bỏ qua, không gây lỗi."""
    registry.update_job(FakeEvent("tts", "progress", current=1, total=2))
    assert registry.current() is None


def test_finish_job_clears_state_and_logs(registry: RunRegistry) -> None:
    registry.start_job(ActiveJob(kind="dub", title="video thử",
                                 work_dir="output/x"))
    registry.finish_job(True)
    assert registry.current() is None
    feed = registry.activities()
    assert len(feed) == 1
    assert feed[0].work_dir == "output/x"
    assert "video thử" in feed[0].text


def test_finish_job_failure_is_logged_as_error(registry: RunRegistry) -> None:
    registry.start_job(ActiveJob(kind="dub", title="video thử"))
    registry.finish_job(False, "thiếu FFmpeg")
    entry = registry.activities()[0]
    assert entry.level == LEVEL_ERROR
    assert "thiếu FFmpeg" in entry.text


def test_cancel_calls_registered_callback(registry: RunRegistry) -> None:
    """Nút Dừng ở Trang chủ gọi đúng hàm dừng của trang đang chạy."""
    calls: list[int] = []
    registry.start_job(ActiveJob(kind="dub", title="x"),
                       on_cancel=lambda: calls.append(1))
    assert registry.request_cancel() is True
    assert calls == [1]


def test_cancel_without_job_returns_false(registry: RunRegistry) -> None:
    assert registry.request_cancel() is False


# -- Nhật ký hoạt động -------------------------------------------------

def test_activities_newest_first(registry: RunRegistry) -> None:
    registry.add_activity(LEVEL_INFO, "một")
    registry.add_activity(LEVEL_INFO, "hai")
    assert [a.text for a in registry.activities()] == ["hai", "một"]


def test_activities_respect_limit(registry: RunRegistry) -> None:
    for i in range(30):
        registry.add_activity(LEVEL_INFO, f"dòng {i}")
    assert len(registry.activities()) == DEFAULT_FEED_LIMIT
    assert len(registry.activities(limit=5)) == 5
    assert registry.activities(limit=0) == []


def test_activity_buffer_is_capped(registry: RunRegistry) -> None:
    """Nhật ký không phình vô hạn khi chạy hàng loạt suốt nhiều giờ."""
    for i in range(MAX_ACTIVITIES + 50):
        registry.add_activity(LEVEL_INFO, f"dòng {i}")
    assert len(registry.activities(limit=10_000)) == MAX_ACTIVITIES


def test_unread_counter_and_mark_all_read(registry: RunRegistry) -> None:
    registry.add_activity(LEVEL_INFO, "một")
    registry.add_activity(LEVEL_INFO, "hai")
    assert registry.unread() == 2
    registry.mark_all_read()
    assert registry.unread() == 0
    registry.add_activity(LEVEL_INFO, "ba")
    assert registry.unread() == 1


def test_signals_fire_on_activity(registry: RunRegistry) -> None:
    """Chuông thông báo dựa vào tín hiệu này để hiện chấm đỏ."""
    seen: list[object] = []
    registry.activity_added.connect(seen.append)
    registry.add_activity(LEVEL_INFO, "một")
    assert len(seen) == 1
