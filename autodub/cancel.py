"""Process cancellation shared by GUI workers and long-running subprocesses."""
from __future__ import annotations

import subprocess
import threading
import time
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
        return subprocess.CompletedProcess(args, process.returncode,
                                           stdout, stderr)
    finally:
        with _LOCK:
            _ACTIVE.discard(process)
