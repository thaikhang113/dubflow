"""Kiem tra nhanh batch that cho ba nhanh chua tung chay voi pipeline that.

  A. Huy giua chung batch -> video dang chay dung, video chua chay khong bi tinh
     loi, lan chay sau hoat dong tiep tu cho dung.
  B. retry_done=True -> lam lai ca video da xong.
  C. Mot video cho ban dich tay -> lan dau pending, lan sau (sau khi dien ban
     dich) hoan tat, va khong bi tinh la fail.

Run:  .venv\\Scripts\\python.exe qa\\batch_flows_review.py
"""
from __future__ import annotations

import json
import os
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

from autodub.batch import STATE_FILENAME, BatchItem, run_batch  # noqa: E402
from autodub.config import Settings  # noqa: E402
from autodub.pipeline import DubPipeline, DubRequest  # noqa: E402

QA = os.path.join(ROOT, "qa")
RUNS = os.path.join(QA, "runs")
A_MP4 = os.path.join(ROOT, "test_ui_data", "e2e_test.mp4")
B_MP4 = os.path.join(QA, "work", "long_10min.mp4")

FINDINGS: list[dict] = []


def finding(kind, severity, summary, expected="", actual="", evidence=""):
    FINDINGS.append({"kind": kind, "severity": severity, "summary": summary,
                     "expected": expected, "actual": actual,
                     "evidence": evidence})
    print(f"  !! [{severity}] {kind}: {summary}", flush=True)


def settings_for(out, translate=True):
    s = Settings.load(override=True)
    s.asr_engine = "whisper"
    s.whisper_model = "medium"
    s.ocr_enabled = False
    s.hq_background = False
    s.vsr_enabled = False
    s.video2x_enabled = False
    s.generate_metadata = False
    s.auto_clean_intermediates = False
    s.output_dir = out
    s.translate_enabled = bool(translate)
    return s


def fresh(name):
    out = os.path.join(RUNS, name)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    return out


def read_state(out):
    path = os.path.join(out, STATE_FILENAME)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {v.get("video_url"): v for v in data.get("videos", [])}


# ----------------------------------------------------------------- A -------- #
def flow_cancel_mid_batch():
    print("=== A. Huy giua batch 2 video", flush=True)
    out = fresh("batch_cancel")
    settings = settings_for(out)
    template = DubRequest(source_lang="vi", bg_mode="none", skip_video=True,
                          subtitle_mode="none", output_dir=out)
    items = [BatchItem(file_path=A_MP4), BatchItem(file_path=B_MP4)]
    cancel_event = threading.Event()
    seen: list[tuple[str, str]] = []

    class Cancelling(DubPipeline):
        """Dung sau video dau tien — dung y luc pipeline dang chay video 2."""

        def run(self, req):
            r = super().run(req)
            seen.append((os.path.basename(req.file_path or ""), r.status))
            if len(seen) >= 1:
                cancel_event.set()
            return r

    pipeline = Cancelling(settings, cancel_event=cancel_event)
    started = time.monotonic()
    try:
        summary = run_batch(items, settings, template, pipeline=pipeline)
        outcome = f"returned:{summary}"
    except Exception as exc:
        outcome = f"raised:{type(exc).__name__}"
        if "ancel" not in type(exc).__name__:
            finding("huy batch", "S1",
                    f"huy giua batch nem loi {type(exc).__name__}: {exc}",
                    "PipelineCancelled duoc phat dong de luong GUI bao 'da dung'",
                    evidence=out)
    print(f"  {time.monotonic() - started:.0f}s | {outcome}", flush=True)
    state = read_state(out)
    statuses = {k.split(os.sep)[-1]: v.get("status") for k, v in state.items()}
    print(f"  state: {statuses}", flush=True)
    failed = [k for k, v in statuses.items() if v == "failed"]
    if failed:
        finding("huy batch", "S1",
                f"video bi huy dang ghi nhan 'failed': {failed}",
                "khong video nao bi 'failed' khi nguoi dung bam dung",
                json.dumps(statuses, ensure_ascii=False), out)

    # Chay lai: video dang 'processing' (don vi bi huy giua chung) phai duoc
    # nghi la chua xong va chay lai tu dau, khong bi bo qua vin.
    state_before = {k: v.get("status") for k, v in read_state(out).items()}
    retry_items = [BatchItem(file_path=A_MP4), BatchItem(file_path=B_MP4)]
    again = run_batch(retry_items, settings, template,
                      pipeline=DubPipeline(settings))
    state_after = {k: v.get("status") for k, v in read_state(out).items()}
    print(f"  chay lai: ok={again.success} skip={again.skipped} "
          f"fail={again.failed}", flush=True)
    print(f"  state truoc: {state_before}", flush=True)
    print(f"  state sau:   {state_after}", flush=True)
    stuck = [k for k, v in state_after.items() if v == "processing"]
    if stuck:
        finding("huy batch", "S2",
                f"video bi huy van nguyen 'processing' sau khi chay lai: {stuck}",
                "trang thai phai chuyen sang success/failed/pending",
                json.dumps(state_after, ensure_ascii=False), out)
    unfinished = [k for k, v in state_before.items() if v != "success"]
    if unfinished and again.skipped == len(state_before):
        finding("huy batch", "S1",
                "chay lai bo qua ca video chua xong",
                "chi skip video da success",
                f"skipped={again.skipped}", out)


