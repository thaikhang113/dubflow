"""Progress reporting and cancellation primitives for the dubbing pipeline.

Designed so any frontend (CLI today, GUI later) can observe pipeline progress
through a plain callback and cancel through a ``threading.Event`` — no
framework coupling in the core.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

# Pipeline step identifiers, in execution order
STEPS = (
    "acquire",      # download video / use local file
    "ocr",          # detect hardcoded source subtitles (optional)
    "extract",      # extract original audio
    "separate",     # Demucs vocal separation / ducking
    "asr",          # speech-to-text
    "translate",    # load translation (or stop with hint)
    "tts",          # per-segment synthesis
    "merge_audio",  # slow-down / fit / mix with background
    "merge_video",  # remux dub audio into video
    "content",      # thumbnails + YouTube metadata
    "done",
)


@dataclass
class ProgressEvent:
    step: str                 # one of STEPS
    status: str               # "start" | "progress" | "done" | "skip" | "error"
    detail: str = ""
    current: int = 0          # e.g. segment index during TTS
    total: int = 0


ProgressFn = Callable[[ProgressEvent], None]

# Minimum spacing between "progress" events per step — a 900-segment TTS run
# would otherwise fire hundreds of GUI signal deliveries per second.
_PROGRESS_MIN_INTERVAL_S = 0.1


class PipelineCancelled(Exception):
    """Raised inside the pipeline when the cancel event is set."""


class ProgressReporter:
    """Bundles the progress callback and cancel event, with safe no-op defaults.

    "progress" events are rate-limited per step (state changes like start/
    done/error always pass through, as does the final progress tick where
    ``current == total``).
    """

    def __init__(
        self,
        callback: ProgressFn | None = None,
        cancel_event: threading.Event | None = None,
        state_work_dir: str = "",
    ):
        self._callback = callback
        self._cancel_event = cancel_event
        self._last_progress: dict[str, float] = {}
        self._throttle_lock = threading.Lock()
        self._state_work_dir = state_work_dir

    def set_state_work_dir(self, work_dir: str) -> None:
        self._state_work_dir = work_dir

    def emit(self, step: str, status: str, detail: str = "",
             current: int = 0, total: int = 0) -> None:
        if status == "progress" and not (total and current >= total):
            now = time.monotonic()
            with self._throttle_lock:
                last = self._last_progress.get(step, 0.0)
                if now - last < _PROGRESS_MIN_INTERVAL_S:
                    return
                self._last_progress[step] = now
        event = ProgressEvent(step, status, detail, current, total)
        if self._callback:
            try:
                self._callback(event)
            except Exception:
                # Progress là quan sát, không phải điều khiển — một handler GUI
                # lỗi không được phép giết cả pipeline đang chạy.
                pass
        if (self._state_work_dir
                and (status != "progress" or (total and current >= total))):
            from autodub.pipeline_state import record_event
            try:
                record_event(self._state_work_dir, event)
            except OSError:
                pass

    def check_cancelled(self) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise PipelineCancelled("Pipeline cancelled by user")

    @property
    def cancel_event(self) -> threading.Event | None:
        return self._cancel_event
