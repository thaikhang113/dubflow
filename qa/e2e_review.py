"""End-to-end review as a real user, against the installed local engines.

Scenarios (each isolated so one failure does not hide the rest):
  S1  local file -> ASR -> auto-translate (mock) -> TTS -> export video
  S2  same project resumed: nothing re-transcribed, artifacts reused
  S3  manual translation: auto-translate off -> translate_pending ->
      user drops transcript_vi.json -> resume completes
  S4  batch of two (local file + short YouTube URL) with per-line voice
  S5  batch rerun skips completed videos (batch_state.json)
  S6  AUTO_CLEAN_INTERMEDIATES=true keeps report.json + pipeline_state.json
  S7  editor: edit one line, re-synthesize, rebuild output

Run:  .venv\\Scripts\\python.exe qa\\e2e_review.py
Out:  qa/logs/e2e_review.log, qa/findings_e2e.json, qa/runs/<scenario>/
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
sys.path.insert(0, os.path.join(ROOT, "qa"))

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
LOGS = os.path.join(QA, "logs")
os.makedirs(RUNS, exist_ok=True)
os.makedirs(LOGS, exist_ok=True)

LOCAL_VIDEO = os.path.join(ROOT, "test_ui_data", "e2e_test.mp4")
YT_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"   # 19 s, downloads OK

FINDINGS: list[dict] = []
LOG: list[str] = []


def log(msg: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    LOG.append(line)
    print(line, flush=True)


def finding(scenario, kind, severity, summary, expected="", actual="",
            evidence="") -> None:
    FINDINGS.append({"scenario": scenario, "kind": kind,
                     "severity": severity, "summary": summary,
                     "expected": expected, "actual": actual,
                     "evidence": evidence})
    log(f"  !! [{severity}] {kind}: {summary}")


def probe(path: str) -> dict:
    """ffprobe container summary, or {} when unreadable."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size:stream=codec_type,codec_name",
             "-of", "json", path],
            capture_output=True, text=True, timeout=60, check=False)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def streams(path: str) -> set[str]:
    data = probe(path)
    return {s.get("codec_type") for s in data.get("streams", [])}


