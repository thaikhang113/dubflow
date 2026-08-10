"""Trần tài nguyên dùng chung phải là trần THẬT, không phải gợi ý.

Cái đáng khóa ở đây không phải con số cụ thể (nó theo số lõi của máy chạy
test) mà là hai tính chất: số ffmpeg sống cùng lúc không bao giờ vượt trần dù
bao nhiêu luồng cùng ép, và cpu_share không bao giờ trả 0 (0 thread ONNX =
không chạy được gì).
"""
import threading

from autodub import resources


def test_cpu_share_never_zero():
    for n in (1, 2, 3, 4, 8, 16, 99, 1000):
        assert resources.cpu_share(n) >= 1


def test_cpu_share_shrinks_as_workers_grow():
    """Nhiều worker hơn thì mỗi worker không được nhiều thread hơn."""
    shares = [resources.cpu_share(n) for n in range(1, 9)]
    assert shares == sorted(shares, reverse=True)


def test_cpu_share_handles_bad_input():
    # n=0 và reserve âm là lỗi gọi, nhưng không được sập giữa pipeline.
    assert resources.cpu_share(0) >= 1
    assert resources.cpu_share(4, reserve=-5) >= 1


def test_cpu_share_reserve_leaves_cores_for_gui():
    """reserve lớn hơn số lõi vẫn trả 1, không trả số âm."""
    assert resources.cpu_share(1, reserve=9999) == 1


def test_ffmpeg_slots_caps_concurrency_under_pressure():
    """20 luồng cùng ép — số luồng vào được cùng lúc không vượt trần."""
    limit = resources.FFMPEG_SLOTS._initial_value
    live = 0
    peak = 0
    guard = threading.Lock()
    start = threading.Event()

    def worker():
        nonlocal live, peak
        start.wait(5)
        with resources.FFMPEG_SLOTS:
            with guard:
                live += 1
                peak = max(peak, live)
            # Giữ slot một nhịp để các luồng khác thật sự phải chờ.
            threading.Event().wait(0.01)
            with guard:
                live -= 1

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(10)

    assert peak <= limit
    assert peak > 1          # có song song thật, không phải tuần tự hóa
    assert live == 0         # mọi slot đã được nhả


def test_ffmpeg_slots_is_bounded():
    """BoundedSemaphore: release lệch nhịp phải nổ ngay, không âm thầm nới trần."""
    try:
        resources.FFMPEG_SLOTS.release()
    except ValueError:
        return
    # Nếu không nổ thì đã nới trần — trả lại rồi báo lỗi.
    resources.FFMPEG_SLOTS.acquire()
    raise AssertionError("FFMPEG_SLOTS phải là BoundedSemaphore")


def test_gpu_lock_is_not_reentrant_by_design():
    """GPU_LOCK là Lock thường — hai chỗ giữ nó không được lồng vào nhau."""
    assert resources.GPU_LOCK.acquire(blocking=False)
    try:
        assert resources.GPU_LOCK.acquire(blocking=False) is False
    finally:
        resources.GPU_LOCK.release()
