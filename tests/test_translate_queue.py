from __future__ import annotations

import threading
import time

import pytest

from autodub.progress import PipelineCancelled
from autodub.text.translate_queue import TranslationQueue, TranslationTask


def _tasks(count: int) -> list[TranslationTask]:
    return [
        TranslationTask(index=i, segments=[{"id": i}], job_id=f"job-{i}")
        for i in range(count)
    ]


def test_queue_returns_results_in_task_order():
    def handle(task, report):
        time.sleep((3 - task.index) * 0.005)
        report("done", f"batch {task.index}")
        return [task.index]

    states = []
    result = TranslationQueue(
        _tasks(4), worker_count=3, handler=handle,
        on_state=lambda task, status, detail: states.append(
            (task.index, status)),
    ).run()

    assert result == [[0], [1], [2], [3]]
    assert all((i, "queued") in states for i in range(4))
    assert all((i, "done") in states for i in range(4))


def test_queue_cancel_stops_pending_tasks():
    cancel = threading.Event()
    started = []

    def handle(task, report):
        started.append(task.index)
        if task.index == 0:
            cancel.set()
        return [task.index]

    with pytest.raises(PipelineCancelled, match="cancelled"):
        TranslationQueue(
            _tasks(6), worker_count=1, handler=handle,
            cancel_event=cancel,
        ).run()

    assert started == [0]