def duration(path: str) -> float:
    try:
        return float(probe(path).get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def base_settings(**over) -> Settings:
    settings = Settings.load(override=True)
    settings.asr_engine = "whisper"
    settings.whisper_model = "medium"
    settings.output_dir = over.pop("output_dir", settings.output_dir)
    for key, value in over.items():
        setattr(settings, key, value)
    return settings


def check_project(scenario: str, work_dir: str, *, expect_video: bool,
                  min_segments: int = 1) -> dict:
    """Assert the artifacts a user would expect after a completed run."""
    report = {}
    if not work_dir or not os.path.isdir(work_dir):
        finding(scenario, "artifact", "S1", "không có thư mục kết quả",
                "work_dir tồn tại", repr(work_dir))
        return report
    report_path = os.path.join(work_dir, "data", "report.json")
    if not os.path.isfile(report_path):
        finding(scenario, "artifact", "S1", "thiếu data/report.json",
                "report.json được ghi khi hoàn tất", report_path)
    else:
        try:
            with open(report_path, encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            finding(scenario, "artifact", "S1",
                    f"report.json không đọc được: {exc}")
        n = report.get("total_segments", 0)
        if n < min_segments:
            finding(scenario, "asr", "S2",
                    f"số câu nhận dạng được quá ít ({n} < {min_segments})",
                    f">= {min_segments} câu", f"total_segments={n}",
                    report_path)
        if expect_video:
            video = os.path.join(work_dir, "dubbed_video.mp4")
            if not os.path.isfile(video) or os.path.getsize(video) <= 0:
                finding(scenario, "export", "S1", "thiếu dubbed_video.mp4",
                        "video kết quả tồn tại và khác rỗng", video)
            else:
                kinds = streams(video)
                if "video" not in kinds or "audio" not in kinds:
                    finding(scenario, "export", "S1",
                            f"video thiếu stream (có: {sorted(kinds)})",
                            "ít nhất video + audio", video)
                src_dur = report.get("total_original_duration") or 0
                out_dur = duration(video)
                if src_dur and out_dur and abs(out_dur - src_dur) > max(
                        3.0, src_dur * 0.25):
                    finding(scenario, "export", "S2",
                            f"thời lượng video lệch nhiều so với nguồn "
                            f"({out_dur:.1f}s so với {src_dur:.1f}s)",
                            "chênh trong dung sai hợp lý", video)
                else:
                    log(f"  video OK {out_dur:.1f}s streams={sorted(kinds)}")
        audio = os.path.join(work_dir, "data", "audio_vi_full.wav")
        if not os.path.isfile(audio):
            log("  (audio_vi_full.wav đã dọn — hợp lệ khi auto-clean bật)")
        srt = os.path.join(work_dir, "transcript_vi.srt")
        if not os.path.isfile(srt):
            srt = os.path.join(work_dir, "data", "transcript_vi.srt")
        if not os.path.isfile(srt):
            finding(scenario, "subtitle", "S3", "không tìm thấy phụ đề .srt",
                    "transcript_vi.srt cạnh video hoặc trong data/", work_dir)
    for name in ("quality_report.json", "pipeline_state.json"):
        if not os.path.isfile(os.path.join(work_dir, "data", name)):
            finding(scenario, "artifact", "S2", f"thiếu data/{name}",
                    f"{name} luôn tồn tại sau khi chạy xong", work_dir)
    return report


# ---------------------------------------------------------------- S1/S2 ----- #
def scenario_auto_translate(mock_endpoint: str) -> str:
    out = os.path.join(RUNS, "s1_auto")
    settings = base_settings(output_dir=out, translate_enabled=True,
                             translation_endpoint=mock_endpoint,
                             translation_api_key="mock",
                             translation_model="mock-vi")
    req = DubRequest(file_path=LOCAL_VIDEO, source_lang="vi", bg_mode="none",
                     skip_video=False, subtitle_mode="soft", output_dir=out)
    pipeline = DubPipeline(settings)
    result = pipeline.run(req)
    log(f"  status={result.status} work_dir={result.work_dir}")
    if result.status != "completed":
        finding("S1 auto-translate", "pipeline", "S1",
                f"pipeline dừng ở trạng thái {result.status}",
                "completed", result.work_dir)
        return result.work_dir
    check_project("S1 auto-translate", result.work_dir, expect_video=True)

    # S2: resume cùng thư mục — không được nghe lại
    log("  resume cùng work_dir")
    started = time.time()
    asr_cache = os.path.join(result.work_dir, "data",
                             "transcript_original.json")
    if not os.path.isfile(asr_cache):
        finding("S2 resume", "cache", "S1",
                "chạy xong mà mất data/transcript_original.json — không thể "
                "tái sử dụng kết quả ASR",
                "lưu transcript gốc để lần sau chạy tiếp", asr_cache)
        return result.work_dir
    state_before = os.path.getmtime(asr_cache)
    again = DubPipeline(settings).run(
        DubRequest(file_path=LOCAL_VIDEO, source_lang="vi", bg_mode="none",
                   skip_video=False, subtitle_mode="soft", output_dir=out,
                   resume_dir=result.work_dir))
    state_after = os.path.getmtime(asr_cache)
    log(f"  resume xong trong {time.time() - started:.1f}s")
    if again.status != "completed":
        finding("S2 resume", "pipeline", "S1",
                f"resume không hoàn tất ({again.status})", "completed",
                again.work_dir)
    if abs(state_after - state_before) > 0.001:
        finding("S2 resume", "cache", "S2",
                "resume ghi lại transcript_original.json — đã nghe lại từ đầu",
                "transcript gốc được tái sử dụng, không ghi lại",
                again.work_dir)
    return again.work_dir


# ------------------------------------------------------------------- S3 ----- #
def scenario_manual_translate() -> str:
    """Nguồn tiếng Anh + dịch tự động tắt -> pipeline phải dừng chờ dịch tay.

    Phải là ngôn ngữ nguồn KHÁC tiếng Việt: vi->vi được pipeline trả lời thẳng
    (không cần máy dịch) nên không bao giờ ở trạng thái chờ.
    """
    out = os.path.join(RUNS, "s3_manual")
    settings = base_settings(output_dir=out, translate_enabled=False)
    req = DubRequest(file_path=LOCAL_VIDEO, source_lang="en", bg_mode="none",
                     skip_video=True, subtitle_mode="none", output_dir=out)
    result = DubPipeline(settings).run(req)
    log(f"  status={result.status}")
    if result.status != "translate_pending":
        finding("S3 dịch tay", "pipeline", "S1",
                "tắt dịch tự động nhưng không trả translate_pending",
                "status=translate_pending kèm hướng dẫn", result.status)
        return
    work = result.work_dir
    hint = os.path.join(work, "TRANSLATE_PENDING.txt")
    if not os.path.isfile(hint):
        finding("S3 dịch tay", "ux", "S3",
                "không có TRANSLATE_PENDING.txt để hướng dẫn người dùng",
                "file hướng dẫn 3 bước trong thư mục dự án", work)
    orig = os.path.join(work, "data", "transcript_original.json")
    try:
        with open(orig, encoding="utf-8") as handle:
            segments = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        finding("S3 dịch tay", "artifact", "S1",
                f"thiếu transcript gốc để dịch tay: {exc}",
                "data/transcript_original.json hợp lệ", orig)
        return
    if not segments:
        finding("S3 dịch tay", "asr", "S2",
                "ASR trả 0 câu nên không có gì để dịch tay",
                "ít nhất 1 câu", orig)
        return
    for seg in segments:
        seg["text_vi"] = "Đây là bản dịch do người dùng tự viết."
    with open(os.path.join(work, "data", "transcript_vi.json"), "w",
              encoding="utf-8") as handle:
        json.dump(segments, handle, ensure_ascii=False, indent=2)
    resumed = DubPipeline(settings).run(
        DubRequest(file_path=LOCAL_VIDEO, source_lang="en", bg_mode="none",
                   skip_video=True, subtitle_mode="none", output_dir=out,
                   resume_dir=work))
    log(f"  resume sau khi dịch tay: status={resumed.status}")
    if resumed.status != "completed":
        finding("S3 dịch tay", "pipeline", "S1",
                "điền bản dịch tay rồi nhưng resume không đi tiếp",
                "completed", f"{resumed.status} @ {resumed.work_dir}")
        return ""
    else:
        check_project("S3 dịch tay", resumed.work_dir, expect_video=False)
        return resumed.work_dir


# ---------------------------------------------------------------- S4/S5 ----- #
def scenario_batch(mock_endpoint: str) -> None:
    import shutil
    from autodub.batch import BatchItem, run_batch
    out = os.path.join(RUNS, "s4_batch")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    settings = base_settings(output_dir=out, translate_enabled=True,
                             translation_endpoint=mock_endpoint,
                             translation_api_key="mock",
                             translation_model="mock-vi")
    items = [
        BatchItem(file_path=LOCAL_VIDEO, voice=None),
        BatchItem(url=YT_URL, voice=None),
    ]
    req = DubRequest(source_lang="en", bg_mode="none", skip_video=False,
                     subtitle_mode="soft", output_dir=out)
    seen: list[tuple[str, str]] = []

    def observer(index, total, item, status, detail):
        seen.append((item.label, status))
        log(f"  [{index + 1}/{total}] {item.label} -> {status}")

    summary = run_batch(items, settings, req, observer=observer)
    log(f"  batch: ok={summary.success} fail={summary.failed} "
        f"pending={summary.pending} skip={summary.skipped}")
    if summary.failed:
        for item in items:
            ref = item.ref or {}
            if ref.get("status") == "failed":
                finding("S4 batch", "pipeline", "S1",
                        f"video lỗi: {str(ref.get('error'))[:120]}",
                        "mọi video hoàn tất", item.label)
    if summary.success < 1:
        finding("S4 batch", "pipeline", "S1", "batch không xong video nào",
                ">=1 video success", f"success={summary.success}")
    state_path = os.path.join(out, "batch_state.json")
    if not os.path.isfile(state_path):
        finding("S4 batch", "artifact", "S2", "thiếu batch_state.json",
                "state file được ghi để resume", state_path)
        return
    with open(state_path, encoding="utf-8") as handle:
        state = json.load(handle)
    statuses = {v.get("video_url"): v.get("status")
                for v in state.get("videos", [])}
    log(f"  state: {list(statuses.values())}")
    if not statuses:
        finding("S4 batch", "artifact", "S2",
                "batch_state.json không có mục video nào", "mỗi video 1 mục",
                state_path)
    for url, status in statuses.items():
        if status == "success":
            entry = next(v for v in state["videos"]
                         if v.get("video_url") == url)
            folder = entry.get("output_folder", "")
            if not folder or not os.path.isdir(folder):
                finding("S4 batch", "state", "S1",
                        "video đánh dấu success nhưng output_folder không tồn tại",
                        "đường dẫn hợp lệ sau validate", folder)

    # S5: chạy lại phải skip video đã xong
    before = dict(statuses)
    again = run_batch(items, settings, req)
    log(f"  rerun: ok={again.success} skip={again.skipped} "
        f"fail={again.failed}")
    done_before = sum(1 for s in before.values() if s == "success")
    if done_before and again.skipped < done_before:
        finding("S5 batch rerun", "state", "S1",
                f"chạy lại không skip video đã xong (skip={again.skipped}, "
                f"đã xong={done_before})",
                "skipped bằng số video success trước đó",
                f"success={again.success} failed={again.failed}", state_path)


# ------------------------------------------------------------------- S6 ----- #
def scenario_auto_clean(mock_endpoint: str) -> None:
    out = os.path.join(RUNS, "s6_clean")
    settings = base_settings(output_dir=out, translate_enabled=True,
                             translation_endpoint=mock_endpoint,
                             translation_api_key="mock",
                             translation_model="mock-vi",
                             auto_clean_intermediates=True)
    req = DubRequest(file_path=LOCAL_VIDEO, source_lang="vi", bg_mode="none",
                     skip_video=False, subtitle_mode="none", output_dir=out)
    result = DubPipeline(settings).run(req)
    if result.status != "completed":
        finding("S6 auto-clean", "pipeline", "S1",
                f"pipeline fail khi auto-clean bật ({result.status})",
                "completed", result.work_dir)
        return
    data = os.path.join(result.work_dir, "data")
    for name in ("report.json", "pipeline_state.json"):
        if not os.path.isfile(os.path.join(data, name)):
            finding("S6 auto-clean", "state", "S1",
                    f"auto-clean xóa mất data/{name}",
                    "giữ metadata cần cho batch validate và resume", data)
    big = os.path.join(data, "original_audio.wav")
    if os.path.exists(big):
        finding("S6 auto-clean", "diskspace", "S3",
                "auto-clean bật nhưng tệp trung gian lớn vẫn còn",
                "tệp trung gian bị dọn sau khi có video kết quả", big)
    # Batch phải vẫn validate được dự án này
    import shutil
    from autodub.batch import BatchItem, run_batch
    batch_out = os.path.join(RUNS, "s6_batch")
    shutil.rmtree(batch_out, ignore_errors=True)
    os.makedirs(batch_out, exist_ok=True)
    items = [BatchItem(file_path=LOCAL_VIDEO, voice=None)]
    summary = run_batch(items, settings, DubRequest(
        source_lang="vi", bg_mode="none", skip_video=False,
        subtitle_mode="none", output_dir=batch_out))
    if summary.failed:
        finding("S6 auto-clean", "batch", "S1",
                "batch fail vì auto-clean lấy mất tệp validate",
                "success=1", f"failed={summary.failed}")
    else:
        log(f"  batch với auto-clean: success={summary.success}")


# ------------------------------------------------------------------- S7 ----- #
def scenario_editor(work_dir: str) -> None:
    if not work_dir or not os.path.isdir(work_dir):
        log("  bỏ qua S7 (không có dự án để sửa)")
        return
    from autodub import editor
    try:
        state = editor.load_work_dir(work_dir)
    except editor.EditorError as exc:
        finding("S7 editor", "editor", "S1", f"không mở được dự án: {exc}",
                "load_work_dir đọc được transcript", work_dir)
        return
    if not state.segments:
        finding("S7 editor", "editor", "S2", "editor nạp 0 câu",
                "số câu khớp transcript", work_dir)
        return
    first = state.segments[0]["id"]
    changed = editor.save_segment_texts(work_dir, {first: "Câu đã sửa tay."})
    if changed != [first]:
        finding("S7 editor", "editor", "S2",
                "sửa chữ không được ghi nhận là thay đổi",
                f"[{first}]", repr(changed))
    reloaded = editor.load_work_dir(work_dir)
    got = next(s for s in reloaded.segments if s["id"] == first)
    if got.get("text_vi") != "Câu đã sửa tay.":
        finding("S7 editor", "editor", "S1",
                "sửa câu nhưng tải lại mất nội dung",
                "thay đổi được ghi xuống đĩa", repr(got.get("text_vi")))
    else:
        log("  OK sửa câu và ghi đĩa")


def main() -> int:
    from mock_translate import MockTranslate

    if not os.path.isfile(LOCAL_VIDEO):
        log(f"!! thiếu {LOCAL_VIDEO}")
        return 1
    mock = MockTranslate().start()
    log(f"mock dịch: {mock.endpoint}")
    work_for_editor = ""
    try:
        for name, fn in (
                ("S1+S2 auto-translate/resume",
                 lambda: _capture(lambda: scenario_auto_translate(mock.endpoint))),
                ("S3 manual translate",
                 lambda: _capture(scenario_manual_translate)),
                ("S4+S5 batch", lambda: _capture(lambda: scenario_batch(mock.endpoint))),
                ("S6 auto-clean", lambda: _capture(lambda: scenario_auto_clean(mock.endpoint))),
        ):
            log(f"=== {name}")
            started = time.time()
            result = fn()
            if isinstance(result, str) and result:
                work_for_editor = result
            log(f"  ({time.time() - started:.0f}s)")
        log("=== S7 editor")
        _capture(lambda: scenario_editor(work_for_editor))
    finally:
        mock.stop()

    with open(os.path.join(QA, "findings_e2e.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"findings": FINDINGS}, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(LOGS, "e2e_review.log"), "w",
              encoding="utf-8") as handle:
        handle.write("\n".join(LOG))
    log(f"=== {len(FINDINGS)} phát hiện")
    return 0


def _capture(fn):
    try:
        return fn()
    except Exception as exc:
        finding("harness", "crash", "S1",
                f"kịch bản ném exception: {type(exc).__name__}: {exc}",
                actual=traceback.format_exc(limit=6)[-600:])
        return None


if __name__ == "__main__":
    raise SystemExit(main())
