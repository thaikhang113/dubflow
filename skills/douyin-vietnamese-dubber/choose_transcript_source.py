#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path


def parse_srt(path):
    entries = []
    if not Path(path).exists():
        return entries
    text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return entries
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            entries.append({"time": lines[1], "text": " ".join(lines[2:]).strip()})
    return entries


def _parse_time_ms(time_str):
    """Chuyển 'HH:MM:SS,mmm' -> ms. Trả (start_ms, end_ms) từ 'a --> b'."""
    def to_ms(t):
        hh, mm, rest = t.split(":")
        ss, mmm = rest.split(",")
        return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000 + int(mmm)
    a, b = [p.strip() for p in time_str.split("-->", 1)]
    return to_ms(a), to_ms(b)


def _format_time_ms(ms):
    ms = max(0, int(round(ms)))
    hh, rem = divmod(ms, 3600000)
    mm, rem = divmod(rem, 60000)
    ss, mmm = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{mmm:03d}"


def _entry_bounds(entry):
    if "start_ms" in entry and "end_ms" in entry:
        return int(entry["start_ms"]), int(entry["end_ms"])
    return _parse_time_ms(entry["time"])


def _compact_text(text):
    return re.sub(r"\s+", "", text or "")


def write_srt(path, entries):
    out = []
    for idx, entry in enumerate(entries, 1):
        try:
            start_ms, end_ms = _entry_bounds(entry)
        except Exception:
            continue
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        out.append(str(idx))
        out.append(f"{_format_time_ms(start_ms)} --> {_format_time_ms(end_ms)}")
        out.append(text)
        out.append("")
    Path(path).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def repeat_run_spans(entries, min_consecutive):
    """Find consecutive repeated text runs in an SRT entry list."""
    spans = []
    last_text = None
    run_start = 0
    run_count = 0

    def finish(end_index):
        if run_count < min_consecutive or not last_text:
            return
        run_entries = entries[run_start:end_index]
        try:
            start_ms = min(_entry_bounds(e)[0] for e in run_entries)
            end_ms = max(_entry_bounds(e)[1] for e in run_entries)
        except Exception:
            start_ms = 0
            end_ms = 0
        spans.append({
            "start_index": run_start,
            "end_index": end_index,
            "count": run_count,
            "text": last_text,
            "start_ms": start_ms,
            "end_ms": end_ms,
        })

    for idx, entry in enumerate(entries):
        compact = _compact_text(entry.get("text", ""))
        if not compact:
            finish(idx)
            last_text = None
            run_start = idx + 1
            run_count = 0
            continue
        if compact == last_text:
            run_count += 1
        else:
            finish(idx)
            last_text = compact
            run_start = idx
            run_count = 1
    finish(len(entries))
    return spans


