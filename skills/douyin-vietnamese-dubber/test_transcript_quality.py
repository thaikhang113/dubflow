#!/usr/bin/env python3
"""Unit test cho choose_transcript_source.py + OCR quality metrics.

Chạy độc lập, không cần 9Router/video. Tự sinh SRT trong tmpdir.
Case:
- choose: OCR 17 cue (có cue kéo 62s/112s) vs ASR 111 cue -> auto chọn ASR,
  reason chứa ocr_quality_failed_use_asr hoặc ocr_too_sparse, ocr_reject_reasons không rỗng.
- choose: ASR hallucination/truncated 39 cue chỉ phủ 87.6s của video 338s, OCR 82 cue phủ gần hết
  nhưng report quality_ok=false do cảnh báo nhỏ -> auto chọn OCR, không fallback ASR cụt.
- ocr quality: SRT có 2 cue dài bất thường -> long_thin_cues>=1, max_cue_seconds>15.
- good OCR: 24 cue đều <8s, text đủ dài -> quality_ok True (không over-reject).
"""
import json
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
CHOOSE = SKILL_DIR / "choose_transcript_source.py"
OCR_TRANSCRIPT = SKILL_DIR / "ocr_subtitle_transcript.py"
ASR_POSTPROCESS = SKILL_DIR / "postprocess_asr_srt.py"


def ms_to_srt(ms):
    ms = max(0, int(ms))
    hh, rem = divmod(ms, 3600000)
    mm, rem = divmod(rem, 60000)
    ss, mmm = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{mmm:03d}"


def write_srt(path, cues):
    """cues: list (start_ms, end_ms, text)."""
    out = []
    for i, (s, e, text) in enumerate(cues, 1):
        out.append(str(i))
        out.append(f"{ms_to_srt(s)} --> {ms_to_srt(e)}")
        out.append(text)
        out.append("")
    Path(path).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def bad_ocr_cues():
    """Mô phỏng OCR 17 cue có cue dài bất thường: 姓名 kéo 62s, 小然今天怎么来这么晚 kéo 112s."""
    cues = []
    t = 0
    # 15 cue ngắn bình thường
    texts = ["他们恨我", "说我有病", "为什么", "因为我们疯", "不", "是世界疯了", "我只是更重", "我叫莫然", "疯子比杨健可怕", "那时大家都叫我", "代表新时代", "他叫莫然", "是对的人吗", "生物学上我是人", "没有家人同行吗"]
    for tx in texts:
        cues.append((t, t + 2000, tx))
        t += 2500
    # cue 16: 姓名 (2 ký tự) kéo 62s  -> long-thin
    cues.append((t, t + 62000, "姓名"))
    t += 64000
    # cue 17: 小然今天怎么来这么晚 kéo 112s  -> max_cue quá dài
    cues.append((t, t + 112000, "小然今天怎么来这么晚"))
    return cues


def good_ocr_cues(n=20):
    cues = []
    t = 0
    for i in range(n):
        cues.append((t, t + 5000, f"这是第{i+1}句正常的字幕文字"))  # text >12 chars, dur 5s
        t += 6000
    return cues


def good_asr_cues(n=111):
    cues = []
    t = 0
    for i in range(n):
        cues.append((t, t + 2500, f"第{i+1}句语音转写"))
        t += 3050
    return cues


def asr_repeated_loop_cues(n=139, repeat_start=40, repeat_count=68):
    """ASR hallucination loop: một câu dài bị lặp liên tiếp gần 70 lần."""
    cues = []
    t = 0
    loop_text = "好,我明天再來一會兒吃飯吧"
    for i in range(n):
        if repeat_start <= i < repeat_start + repeat_count:
            text = loop_text
        else:
            text = f"第{i+1}句正常语音转写"
        cues.append((t, t + 2000, text))
        t += 2400
    return cues


def sparse_clean_ocr_cues_for_anchor(n=34):
    """OCR giống job 151342: ít cue hơn ASR nhưng cue sạch, đủ làm timing anchor."""
    cues = []
    step = 8280
    dur = 4260
    for i in range(n):
        s = i * step
        cues.append((s, min(s + dur, 280180), f"第{i+1}句字幕"))
    return cues


def sparse_ocr_cues_194118():
    """Job 20260709-194118 shape: OCR clean but too sparse for dubbing timing."""
    starts = [
        2920, 8920, 14920, 17920, 29920, 41920, 47920, 56920,
        65920, 74920, 83920, 89920, 98920, 104920, 113920, 119920,
        128920, 134920, 140920, 146920, 149920, 164920, 170920, 179920,
    ]
    cues = []
    for i, start in enumerate(starts):
        dur = 1260 if i in {2, 11, 16, 17, 19, 23} else 4260
        cues.append((start, start + dur, f"第{i+1}句字幕"))
    return cues


def asr_cues_194118_after_postprocess():
    """ASR remains timeline-rich after dropping a small legitimate short-text burst."""
    cues = []
    step = 3140
    dur = 2400
    for i in range(58):
        start = i * step
        cues.append((start, min(start + dur, 182200), f"第{i+1}句语音"))
    cues[-1] = (179800, 182200, "最后一句语音")
    return cues


def asr_cues_200456_with_tail_loop():
    """Job 20260709-200456 shape: ASR mostly rich, but tail has one local hallucination loop."""
    cues = []
    step = 3000
    dur = 2200
    for i in range(47):
        start = i * step
        cues.append((start, start + dur, f"第{i+1}句正常语音转写"))
    loop_text = "我这边有很多的鬼物"
    loop_start = 141320
    for i in range(18):
        start = loop_start + i * 2200
        cues.append((start, start + 1600, loop_text))
    return cues


def asr_cues_with_four_long_thin_for_repair():
    """ASR giống job 151342: nhiều cue hơn OCR, nhưng 4 cue ngắn bị kéo dài."""
    cues = []
    t = 0
    for i in range(13):
        cues.append((t, t + 2500, f"第{i+1}句语音"))
        t += 3050
    # 1 cue có OCR overlap.
    cues.append((41760, 49160, "第14句语音"))  # len 5, 7.4s
    t = 52000
    for i in range(14, 18):
        cues.append((t, t + 2500, f"第{i+1}句语音"))
        t += 3050
    # 1 cue không có OCR overlap; 2 cue sau có overlap.
    cues.append((71360, 78110, "嗯"))
    cues.append((78110, 91600, "为什么"))
    t = 94000
    for i in range(20, 38):
        cues.append((t, t + 2500, f"第{i+1}句语音"))
        t += 3050
    cues.append((144320, 151480, "第39句语音"))
    t = 154000
    while len(cues) < 91:
        i = len(cues) + 1
        cues.append((t, t + 2500, f"第{i}句语音"))
        t += 3050
    return cues


def ocr_anchor_cues_for_long_thin_repair():
    """OCR sparse nhưng sạch, có overlap cho 3/4 long-thin ASR cue."""
    cues = sparse_clean_ocr_cues_for_anchor(30)
    cues.extend([
        (42000, 46400, "OCR重叠一"),
        (79000, 83300, "OCR重叠二"),
        (145000, 149000, "OCR重叠三"),
        (276000, 280180, "片尾字幕"),
    ])
    return cues


