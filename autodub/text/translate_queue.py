"""Bounded worker queue for blocking translation API calls."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable

from autodub.progress import PipelineCancelled


@dataclass(frozen=True)
class TranslationTask:
    index: int
    segments: list[dict]
    job_id: str


Handler = Callable[[TranslationTask, Callable[[str, str], None]], list[dict]]
StateFn = Callable[[TranslationTask, str, str], None]


class TranslationQueue:
    """Run blocking API tasks through a bounded set of worker threads."""

    def __init__(
        self,
        tasks: list[TranslationTask],
        worker_count: int,
        handler: Handler,
        on_state: StateFn | None = None,
        cancel_event: threading.Event | None = None,
    ):
        self.tasks = list(tasks)
        self.worker_count = max(1, int(worker_count))
        self.handler = handler
        self.on_state = on_state
        self.cancel_event = cancel_event or threading.Event()

    def _state(self, task: TranslationTask, status: str, detail: str = ""):
        if self.on_state is not None:
            self.on_state(task, status, detail)

    def run(self) -> list[list[dict]]:
        work: queue.Queue[TranslationTask | None] = queue.Queue(
            maxsize=max(1, self.worker_count * 2))
        results: dict[int, list[dict]] = {}
        errors: list[BaseException] = []
        stop = threading.Event()

        for task in self.tasks:
            self._state(task, "queued")

        def produce():
            try:
                for task in self.tasks:
                    if stop.is_set() or self.cancel_event.is_set():
                        break
                    work.put(task)
            finally:
                for _ in range(self.worker_count):
                    work.put(None)

        def consume():
            while True:
                task = work.get()
                try:
                    if task is None:
                        return
                    if stop.is_set() or self.cancel_event.is_set():
                        continue
                    self._state(task, "running")
                    result = self.handler(
                        task,
                        lambda status, detail="": self._state(
                            task, status, detail),
                    )
                    if self.cancel_event.is_set():
                        raise PipelineCancelled(
                            "Translation queue cancelled by user")
                    results[task.index] = result
                    self._state(task, "done")
                except BaseException as exc:
                    errors.append(exc)
                    stop.set()
                finally:
                    work.task_done()

        workers = [
            threading.Thread(
                target=consume, name=f"translate-worker-{i}", daemon=True)
            for i in range(min(self.worker_count, max(1, len(self.tasks))))
        ]
        producer = threading.Thread(
            target=produce, name="translate-producer", daemon=True)
        for worker in workers:
            worker.start()
        producer.start()
        producer.join()
        work.join()
        for worker in workers:
            worker.join()

        if self.cancel_event.is_set() and not errors:
            raise PipelineCancelled("Translation queue cancelled by user")
        if errors:
            raise errors[0]
        return [results[task.index] for task in self.tasks]
