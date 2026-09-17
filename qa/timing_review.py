"""Where does the wall-clock time actually go? One real run, per-stage cost.

Reads the pipeline's own ``⏱ <stage>: Ns`` lines plus worker-start markers, so
the numbers come from the product's logging rather than from guesses.

Run:  .venv\\Scripts\\python.exe qa\\timing_review.py
"""
from __future__ import annotations

import json
import logging
import os
import re
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
RUNS = os.path.join(QA, "runs")
SRC = os.path.join(ROOT, "test_ui_data", "e2e_test.mp4")

STAGE_RE = re.compile(r"\u23f1\s+(\w+): ([\d.]+)s")
WORKER_RE = re.compile(r"\[worker (\d+)\] (Starting VieNeu worker|VieNeu worker ready)")


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.stages: dict[str, float] = {}
        self.worker_events: list[tuple[float, int, str]] = []
        self.t0 = time.monotonic()

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        m = STAGE_RE.search(msg)
        if m:
            self.stages[m.group(1)] = float(m.group(2))
        w = WORKER_RE.search(msg)
        if w:
            self.worker_events.append(
                (round(time.monotonic() - self.t0, 1), int(w.group(1)),
                 "start" if "Starting" in msg else "ready"))


def fresh_run(label: str) -> dict:
    """Mot lan chay KHONG cache: do dung thoi gian nguoi dung cam nhan."""
    import shutil

    base = os.path.join(RUNS, label)
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    settings = Settings.load(override=True)
    settings.asr_engine = "whisper"
    settings.whisper_model = "medium"
    settings.ocr_enabled = False
    settings.hq_background = False
    settings.translate_enabled = False
    settings.generate_metadata = False
    out = base
    cap = Capture()
    logging.getLogger("autodub").addHandler(cap)
    started = time.monotonic()
    try:
        # Lan 1: ASR that, dung o buoc dich.
        try:
            DubPipeline(settings).run(DubRequest(
                file_path=SRC, source_lang="vi", bg_mode="none",
                skip_video=True, subtitle_mode="none", output_dir=out))
        except Exception:
            pass
        work = max(
            (os.path.join(out, d) for d in os.listdir(out)
             if os.path.isdir(os.path.join(out, d))),
            key=os.path.getmtime, default="")
        if work:
            src_json = os.path.join(work, "data", "transcript_original.json")
            dst_json = os.path.join(work, "data", "transcript_vi.json")
            if os.path.isfile(src_json) and not os.path.isfile(dst_json):
                with open(src_json, encoding="utf-8") as handle:
                    segs = json.load(handle)
                for s in segs:
                    s["text_vi"] = s.get("text", "")
                with open(dst_json, "w", encoding="utf-8") as handle:
                    json.dump(segs, handle, ensure_ascii=False)
        # Lan 2: do TTS + ghep + xuat, van tai model moi (khong dung cache
        # cua lan 1 vi do la hai luot chay tach roi trong cung mot qua trinh).
        cap.stages.clear()
        cap.worker_events.clear()
        cap.t0 = time.monotonic()
        result = DubPipeline(settings).run(DubRequest(
            file_path=SRC, source_lang="vi", bg_mode="none",
            skip_video=False, subtitle_mode="none", output_dir=out,
            resume_dir=work))
        wall = round(time.monotonic() - started, 1)
    finally:
        logging.getLogger("autodub").removeHandler(cap)
    return {"status": result.status, "stages": dict(cap.stages),
            "worker_events": list(cap.worker_events), "wall_s": wall}


def main() -> int:
    cap = Capture()
    data = fresh_run("timing_fresh")
    result_status = data["status"]
    cap.stages = data["stages"]
    cap.worker_events = data["worker_events"]
    print(f"ket qua: {result_status}", flush=True)
    print("--- thoi gian tung buoc (do chinh pipeline ghi) ---", flush=True)
    stages = cap.stages
    ssum = sum(stages.values())
    for name, secs in sorted(stages.items(), key=lambda kv: -kv[1]):
        print(f"  {name:14} {secs:7.1f}s", flush=True)
    print(f"  {'TONG do duoc':14} {ssum:7.1f}s", flush=True)
    print("--- khoi dong worker VieNeu ---", flush=True)
    for ev in cap.worker_events:
        print(f"  t={ev[0]:6.1f}s worker{ev[1]} {ev[2]}", flush=True)
    loads = [e for e in cap.worker_events if e[2] == "ready"]
    starts = {e[1]: e[0] for e in cap.worker_events if e[2] == "start"}
    for t, idx, _kind in loads:
        if idx in starts:
            print(f"  worker{idx} nap model het {t - starts[idx]:.1f}s",
                  flush=True)
    with open(os.path.join(QA, "findings_timing.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"stages": stages, "worker_events": cap.worker_events,
                   "total_s": data.get("wall_s")}, handle, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
