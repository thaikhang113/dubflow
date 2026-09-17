"""Chay pipeline that tren video dai va ghi lai thoi gian + dinh RAM.

Cau hoi can tra loi: "xu ly duoc video lon chua?" - phai do, khong doan.

Run:  .venv\\Scripts\\python.exe qa\\long_video_review.py [ten_file.mp4]
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
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

from autodub.config import Settings  # noqa: E402
from autodub.pipeline import DubPipeline, DubRequest  # noqa: E402

QA = os.path.join(ROOT, "qa")
STAGE_RE = re.compile("\u23f1\\s+(\\w+): ([\\d.]+)s")


def ram_now_gb() -> float:
    from autodub.sysinfo import available_ram_gb

    return available_ram_gb() or 0.0


class Sampler(threading.Thread):
    """Do RAM trong + kich thuoc thu muc lam viec dinh ky."""

    def __init__(self, watch_dir: str) -> None:
        super().__init__(daemon=True)
        self.watch_dir = watch_dir
        self.samples: list[tuple[float, float, int]] = []
        self.min_free = 999.0
        self.max_dir_mb = 0
        self.t0 = time.monotonic()
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            free = ram_now_gb()
            mb = 0
            try:
                for root, _d, files in os.walk(self.watch_dir):
                    for f in files:
                        try:
                            mb += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
            except OSError:
                pass
            mb //= 1024 * 1024
            self.samples.append((round(time.monotonic() - self.t0, 1), free, mb))
            self.min_free = min(self.min_free, free)
            self.max_dir_mb = max(self.max_dir_mb, mb)
            self._stop.wait(5.0)

    def stop(self) -> None:
        self._stop.set()


class Ticker(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.stages: dict[str, float] = {}
        self.t0 = time.monotonic()
        self.marks: list[tuple[float, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        m = STAGE_RE.search(msg)
        if m:
            self.stages[m.group(1)] = float(m.group(2))
        for key in ("STEP 3", "STEP 5", "STEP 6", "STEP 7", "Segment 1:"):
            if key in msg:
                self.marks.append((round(time.monotonic() - self.t0, 1),
                                   msg[:80]))
                break


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "long_10min.mp4"
    src = os.path.join(QA, "work", name)
    if not os.path.isfile(src):
        print("thieu video test:", src)
        return 1
    out = os.path.join(QA, "runs", "longrun_" + os.path.splitext(name)[0])
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)

    settings = Settings.load(override=True)
    settings.asr_engine = "whisper"
    settings.whisper_model = "medium"
    settings.ocr_enabled = False
    settings.hq_background = False
    settings.vsr_enabled = False
    settings.translate_enabled = False
    settings.generate_metadata = False
    settings.auto_clean_intermediates = False

    ticker = Ticker()
    logging.getLogger("autodub").addHandler(ticker)
    started = time.monotonic()
    status = "?"
    work = ""
    try:
        # Lan 1: tai + tach + nghe (ASR) -> dung o buoc dich
        try:
            r = DubPipeline(settings).run(DubRequest(
                file_path=src, source_lang="vi", bg_mode="none",
                skip_video=True, subtitle_mode="none", output_dir=out))
            status = r.status
            work = r.work_dir
        except Exception as exc:
            print(f"lan 1 loi: {type(exc).__name__}: {str(exc)[:160]}",
                  flush=True)
        if work:
            import json as _json

            src_j = os.path.join(work, "data", "transcript_original.json")
            dst_j = os.path.join(work, "data", "transcript_vi.json")
            if os.path.isfile(src_j):
                with open(src_j, encoding="utf-8") as handle:
                    segs = _json.load(handle)
                print(f"ASR thay {len(segs)} cau trong video 10 phut",
                      flush=True)
                for s in segs:
                    s["text_vi"] = s.get("text", "")
                with open(dst_j, "w", encoding="utf-8") as handle:
                    _json.dump(segs, handle, ensure_ascii=False)
        ticker.stages.clear()
        ticker.marks.clear()
        ticker.t0 = time.monotonic()
        result = DubPipeline(settings).run(DubRequest(
            file_path=src, source_lang="vi", bg_mode="none",
            skip_video=False, subtitle_mode="none", output_dir=out,
            resume_dir=work))
        status = result.status
        work = result.work_dir
    finally:
        logging.getLogger("autodub").removeHandler(ticker)
    wall = round(time.monotonic() - started, 1)

    print(f"ket qua: {status} | tong {wall}s", flush=True)
    print("--- tung buoc (lan 2: doc + ghep + xuat) ---", flush=True)
    for name, secs in sorted(ticker.stages.items(), key=lambda kv: -kv[1]):
        print(f"  {name:14} {secs:8.1f}s", flush=True)
    if work:
        video = os.path.join(work, "dubbed_video.mp4")
        if os.path.isfile(video):
            import subprocess

            dur = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "default=nk=1:nw=1", video],
                capture_output=True, text=True, check=False).stdout.strip()
            print(f"  video ra: {os.path.getsize(video)/1e6:.1f} MB "
                  f"dur={dur}", flush=True)
        total_mb = sum(
            os.path.getsize(os.path.join(r, f))
            for r, _d, fs in os.walk(work) for f in fs) / 1e6
        print(f"  thu muc du an: {total_mb:.0f} MB", flush=True)
    with open(os.path.join(QA, "findings_long_video.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"wall_s": wall, "stages": ticker.stages,
                   "marks": ticker.marks}, handle, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
