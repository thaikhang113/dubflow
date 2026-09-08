"""Process cancellation shared by GUI workers and long-running subprocesses."""
from __future__ import annotations

import subprocess
import threading
import time
import contextlib
from collections.abc import Iterator
from typing import Any

from autodub.progress import PipelineCancelled

_LOCK = threading.Lock()
_ACTIVE: set[subprocess.Popen] = set()
_REQUESTED = threading.Event()


def clear_cancel_request() -> None:
    _REQUESTED.clear()


def cancel_processes() -> None:
    _REQUESTED.set()
    with _LOCK:
        processes = list(_ACTIVE)
    for process in processes:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
    deadline = time.monotonic() + 1.0
    for process in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass


def run_registered(
    args: list[str], *, timeout: float | None = None, **kwargs: Any
) -> subprocess.CompletedProcess:
    """Run child process while allowing global GUI cancellation."""
    if _REQUESTED.is_set():
        raise PipelineCancelled("Pipeline cancelled by user")

    # Preserve the existing subprocess.run seam used by unit tests and
    # integrations that inject a runner.
    runner = subprocess.run
    if getattr(runner, "__module__", "subprocess") != "subprocess":
        return runner(args, timeout=timeout, **kwargs)

    # Nhận đúng bộ tham số của subprocess.run để các chỗ gọi đổi qua đây mà
    # không phải sửa lời gọi: check được bóc ra và tự xử lý vì Popen không
    # nhận từ khóa đó.
    check = bool(kwargs.pop("check", False))
    if kwargs.pop("capture_output", False):
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    process = subprocess.Popen(args, **kwargs)
    with _LOCK:
        _ACTIVE.add(process)
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        if _REQUESTED.is_set():
            raise PipelineCancelled("Pipeline cancelled by user")
        result = subprocess.CompletedProcess(args, process.returncode,
                                             stdout, stderr)
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, args,
                                                result.stdout, result.stderr)
        return result
    finally:
        with _LOCK:
            _ACTIVE.discard(process)


@contextlib.contextmanager
def registered_process(*args: Any, **kwargs: Any) -> Iterator[subprocess.Popen]:
    """``Popen`` đã ghi danh: ``cancel_processes()`` giết được tiến trình con.

    Worker ASR/TTS giữ tiến trình con sống suốt một lần chạy nên không đi qua
    ``run_registered`` được; nếu không ghi danh thì bấm Dừng chỉ chờ tới khi
    worker tự trả lời, tức là vẫn phải nghe hết cả video.
    """
    if _REQUESTED.is_set():
        raise PipelineCancelled("Pipeline cancelled by user")
    process = subprocess.Popen(*args, **kwargs)
    register(process)
    try:
        yield process
    finally:
        unregister(process)


def register(process: subprocess.Popen) -> subprocess.Popen:
    """Cho một ``Popen`` đang sống vào danh sách để ``cancel_processes()`` giết.

    Worker ASR/TTS giữ tiến trình con suốt một lần chạy nên không đi qua
    ``run_registered``; ghi danh tay là cách duy nhất để nút Dừng không phải
    chờ worker tự xong việc.
    """
    with _LOCK:
        _ACTIVE.add(process)
    return process


def unregister(process: subprocess.Popen) -> None:
    with _LOCK:
        _ACTIVE.discard(process)
