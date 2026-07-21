#!/usr/bin/env python3
"""ASR timing repair: chia long-thin ASR cue theo ranh giới OCR cue chồng lấp.

Fix false-positive TranscriptTooSparse khi choose_transcript_source chọn ASR (vd job
input-20260702-201915: ASR 94 cue có 3 long-thin, OCR 65 cue quality_ok). ASR được chọn
vì bám giọng tốt hơn cho dubbing, nhưng vài ASR cue dài-mỏng (text<12 chars & dur>6s) làm
TX_GATE fail. Thay vì fail, chia các long-thin cue đó theo ranh giới OCR cue chồng lấp
(display timing thật), giữ text ASR, bỏ khoảng im lặng giữa.

Chỉ chạy khi chosen=asr & !severe_asr & ocr_timing_anchor_usable. OCR có thể quá
thưa để làm transcript chính nhưng vẫn sạch để làm mốc sửa timing ASR. Nếu repair
được một phần và phần còn lại nằm trong ngưỡng nhỏ thì ghi output status=partial_ok;
nếu không giảm đủ long_thin -> exit 9 (incomplete), để TX_GATE xử lý.

Importable cho test (repair_asr_with_ocr). Exit codes: 0 (ok/no-op), 9 (incomplete).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path


def _to_ms(t):
    hh, mm, rest = t.split(":")
    ss, mmm = rest.split(",")
    return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000 + int(mmm)


def _fmt_ms(ms):
    ms = max(0, int(ms))
    hh, rem = divmod(ms, 3600000)
    mm, rem = divmod(rem, 60000)
    ss, mmm = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{mmm:03d}"


def parse_srt(path):
    """Trả list of dict {start_ms, end_ms, text}."""
    p = Path(path)
    if not p.exists():
        return []
    content = p.read_text(encoding="utf-8", errors="replace").strip()
    out = []
    if not content:
        return out
    for block in re.split(r"\n\s*\n", content):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        try:
            a, b = [x.strip() for x in lines[1].split("-->", 1)]
            out.append({"start_ms": _to_ms(a), "end_ms": _to_ms(b),
                        "text": " ".join(lines[2:]).strip()})
        except Exception:
            continue
    return out


def write_srt(path, cues):
    """cues: list of {start_ms, end_ms, text}."""
    parts = []
    for i, c in enumerate(cues, 1):
        parts.append(str(i))
        parts.append(f"{_fmt_ms(c['start_ms'])} --> {_fmt_ms(c['end_ms'])}")
        parts.append(c.get("text", ""))
        parts.append("")
    Path(path).write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")


def _compact_chars(text):
    return len(re.sub(r"\s+", "", text or ""))


def long_thin_indexes(cues, min_chars, max_thin_s):
    """Index của cue long-thin (text<min_chars & dur>max_thin_s)."""
    out = []
    for i, c in enumerate(cues):
        dur_s = (c["end_ms"] - c["start_ms"]) / 1000.0
        if _compact_chars(c.get("text", "")) < min_chars and dur_s > max_thin_s:
            out.append(i)
    return out


def _overlaps(asr_cue, ocr_cue):
    s = max(asr_cue["start_ms"], ocr_cue["start_ms"])
    e = min(asr_cue["end_ms"], ocr_cue["end_ms"])
    if e - s > 0:
        return s, e
    return None


def repair_asr_with_ocr(asr_cues, ocr_cues, min_chars, max_thin_s):
    """Chia mỗi long-thin ASR cue thành các sub-cue = vùng chồng lấp với OCR cue.
    Giữ text ASR. Cue không long-thin hoặc không có OCR chồng -> giữ nguyên.
    Trả (repaired_cues, report_dict)."""
    long_thin_idx = long_thin_indexes(asr_cues, min_chars, max_thin_s)
    repaired_cues = []
    repaired_count = 0
    unrepaired_long_thin = 0
    sub_splits = []
    for i, cue in enumerate(asr_cues):
        if i not in long_thin_idx:
            repaired_cues.append(dict(cue))
            continue
        # Tìm tất cả OCR cue chồng lấp, sắp xếp theo start.
        segs = []
        for oc in ocr_cues:
            ov = _overlaps(cue, oc)
            if ov:
                segs.append(ov)
        if not segs:
            # Không có OCR chồng -> giữ nguyên (không repair được).
            repaired_cues.append(dict(cue))
            unrepaired_long_thin += 1
            continue
        segs.sort()
        # Gộp các vùng chồng liên tiếp/trùng.
        merged = [list(segs[0])]
        for s, e in segs[1:]:
            if s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        # Giới hạn sub-cue trong [cue.start, cue.end] và bỏ vùng quá ngắn (<200ms).
        subs = []
        for s, e in merged:
            s = max(s, cue["start_ms"])
            e = min(e, cue["end_ms"])
            if e - s >= 200:
                subs.append({"start_ms": s, "end_ms": e, "text": cue.get("text", "")})
        if subs:
            repaired_cues.extend(subs)
            repaired_count += 1
            sub_splits.append({"cue_index": i, "sub_cues": len(subs)})
        else:
            repaired_cues.append(dict(cue))
            unrepaired_long_thin += 1
    remaining = long_thin_indexes(repaired_cues, min_chars, max_thin_s)
    report = {
        "original_cue_count": len(asr_cues),
        "ocr_cue_count": len(ocr_cues),
        "long_thin_before": len(long_thin_idx),
        "repaired_cues": repaired_count,
        "unrepaired_long_thin": unrepaired_long_thin,
        "remaining_long_thin": len(remaining),
        "sub_splits": sub_splits,
        "repaired_cue_count": len(repaired_cues),
        "status": "ok" if len(remaining) == 0 else "incomplete",
    }
    return repaired_cues, report


def _load_decision(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--asr-srt", required=True)
    parser.add_argument("--ocr-srt", required=True)
    parser.add_argument("--decision-json", required=True)
    parser.add_argument("--output-srt", required=True, help="ghi lại SRT repaired (thường = asr-srt)")
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--max-thin-seconds", type=float, default=float(os.environ.get("VI_GATE_MAX_THIN_SECONDS", "6")))
    parser.add_argument("--min-text-chars", type=int, default=int(float(os.environ.get("VI_GATE_MIN_TEXT_CHARS", "12"))))
    parser.add_argument("--max-remaining-long-thin", type=int, default=int(os.environ.get("TX_REPAIR_MAX_REMAINING_LONG_THIN", "0")))
    args = parser.parse_args()

    dec = _load_decision(args.decision_json)
    chosen = dec.get("chosen") or ""
    severe_asr = bool(dec.get("severe_asr"))
    ocr_quality_ok = bool(dec.get("ocr_quality_ok"))
    ocr_transcript_usable = bool(dec.get("ocr_transcript_usable", ocr_quality_ok))
    ocr_timing_anchor_usable = bool(dec.get("ocr_timing_anchor_usable", ocr_quality_ok))
    asr_quality = dec.get("asr_quality") or {}
    asr_long_thin = int((asr_quality.get("long_thin_cues") or 0))

    # Chỉ repair khi chosen=asr & !severe & OCR anchor usable & có long-thin.
    if chosen != "asr" or severe_asr or not ocr_timing_anchor_usable or asr_long_thin == 0:
        report = {"skipped": True, "chosen": chosen, "severe_asr": severe_asr,
                   "ocr_quality_ok": ocr_quality_ok,
                   "ocr_transcript_usable": ocr_transcript_usable,
                   "ocr_timing_anchor_usable": ocr_timing_anchor_usable,
                   "asr_long_thin": asr_long_thin,
                   "repaired": 0, "remaining_long_thin": 0, "status": "skipped",
                   "reason": "not asr / severe / ocr anchor not usable / no long-thin"}
        Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"TX_REPAIR_SKIP: chosen={chosen} severe={severe_asr} "
              f"ocr_anchor={ocr_timing_anchor_usable} asr_long_thin={asr_long_thin}")
        return 0

    asr_cues = parse_srt(args.asr_srt)
    ocr_cues = parse_srt(args.ocr_srt)
    if not asr_cues:
        report = {"skipped": True, "reason": "asr-srt empty", "repaired": 0,
                  "remaining_long_thin": 0, "status": "skipped"}
        Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("TX_REPAIR_SKIP: asr-srt empty")
        return 0

    max_thin = float(args.max_thin_seconds)
    min_chars = int(args.min_text_chars)
    repaired_cues, report = repair_asr_with_ocr(asr_cues, ocr_cues, min_chars, max_thin)

    report["ocr_quality_ok"] = ocr_quality_ok
    report["ocr_transcript_usable"] = ocr_transcript_usable
    report["ocr_timing_anchor_usable"] = ocr_timing_anchor_usable

    # Ghi output khi repair hết long-thin, hoặc repair được một phần và số còn lại
    # nằm trong ngưỡng gate cho ASR usable. Không ghi nếu không sửa được cue nào.
    remaining = int(report["remaining_long_thin"])
    repaired_count = int(report["repaired_cues"])
    ok = remaining == 0
    partial_ok = (not ok) and repaired_count > 0 and remaining <= args.max_remaining_long_thin
    if ok or partial_ok:
        write_srt(args.output_srt, repaired_cues)
        report["status"] = "ok" if ok else "partial_ok"
        report["output_srt"] = args.output_srt
    else:
        report["status"] = "incomplete"
        # KHÔNG ghi đè asr-srt; để TX_GATE fail trên bản gốc.
    Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"TX_REPAIR_{'OK' if ok else 'PARTIAL_OK' if partial_ok else 'INCOMPLETE'}: repaired={report['repaired_cues']} "
          f"long_thin_before={report['long_thin_before']} remaining={report['remaining_long_thin']} "
          f"unrepaired={report['unrepaired_long_thin']}")
    return 0 if (ok or partial_ok) else 9


if __name__ == "__main__":
    sys.exit(main())