def dashboard_ocr_cues(n=82):
    """OCR giống job Bilibili 5m38s: nhiều cue đều, phủ tới cuối, có 1 cue hơi mỏng."""
    cues = []
    step = 4130
    dur = 3760
    for i in range(n):
        s = i * step
        e = min(s + dur, 339180)
        text = f"这是第{i+1}句正常字幕"
        cues.append((s, e, text))
    # Một cảnh báo long-thin nhẹ: cue ngắn 7.76s, nhưng chỉ 1/82 cue và vẫn dưới max 15s.
    cues[-1] = (335920, 339180, "未成年")
    cues[10] = (41300, 49060, "姓名")
    return cues


def truncated_severe_asr_cues(n=39):
    cues = []
    t = 0
    for i in range(n):
        cues.append((t, min(t + 2040, 87600), f"第{i+1}句语音"))
        t += 2250
    cues[-1] = (84880, 87600, "今晚还是早点休息吧")
    return cues


def import_choose():
    import importlib.util
    spec = importlib.util.spec_from_file_location("choose_ts", CHOOSE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_srt_quality():
    mod = import_choose()
    bad = mod.srt_quality([{"time": "00:00:00,000 --> 00:01:02,000", "text": "姓名"}],
                          video_duration=338.0)
    ok = True
    if bad["long_thin_cues"] < 1:
        print(f"  FAIL: bad OCR long_thin_cues={bad['long_thin_cues']} (need >=1)")
        ok = False
    else:
        print(f"  OK: bad OCR long_thin_cues={bad['long_thin_cues']} max_cue={bad['max_cue_seconds']}s")
    good = mod.srt_quality([{"time": "00:00:00,000 --> 00:00:05,000", "text": "这是正常的字幕文字"}],
                           video_duration=300.0)
    if good["long_thin_cues"] != 0:
        print(f"  FAIL: good OCR long_thin_cues={good['long_thin_cues']} (need 0)")
        ok = False
    else:
        print(f"  OK: good OCR long_thin_cues=0 max_cue={good['max_cue_seconds']}s density={good['cue_density_per_min']}/min")
    return ok


def run_choose(ocr_cues, asr_cues, ocr_report_extra=None, asr_report=None):
    """Sinh SRT + reports, gọi choose_transcript_source.py --mode auto. Trả decision dict."""
    with tempfile.TemporaryDirectory(prefix="choose_ts_") as td:
        td = Path(td)
        ocr_srt = td / "original_ocr.srt"
        asr_srt = td / "original_asr.srt"
        out_srt = td / "original.srt"
        asr_report_p = td / "asr_report.json"
        ocr_report_p = td / "ocr_report.json"
        decision_p = td / "decision.json"
        consistency_p = td / "consistency.json"
        write_srt(ocr_srt, ocr_cues)
        write_srt(asr_srt, asr_cues)
        ocr_report = {
            "status": "ok",
            "engine_used": "9router_vision",
            "segment_count": len(ocr_cues),
            "coverage_ratio": 0.901,
            "avg_confidence": 0.9,
            "video_duration": 338.0,
        }
        if ocr_report_extra:
            ocr_report.update(ocr_report_extra)
        ocr_report_p.write_text(json.dumps(ocr_report, ensure_ascii=False), encoding="utf-8")
        asr_report_p.write_text(json.dumps(asr_report or {"hallucination": {"severe": False}}, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            ["python3", str(CHOOSE), "--mode", "auto",
             "--asr-srt", str(asr_srt), "--ocr-srt", str(ocr_srt),
             "--output-srt", str(out_srt),
             "--asr-report", str(asr_report_p), "--ocr-report", str(ocr_report_p),
             "--decision-json", str(decision_p), "--consistency-json", str(consistency_p)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            result = {"_returncode": proc.returncode, "_stderr": proc.stderr, "_stdout": proc.stdout}
            if decision_p.exists():
                result["_decision"] = json.loads(decision_p.read_text(encoding="utf-8"))
            if consistency_p.exists():
                result["_consistency"] = json.loads(consistency_p.read_text(encoding="utf-8"))
            return result
        result = json.loads(decision_p.read_text(encoding="utf-8"))
        if out_srt.exists():
            out_text = out_srt.read_text(encoding="utf-8")
            result["_output_cues"] = out_text.count(" --> ")
            result["_output_text"] = out_text
        return result


def test_choose_bad_ocr_use_asr():
    """Case chính: OCR 17 cue (có cue 62s/112s) vs ASR 111 cue -> chọn ASR."""
    dec = run_choose(bad_ocr_cues(), good_asr_cues(111),
                     ocr_report_extra={"quality_ok": False, "max_cue_seconds": 112.0, "long_thin_cues": 1})
    ok = True
    if dec.get("_returncode"):
        print(f"  FAIL: choose exited {dec['_returncode']}: {dec.get('_stderr')}")
        return False
    chosen = dec.get("chosen")
    reason = dec.get("reason", "")
    rejects = dec.get("ocr_reject_reasons", [])
    print(f"[choose bad OCR] chosen={chosen} reason={reason} ocr_reject_reasons={rejects}")
    if chosen != "asr":
        print(f"  FAIL: chosen={chosen} (need asr) - OCR 17 thưa vs ASR 111 phải bị reject")
        ok = False
    else:
        print("  OK: chọn ASR thay vì OCR thưa")
    if not rejects:
        print("  FAIL: ocr_reject_reasons rỗng")
        ok = False
    else:
        print(f"  OK: có reject reasons: {rejects}")
    if "ocr_quality_failed_use_asr" not in reason and "ocr_too_sparse" not in reason and "asr_better_for_dub_timing" not in reason:
        print(f"  WARN: reason={reason} (mong đợi ocr_quality_failed_use_asr / ocr_too_sparse / asr_better_for_dub_timing)")
    return ok


def test_choose_truncated_severe_asr_prefers_usable_ocr():
    """Regression cho job input-20260705-144608: ASR severe chỉ tới 87.6s, OCR phủ full video."""
    dec = run_choose(
        dashboard_ocr_cues(82),
        truncated_severe_asr_cues(39),
        ocr_report_extra={
            "quality_ok": False,
            "coverage_ratio": 0.874,
            "avg_confidence": 0.952,
            "video_duration": 338.858667,
            "max_cue_seconds": 7.76,
            "long_thin_cues": 1,
        },
        asr_report={"hallucination": {"severe": True}, "video_duration": 338.858667},
    )
    if dec.get("_returncode"):
        print(f"  FAIL: choose exited {dec['_returncode']}: {dec.get('_stderr')}")
        return False
    chosen = dec.get("chosen")
    reason = dec.get("reason", "")
    asr_quality = dec.get("asr_quality", {})
    ocr_quality = dec.get("ocr_quality", {})
    print(f"[choose truncated ASR] chosen={chosen} reason={reason} "
          f"asr_coverage={asr_quality.get('timeline_coverage_ratio')} "
          f"ocr_density={ocr_quality.get('cue_density_per_min')} "
          f"warnings={dec.get('ocr_warnings')}")
    if chosen != "ocr":
        print("  FAIL: ASR severe/truncated không được thắng OCR usable")
        return False
    if not dec.get("ocr_quality_ok"):
        print(f"  FAIL: OCR usable bị reject: {dec.get('ocr_reject_reasons')}")
        return False
    if dec.get("asr_timeline_ok"):
        print("  FAIL: ASR timeline coverage 87.6/338s phải bị đánh dấu không ok")
        return False
    print("  OK: chọn OCR khi ASR severe/truncated, dù OCR report có warning nhỏ")
    return True


def test_choose_good_ocr_not_overrejected():
    """OCR tốt (24 cue, text đủ, <8s) vs ASR tốt (29 cue) -> không over-reject OCR.

    ASR/OCR = 29/24 = 1.21 < 1.25 nên dub-timing rule (asr_better_for_dub) KHÔNG kích hoạt;
    OCR quality_ok -> chọn OCR. Dub-timing rule (ASR > OCR*1.25 -> ASR) được test riêng
    trong test_voice_sync.py với fixture job thật (ASR 94 / OCR 65).
    """
    dec = run_choose(good_ocr_cues(24), good_asr_cues(29),
                     ocr_report_extra={"quality_ok": True, "max_cue_seconds": 5.0, "long_thin_cues": 0})
    chosen = dec.get("chosen")
    reason = dec.get("reason", "")
    print(f"[choose good OCR] chosen={chosen} reason={reason}")
    # OCR 20 vs ASR 24 -> ratio 1.2 < 1.25 -> dub rule không fire; OCR quality_ok -> chọn OCR.
    if chosen != "ocr":
        print(f"  FAIL: chosen={chosen} (need ocr) - OCR tốt (ASR/OCR<1.25) không nên bị over-reject")
        return False
    print("  OK: OCR tốt được chọn, không over-reject (ASR/OCR=1.21<1.25, dub rule không fire)")
    return True


def test_choose_sparse_clean_ocr_keeps_timing_anchor():
    """OCR sparse-vs-ASR không đủ làm transcript chính, nhưng vẫn sạch để làm timing anchor."""
    dec = run_choose(
        sparse_clean_ocr_cues_for_anchor(34),
        asr_cues_with_four_long_thin_for_repair(),
        ocr_report_extra={
            "status": "ok",
            "quality_ok": True,
            "coverage_ratio": 0.493,
            "avg_confidence": 0.954,
            "video_duration": 281.797,
        },
        asr_report={"hallucination": {"severe": False}, "video_duration": 281.797},
    )
    ok = True
    if dec.get("_returncode"):
        print(f"  FAIL: choose exited {dec['_returncode']}: {dec.get('_stderr')}")
        return False
    print(f"[choose sparse OCR anchor] chosen={dec.get('chosen')} reason={dec.get('reason')} "
          f"ocr_transcript_usable={dec.get('ocr_transcript_usable')} "
          f"ocr_timing_anchor_usable={dec.get('ocr_timing_anchor_usable')} "
          f"rejects={dec.get('ocr_reject_reasons')}")
    if dec.get("chosen") != "asr":
        print(f"  FAIL: ASR phải được chọn làm transcript/dub timing, got {dec.get('chosen')}")
        ok = False
    if dec.get("ocr_transcript_usable") is not False:
        print("  FAIL: OCR sparse-vs-ASR phải là không đủ làm transcript chính")
        ok = False
    if dec.get("ocr_timing_anchor_usable") is not True:
        print("  FAIL: OCR sạch phải còn usable để làm timing anchor sửa ASR")
        ok = False
    if not any(str(r).startswith("ocr_too_sparse_vs_asr") for r in dec.get("ocr_reject_reasons", [])):
        print(f"  FAIL: thiếu reject reason sparse-vs-ASR: {dec.get('ocr_reject_reasons')}")
        ok = False
    if ok:
        print("  OK: OCR sparse không làm transcript chính nhưng vẫn làm timing anchor")
    return ok


def test_choose_both_sources_failed_qc():
    """ASR severe + OCR timeout/rỗng phải fail rõ exit 7, không được chọn ASR mù quáng."""
    dec = run_choose(
        [],
        good_asr_cues(53),
        ocr_report_extra={
            "status": "error",
            "exit": 124,
            "quality_ok": False,
            "coverage_ratio": 0.0,
            "avg_confidence": 0.0,
            "video_duration": 338.0,
        },
        asr_report={"hallucination": {"severe": True}, "video_duration": 338.0},
    )
    ok = True
    print(f"[choose both failed QC] returncode={dec.get('_returncode')} stderr={dec.get('_stderr', '').strip()[:120]}")
    if dec.get("_returncode") != 7:
        print(f"  FAIL: returncode={dec.get('_returncode')} (need 7)")
        return False
    decision = dec.get("_decision") or {}
    if decision.get("status") != "failed_qc":
        print(f"  FAIL: decision.status={decision.get('status')} (need failed_qc)")
        ok = False
    if decision.get("reason") != "both_sources_failed_qc":
        print(f"  FAIL: decision.reason={decision.get('reason')} (need both_sources_failed_qc)")
        ok = False
    if decision.get("error_code") != "TranscriptSourcesFailedQC":
        print(f"  FAIL: decision.error_code={decision.get('error_code')} (need TranscriptSourcesFailedQC)")
        ok = False
    if decision.get("chosen") not in ("", None):
        print(f"  FAIL: decision.chosen={decision.get('chosen')} (need empty)")
        ok = False
    if not decision.get("severe_asr") or decision.get("ocr_quality_ok"):
        print("  FAIL: metrics không phản ánh ASR severe + OCR rejected")
        ok = False
    if ok:
        print("  OK: both sources failed QC -> decision JSON failed_qc + exit 7")
    return ok


def test_choose_severe_asr_does_not_reject_good_ocr_as_sparse():
    """ASR severe/hallucinated có thể phình cue count; không được dùng nó để reject OCR tốt."""
    dec = run_choose(
        good_ocr_cues(45),
        good_asr_cues(119),
        ocr_report_extra={
            "status": "ok",
            "quality_ok": True,
            "coverage_ratio": 0.539,
            "avg_confidence": 0.72,
            "video_duration": 338.859,
        },
        asr_report={
            "hallucination": {"severe": True},
            "video_duration": 338.859,
        },
    )
    ok = True
    if dec.get("_returncode"):
        print(f"  FAIL: choose exited {dec['_returncode']}: {dec.get('_stderr')}")
        return False
    print(f"[choose severe ASR sparse OCR] chosen={dec.get('chosen')} reason={dec.get('reason')} warnings={dec.get('ocr_warnings')}")
    if dec.get("chosen") != "ocr":
        print(f"  FAIL: severe ASR + quality OCR phải chọn OCR, got {dec.get('chosen')}")
        ok = False
    if dec.get("reason") != "asr_severe_and_ocr_quality_ok":
        print(f"  FAIL: reason={dec.get('reason')} (need asr_severe_and_ocr_quality_ok)")
        ok = False
    reject_reasons = dec.get("ocr_reject_reasons") or []
    if any(str(r).startswith("ocr_too_sparse_vs_asr") for r in reject_reasons):
        print(f"  FAIL: ocr_too_sparse_vs_asr không được là reject khi ASR severe: {reject_reasons}")
        ok = False
    warnings = dec.get("ocr_warnings") or []
    if not any("ignored_due_to_severe_asr" in str(w) for w in warnings):
        print(f"  FAIL: thiếu warning ignored_due_to_severe_asr: {warnings}")
        ok = False
    if ok:
        print("  OK: ASR severe không còn làm OCR tốt bị reject vì sparse ratio")
    return ok


def test_choose_repeated_asr_loop_prefers_ocr():
    """Regression job input-20260707-223825: ASR loop 'ăn cơm' 68 lần, OCR sạch -> chọn OCR."""
    dec = run_choose(
        good_ocr_cues(45),
        asr_repeated_loop_cues(),
        ocr_report_extra={
            "status": "ok",
            "quality_ok": True,
            "coverage_ratio": 0.539,
            "avg_confidence": 0.958,
            "video_duration": 338.859,
        },
        asr_report={
            "hallucination": {"severe": False},
            "video_duration": 338.859,
        },
    )
    ok = True
    if dec.get("_returncode"):
        print(f"  FAIL: choose exited {dec['_returncode']}: {dec.get('_stderr')}")
        return False
    repeat = dec.get("asr_repeat") or {}
    print(f"[choose repeated ASR loop] chosen={dec.get('chosen')} reason={dec.get('reason')} "
          f"severe={dec.get('severe_asr')} max_run={repeat.get('max_consecutive_count')} "
          f"top_count={repeat.get('top_count')} warnings={dec.get('ocr_warnings')}")
    if not dec.get("severe_asr"):
        print("  FAIL: ASR loop dài phải bị đánh severe_asr")
        ok = False
    if dec.get("chosen") != "ocr":
        print(f"  FAIL: ASR loop + OCR sạch phải chọn OCR, got {dec.get('chosen')}")
        ok = False
    if dec.get("reason") != "asr_severe_and_ocr_quality_ok":
        print(f"  FAIL: reason={dec.get('reason')} (need asr_severe_and_ocr_quality_ok)")
        ok = False
    reject_reasons = dec.get("ocr_reject_reasons") or []
    if any(str(r).startswith("ocr_too_sparse_vs_asr") for r in reject_reasons):
        print(f"  FAIL: ASR loop không được dùng để reject OCR sparse: {reject_reasons}")
        ok = False
    if ok:
        print("  OK: ASR loop bị loại, OCR sạch được chọn")
    return ok


def test_choose_local_asr_tail_loop_uses_ocr_without_hybrid():
    """A repeat-hallucinated ASR must select one source, never a mixed transcript."""
    dec = run_choose(
        sparse_ocr_cues_194118(),
        asr_cues_200456_with_tail_loop(),
        ocr_report_extra={
            "status": "ok",
            "quality_ok": True,
            "coverage_ratio": 0.462,
            "avg_confidence": 0.960,
            "video_duration": 182.486,
        },
        asr_report={
            "hallucination": {"severe": False, "bursts": [], "dropped_burst_segments": 0},
            "video_duration": 182.486,
        },
    )
    ok = True
    if dec.get("_returncode"):
        print(f"  FAIL: choose exited {dec['_returncode']}: {dec.get('_stderr')}")
        return False
    hybrid = dec.get("transcript_hybrid_report") or {}
    print(f"[choose local ASR tail loop] chosen={dec.get('chosen')} reason={dec.get('reason')} "
          f"severe={dec.get('severe_asr')} hybrid_used={dec.get('transcript_hybrid_used')} "
          f"removed={hybrid.get('removed_repeat_segments')} fill={hybrid.get('ocr_fill_cues')} "
          f"output_cues={dec.get('_output_cues')}")
    if dec.get("chosen") != "ocr":
        print(f"  FAIL: local ASR loop phải chọn OCR usable, got {dec.get('chosen')}")
        ok = False
    if dec.get("reason") != "asr_severe_and_ocr_quality_ok":
        print(f"  FAIL: reason={dec.get('reason')} (need asr_severe_and_ocr_quality_ok)")
        ok = False
    if dec.get("transcript_hybrid_used") is not False:
        print("  FAIL: transcript_hybrid_used phải false")
        ok = False
    if int(hybrid.get("ocr_fill_cues") or 0) != 0:
        print("  FAIL: selector không được fill OCR vào ASR")
        ok = False
    if dec.get("speech_timing_source") != "tts_natural":
        print(f"  FAIL: speech_timing_source={dec.get('speech_timing_source')} (need tts_natural)")
        ok = False
    if ok:
        print("  OK: local tail loop chọn OCR nguyên vẹn, không build hybrid")
    return ok


def test_choose_short_repetition_false_positive_uses_asr():
    """Regression job input-20260709-194118: true repeated short dialogue must not force sparse OCR."""
    dec = run_choose(
        sparse_ocr_cues_194118(),
        asr_cues_194118_after_postprocess(),
        ocr_report_extra={
            "status": "ok",
            "quality_ok": True,
            "coverage_ratio": 0.462,
            "avg_confidence": 0.957,
            "video_duration": 182.486,
        },
        asr_report={
            "hallucination": {
                "severe": True,
                "dropped_burst_segments": 5,
                "bursts": [
                    {"type": "single_text", "text": "下一个", "count": 5, "start_ms": 48800, "end_ms": 74200}
                ],
            },
            "video_duration": 182.486,
        },
    )
    ok = True
    if dec.get("_returncode"):
        print(f"  FAIL: choose exited {dec['_returncode']}: {dec.get('_stderr')}")
        return False
    print(f"[choose short repetition false-positive] chosen={dec.get('chosen')} reason={dec.get('reason')} "
          f"reported_severe={dec.get('reported_severe_asr')} relaxed={dec.get('asr_burst_severe_relaxed')} "
          f"warnings={dec.get('ocr_warnings')}")
    if dec.get("reported_severe_asr") is not True:
        print("  FAIL: fixture phải mô phỏng report severe từ postprocess")
        ok = False
    if dec.get("asr_burst_severe_relaxed") is not True:
        print("  FAIL: burst 5 câu ngắn + ASR timeline tốt + OCR thưa phải được relax")
        ok = False
    if dec.get("severe_asr"):
        print("  FAIL: severe_asr phải false sau khi relax false-positive")
        ok = False
    if dec.get("chosen") != "asr":
        print(f"  FAIL: phải chọn ASR để tránh OCR thưa gây VoiceSyncFail, got {dec.get('chosen')}")
        ok = False
    if dec.get("reason") != "asr_better_for_dub_timing":
        print(f"  FAIL: reason={dec.get('reason')} (need asr_better_for_dub_timing)")
        ok = False
    if not any(str(r).startswith("ocr_too_sparse_vs_asr") for r in dec.get("ocr_reject_reasons", [])):
        print(f"  FAIL: OCR thưa phải bị reject làm transcript chính: {dec.get('ocr_reject_reasons')}")
        ok = False
    if ok:
        print("  OK: không dùng OCR thưa khi ASR chỉ bị false-positive burst ngắn")
    return ok


def test_asr_postprocess_short_repetition_default_static():
    """Five short repeated lines like '下一个' can be real dialogue; default should be conservative."""
    source = ASR_POSTPROCESS.read_text(encoding="utf-8")
    ok = True
    print("[asr postprocess short repetition] checking default repeat threshold")
    if 'ASR_REPEAT_TEXT_MIN_COUNT", "8"' not in source:
        print("  FAIL: default ASR_REPEAT_TEXT_MIN_COUNT phải là 8 để không xóa 5 câu thoại lặp thật")
        ok = False
    if ok:
        print("  OK: default repeat burst threshold is conservative")
    return ok


def test_resume_ocr_timeout_keeps_auto_mode():
    """Regression: OCR timeout cache chỉ skip retry OCR, không force mode asr khi ASR có thể severe."""
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    marker = "Resume: OCR transcript trước đó lỗi/timeout"
    idx = run_sh.find(marker)
    if idx < 0:
        print("  FAIL: không tìm thấy resume OCR timeout block trong run.sh")
        return False
    block = run_sh[idx:idx + 900]
    ok = True
    print("[resume OCR timeout] checking run.sh block")
    if 'SUBTITLE_TRANSCRIPT_SOURCE="asr"' in block:
        print("  FAIL: resume OCR timeout block vẫn force SUBTITLE_TRANSCRIPT_SOURCE=asr")
        ok = False
    if "giữ mode auto" not in block:
        print("  FAIL: block không ghi rõ giữ mode auto để QC ASR")
        ok = False
    if "ocr_transcript_previously_failed=1" not in block:
        print("  FAIL: block không set flag skip OCR retry")
        ok = False
    if "TranscriptSourcesFailedQC" not in run_sh:
        print("  FAIL: run.sh chưa xử lý error_code TranscriptSourcesFailedQC")
        ok = False
    if ok:
        print("  OK: resume OCR timeout skip retry nhưng vẫn giữ auto QC")
    return ok


def test_asr_long_thin_repair():
    """Regression test cho job input-20260702-201915: ASR 94 cue có 3 long-thin, OCR 65 ok.
    chosen=asr (asr_better_for_dub_timing). Repair chia long-thin ASR cue theo ranh giới
    OCR chồng lấp -> long_thin về 0. Gate source-aware -> warning (KHÔNG TranscriptTooSparse).
    Edge: long-thin ASR cue KHÔNG có OCR chồng -> repair incomplete -> gate fail (hard-fail)."""
    import importlib.util
    REPAIR = SKILL_DIR / "asr_timing_repair.py"
    spec = importlib.util.spec_from_file_location("asr_repair", REPAIR)
    rep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rep)
    ok = True

    # ASR 94 cue: 91 cue bình thường + 3 cue long-thin (text<12 chars, dur 7s).
    asr_cues = []
    t = 0
    for i in range(91):
        asr_cues.append((t, t + 2600, f"第{i+1}句语音转写"))
        t += 2900
    # 3 long-thin: "哦" (1 char) kéo 7s, có OCR cue chồng lấp -> repair thành sub-cue.
    asr_cues.append((t, t + 7000, "哦")); t += 7200
    asr_cues.append((t, t + 7000, "嗯")); t += 7200
    asr_cues.append((t, t + 7000, "啊")); t += 7200

    # OCR 65 cue: phần lớn 3.5-4.76s, có 3 cue chồng lấp đúng vào 3 long-thin ASR cue.
    ocr_cues = []
    ot = 0
    for i in range(62):
        ocr_cues.append((ot, ot + 4000, f"这是第{i+1}句正常的字幕文字"))
        ot += 4500
    # 3 OCR cue khớp thời gian với 3 long-thin ASR cue (chồng lấp).
    for j, (s, e, _) in enumerate(asr_cues[-3:]):
        ocr_cues.append((s + 500, s + 3000, f"OCR重叠{j+1}"))
    assert len(ocr_cues) == 65, len(ocr_cues)

    asr_dicts = [{"start_ms": s, "end_ms": e, "text": tx} for s, e, tx in asr_cues]
    ocr_dicts = [{"start_ms": s, "end_ms": e, "text": tx} for s, e, tx in ocr_cues]
    repaired, report = rep.repair_asr_with_ocr(asr_dicts, ocr_dicts, min_chars=12, max_thin_s=6.0)
    print(f"[repair] long_thin_before={report['long_thin_before']} repaired={report['repaired_cues']} "
          f"remaining={report['remaining_long_thin']} unrepaired={report['unrepaired_long_thin']} status={report['status']}")
    if report["long_thin_before"] != 3:
        print(f"  FAIL: long_thin_before={report['long_thin_before']} (need 3)")
        ok = False
    if report["status"] != "ok":
        print(f"  FAIL: repair status={report['status']} (need ok, remaining should be 0)")
        ok = False
    if report["repaired_cues"] != 3:
        print(f"  FAIL: repaired_cues={report['repaired_cues']} (need 3)")
        ok = False
    if report["remaining_long_thin"] != 0:
        print(f"  FAIL: remaining_long_thin={report['remaining_long_thin']} (need 0)")
        ok = False
    else:
        print("  OK: 3 long-thin ASR cue repaired from OCR overlap, long_thin -> 0")

    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    if "asr_repaired_ok" in run_sh:
        print("  FAIL: TX_GATE không được bypass canonical transcript bằng repair sidecar")
        ok = False
    else:
        print("  OK: repair là diagnostic, TX_GATE không bypass canonical transcript")

    # Job resume edge: OCR fail/timeout, chosen=asr, ASR phủ timeline tốt và chỉ vài long-thin cue.
    # Gate nên warning để pipeline đi tiếp bằng ASR, không kẹt needs_attention vì OCR đã fail.
    failed_ocr_dec = {
        "chosen": "asr",
        "severe_asr": False,
        "ocr_quality_ok": False,
        "asr_timeline_ok": True,
    }
    repair_skipped = {"status": "skipped", "remaining_long_thin": 0}
    gate_fail = tx_gate_eval(failed_ocr_dec, repair_skipped, asr_dicts, video_duration_s=(t / 1000.0))
    if gate_fail is not None:
        print(f"  FAIL: OCR failed but ASR is usable; gate should warn/continue, got: {gate_fail}")
        ok = False
    else:
        print("  OK: TX_GATE OCR-failed + usable ASR -> warning (no TranscriptTooSparse)")

    # Edge: long-thin ASR cue KHÔNG có OCR chồng -> repair incomplete -> gate fail (hard-fail giữ).
    edge_asr = [{"start_ms": 0, "end_ms": 7000, "text": "哦"}]  # long-thin, không OCR chồng
    edge_ocr = [{"start_ms": 100000, "end_ms": 104000, "text": "OCRxa"}]  # xa, không chồng
    repaired2, report2 = rep.repair_asr_with_ocr(edge_asr, edge_ocr, 12, 6.0)
    print(f"[repair edge] long_thin_before={report2['long_thin_before']} remaining={report2['remaining_long_thin']} status={report2['status']}")
    if report2["status"] != "incomplete":
        print(f"  FAIL: edge repair status={report2['status']} (need incomplete)")
        ok = False
    else:
        print("  OK: edge — long-thin không OCR chồng -> repair incomplete (giữ hard-fail)")
    return ok


def test_asr_repair_uses_sparse_clean_ocr_anchor():
    """Regression job 151342: ocr_quality_ok False do sparse, nhưng OCR report sạch nên repair vẫn chạy."""
    ok = True
    REPAIR = SKILL_DIR / "asr_timing_repair.py"
    with tempfile.TemporaryDirectory(prefix="asr_repair_anchor_") as td:
        td = Path(td)
        asr_srt = td / "asr.srt"
        ocr_srt = td / "ocr.srt"
        out_srt = td / "out.srt"
        decision = td / "decision.json"
        report_p = td / "repair_report.json"
        write_srt(asr_srt, asr_cues_with_four_long_thin_for_repair())
        write_srt(ocr_srt, ocr_anchor_cues_for_long_thin_repair())
        decision.write_text(json.dumps({
            "chosen": "asr",
            "severe_asr": False,
            "ocr_quality_ok": False,
            "ocr_transcript_usable": False,
            "ocr_timing_anchor_usable": True,
            "asr_quality": {"long_thin_cues": 4},
        }, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([
            "python3", str(REPAIR),
            "--asr-srt", str(asr_srt),
            "--ocr-srt", str(ocr_srt),
            "--decision-json", str(decision),
            "--output-srt", str(out_srt),
            "--report-json", str(report_p),
            "--max-thin-seconds", "6",
            "--min-text-chars", "12",
            "--max-remaining-long-thin", "5",
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"  FAIL: repair exit={proc.returncode} stderr={proc.stderr[:160]}")
            return False
        rep = json.loads(report_p.read_text(encoding="utf-8"))
        print(f"[repair sparse OCR anchor] status={rep.get('status')} repaired={rep.get('repaired_cues')} "
              f"remaining={rep.get('remaining_long_thin')} anchor={rep.get('ocr_timing_anchor_usable')}")
        if rep.get("status") != "partial_ok":
            print(f"  FAIL: expected partial_ok, got {rep.get('status')}")
            ok = False
        if int(rep.get("repaired_cues") or 0) < 1:
            print("  FAIL: repair không dùng OCR anchor để sửa cue nào")
            ok = False
        if int(rep.get("remaining_long_thin") or 0) > 5:
            print("  FAIL: còn quá nhiều long-thin sau repair")
            ok = False
        if not out_srt.exists() or out_srt.stat().st_size == 0:
            print("  FAIL: partial_ok phải ghi output_srt đã repair")
            ok = False
        if ok:
            print("  OK: repair dùng OCR anchor dù OCR không usable làm transcript chính")
    return ok


def tx_gate_eval(dec, repair_report, cues, video_duration_s, min_per_min=4.0,
                 max_cue_s=15.0, max_thin_s=6.0, min_chars=12,
                 allow_asr_failed_ocr=True, asr_max_long_thin_cues=5,
                 asr_max_long_thin_ratio=0.05, asr_max_warn_cue_s=10.0):
    """Tái tạo TX_GATE source-aware logic. Trả None nếu OK/warn, hoặc fail reason string."""
    if not cues:
        return "no cue"
    max_cue = 0.0
    long_thin = 0
    for c in cues:
        dur = (c["end_ms"] - c["start_ms"]) / 1000.0
        if dur > max_cue:
            max_cue = dur
        if len(re.sub(r"\s+", "", c.get("text", ""))) < min_chars and dur > max_thin_s:
            long_thin += 1
    dur_min = video_duration_s / 60.0 if video_duration_s > 0 else 0
    density = len(cues) / dur_min if dur_min > 0 else 999
    chosen = dec.get("chosen")
    severe = bool(dec.get("severe_asr"))
    ocr_transcript_ok = bool(dec.get("ocr_transcript_usable", dec.get("ocr_quality_ok")))
    ocr_anchor_ok = bool(dec.get("ocr_timing_anchor_usable", ocr_transcript_ok))
    asr_timeline_ok = bool(dec.get("asr_timeline_ok"))
    if max_cue > max_cue_s:
        return f"max_cue {max_cue:.2f}>{max_cue_s}"
    if dur_min > 0 and density < min_per_min:
        return f"density {density:.2f}<{min_per_min}"
    if long_thin > 0:
        remaining = int(repair_report.get("remaining_long_thin") or 0)
        repaired = int(repair_report.get("repaired_cues") or repair_report.get("repaired") or 0)
        long_thin_ratio = long_thin / len(cues)
        asr_ok = (
            chosen == "asr"
            and not severe
            and ocr_anchor_ok
            and repair_report.get("status") in ("ok", "partial_ok")
            and (
                remaining == 0
                or (
                    repaired > 0
                    and remaining <= asr_max_long_thin_cues
                    and long_thin <= asr_max_long_thin_cues
                    and long_thin_ratio <= asr_max_long_thin_ratio
                    and max_cue <= asr_max_warn_cue_s
                )
            )
        )
        if asr_ok:
            return None  # warning
        asr_failed_ocr_but_usable = (
            allow_asr_failed_ocr
            and chosen == "asr"
            and not severe
            and not ocr_anchor_ok
            and asr_timeline_ok
            and long_thin <= asr_max_long_thin_cues
            and long_thin_ratio <= asr_max_long_thin_ratio
            and max_cue <= asr_max_warn_cue_s
            and (dur_min <= 0 or density >= min_per_min)
        )
        if asr_failed_ocr_but_usable:
            return None  # warning
        return f"long_thin={long_thin} (chosen={chosen} repair={repair_report.get('status')})"
    return None


def test_tx_gate_preserves_transcript_too_sparse_status():
    """TX_GATE needs_attention không được gọi fail() rồi ghi đè thành PipelineError."""
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    marker = 'if [[ "$tx_gate_status" -eq 7 ]]; then'
    idx = run_sh.find(marker)
    if idx < 0:
        print("  FAIL: không tìm thấy TX_GATE status block")
        return False
    block = run_sh[idx:idx + 2600]
    ok = True
    if 'status_update "needs_attention" "97" "Transcript gốc quá thưa' not in block:
        print("  FAIL: TX_GATE không ghi needs_attention TranscriptTooSparse")
        ok = False
    if 'fail "$tx_gate_msg"' in block:
        print("  FAIL: TX_GATE vẫn gọi fail(), sẽ ghi đè thành PipelineError")
        ok = False
    if "exit 7" not in block:
        print("  FAIL: TX_GATE phải exit 7 trực tiếp sau needs_attention")
        ok = False
    if ok:
        print("  OK: TX_GATE giữ TranscriptTooSparse/needs_attention, không ghi đè PipelineError")
    return ok


def test_vi_gate_blocks_repeated_translation_loop_static():
    """VI gate phải chặn bản dịch bị loop một câu, không render tiếp."""
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    marker = 'TranslationRepeatedLoop'
    idx = run_sh.find(marker)
    if idx < 0:
        print("  FAIL: run.sh thiếu TranslationRepeatedLoop gate")
        return False
    block = run_sh[max(0, idx - 1400):idx + 900]
    ok = True
    if "VI_GATE_MAX_REPEAT_RUN" not in run_sh or "repeated translation run" not in run_sh:
        print("  FAIL: thiếu ngưỡng/detect repeated translation run")
        ok = False
    if 'status_update "manual_translate" "58" "Bản dịch bị lặp câu' not in block:
        print("  FAIL: TranslationRepeatedLoop không ghi manual_translate status rõ")
        ok = False
    if 'fail "Bản dịch Việt bị lặp' in block:
        print("  FAIL: TranslationRepeatedLoop vẫn gọi fail(), sẽ ghi đè PipelineError")
        ok = False
    if "exit 7" not in block:
        print("  FAIL: TranslationRepeatedLoop phải exit 7 trực tiếp")
        ok = False
    if ok:
        print("  OK: VI_GATE chặn repeated translation loop trước TTS/render")
    return ok


def test_choose_ocr_partial_accepted_when_quality_ok():
    """OCR bị budget timeout giữa chừng (status=timeout_partial, timed_out=true) nhưng có đủ
    segment chất lượng tốt -> chọn OCR (không reject chỉ vì partial)."""
    dec = run_choose(good_ocr_cues(24), good_asr_cues(20),
                     ocr_report_extra={
                         "status": "timeout_partial", "partial": True, "timed_out": True,
                         "timeout_reason": "vision_budget_exceeded",
                         "quality_ok": True, "max_cue_seconds": 7.0,
                         "long_thin_cues": 0, "frame_count": 600,
                         "processed_frame_count": 180, "vision_call_count": 180,
                         "bounded_fast_mode": {"frame_stride": 3, "max_frames": 0},
                     })
    ok = True
    if dec.get("_returncode"):
        print(f"  FAIL: choose exited {dec['_returncode']}: {dec.get('_stderr')}")
        return False
    chosen = dec.get("chosen")
    print(f"[choose partial OCR] chosen={chosen} reason={dec.get('reason')} partial={dec.get('ocr_partial')} timed_out={dec.get('ocr_timed_out')}")
    if chosen != "ocr":
        print(f"  FAIL: partial OCR đủ chất lượng phải được chọn, got {chosen}")
        ok = False
    if not dec.get("ocr_partial"):
        print("  FAIL: consistency report không có ocr_partial=true")
        ok = False
    if not dec.get("ocr_timed_out"):
        print("  FAIL: consistency report không có ocr_timed_out=true")
        ok = False
    if dec.get("text_source") != "ocr":
        print(f"  FAIL: decision.text_source={dec.get('text_source')} (need ocr)")
        ok = False
    if dec.get("display_subtitle_timing") != "ocr":
        print(f"  FAIL: display_subtitle_timing={dec.get('display_subtitle_timing')} (need ocr)")
        ok = False
    if dec.get("speech_timing_source") not in ("tts_natural", "asr"):
        print(f"  FAIL: speech_timing_source={dec.get('speech_timing_source')} (need tts_natural/asr)")
        ok = False
    if ok:
        print("  OK: OCR timeout_partial đủ chất lượng được chọn, không bị reject")
    return ok


def test_run_sh_bounded_fast_mode_and_flock():
    """Regression: run.sh có bounded fast mode env vars, exclusive flock khi cùng model, không
    overwrite partial report thành JSON nghèo khi timeout."""
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    ok = True
    print("[run.sh bounded fast mode] checking config + OCR block")
    for var in ("OCR_TRANSCRIPT_FRAME_STRIDE", "OCR_TRANSCRIPT_MAX_FRAMES",
                "OCR_TRANSCRIPT_VISION_TIMEOUT_SECONDS", "OCR_TRANSCRIPT_TOTAL_TIMEOUT_SECONDS",
                "OCR_TRANSCRIPT_DISABLE_PADDLE_FALLBACK"):
        if var not in run_sh:
            print(f"  FAIL: thiếu env var {var} trong run.sh")
            ok = False
    # Exclusive nonblocking flock khi cùng model: shared lock (-s) vẫn cho nhiều job cùng chạy vision,
    # còn blocking trực tiếp dễ làm dashboard tưởng job treo vì heartbeat không cập nhật.
    if "flock -x -n 9" not in run_sh or "OCR_VISION_MODEL" not in run_sh or "NINEROUTER_MODEL" not in run_sh:
        print("  FAIL: thiếu exclusive nonblocking flock khi OCR_VISION_MODEL == NINEROUTER_MODEL")
        ok = False
    if "Đợi model vision rảnh" not in run_sh or "VisionModelBusy" not in run_sh:
        print("  FAIL: thiếu heartbeat/status khi OCR phải đợi model vision")
        ok = False
    if "flock -s 9" in run_sh:
        print("  FAIL: OCR vision lock vẫn là shared flock (-s), nhiều job vẫn chạy chồng")
        ok = False
    if re.search(r'\bOCR_VISION_API_KEY="\$API_KEY"\s*\\', run_sh):
        print("  FAIL: OCR_VISION_API_KEY còn bị truyền qua argv bằng env KEY=..., dễ lộ qua ps")
        ok = False
    if 'export OCR_VISION_API_KEY="$API_KEY"' not in run_sh:
        print("  FAIL: thiếu export OCR_VISION_API_KEY trước khi gọi OCR python")
        ok = False
    if "trap on_pipeline_exit EXIT" not in run_sh or "Pipeline exited unexpectedly" not in run_sh:
        print("  FAIL: thiếu EXIT trap finalize stale running status khi pipeline chết bất thường")
        ok = False
    if '"$current_state" == "running"' not in run_sh or '"$current_state" == "queued"' not in run_sh:
        print("  FAIL: EXIT trap không kiểm state trước khi ghi PipelineError")
        ok = False
    # Không overwrite partial report mù — phải check report rỗng trước khi ghi error nghèo.
    if "shell_timeout_or_crash" not in run_sh:
        print("  FAIL: thiếu timeout_reason rõ khi shell kill/crash")
        ok = False
    # Guard: chỉ ghi error nghèo khi report rỗng/thiếu (không đè partial report đầy đủ).
    if "if [[ ! -s \"$OCR_TRANSCRIPT_REPORT_JSON\" ]] || ! python3 -c" not in run_sh:
        print("  FAIL: run.sh thiếu guard kiểm report rỗng trước khi overwrite error nghèo")
        ok = False
    if ok:
        print("  OK: bounded fast mode env vars + exclusive flock + partial-report guard có mặt")
    return ok


def test_ocr_report_status_names_static():
    """OCR report phải dùng status dễ đọc: ok / timeout_partial / failed."""
    source = OCR_TRANSCRIPT.read_text(encoding="utf-8")
    ok = True
    print("[ocr report status names] checking status vocabulary")
    if '"timeout_partial"' not in source:
        print("  FAIL: OCR report chưa có status timeout_partial")
        ok = False
    if '"failed"' not in source:
        print("  FAIL: OCR report chưa có status failed")
        ok = False
    forbidden = '"partial" if partial else "error"'
    if forbidden in source:
        print("  FAIL: OCR report vẫn dùng status partial/error cũ")
        ok = False
    if ok:
        print("  OK: OCR report dùng ok/timeout_partial/failed")
    return ok


def test_ocr_budget_flag_not_expired_on_start():
    """Regression: bật budget timer không được tự xem là đã hết giờ ngay lập tức."""
    spec = importlib.util.spec_from_file_location("ocr_subtitle_transcript_test", OCR_TRANSCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ok = True
    print("[ocr budget] checking timer state")
    module._start_budget(30)
    try:
        if module._budget_expired():
            print("  FAIL: _budget_expired=true ngay sau _start_budget; OCR sẽ dừng trước khi đọc frame")
            ok = False
    finally:
        module._clear_budget()
    if ok:
        print("  OK: budget timer running != expired")
    return ok


def test_ocr_max_frames_zero_means_unlimited():
    """Regression: OCR_TRANSCRIPT_MAX_FRAMES=0 phải là unlimited, không phải stop ở 0 frame."""
    source = OCR_TRANSCRIPT.read_text(encoding="utf-8")
    ok = True
    print("[ocr max_frames] checking zero normalization")
    if "if args.max_frames <= 0:" not in source or "args.max_frames = None" not in source:
        print("  FAIL: max_frames=0 chưa được normalize thành None/unlimited")
        ok = False
    if "processed_frames >= args.max_frames" not in source:
        print("  FAIL: max_frames guard không dựa trên processed_frames")
        ok = False
    if ok:
        print("  OK: max_frames=0 là unlimited và guard dùng processed_frames")
    return ok


def test_vision_model_is_independent_from_text_model():
    """Regression: host-runner text model must never become the OCR vision model."""
    spec = importlib.util.spec_from_file_location("nine_router_vision_test", SKILL_DIR / "nine_router_vision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    managed = ("OCR_VISION_MODEL", "NINEROUTER_VISION_MODEL", "OPENCLAW_VISION_MODEL",
               "NINEROUTER_MODEL", "OPENCLAW_AI_PROVIDER")
    saved = {name: os.environ.get(name) for name in managed}
    try:
        for name in managed:
            os.environ.pop(name, None)
        os.environ["NINEROUTER_MODEL"] = "API deepseek"
        cfg = module.resolve_config()
        if cfg["model"] != "ollama/minimax-m3:cloud":
            print(f"  FAIL: text model leaked into vision config: {cfg['model']!r}")
            return False
        os.environ["OPENCLAW_VISION_MODEL"] = "provider/openclaw-vision"
        if module.resolve_config()["model"] != "provider/openclaw-vision":
            print("  FAIL: OPENCLAW_VISION_MODEL override was ignored")
            return False
        os.environ["NINEROUTER_VISION_MODEL"] = "provider/ninerouter-vision"
        if module.resolve_config()["model"] != "provider/ninerouter-vision":
            print("  FAIL: NINEROUTER_VISION_MODEL did not override OPENCLAW_VISION_MODEL")
            return False
        os.environ["OCR_VISION_MODEL"] = "provider/ocr-vision"
        if module.resolve_config()["model"] != "provider/ocr-vision":
            print("  FAIL: OCR_VISION_MODEL did not take highest precedence")
            return False
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    print("  OK: vision model uses dedicated default and explicit overrides")
    return True


def test_run_sh_keeps_vision_default_independent():
    """The shell must pass the same dedicated default to the OCR subprocess."""
    source = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    expected = 'OCR_VISION_MODEL="${OCR_VISION_MODEL:-${NINEROUTER_VISION_MODEL:-${OPENCLAW_VISION_MODEL:-ollama/minimax-m3:cloud}}}"'
    if expected not in source:
        print("  FAIL: run.sh vision model fallback is missing or can inherit text model")
        return False
    print("  OK: run.sh does not derive OCR vision model from NINEROUTER_MODEL")
    return True


def main():
    ok = True
    print("== srt_quality metrics ==")
    ok = test_srt_quality() and ok
    print("== choose: bad OCR (17 cue) vs ASR (111 cue) -> ASR ==")
    ok = test_choose_bad_ocr_use_asr() and ok
    print("== choose: truncated severe ASR (39 cue/87s) vs usable OCR (82 cue/full) -> OCR ==")
    ok = test_choose_truncated_severe_asr_prefers_usable_ocr() and ok
    print("== choose: good OCR (24 cue) vs ASR (29 cue) -> OCR ==")
    ok = test_choose_good_ocr_not_overrejected() and ok
    print("== choose: sparse clean OCR remains timing anchor for ASR repair ==")
    ok = test_choose_sparse_clean_ocr_keeps_timing_anchor() and ok
    print("== choose: ASR severe + OCR timeout/empty -> failed_qc exit 7 ==")
    ok = test_choose_both_sources_failed_qc() and ok
    print("== choose: ASR severe + OCR good but sparse-vs-ASR -> OCR ==")
    ok = test_choose_severe_asr_does_not_reject_good_ocr_as_sparse() and ok
    print("== choose: ASR repeated loop + clean OCR -> OCR ==")
    ok = test_choose_repeated_asr_loop_prefers_ocr() and ok
    print("== choose: local ASR tail loop + sparse OCR -> OCR, never hybrid ==")
    ok = test_choose_local_asr_tail_loop_uses_ocr_without_hybrid() and ok
    print("== choose: short repeated dialogue false-positive + sparse OCR -> ASR ==")
    ok = test_choose_short_repetition_false_positive_uses_asr() and ok
    print("== ASR postprocess: short repeated dialogue threshold ==")
    ok = test_asr_postprocess_short_repetition_default_static() and ok
    print("== choose: OCR partial (timed_out) đủ chất lượng -> OCR ==")
    ok = test_choose_ocr_partial_accepted_when_quality_ok() and ok
    print("== run.sh regression: resume OCR timeout keeps auto mode ==")
    ok = test_resume_ocr_timeout_keeps_auto_mode() and ok
    print("== run.sh regression: bounded fast mode + flock + partial-report guard ==")
    ok = test_run_sh_bounded_fast_mode_and_flock() and ok
    print("== ocr regression: report status names are explicit ==")
    ok = test_ocr_report_status_names_static() and ok
    print("== ocr regression: budget timer running is not expired ==")
    ok = test_ocr_budget_flag_not_expired_on_start() and ok
    print("== ocr regression: max_frames=0 means unlimited ==")
    ok = test_ocr_max_frames_zero_means_unlimited() and ok
    print("== vision config: text model never leaks into OCR ==")
    ok = test_vision_model_is_independent_from_text_model() and ok
    print("== run.sh vision config: dedicated default ==")
    ok = test_run_sh_keeps_vision_default_independent() and ok
    print("== ASR long-thin repair (job 201915: ASR 94/OCR 65, 3 long-thin) ==")
    ok = test_asr_long_thin_repair() and ok
    print("== ASR repair uses sparse clean OCR timing anchor (job 151342 shape) ==")
    ok = test_asr_repair_uses_sparse_clean_ocr_anchor() and ok
    print("== TX_GATE preserves TranscriptTooSparse status ==")
    ok = test_tx_gate_preserves_transcript_too_sparse_status() and ok
    print("== VI_GATE blocks repeated translation loop ==")
    ok = test_vi_gate_blocks_repeated_translation_loop_static() and ok
    print()
    if ok:
        print("ALL PASS")
        sys.exit(0)
    print("FAIL")
    sys.exit(1)


if __name__ == "__main__":
    main()
