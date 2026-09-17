"""Do thoi gian MOT lan chay hoan chinh, khong cache, khong resume.

Day la con so nguoi dung cam nhan khi bo video vao va bam chay.

Run:  .venv\\Scripts\\python.exe qa\\timing_single.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault(
    "DUBFLOW_DATA_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                 "DubFlow"),
)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from autodub.config import Settings  # noqa: E402
from autodub.pipeline import DubPipeline, DubRequest  # noqa: E402

QA = os.path.join(ROOT, "qa")
SRC = os.path.join(ROOT, "test_ui_data", "e2e_test.mp4")
STAGE_RE = re.compile("\u23f1\\s+(\\w+): ([\\d.]+)s")
WORKER_RE = re.compile(r"\[worker (\d+)\] (Starting VieNeu worker|VieNeu worker ready)")


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.stages: dict[str, float] = {}
        self.events: list[list] = []
        self.lines: list[str] = []
        self.t0 = time.monotonic()

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        self.lines.append(f"{time.monotonic() - self.t0:6.1f}s  {msg[:110]}")
        m = STAGE_RE.search(msg)
        if m:
            self.stages[m.group(1)] = float(m.group(2))
        w = WORKER_RE.search(msg)
        if w:
            self.events.append([round(time.monotonic() - self.t0, 1),
                                int(w.group(1)),
                                "start" if "Starting" in msg else "ready"])


def main() -> int:
    out = os.path.join(QA, "runs", "timing_single")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    settings = Settings.load(override=True)
    settings.asr_engine = "whisper"
    settings.whisper_model = "medium"
    settings.ocr_enabled = False
    settings.hq_background = False
    settings.translate_enabled = False
    settings.generate_metadata = False

    cap = Capture()
    logging.getLogger("autodub").addHandler(cap)
    started = time.monotonic()
    try:
        result = DubPipeline(settings).run(DubRequest(
            file_path=SRC, source_lang="vi", bg_mode="none",
            skip_video=False, subtitle_mode="none", output_dir=out))
    finally:
        logging.getLogger("autodub").removeHandler(cap)
    wall = round(time.monotonic() - started, 1)

    print(f"ket qua: {result.status}", flush=True)
    print(f"TONG thoi gian cho video 5 giay: {wall}s", flush=True)
    print("--- tung buoc (pipeline tu do) ---", flush=True)
    for name, secs in sorted(cap.stages.items(), key=lambda kv: -kv[1]):
        print(f"  {name:14} {secs:7.1f}s", flush=True)
    print("--- moc quan sat duoc ---", flush=True)
    for ev in cap.events:
        print(f"  t={ev[0]:6.1f}s worker{ev[1]} {ev[2]}", flush=True)
    with open(os.path.join(QA, "logs", "timing_single_lines.txt"), "w",
              encoding="utf-8") as handle:
        handle.write("\n".join(cap.lines))
    with open(os.path.join(QA, "findings_timing.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"wall_s": wall, "stages": cap.stages,
                   "worker_events": cap.events}, handle, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