# ----------------------------------------------------------------- B -------- #
def flow_retry_done():
    print("=== B. retry_done=True lam lai video da xong", flush=True)
    out = fresh("batch_retry")
    settings = settings_for(out)
    template = DubRequest(source_lang="vi", bg_mode="none", skip_video=True,
                          subtitle_mode="none", output_dir=out)
    items = [BatchItem(file_path=A_MP4)]
    first = run_batch(items, settings, template,
                      pipeline=DubPipeline(settings))
    print(f"  lan 1: success={first.success} skipped={first.skipped}",
          flush=True)
    again = run_batch(items, settings, template,
                      pipeline=DubPipeline(settings))
    print(f"  lan 2 (mac dinh): success={again.success} "
          f"skipped={again.skipped}", flush=True)
    if again.skipped != 1:
        finding("batch resume", "S1",
                f"lan chay lai khong skip video da xong (skipped={again.skipped})",
                "skipped=1, success=0", f"success={again.success}", out)
    retried = run_batch(items, settings, template,
                        pipeline=DubPipeline(settings), retry_done=True)
    print(f"  lan 3 (retry_done): success={retried.success} "
          f"skipped={retried.skipped}", flush=True)
    if retried.success != 1 or retried.skipped != 0:
        finding("retry_done", "S1",
                "retry_done=True khong lam lai video da xong",
                "success=1 skipped=0",
                f"success={retried.success} skipped={retried.skipped}", out)


# ----------------------------------------------------------------- C -------- #
def flow_pending_then_complete():
    print("=== C. Batch cho ban dich tay roi hoan tat", flush=True)
    out = fresh("batch_pending")
    settings = settings_for(out, translate=False)
    template = DubRequest(source_lang="zh", bg_mode="none", skip_video=True,
                          subtitle_mode="none", output_dir=out)
    items = [BatchItem(file_path=A_MP4)]
    s1 = run_batch(items, settings, template, pipeline=DubPipeline(settings))
    print(f"  lan 1: pending={s1.pending} failed={s1.failed}", flush=True)
    if s1.pending != 1 or s1.failed != 0:
        finding("batch pending", "S1",
                f"video cho dich tay bi tinh sai (pending={s1.pending} "
                f"failed={s1.failed})", "pending=1 failed=0", out)
        return
    state = read_state(out)
    entry = next(iter(state.values()))
    work = entry.get("work_dir", "")
    if not work or not os.path.isdir(work):
        finding("batch pending", "S2",
                "state khong luu work_dir cho video dang cho dich",
                "work_dir duoc ghi de mo lai dung noi", repr(entry), out)
        return
    src = os.path.join(work, "data", "transcript_original.json")
    if not os.path.isfile(src):
        finding("batch pending", "S1", "khong tim thay transcript goc de dich",
                "duoc giu lai cho nuoc dich tay", src)
        return
    with open(src, encoding="utf-8") as handle:
        segs = json.load(handle)
    for s in segs:
        s["text_vi"] = s.get("text", "")
    with open(os.path.join(work, "data", "transcript_vi.json"), "w",
              encoding="utf-8") as handle:
        json.dump(segs, handle, ensure_ascii=False)
    s2 = run_batch(items, settings, template, pipeline=DubPipeline(settings))
    print(f"  lan 2 sau khi dien ban dich: success={s2.success} "
          f"pending={s2.pending} skipped={s2.skipped}", flush=True)
    if s2.success != 1:
        finding("batch pending", "S1",
                "dien ban dich tay roi batch van khong hoan tat",
                "success=1",
                f"success={s2.success} pending={s2.pending} "
                f"failed={s2.failed}", out)


def main() -> int:
    sys.path.insert(0, os.path.join(ROOT, "qa"))
    for fn in (flow_cancel_mid_batch, flow_retry_done,
               flow_pending_then_complete):
        try:
            fn()
        except Exception as exc:
            import traceback

            finding("harness", "S1", f"{fn.__name__}: {exc}",
                    actual=traceback.format_exc(limit=5)[-400:])
    print(f"=== {len(FINDINGS)} phat hien", flush=True)
    with open(os.path.join(QA, "findings_batch_flows.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"findings": FINDINGS}, handle, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
