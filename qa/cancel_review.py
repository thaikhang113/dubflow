"""Measure how long "Dừng" actually takes, and whether ffmpeg keeps running.

Presses cancel the moment a given pipeline step starts, exactly the way the GUI
worker does (set the event + kill registered child processes), then reports the
latency and how many ffmpeg processes survive afterwards.

Run:  .venv\\Scripts\\python.exe qa\\cancel_review.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault(
    "DUBFLOW_DATA_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                 "DubFlow"),
)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from autodub.cancel import cancel_processes, clear_cancel_request  # noqa: E402
from autodub.config import Settings  # noqa: E402
from autodub.pipeline import DubPipeline, DubRequest  # noqa: E402
from autodub.progress import PipelineCancelled  # noqa: E402

QA = os.path.join(ROOT, "qa")
RUNS = os.path.join(QA, "runs")
# Video co loi tieng Viet that (TTS sinh ra) de pipeline vuot qua ASR va buoc
# den nhung buoc keo dai nhu TTS / xuat video.
SPEECH = os.path.join(ROOT, "test_ui_data", "e2e_test.mp4")


def ffmpeg_alive() -> int:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/NH"],
            capture_output=True, text=True, timeout=20, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return -1
    return sum(1 for line in out.splitlines() if "ffmpeg.exe" in line)


def settings_for() -> Settings:
    s = Settings.load(override=True)
    s.asr_engine = "whisper"
    s.whisper_model = "medium"
    s.ocr_enabled = False
    s.hq_background = False
    s.vsr_enabled = False
    s.video2x_enabled = False
    s.generate_metadata = False
    return s


def cancel_after_step_event(stage: str, tag: str) -> dict:
    """Hủy ngay khi một bước phát ``progress`` đầu tiên (bước dài giữa chừng)."""
    return cancel_at_stage(stage, tag, on_progress=True)


def cancel_at_stage(stage: str, tag: str) -> dict:
    """Start a real run, press Dừng the instant ``stage`` begins, measure."""
    out = os.path.join(RUNS, tag)
    cancel_event = threading.Event()
    seen: list[str] = []
    pressed: list[float] = []
    result: dict = {"stage": stage, "tag": tag, "latency_s": None,
                    "outcome": None, "steps": seen, "ffmpeg_left": None}

    def on_event(event) -> None:
        if event.status == "start" and event.step not in seen:
            seen.append(event.step)
        fires = event.step == stage and (
            event.status == "start" or event.status == "progress")
        if fires and not pressed:
            pressed.append(time.monotonic())
            # Exactly what DubWorker.cancel() does.
            cancel_event.set()
            cancel_processes()

    def worker() -> None:
        # GUI gọi clear_cancel_request() ở đầu mỗi lượt chạy; _REQUESTED là
        # event toàn cục, không xóa thì lượt sau abort ngay từ tiêu đề.
        clear_cancel_request()
        try:
            r = DubPipeline(settings_for(), progress=on_event,
                            cancel_event=cancel_event).run(
                DubRequest(file_path=SPEECH, source_lang="vi", bg_mode="none",
                           skip_video=False, subtitle_mode="none",
                           output_dir=out))
            result["outcome"] = f"returned:{r.status}"
        except PipelineCancelled:
            result["outcome"] = "cancelled"
        except Exception as exc:
            result["outcome"] = f"error:{type(exc).__name__}: {str(exc)[:90]}"
        finally:
            if pressed:
                result["latency_s"] = round(time.monotonic() - pressed[0], 1)

    thread = threading.Thread(target=worker, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(timeout=900)
    if thread.is_alive():
        result["outcome"] = "STILL RUNNING after 900s"
        result["latency_s"] = 900.0
    result["ffmpeg_left"] = ffmpeg_alive()
    result["wall_s"] = round(time.monotonic() - started, 1)
    return result


def main() -> int:
    print(f"ffmpeg luc dau: {ffmpeg_alive()}", flush=True)
    rows = []
    for stage, tag in (("merge_audio", "cancel_during_merge_audio"),
                       ("tts", "cancel_during_tts"),
                       ("merge_video", "cancel_during_export")):
        print(f"=== bam Dung khi bat dau buoc: {stage}", flush=True)
        r = cancel_at_stage(stage, tag)
        rows.append(r)
        print(f"  ket qua={r['outcome']} | dung sau {r['latency_s']}s "
              f"| ffmpeg con song={r['ffmpeg_left']} | buoc={r['steps']}",
              flush=True)
    print(f"ffmpeg sau cung: {ffmpeg_alive()}", flush=True)
    with open(os.path.join(QA, "findings_cancel.json"), "w",
              encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
