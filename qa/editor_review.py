"""Review the Editor surface the way a user finishes a project: edit text,
re-synthesize one line, rebuild audio/video, and export subtitle-only.

Uses the newest completed project under qa/runs as input.

Run:  .venv\\Scripts\\python.exe qa\\editor_review.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault(
    "DUBFLOW_DATA_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                 "DubFlow"),
)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from autodub import editor  # noqa: E402
from autodub.config import Settings  # noqa: E402
from autodub.progress import ProgressReporter  # noqa: E402

RUNS = os.path.join(ROOT, "qa", "runs")
FINDINGS: list[dict] = []


def finding(kind, severity, summary, expected="", actual="", evidence=""):
    FINDINGS.append({"kind": kind, "severity": severity, "summary": summary,
                     "expected": expected, "actual": actual,
                     "evidence": evidence})
    print(f"  !! [{severity}] {kind}: {summary}", flush=True)


def probe(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type", "-of", "json", path],
            capture_output=True, text=True, timeout=60, check=False)
        return json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def newest_project():
    found = []
    for root, _dirs, files in os.walk(RUNS):
        if "dubbed_video.mp4" in files and os.path.isfile(
                os.path.join(root, "data", "transcript_vi.json")):
            found.append(root)
    return sorted(found, key=os.path.getmtime)[-1] if found else ""


def main() -> int:
    work = newest_project()
    if not work:
        print("khong co du an de test editor - chay e2e_review truoc")
        return 1
    print(f"du an: {work}", flush=True)
    settings = Settings.load(override=True)
    settings.asr_engine = "whisper"
    settings.whisper_model = "medium"

    state = editor.load_work_dir(work)
    print(f"  {len(state.segments)} cau, video={state.video_path}", flush=True)
    if not state.segments:
        finding("editor", "S1", "mo du an nhung 0 cau")
        return 0

    # 1. Sua chu mot cau
    first_id = state.segments[0]["id"]
    editor.save_segment_texts(work, {first_id: "Câu đã sửa để kiểm tra editor."})
    reloaded = editor.load_work_dir(work)
    got = next(s for s in reloaded.segments if s["id"] == first_id)
    if got.get("text_vi") != "Câu đã sửa để kiểm tra editor.":
        finding("editor", "S1", "sửa câu không được ghi xuống đĩa",
                "Câu đã sửa để kiểm tra editor.", repr(got.get("text_vi")))
    else:
        print("  OK sua cau va ghi dia", flush=True)

    # 2. Phu de viet rieng khong lam doi loi doc
    editor.save_subtitle_texts(work, {first_id: "Phụ đề viết riêng."})
    st2 = editor.load_work_dir(work)
    seg = next(s for s in st2.segments if s["id"] == first_id)
    if seg.get("sub_vi") != "Phụ đề viết riêng.":
        finding("editor", "S2", "phụ đề riêng không được lưu",
                "sub_vi = Phụ đề viết riêng.", repr(seg.get("sub_vi")))
    if seg.get("text_vi") != "Câu đã sửa để kiểm tra editor.":
        finding("editor", "S1",
                "sửa phụ đề riêng làm thay đổi lời đọc",
                "text_vi giữ nguyên", repr(seg.get("text_vi")))
    else:
        print("  OK phu de rieng tach khoi loi doc", flush=True)

    # 3. Doc lai giong cho mot cau
    try:
        started = time.time()
        result = editor.resynth_segment(work, first_id, settings)
        print(f"  OK resynth 1 cau trong {time.time() - started:.1f}s "
              f"({result.get('actual_duration', 0):.1f}s audio)", flush=True)
    except Exception as exc:
        finding("editor", "S1", f"doc lai giong that bai: {exc}",
                actual=traceback.format_exc(limit=4)[-400:])

    # 4. resynth phai vo hieu hoa video cu de buoc dung lai khong dung lai no
    stale = os.path.join(work, "dubbed_video.mp4")
    if os.path.isfile(stale):
        finding("editor", "S2",
                "resynth xong ma video cu van nguyen — dung lai co the phat "
                "lai ban cu",
                "xoa artifact da het hieu luc", stale)
    else:
        print("  OK video cu bi vo hieu hoa sau resynth", flush=True)

    # 5. Dung lai video
    events = []
    reporter = ProgressReporter(lambda e: events.append((e.step, e.status)))
    try:
        started = time.time()
        out = editor.rebuild_output(
            work, settings, subtitle_mode="soft", reporter=reporter)
        print(f"  OK dung lai video trong {time.time() - started:.1f}s -> {out}",
              flush=True)
    except Exception as exc:
        finding("editor", "S1", f"rebuild_output that bai: {exc}",
                actual=traceback.format_exc(limit=5)[-500:])
        out = ""

    if out and os.path.isfile(out):
        data = probe(out)
        kinds = {s.get("codec_type") for s in data.get("streams", [])}
        dur = float(data.get("format", {}).get("duration", 0) or 0)
        print(f"  video moi: {dur:.1f}s streams={sorted(kinds)}", flush=True)
        if "video" not in kinds or "audio" not in kinds:
            finding("editor", "S1", "video dung lai thieu stream",
                    "video + audio", str(sorted(kinds)), out)
        if dur <= 0:
            finding("editor", "S1", "video dung lai co thoi luong 0",
                    "> 0", str(dur), out)
        # Loi doc moi phai nam trong video
        srt = os.path.join(work, "transcript_vi.srt")
        if os.path.isfile(srt):
            with open(srt, encoding="utf-8") as handle:
                body = handle.read()
            if "Phụ đề viết riêng." not in body:
                finding("editor", "S2",
                        "phụ đề xuất ra không chứa bản sửa riêng của người dùng",
                        "co dong 'Phu de viet rieng.'", srt)
            else:
                print("  OK phu de dung theo ban sua rieng", flush=True)

    # 6. Chi doi phu de -> khong can doc lai giong
    try:
        started = time.time()
        subs = editor.rebuild_subtitles(work, settings, subtitle_mode="burn")
        print(f"  OK rebuild_subtitles {time.time() - started:.1f}s -> {subs}",
              flush=True)
    except AttributeError:
        print("  (rebuild_subtitles khong ton tai)", flush=True)
    except Exception as exc:
        finding("editor", "S2", f"rebuild_subtitles loi: {exc}",
                actual=str(exc)[:200])

    print(f"=== {len(FINDINGS)} phat hien", flush=True)
    with open(os.path.join(ROOT, "qa", "findings_editor.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"project": work, "findings": FINDINGS}, handle,
                  ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
