"""Process cancellation shared by GUI workers and long-running subprocesses."""
from __future__ import annotations

import contextlib
import contextvars
import subprocess
import threading
import time
from collections.abc import Iterator
from typing import Any

from autodub.progress import PipelineCancelled

_LOCK = threading.Lock()
_ACTIVE: set[subprocess.Popen] = set()
_ACTIVE_BY_SCOPE: dict[subprocess.Popen, str | None] = {}
_REQUESTED = threading.Event()
_REQUESTED_SCOPES: set[str] = set()

CURRENT_CANCEL_SCOPE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "CURRENT_CANCEL_SCOPE", default=None
)


def set_cancel_scope(scope: str | None) -> contextvars.Token:
    """Set cancel scope for current context/thread."""
    return CURRENT_CANCEL_SCOPE.set(scope)


def reset_cancel_scope(token: contextvars.Token) -> None:
    """Reset cancel scope to previous token."""
    CURRENT_CANCEL_SCOPE.reset(token)


@contextlib.contextmanager
def cancel_scope(scope: str | None) -> Iterator[str | None]:
    """Context manager to execute block under a specific cancel scope."""
    token = set_cancel_scope(scope)
    try:
        yield scope
    finally:
        reset_cancel_scope(token)


def is_cancel_requested(scope: str | None = None) -> bool:
    """Kiểm tra xem đã có lệnh hủy toàn cục hoặc cho scope cụ thể chưa."""
    if _REQUESTED.is_set():
        return True
    target = scope if scope is not None else CURRENT_CANCEL_SCOPE.get()
    if target is not None:
        with _LOCK:
            return target in _REQUESTED_SCOPES
    return False


def clear_cancel_request(scope: str | None = None) -> None:
    with _LOCK:
        if scope is None:
            _REQUESTED.clear()
            _REQUESTED_SCOPES.clear()
        else:
            _REQUESTED_SCOPES.discard(scope)


def cancel_processes(scope: str | None = None) -> None:
    """Dừng các tiến trình con đã ghi danh.

    - Nếu scope is None: dừng toàn bộ tiến trình con toàn cục.
    - Nếu có scope: chỉ dừng các tiến trình con thuộc scope được chỉ định.
    """
    with _LOCK:
        if scope is None:
            _REQUESTED.set()
            processes = list(_ACTIVE)
        else:
            _REQUESTED_SCOPES.add(scope)
            processes = [p for p, s in _ACTIVE_BY_SCOPE.items() if s == scope]

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
    args: list[str], *, timeout: float | None = None, scope: str | None = None, **kwargs: Any
) -> subprocess.CompletedProcess:
    """Run child process while allowing global or scoped GUI cancellation."""
    eff_scope = scope if scope is not None else CURRENT_CANCEL_SCOPE.get()
    if is_cancel_requested(eff_scope):
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
        _ACTIVE_BY_SCOPE[process] = eff_scope
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        if is_cancel_requested(eff_scope):
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
            _ACTIVE_BY_SCOPE.pop(process, None)


@contextlib.contextmanager
def registered_process(*args: Any, scope: str | None = None, **kwargs: Any) -> Iterator[subprocess.Popen]:
    """``Popen`` đã ghi danh: ``cancel_processes()`` giết được tiến trình con.

    Worker ASR/TTS giữ tiến trình con sống suốt một lần chạy nên không đi qua
    ``run_registered`` được; nếu không ghi danh thì bấm Dừng chỉ chờ tới khi
    worker tự trả lời, tức là vẫn phải nghe hết cả video.
    """
    eff_scope = scope if scope is not None else CURRENT_CANCEL_SCOPE.get()
    if is_cancel_requested(eff_scope):
        raise PipelineCancelled("Pipeline cancelled by user")
    process = subprocess.Popen(*args, **kwargs)
    register(process, scope=eff_scope)
    try:
        yield process
    finally:
        unregister(process)


def register(process: subprocess.Popen, scope: str | None = None) -> subprocess.Popen:
    """Cho một ``Popen`` đang sống vào danh sách để ``cancel_processes()`` giết.

    Worker ASR/TTS giữ tiến trình con suốt một lần chạy nên không đi qua
    ``run_registered``; ghi danh tay là cách duy nhất để nút Dừng không phải
    chờ worker tự xong việc.
    """
    eff_scope = scope if scope is not None else CURRENT_CANCEL_SCOPE.get()
    with _LOCK:
        _ACTIVE.add(process)
        _ACTIVE_BY_SCOPE[process] = eff_scope
    return process


def unregister(process: subprocess.Popen) -> None:
    with _LOCK:
        _ACTIVE.discard(process)
        _ACTIVE_BY_SCOPE.pop(process, None)