def srt_quality(entries, video_duration=0.0, min_text_chars=12, max_thin_seconds=6.0, max_cue_seconds=15.0):
    """Quality metrics cho một SRT transcript.

    Phát hiện OCR/ASR thưa + cue dài bất thường (text ngắn nhưng kéo dài).
    Trả dict: cue_count, max_cue_seconds, long_thin_cues, cue_density_per_min,
              avg_text_chars, total_text_chars.
    """
    cue_count = len(entries)
    max_cue = 0.0
    long_thin = 0
    total_chars = 0
    last_end_ms = 0
    for e in entries:
        try:
            s_ms, e_ms = _parse_time_ms(e["time"])
        except Exception:
            continue
        dur = (e_ms - s_ms) / 1000.0
        if dur > max_cue:
            max_cue = dur
        compact = _compact_text(e.get("text", ""))
        total_chars += len(compact)
        if e_ms > last_end_ms:
            last_end_ms = e_ms
        if len(compact) < min_text_chars and dur > max_thin_seconds:
            long_thin += 1
    dur_s = float(video_duration) if video_duration else (last_end_ms / 1000.0)
    density = cue_count / (dur_s / 60.0) if dur_s > 0 else 0.0
    avg_chars = (total_chars / cue_count) if cue_count else 0
    timeline_coverage = (last_end_ms / 1000.0 / dur_s) if dur_s > 0 else 0.0
    return {
        "cue_count": cue_count,
        "max_cue_seconds": round(max_cue, 3),
        "long_thin_cues": long_thin,
        "cue_density_per_min": round(density, 3),
        "avg_text_chars": round(avg_chars, 3),
        "total_text_chars": total_chars,
        "video_duration": round(dur_s, 3),
        "last_end_seconds": round(last_end_ms / 1000.0, 3),
        "timeline_coverage_ratio": round(timeline_coverage, 3),
    }


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def repeated_text_score(entries):
    counts = {}
    short_total = 0
    total = 0
    last = None
    current_run = 0
    max_run = 0
    max_run_text = ""
    for entry in entries:
        compact = _compact_text(entry.get("text", ""))
        if not compact:
            continue
        total += 1
        counts[compact] = counts.get(compact, 0) + 1
        if compact == last:
            current_run += 1
        else:
            if current_run > max_run:
                max_run = current_run
                max_run_text = last or ""
            last = compact
            current_run = 1
        if len(compact) <= 8:
            short_total += 1
    if current_run > max_run:
        max_run = current_run
        max_run_text = last or ""
    top_count = max(counts.values()) if counts else 0
    top_ratio = top_count / total if total else 0.0
    max_run_ratio = max_run / total if total else 0.0
    return {
        "total": total,
        "short_total": short_total,
        "top_count": top_count,
        "top_ratio": round(top_ratio, 4),
        "max_consecutive_count": max_run,
        "max_consecutive_ratio": round(max_run_ratio, 4),
        "max_consecutive_text_len": len(max_run_text),
        "top_texts": sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("auto", "ocr", "asr"), required=True)
    parser.add_argument("--asr-srt", required=True)
    parser.add_argument("--ocr-srt", required=True)
    parser.add_argument("--output-srt", required=True)
    parser.add_argument("--asr-report", required=True)
    parser.add_argument("--ocr-report", required=True)
    parser.add_argument("--decision-json", required=True)
    parser.add_argument("--consistency-json", required=True)
    parser.add_argument("--min-ocr-segments", type=int, default=8)
    parser.add_argument("--min-ocr-coverage", type=float, default=0.10)
    parser.add_argument("--ocr-quality-min-text-chars", type=int, default=int(os.environ.get("CHOOSE_OCR_QUALITY_MIN_TEXT_CHARS", "12")))
    parser.add_argument("--ocr-quality-max-thin-seconds", type=float, default=float(os.environ.get("CHOOSE_OCR_QUALITY_MAX_THIN_SECONDS", "6")))
    parser.add_argument("--ocr-quality-max-cue-seconds", type=float, default=float(os.environ.get("CHOOSE_OCR_QUALITY_MAX_CUE_SECONDS", "15")))
    parser.add_argument("--ocr-sparse-ratio", type=float, default=float(os.environ.get("CHOOSE_OCR_SPARSE_RATIO", "0.5")))
    parser.add_argument("--dub-favor-asr-ratio", type=float, default=float(os.environ.get("CHOOSE_DUB_FAVOR_ASR_RATIO", "1.25")))
    parser.add_argument("--min-cues-per-min", type=float, default=float(os.environ.get("CHOOSE_MIN_CUES_PER_MIN", "4")))
    parser.add_argument("--max-long-thin-ratio", type=float, default=float(os.environ.get("CHOOSE_MAX_LONG_THIN_RATIO", "0.08")))
    parser.add_argument("--asr-min-timeline-coverage", type=float, default=float(os.environ.get("CHOOSE_ASR_MIN_TIMELINE_COVERAGE", "0.65")))
    parser.add_argument("--asr-repeat-max-consecutive", type=int, default=int(os.environ.get("CHOOSE_ASR_REPEAT_MAX_CONSECUTIVE", "12")))
    parser.add_argument("--asr-repeat-min-top-count", type=int, default=int(os.environ.get("CHOOSE_ASR_REPEAT_MIN_TOP_COUNT", "20")))
    parser.add_argument("--asr-repeat-max-top-ratio", type=float, default=float(os.environ.get("CHOOSE_ASR_REPEAT_MAX_TOP_RATIO", "0.25")))
    parser.add_argument("--asr-repeat-local-max-run-ratio", type=float, default=float(os.environ.get("CHOOSE_ASR_REPEAT_LOCAL_MAX_RUN_RATIO", "0.35")))
    args = parser.parse_args()

    asr_entries = parse_srt(args.asr_srt)
    ocr_entries = parse_srt(args.ocr_srt)
    asr_report = load_json(args.asr_report, {})
    ocr_report = load_json(args.ocr_report, {})
    hallucination = asr_report.get("hallucination", {}) if isinstance(asr_report, dict) else {}
    asr_repeat = repeated_text_score(asr_entries)
    ocr_coverage = float(ocr_report.get("coverage_ratio") or 0.0)
    ocr_avg_conf = float(ocr_report.get("avg_confidence") or 0.0)
    # OCR producer quality is evidence about extraction; it is deliberately not
    # the same decision as whether OCR is usable as the canonical transcript.
    ocr_extraction_quality_ok = bool(ocr_report.get("quality_ok", False))
    ocr_observation_usable = len(ocr_entries) >= args.min_ocr_segments and ocr_coverage >= args.min_ocr_coverage and ocr_avg_conf >= 0.45
    reported_severe_asr = bool(hallucination.get("severe"))
    asr_repeat_loop_severe = (
        asr_repeat["max_consecutive_count"] >= args.asr_repeat_max_consecutive
        or (
            asr_repeat["top_count"] >= args.asr_repeat_min_top_count
            and asr_repeat["top_ratio"] >= args.asr_repeat_max_top_ratio
        )
    )
    asr_repeat_runs = repeat_run_spans(asr_entries, args.asr_repeat_max_consecutive)
    severe_asr_before_relax = reported_severe_asr or asr_repeat_loop_severe

    # Quality metrics (bắt OCR thưa / cue dài bất thường).
    video_duration = float(ocr_report.get("video_duration") or asr_report.get("video_duration") or 0.0)
    ocr_quality = srt_quality(
        ocr_entries, video_duration=video_duration,
        min_text_chars=args.ocr_quality_min_text_chars,
        max_thin_seconds=args.ocr_quality_max_thin_seconds,
        max_cue_seconds=args.ocr_quality_max_cue_seconds,
    )
    asr_quality = srt_quality(
        asr_entries, video_duration=video_duration,
        min_text_chars=args.ocr_quality_min_text_chars,
        max_thin_seconds=args.ocr_quality_max_thin_seconds,
        max_cue_seconds=args.ocr_quality_max_cue_seconds,
    )
    ocr_anchor_reject_reasons = []
    ocr_warnings = []
    if not ocr_extraction_quality_ok:
        ocr_warnings.append("ocr_report_quality_ok_false")
    long_thin_ratio = ocr_quality["long_thin_cues"] / max(1, ocr_quality["cue_count"])
    if long_thin_ratio > args.max_long_thin_ratio:
        ocr_anchor_reject_reasons.append(
            f"ocr_long_thin_ratio={long_thin_ratio:.3f}>{args.max_long_thin_ratio}"
        )
    if ocr_quality["max_cue_seconds"] > args.ocr_quality_max_cue_seconds:
        ocr_anchor_reject_reasons.append(f"ocr_max_cue_too_long={ocr_quality['max_cue_seconds']}s")
    if ocr_quality["cue_density_per_min"] < args.min_cues_per_min:
        ocr_anchor_reject_reasons.append(f"ocr_density_too_low={ocr_quality['cue_density_per_min']}/min")
    if not ocr_observation_usable:
        ocr_anchor_reject_reasons.append("ocr_insufficient_coverage_or_conf")
    # "Usable as a transcript" and "usable as timing anchors" are intentionally
    # separate. Sparse OCR can be too thin to replace ASR text, but still clean
    # enough to split/repair a few long ASR timing spans.
    ocr_timing_anchor_usable = ocr_observation_usable and not ocr_anchor_reject_reasons
    ocr_transcript_reject_reasons = list(ocr_anchor_reject_reasons)
    # OCR quá thưa so với ASR (case OCR 17 / ASR 111 -> ratio 0.15).
    ocr_too_sparse = bool(asr_entries) and (
        ocr_quality["cue_count"] / max(1, asr_quality["cue_count"]) < args.ocr_sparse_ratio
    )
    asr_timeline_ok = True
    if video_duration >= 60.0 and asr_entries:
        asr_timeline_ok = asr_quality["timeline_coverage_ratio"] >= args.asr_min_timeline_coverage

    reported_bursts = hallucination.get("bursts") if isinstance(hallucination, dict) else []
    reported_burst_segments = int(hallucination.get("dropped_burst_segments") or 0)
    asr_much_richer_than_ocr = (
        asr_quality["cue_count"] / max(1, ocr_quality["cue_count"]) >= args.dub_favor_asr_ratio
        and asr_quality["total_text_chars"] > ocr_quality["total_text_chars"] * 1.2
        and asr_quality["cue_density_per_min"] >= args.min_cues_per_min
    )
    burst_only_reported_severe = (
        reported_severe_asr
        and bool(reported_bursts)
        and reported_burst_segments > 0
        and reported_burst_segments < args.asr_repeat_max_consecutive
        and not asr_repeat_loop_severe
    )
    asr_burst_severe_relaxed = (
        burst_only_reported_severe
        and asr_timeline_ok
        and ocr_too_sparse
        and asr_much_richer_than_ocr
    )
    severe_asr = severe_asr_before_relax and not asr_burst_severe_relaxed
    if asr_burst_severe_relaxed:
        ocr_warnings.append(
            "asr_burst_severe_relaxed_due_to_good_asr_sparse_ocr="
            f"burst_dropped={reported_burst_segments},asr_cues={asr_quality['cue_count']},"
            f"ocr_cues={ocr_quality['cue_count']}"
        )
    if ocr_too_sparse:
        sparse_reason = f"ocr_too_sparse_vs_asr={ocr_quality['cue_count']}/{max(1, asr_quality['cue_count'])}"
        if severe_asr:
            # ASR severe/hallucinated can inflate cue count with repeated junk, so its
            # segment count is not a trustworthy baseline for rejecting otherwise good OCR.
            ocr_warnings.append(f"{sparse_reason}_ignored_due_to_severe_asr")
        else:
            ocr_transcript_reject_reasons.append(sparse_reason)
    ocr_transcript_usable = ocr_observation_usable and not ocr_transcript_reject_reasons
    # Backward-compatible alias used by run.sh/dashboard/tests before the split.
    ocr_quality_ok = ocr_transcript_usable

    # Dub-timing rule: OCR timing là thời gian subtitle Trung hiển thị, KHÔNG phải
    # speech/mouth timing. Khi ASR có rõ rệt nhiều cue hơn (vd OCR 65 / ASR 94 = 0.69)
    # và ASR không severe, dùng ASR làm master cho cả dub lẫn display để lồng tiếng
    # khớp giọng gốc thay vì kéo TTS theo OCR display (gây padding im lặng lớn).
    asr_better_for_dub = (
        bool(asr_entries)
        and not severe_asr
        and asr_timeline_ok
        and ocr_quality["cue_count"] > 0
        and (asr_quality["cue_count"] / ocr_quality["cue_count"]) >= args.dub_favor_asr_ratio
    )
    asr_repeat_loop_local = (
        bool(asr_repeat_runs)
        and asr_repeat_loop_severe
        and asr_timeline_ok
        and asr_repeat["max_consecutive_ratio"] <= args.asr_repeat_local_max_run_ratio
    )
    transcript_hybrid_report = {
        "used": False,
        "usable": False,
        "reason": "disabled_transcript_sources_must_remain_separate",
        "local_loop": asr_repeat_loop_local,
        "max_local_run_ratio": args.asr_repeat_local_max_run_ratio,
        "candidate_repeat_runs": asr_repeat_runs,
        "removed_repeat_segments": 0,
        "ocr_fill_cues": 0,
        "hybrid_cue_count": 0,
        "hybrid_quality": {},
    }
    consistency = {
        "asr_segments": len(asr_entries),
        "ocr_segments": len(ocr_entries),
        "asr_repeat": asr_repeat,
        "reported_severe_asr": reported_severe_asr,
        "severe_asr_before_relax": severe_asr_before_relax,
        "asr_burst_severe_relaxed": asr_burst_severe_relaxed,
        "asr_reported_burst_segments": reported_burst_segments,
        "asr_repeat_loop_severe": asr_repeat_loop_severe,
        "asr_repeat_loop_local": asr_repeat_loop_local,
        "asr_repeat_loop_runs": asr_repeat_runs,
        "ocr_coverage_ratio": ocr_coverage,
        "ocr_avg_confidence": ocr_avg_conf,
        "ocr_extraction_quality_ok": ocr_extraction_quality_ok,
        "ocr_observation_usable": ocr_observation_usable,
        "ocr_ok": ocr_observation_usable,
        "ocr_transcript_usable": ocr_transcript_usable,
        "ocr_timing_anchor_usable": ocr_timing_anchor_usable,
        # Legacy alias: it means transcript usability, not OCR extraction quality.
        "ocr_quality_ok": ocr_quality_ok,
        "ocr_roles": {
            "extraction_quality_ok": ocr_extraction_quality_ok,
            "transcript_usable": ocr_transcript_usable,
            "timing_anchor_usable": ocr_timing_anchor_usable,
        },
        "ocr_too_sparse": ocr_too_sparse,
        "ocr_reject_reasons": ocr_transcript_reject_reasons,
        "ocr_transcript_reject_reasons": ocr_transcript_reject_reasons,
        "ocr_timing_anchor_reject_reasons": ocr_anchor_reject_reasons,
        "ocr_warnings": ocr_warnings,
        "ocr_quality": ocr_quality,
        "asr_quality": asr_quality,
        "severe_asr": severe_asr,
        "asr_timeline_ok": asr_timeline_ok,
        "asr_better_for_dub": asr_better_for_dub,
        "transcript_hybrid_used": bool(transcript_hybrid_report.get("used")),
        "transcript_hybrid_usable": bool(transcript_hybrid_report.get("usable")),
        "transcript_hybrid_report": transcript_hybrid_report,
        "ocr_partial": bool(ocr_report.get("partial")) if isinstance(ocr_report, dict) else False,
        "ocr_timed_out": bool(ocr_report.get("timed_out")) if isinstance(ocr_report, dict) else False,
        "ocr_timeout_reason": (ocr_report.get("timeout_reason") if isinstance(ocr_report, dict) else "") or "",
    }

    def write_decision(status, chosen_value, reason_value, error_code="", error_message=""):
        text_source = chosen_value if chosen_value else ""
        if not chosen_value:
            display_timing_source = ""
            speech_timing_source = ""
        elif asr_better_for_dub:
            display_timing_source = "asr"
            speech_timing_source = "asr"
        elif chosen_value == "asr":
            display_timing_source = "asr"
            speech_timing_source = "asr" if asr_timeline_ok and not severe_asr else "tts_natural"
        else:
            display_timing_source = "ocr"
            speech_timing_source = "tts_natural"
        decision = {
            "mode": args.mode,
            "chosen": chosen_value,
            "reason": reason_value,
            "status": status,
            **consistency,
            # Tách 2 timeline: display (phụ đề Việt hiển thị) và dub (TTS lồng tiếng).
            # Khi chọn ASR vì ASR bám giọng tốt hơn, cả 2 đều theo ASR timing.
            # Khi chọn OCR, display dùng OCR/blur-band timing; speech_timing_source
            # là tts_natural để TTS không bị kéo chậm theo OCR display slot quá dài.
            "text_source": text_source,
            "display_subtitle_timing": display_timing_source,
            "speech_timing_source": speech_timing_source,
            "dub_tts_timing": ("asr" if asr_better_for_dub else chosen_value) if chosen_value else "",
        }
        if error_code:
            decision["error_code"] = error_code
        if error_message:
            decision["error_message"] = error_message
        Path(args.consistency_json).write_text(
            json.dumps(consistency, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        Path(args.decision_json).write_text(
            json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return decision

    if args.mode == "ocr":
        chosen = "ocr"
        reason = "forced_ocr"
    elif args.mode == "asr":
        chosen = "asr"
        reason = "forced_asr"
    elif severe_asr and ocr_quality_ok:
        chosen = "ocr"
        reason = "asr_severe_and_ocr_quality_ok"
    elif asr_better_for_dub:
        # ASR nhiều cue hơn OCR rõ rệt -> ASR bám giọng tốt hơn cho dubbing.
        # OCR vẫn đủ chất lượng để hỗ trợ text/blur/subtitle display, nhưng KHÔNG làm
        # timing master cho TTS khi mục tiêu là lồng tiếng khớp miệng.
        chosen = "asr"
        reason = "asr_better_for_dub_timing"
    elif ocr_quality_ok and not ocr_too_sparse:
        chosen = "ocr"
        reason = "ocr_quality_ok"
    elif ocr_quality_ok and ocr_too_sparse and asr_entries:
        # OCR đủ chất lượng nhưng quá thưa so với ASR -> dùng ASR.
        chosen = "asr"
        reason = "ocr_too_sparse_use_asr"
    elif not ocr_quality_ok and asr_entries and not severe_asr and asr_timeline_ok:
        # OCR có cue dài bất thường / thưa -> ASR (case chính của fix này).
        chosen = "asr"
        reason = "ocr_quality_failed_use_asr"
    elif not asr_entries and ocr_entries and ocr_quality_ok:
        chosen = "ocr"
        reason = "asr_empty_ocr_available"
    elif severe_asr and not ocr_quality_ok and asr_entries:
        # Cả hai xấu: vẫn chọn ASR postprocessed với warning, không render output lỗi.
        chosen = "asr"
        reason = "asr_severe_but_ocr_also_bad_use_asr_with_warning"
    else:
        chosen = "asr"
        reason = "ocr_insufficient_or_asr_ok"

    if (
        args.mode == "auto"
        and chosen == "asr"
        and asr_entries
        and (severe_asr or not asr_timeline_ok)
    ):
        if ocr_quality_ok:
            chosen = "ocr"
            reason = "asr_failed_qc_use_ocr"
        else:
            msg = (
                "Transcript sources failed QC: ASR severe/truncated "
                f"(severe={severe_asr}, timeline_ok={asr_timeline_ok}, "
                f"coverage={asr_quality['timeline_coverage_ratio']}) and OCR rejected "
                f"({', '.join(ocr_transcript_reject_reasons) or 'unknown'})."
            )
            write_decision(
                "failed_qc",
                "",
                "both_sources_failed_qc",
                "TranscriptSourcesFailedQC",
                msg,
            )
            print(msg, file=sys.stderr, flush=True)
            raise SystemExit(7)

    source = Path(args.ocr_srt if chosen == "ocr" else args.asr_srt)
    if not source.exists() or source.stat().st_size == 0:
        raise SystemExit(f"chosen transcript missing/empty: {source}")
    if severe_asr and chosen == "asr" and args.mode == "auto" and not asr_entries:
        raise SystemExit("ASR transcript flagged severe hallucination and empty; OCR also bad; refusing to continue with no transcript")
    # The selected transcript is a byte-for-byte copy of exactly one immutable
    # source. Never combine OCR text into ASR text here.
    shutil.copy2(source, args.output_srt)
    write_decision("ok", chosen, reason)
    print(f"transcript_source={chosen} reason={reason} asr_segments={len(asr_entries)} ocr_segments={len(ocr_entries)} ocr_quality_ok={ocr_quality_ok} asr_better_for_dub={asr_better_for_dub}", flush=True)


if __name__ == "__main__":
    main()
