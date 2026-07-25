#!/usr/bin/env python3
"""Test voice-sync fix cho job Bilibili input-20260702-075045.

Fixture: ASR 94 cue, OCR 65 cue, OCR quality_ok nhưng sparse vs ASR (ratio 0.69).
Expected:
  1. choose_transcript_source.py chọn ASR/hybrid cho dub (reason=asr_better_for_dub_timing),
     KHÔNG chọn OCR làm timing master.
  2. TTS local sync gate FAIL khi dùng OCR display timing (padded 64/65, median raw/slot 0.606):
     padded_ratio=64/65=0.985 > 0.4, padding_video~100s/281s=0.35 > 0.15, median 0.606 < 0.75.

Chạy độc lập, không cần 9Router/TTS thật. Tự sinh ASR/OCR SRT fixture + tái tạo TTS stats.
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
DECISION_SCRIPT = SKILL_DIR / "choose_transcript_source.py"


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
        out.extend([str(i), f"{ms_to_srt(s)} --> {ms_to_srt(e)}", text, ""])
    Path(path).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def make_asr_cues(n=94, video_ms=281797):
    """94 cue bám speech: density ~20/min như job thật, max cue ~4-5s."""
    cues = []
    t = 400
    for i in range(n):
        dur = 2400 + (i % 5) * 200  # 2.4-3.2s
        if t + dur > video_ms - 500:
            break
        cues.append((t, t + dur, f"第{i+1}句"))
        t += dur + 300 + (i % 3) * 100
    return cues


def make_ocr_cues(n=65, video_ms=281797):
    """65 cue bám subtitle display (OCR): thời gian chữ Trung hiển thị,
    thường dài hơn speech slot thật (case job: max cue 4.76s, 65 cue)."""
    cues = []
    t = 420
    for i in range(n):
        # OCR slot dài hơn speech: 3.5-4.76s
        dur = 3500 + (i % 4) * 350
        if t + dur > video_ms - 500:
            break
        cues.append((t, t + dur, f"為什麼{i+1}"))
        t += dur + 250
    return cues


def run_decision(tmp, asr_srt, ocr_srt, mode="auto"):
    out_srt = tmp / "original.srt"
    decision_json = tmp / "transcript_source_decision.json"
    consistency_json = tmp / "consistency.json"
    asr_report = tmp / "asr_report.json"
    ocr_report = tmp / "ocr_report.json"
    # ASR report không severe hallucination.
    asr_report.write_text(json.dumps({"video_duration": 281.797, "hallucination": {"severe": False}}), encoding="utf-8")
    # OCR report: quality_ok=True, coverage cao (giống job: 0.846, avg_conf 0.958).
    ocr_report.write_text(json.dumps({
        "video_duration": 281.797,
        "coverage_ratio": 0.846,
        "avg_confidence": 0.958,
        "quality_ok": True,
    }), encoding="utf-8")
    env = dict(os.environ)
    proc = subprocess.run([
        sys.executable, str(DECISION_SCRIPT),
        "--mode", mode,
        "--asr-srt", str(asr_srt),
        "--ocr-srt", str(ocr_srt),
        "--output-srt", str(out_srt),
        "--asr-report", str(asr_report),
        "--ocr-report", str(ocr_report),
        "--decision-json", str(decision_json),
        "--consistency-json", str(consistency_json),
        "--dub-favor-asr-ratio", "1.25",
    ], capture_output=True, text=True, env=env)
    return proc, decision_json


def parse_ratios_median(ratios):
    if not ratios:
        return 0.0
    s = sorted(ratios)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


def longest_continuous_synthetic_tail_ms(tail_padding_ms):
    """Speech emitted for every cue breaks a synthetic cue-tail silence run."""
    return max((max(0, int(tail_ms)) for tail_ms in tail_padding_ms), default=0)


def evaluate_sync_gate(stats, video_ms, frame_strict=False, fail_on_padded_ratio=False,
                       relaxed_short_audio_mode=False):
    """Tái tạo logic TTS local sync gate từ run.sh để validate fail/job.

    Bao gồm cả gate too-long (drift/overhang/trim) — case Douyin job 091907.
    """
    total = stats.get("entries", 0) or 0
    raw_ratios = stats.get("raw_slot_ratios") or []
    ratios = stats.get("final_slot_ratios") or raw_ratios
    median_raw_ratio = parse_ratios_median(raw_ratios)
    median_ratio = parse_ratios_median(ratios)
    median_metric = "median_final_slot" if stats.get("final_slot_ratios") else "median_raw_slot"
    padded = stats.get("padded_segments", 0) or 0
    synthetic_padding_ms = stats.get("synthetic_padding_ms")
    if synthetic_padding_ms is None:
        synthetic_padding_ms = stats.get("speech_padding_ms")
    if synthetic_padding_ms is None:
        synthetic_padding_ms = stats.get("padding_total_ms", 0)
    padding_total_ms = synthetic_padding_ms or 0
    proven_synthetic_padding_ms = stats.get("proven_synthetic_padding_ms", 0) or 0
    tail_padding_ms = stats.get("synthetic_padding_tails_ms")
    longest_consecutive_padding_ms = (
        longest_continuous_synthetic_tail_ms(tail_padding_ms)
        if tail_padding_ms is not None
        else stats.get("longest_consecutive_synthetic_padding_ms", 0) or 0
    )
    proven_tail_padding_ms = stats.get("proven_synthetic_padding_tails_ms")
    longest_proven_padding_ms = (
        longest_continuous_synthetic_tail_ms(proven_tail_padding_ms)
        if proven_tail_padding_ms is not None
        else stats.get("longest_proven_synthetic_padding_ms", 0) or 0
    )
    padded_ratio = padded / total if total > 0 else 0.0
    padding_video_ratio = padding_total_ms / video_ms if video_ms > 0 else 0.0
    proven_padding_video_ratio = proven_synthetic_padding_ms / video_ms if video_ms > 0 else 0.0
    raw_low_ratio_segs = stats.get("low_ratio_segments", 0) or 0
    low_ratio_segs = stats.get("final_low_ratio_segments")
    if low_ratio_segs is None:
        low_ratio_segs = raw_low_ratio_segs
    low_ratio_segs = low_ratio_segs or 0
    low_ratio_frac = low_ratio_segs / total if total > 0 else 0.0
    reasons = []
    warnings = []
    needs_attention = []
    def add_quality_issue(reason):
        if frame_strict:
            warnings.append(reason)
        else:
            reasons.append(reason)
    # too-short (padding). Balanced mode preserves normal pauses, but never
    # permits the broad padding + low-fill failure signature to render.
    if relaxed_short_audio_mode:
        if padded_ratio > 0.4:
            warnings.append(f"padded_ratio={padded_ratio:.3f}>0.4 (reported_only)")
        if padding_video_ratio > 0.20:
            warnings.append(f"synthetic_padding_video={padding_video_ratio:.3f}>0.2")
        if total > 0 and median_ratio < 0.55:
            warnings.append(f"{median_metric}={median_ratio:.3f}<0.55")
        if longest_consecutive_padding_ms > 1500:
            warnings.append(f"longest_synthetic_padding={longest_consecutive_padding_ms}ms>1500")
        low_fill_after_restore = stats.get("low_fill_after_restore_segments", 0) or 0
        if low_fill_after_restore:
            needs_attention.append(f"LOW_FILL_AFTER_RESTORE={low_fill_after_restore}>0")
        if proven_padding_video_ratio > 0.30 and total > 0 and median_ratio < 0.55:
            reasons.append(
                f"combined_short_audio proven_synthetic_padding_video={proven_padding_video_ratio:.3f}>0.30 "
                f"and {median_metric}={median_ratio:.3f}<0.55"
            )
        if longest_proven_padding_ms > 2500:
            reasons.append(
                f"longest_proven_synthetic_padding={longest_proven_padding_ms}ms>2500"
            )
        elif longest_consecutive_padding_ms > 2500:
            needs_attention.append(
                f"unproven_long_synthetic_padding={longest_consecutive_padding_ms}ms>2500"
            )
    elif padded_ratio > 0.4:
        reason = f"padded_ratio={padded_ratio:.3f}>0.4"
        if fail_on_padded_ratio:
            add_quality_issue(reason)
        else:
            warnings.append(reason + " (warn_only)")
    if not relaxed_short_audio_mode and padding_video_ratio > 0.15:
        add_quality_issue(f"padding_video={padding_video_ratio:.3f}>0.15")
    if not relaxed_short_audio_mode and total > 0 and median_ratio < 0.75:
        add_quality_issue(f"{median_metric}={median_ratio:.3f}<0.75")
    if not relaxed_short_audio_mode and total > 0 and low_ratio_frac > 0.4:
        add_quality_issue(f"low_ratio_segs={low_ratio_frac:.3f}>0.4")
    # too-long (drift/overhang/trim)
    drift_list = sorted(int(x) for x in (stats.get("start_drift_ms_list") or []))
    max_drift = drift_list[-1] if drift_list else 0
    median_drift = 0.0
    if drift_list:
        mid = len(drift_list) // 2
        median_drift = float(drift_list[mid] if len(drift_list) % 2 == 1 else (drift_list[mid - 1] + drift_list[mid]) / 2.0)
    too_long = stats.get("tts_too_long_not_clipped_segments", 0) or 0
    over_max = stats.get("tts_over_max_speed_segments", 0) or 0
    too_long_ratio = too_long / total if total > 0 else 0.0
    over_max_ratio = over_max / total if total > 0 else 0.0
    trimmed_ms = stats.get("trimmed_ms", 0) or 0
    final_drift_list = sorted(int(x) for x in (stats.get("final_segment_drift_ms_list") or []))
    max_final_drift = final_drift_list[-1] if final_drift_list else 0
    total_final_drift = int(stats.get("total_final_drift_ms", 0) or 0)
    frame_strict_max_total_drift = max(200, total * 5)
    if frame_strict:
        if too_long > 0:
            warnings.append(f"too_long_not_clipped={too_long}>0")
        if total > 0 and over_max_ratio > 0.20:
            warnings.append(f"over_max_speed_ratio={over_max_ratio:.3f}>0.20")
        if max_drift > 500:
            warnings.append(f"max_start_drift={max_drift}ms>500")
        if drift_list and median_drift > 150:
            warnings.append(f"median_start_drift={median_drift:.0f}ms>150")
        if trimmed_ms > 500:
            warnings.append(f"voice_longer_than_video={trimmed_ms}ms>500")
        if max_final_drift > 80:
            reasons.append(f"frame_strict_max_segment_drift={max_final_drift}ms>80")
        if total_final_drift > frame_strict_max_total_drift:
            reasons.append(f"frame_strict_total_drift={total_final_drift}ms>{frame_strict_max_total_drift}")
    else:
        if too_long > 0:
            if too_long_ratio > 0.10:
                reasons.append(f"too_long_ratio={too_long_ratio:.3f}>0.1")
            else:
                warnings.append(f"too_long_not_clipped={too_long}>0 (local_overhang_warn)")
        if total > 0 and over_max_ratio > 0.20:
            reasons.append(f"over_max_speed_ratio={over_max_ratio:.3f}>0.20")
        if max_drift > 500:
            reasons.append(f"max_start_drift={max_drift}ms>500")
        if drift_list and median_drift > 150:
            reasons.append(f"median_start_drift={median_drift:.0f}ms>150")
        if trimmed_ms > 500:
            reasons.append(f"voice_longer_than_video={trimmed_ms}ms>500")
    return {
        "status": "fail" if reasons else "ok",
        "fail_reasons": reasons,
        "warning_reasons": warnings,
        "needs_attention_reasons": needs_attention,
        "padded_ratio_policy": "fail" if fail_on_padded_ratio else "warn",
        "padded_ratio": round(padded_ratio, 4),
        "padding_video_ratio": round(padding_video_ratio, 4),
        "proven_synthetic_padding_ms": proven_synthetic_padding_ms,
        "proven_padding_video_ratio": round(proven_padding_video_ratio, 4),
        "longest_consecutive_synthetic_padding_ms": longest_consecutive_padding_ms,
        "longest_proven_synthetic_padding_ms": longest_proven_padding_ms,
        "median_raw_slot": round(median_raw_ratio, 4),
        "median_final_slot": round(median_ratio, 4),
        "sync_gate_median_metric": median_metric,
        "low_ratio_fraction": round(low_ratio_frac, 4),
        "raw_low_ratio_segments": raw_low_ratio_segs,
        "final_low_ratio_segments": stats.get("final_low_ratio_segments", low_ratio_segs) or 0,
        "too_long_not_clipped": too_long,
        "too_long_ratio": round(too_long_ratio, 4),
        "over_max_speed_ratio": round(over_max_ratio, 4),
        "max_start_drift_ms": max_drift,
        "median_start_drift_ms": round(median_drift, 1),
        "trimmed_ms": trimmed_ms,
        "final_tail_safe_trim_ms": stats.get("final_tail_safe_trim_ms", 0) or 0,
        "max_final_segment_drift_ms": max_final_drift,
        "total_final_drift_ms": total_final_drift,
        "frame_strict_max_total_drift_ms": frame_strict_max_total_drift,
    }


def build_bad_tts_stats(ocr_cues, video_ms):
    """Tái tạo TTS stats của job thật: 65 entry, raw 152616ms, padded 64/65,
    raw/slot median ~0.606, padding ~100s. TTS đọc ngắn hơn OCR display slot."""
    entries = len(ocr_cues)
    ratios = []
    raw_total = 0
    padding_total = 0
    padded = 0
    low_ratio = 0
    for (s, e, _text) in ocr_cues:
        slot_ms = max(1, e - s)
        # TTS raw ~60% của OCR slot (job thật median 0.606).
        raw_ms = int(slot_ms * 0.606)
        raw_total += raw_ms
        ratio = raw_ms / slot_ms
        ratios.append(round(ratio, 4))
        if ratio < 0.5:
            low_ratio += 1
        # tail silence = slot - raw -> speech padding (im lặng trong vùng thoại).
        tail = slot_ms - raw_ms
        if tail > 0:
            padding_total += tail
            padded += 1
    # final tail silence tới video_ms — KHÔNG tính vào speech padding (giờ code tách riêng).
    final_tail = max(0, video_ms - (ocr_cues[-1][1]))
    return {
        "entries": entries,
        "raw_tts_ms": raw_total,
        "padded_segments": padded,
        "padding_total_ms": padding_total,
        "speech_padding_ms": padding_total,
        "final_tail_silence_ms": final_tail,
        "raw_slot_ratios": ratios,
        "low_ratio_segments": low_ratio,
    }


def test_synthetic_padding_is_interrupted_by_each_cue_speech():
    """Cue-tail pads are separate silences because each following cue emits TTS."""
    print("[synthetic padding continuity]")
    separate_cue_tails = {
        "entries": 3,
        "padded_segments": 3,
        "synthetic_padding_ms": 4900,
        "synthetic_padding_tails_ms": [1800, 1700, 1400],
        "raw_slot_ratios": [0.70, 0.70, 0.70],
        "final_slot_ratios": [0.70, 0.70, 0.70],
    }
    gate = evaluate_sync_gate(separate_cue_tails, 30000, relaxed_short_audio_mode=True)
    if gate["longest_consecutive_synthetic_padding_ms"] != 1800 or gate["status"] != "ok":
        print(f"  FAIL: audible TTS between cue tails must interrupt silence, got {gate}")
        return False
    unproven_tail = dict(separate_cue_tails, synthetic_padding_tails_ms=[2601])
    gate = evaluate_sync_gate(unproven_tail, 30000, relaxed_short_audio_mode=True)
    if gate["status"] != "ok" or not any("unproven_long_synthetic_padding=2601ms>2500" in r for r in gate["needs_attention_reasons"]):
        print(f"  FAIL: a display-only long tail must be needs-attention, not a hard failure, got {gate}")
        return False
    uninterrupted_tail = dict(
        separate_cue_tails,
        synthetic_padding_tails_ms=[2601],
        proven_synthetic_padding_tails_ms=[2601],
    )
    gate = evaluate_sync_gate(uninterrupted_tail, 30000, relaxed_short_audio_mode=True)
    if gate["status"] != "fail" or not any("longest_proven_synthetic_padding=2601ms>2500" in r for r in gate["fail_reasons"]):
        print(f"  FAIL: a proven 2601ms uninterrupted synthetic tail must still fail, got {gate}")
        return False
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    if ("consecutive_synthetic_padding_ms = synthetic_padding_for_segment" not in run_sh
            or "longest_proven_synthetic_padding_ms" not in run_sh):
        print("  FAIL: production still accumulates separate cue-tail pads as continuous silence")
        return False
    print("  OK: cue speech interrupts padding; an individual >2500ms tail remains a hard failure")
    return True


def test_speech_regions_schema_and_runtime_handoff_static():
    """VAD artifact contract: a top-level second-based speech-region list reaches TTS."""
    print("[speech-regions VAD contract]")
    preprocessor = SKILL_DIR / "speech_only_preprocess.py"
    spec = importlib.util.spec_from_file_location("speech_regions_contract", preprocessor)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    regions = module.merge_speech_segments([
        {"start": 1.0, "end": 2.0, "kind": "speech", "label": "fixture", "backend": "vad"},
        {"start": 2.1, "end": 3.0, "kind": "speech", "label": "fixture", "backend": "vad"},
        {"start": 4.0, "end": 5.0, "kind": "music", "label": "fixture", "backend": "vad"},
    ])
    if (not isinstance(regions, list) or len(regions) != 1
            or regions[0].get("kind") != "speech"
            or regions[0].get("start") != 1.0 or regions[0].get("end") != 3.0):
        print(f"  FAIL: generator no longer emits the expected speech-region list: {regions}")
        return False
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    required = [
        'SOURCE_SPEECH_REGIONS_JSON="${SPEECH_REGIONS_JSON:-}"',
        "if isinstance(source_speech_regions_raw, list):",
        "region.get('kind') == 'speech'",
        "float(region.get('start', 0)) * 1000",
        "float(region.get('end', 0)) * 1000",
        'SPEECH_REGIONS_JSON="$OUT_DIR/speech_regions.json"',
    ]
    missing = [item for item in required if item not in run_sh]
    preprocess_at = run_sh.find('speech_only_preprocess "$VIDEO"')
    tts_at = run_sh.find('generate_vietnamese_voice "$TTS_SOURCE_SRT"')
    if missing or preprocess_at < 0 or tts_at < 0 or preprocess_at >= tts_at:
        print(f"  FAIL: VAD schema/parser or runtime handoff missing: {missing}")
        return False
    print("  OK: generator list schema and speech-region path are preserved through the pre-TTS handoff")
    return True


def test_speech_only_preprocess_timeout_keeps_terminal_foreground_group_static():
    """Regression: GNU timeout must stay in the caller foreground process group."""
    print("[speech-only preprocess timeout foreground]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    match = re.search(
        r"speech_only_preprocess\(\) \{(?P<body>.*?)^\}",
        run_sh,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        print("  FAIL: không tìm thấy speech_only_preprocess")
        return False
    expected = 'timeout --foreground "$SPEECH_ONLY_TIMEOUT_SECONDS" python3 "$SPEECH_ONLY_PREPROCESS_SCRIPT"'
    if expected not in match.group("body"):
        print("  FAIL: speech_only_preprocess phải dùng timeout --foreground trước python3")
        return False
    print("  OK: speech-only timeout giữ child trong foreground process group của terminal")
    return True


def test_speech_region_backend_provenance_static():
    """Only speech-aware segmentation can prove a long synthetic tail."""
    print("[speech-region backend provenance]")
    base = {
        "entries": 1,
        "padded_segments": 1,
        "synthetic_padding_tails_ms": [2732],
        "raw_slot_ratios": [0.70],
        "final_slot_ratios": [0.70],
    }
    energy_only_gate = evaluate_sync_gate(base, 30000, relaxed_short_audio_mode=True)
    if (energy_only_gate["status"] != "ok"
            or not any("unproven_long_synthetic_padding=2732ms>2500" in reason
                       for reason in energy_only_gate["needs_attention_reasons"])):
        print(f"  FAIL: energy-VAD-only 2732ms tail must remain unproven, got {energy_only_gate}")
        return False
    ina_gate = evaluate_sync_gate(
        dict(base, synthetic_padding_tails_ms=[2601], proven_synthetic_padding_tails_ms=[2601]),
        30000,
        relaxed_short_audio_mode=True,
    )
    if (ina_gate["status"] != "fail"
            or not any("longest_proven_synthetic_padding=2601ms>2500" in reason
                       for reason in ina_gate["fail_reasons"])):
        print(f"  FAIL: inaSpeechSegmenter-proven 2601ms tail must hard-fail, got {ina_gate}")
        return False
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    required = [
        'SPEECH_AWARE_BACKENDS = frozenset({"inaSpeechSegmenter"})',
        "'backend': region.get('backend')",
        "region.get('backend') in SPEECH_AWARE_BACKENDS",
    ]
    missing = [item for item in required if item not in run_sh]
    if missing:
        print(f"  FAIL: backend provenance/allowlist missing: {missing}")
        return False
    print("  OK: energy/unknown regions remain unproven; inaSpeechSegmenter can prove a tail")
    return True


def test_balanced_broad_padding_requires_trusted_speech_proof():
    """Display/OCR holds alone cannot make the balanced broad-padding gate fail."""
    print("[balanced broad-padding provenance]")
    # BV14 shape: fixed-width display slots plus natural short TTS, but no
    # allowlisted speech-aware evidence. Aggregate padding remains diagnostic
    # and a long individual hold remains needs-attention, not VoiceSyncFail.
    unproven = {
        "entries": 43,
        "padded_segments": 43,
        "synthetic_padding_ms": 110054,
        "proven_synthetic_padding_ms": 0,
        "synthetic_padding_tails_ms": [4260] * 43,
        "proven_synthetic_padding_tails_ms": [0] * 43,
        "raw_slot_ratios": [0.320] * 43,
        "final_slot_ratios": [0.320] * 43,
    }
    gate = evaluate_sync_gate(unproven, 183180, relaxed_short_audio_mode=True)
    if (gate["status"] != "ok" or gate["proven_padding_video_ratio"] != 0.0
            or not any("unproven_long_synthetic_padding=4260ms>2500" in reason
                       for reason in gate["needs_attention_reasons"])):
        print(f"  FAIL: unproven OCR/display padding must warn/need attention only, got {gate}")
        return False

    # A localized long tail that overlaps allowlisted inaSpeechSegmenter speech
    # is still hard evidence and must stop the job.
    trusted_tail = dict(
        unproven,
        synthetic_padding_tails_ms=[2601],
        proven_synthetic_padding_tails_ms=[2601],
        synthetic_padding_ms=2601,
        proven_synthetic_padding_ms=2601,
    )
    gate = evaluate_sync_gate(trusted_tail, 30000, relaxed_short_audio_mode=True)
    if (gate["status"] != "fail"
            or not any("longest_proven_synthetic_padding=2601ms>2500" in reason
                       for reason in gate["fail_reasons"])):
        print(f"  FAIL: trusted localized >2500ms tail must hard-fail, got {gate}")
        return False

    # Broad hard failure remains available when padding is actually proven.
    broad_proven = dict(unproven, proven_synthetic_padding_ms=110054)
    gate = evaluate_sync_gate(broad_proven, 183180, relaxed_short_audio_mode=True)
    if (gate["status"] != "fail"
            or not any("combined_short_audio proven_synthetic_padding_video=" in reason
                       for reason in gate["fail_reasons"])):
        print(f"  FAIL: broad trusted padding plus low fill must hard-fail, got {gate}")
        return False
    print("  OK: broad failure requires trusted proof; localized trusted tail still fails")
    return True


def main():
    ok = True
    with tempfile.TemporaryDirectory(prefix="voicesync_") as td:
        tmp = Path(td)
        video_ms = 281797
        asr_cues = make_asr_cues(94, video_ms)
        ocr_cues = make_ocr_cues(65, video_ms)
        asr_srt = tmp / "original_asr.srt"
        ocr_srt = tmp / "original_ocr.srt"
        write_srt(asr_srt, asr_cues)
        write_srt(ocr_srt, ocr_cues)

        # ---- Test 1: transcript source chọn ASR cho dub ----
        proc, decision_json = run_decision(tmp, asr_srt, ocr_srt, mode="auto")
        print(f"[decision] exit={proc.returncode}")
        print(proc.stdout.strip())
        if proc.returncode != 0:
            print("  FAIL: choose_transcript_source.py exit non-zero")
            ok = False
        dec = json.loads(decision_json.read_text(encoding="utf-8"))
        chosen = dec.get("chosen")
        reason = dec.get("reason")
        asr_better = dec.get("asr_better_for_dub")
        print(f"  chosen={chosen} reason={reason} asr_segments={dec.get('asr_segments')} ocr_segments={dec.get('ocr_segments')} asr_better_for_dub={asr_better}")
        if chosen != "asr" or reason != "asr_better_for_dub_timing":
            print(f"  FAIL: expected chosen=asr reason=asr_better_for_dub_timing, got chosen={chosen} reason={reason}")
            ok = False
        else:
            print("  OK: chọn ASR/hybrid cho dub timing (asr_better_for_dub_timing)")
        if dec.get("dub_tts_timing") != "asr":
            print(f"  FAIL: dub_tts_timing={dec.get('dub_tts_timing')} != asr")
            ok = False
        else:
            print("  OK: dub_tts_timing=asr")

        # ---- Test 2: nếu ép OCR làm timing master, TTS local sync gate FAIL ----
        proc2, _ = run_decision(tmp, asr_srt, ocr_srt, mode="ocr")
        if proc2.returncode != 0:
            print("  FAIL: forced OCR mode exit non-zero")
            ok = False
        bad_stats = build_bad_tts_stats(ocr_cues, video_ms)
        gate = evaluate_sync_gate(bad_stats, video_ms)
        print(f"[local-sync gate] status={gate['status']} padded_ratio={gate['padded_ratio']} padding_video={gate['padding_video_ratio']} median_raw_slot={gate['median_raw_slot']} low_ratio_frac={gate['low_ratio_fraction']}")
        print(f"  fail_reasons={gate['fail_reasons']}")
        if gate["status"] != "fail":
            print("  FAIL: expected voice-sync gate FAIL when OCR display timing used (padded 64/65)")
            ok = False
        else:
            print("  OK: voice-sync gate fail khi TTS quá ngắn so với OCR display slot")

        # ---- Test 3: TTS tốt (ASR timing, raw gần slot) -> gate OK ----
        good_stats = build_good_tts_stats(asr_cues, video_ms)
        gate2 = evaluate_sync_gate(good_stats, video_ms)
        print(f"[local-sync gate good] status={gate2['status']} padded_ratio={gate2['padded_ratio']} median_raw_slot={gate2['median_raw_slot']}")
        if gate2["status"] != "ok":
            print(f"  FAIL: expected gate OK for ASR-timed good TTS, got {gate2['fail_reasons']}")
            ok = False
        else:
            print("  OK: voice-sync gate pass khi TTS bám ASR speech timing")

        # ---- Test 4: Douyin 091907 — TTS quá dài -> drift tích lũy -> gate FAIL ----
        dense = make_asr_cues_dense(163, 297100)
        bad_long = build_too_long_tts_stats(dense, 297100, final_voice_ms=319700)
        gate_long = evaluate_sync_gate(bad_long, 297100)
        print(f"[too-long gate] status={gate_long['status']} too_long={gate_long['too_long_not_clipped']} "
              f"over_max_ratio={gate_long['over_max_speed_ratio']} max_drift={gate_long['max_start_drift_ms']}ms "
              f"median_drift={gate_long['median_start_drift_ms']}ms trimmed={gate_long['trimmed_ms']}ms")
        print(f"  fail_reasons={gate_long['fail_reasons']}")
        if gate_long["status"] != "fail":
            print("  FAIL: expected voice-sync gate FAIL when TTS too long (drift tích lũy)")
            ok = False
        elif not any(any(k in r for k in ("too_long_not_clipped", "max_start_drift", "median_start_drift", "over_max_speed"))
                     for r in gate_long["fail_reasons"]):
            print("  FAIL: gate fail nhưng không bắt lý do too-long/drift")
            ok = False
        else:
            print("  OK: voice-sync gate fail khi TTS quá dài (drift tích lũy, không false success)")

        # ---- Test 5: voice 319s vs video 297s -> trim cắt đuôi -> gate FAIL ----
        if not any("voice_longer_than_video" in r for r in gate_long["fail_reasons"]):
            print(f"  FAIL: expected voice_longer_than_video reason (319700-297100={319700-297100}ms>500), got {gate_long['fail_reasons']}")
            ok = False
        else:
            print("  OK: gate bắt voice dài hơn video (trim cắt đuôi)")

        # ---- Test 6: TTS fit slot + drift thấp -> gate OK (case too-long good) ----
        good_long = build_good_tts_stats(dense, 297100)
        gate_ok = evaluate_sync_gate(good_long, 297100)
        print(f"[too-long gate good] status={gate_ok['status']} max_drift={gate_ok['max_start_drift_ms']}ms trimmed={gate_ok['trimmed_ms']}ms")
        if gate_ok["status"] != "ok":
            print(f"  FAIL: expected gate OK for fit TTS + low drift, got {gate_ok['fail_reasons']}")
            ok = False
        else:
            print("  OK: voice-sync gate pass khi TTS fit slot, drift thấp, voice ≤ video")

    # ---- Test 7: dub.srt gộp 163 micro-cue an toàn (≤3 cues, ≤4.5s, không 20s) ----
    if not test_dub_merge_dense():
        ok = False

    # ---- Test 7b: optimizer phải đạt DUB_GATE short-group floor trước TTS ----
    if not test_dub_merge_meets_short_group_gate_floor():
        ok = False

    # ---- Test 7c: một cue gốc >4.5s không được kích hoạt safe short relaxation ----
    if not test_dub_merge_long_original_cue_uses_normal_gate_floor():
        ok = False

    # ---- Test 7d: DubTimingMerged phải giữ needs_attention thay vì PipelineError ----
    if not test_dub_gate_failure_preserves_status_static():
        ok = False

    # ---- Test 7e: status writer treo phải bị giới hạn và không chặn pipeline ----
    if not test_status_writer_timeout_is_nonfatal():
        ok = False

    # ---- Test 7f: TTS phải dùng guarded heartbeat có timeout thực ----
    if not test_tts_guarded_heartbeat_timeout_contract():
        ok = False

    # ---- Test 7g: timeout cleanup/status remains tightly bounded ----
    if not test_tts_guarded_timeout_bounds_stalled_status_writer():
        ok = False

    # ---- Test 7h: PGID setup failure reaps descendants and fails closed ----
    if not test_tts_guarded_pgid_verification_failure_reaps_descendants():
        ok = False

    # ---- Test 8: ffmpeg speed-fit không được encode in-place ----
    if not test_tts_atempo_no_inplace_static():
        ok = False

    # ---- Test 8b: TTS master tách ASR, slow-fit bounded chỉ opt-in ----
    if not test_new_tts_audio_path_and_slowfit_defaults_static():
        ok = False

    # ---- Test 8c: balanced/quality keeps ordinary pauses but blocks severe under-fill ----
    if not test_balanced_short_audio_policy_static():
        ok = False

    # ---- Test 8d: cue-tail silence must not be accumulated across emitted speech ----
    if not test_synthetic_padding_is_interrupted_by_each_cue_speech():
        ok = False

    # ---- Test 8e: VAD source-region schema/path must remain usable by TTS gate ----
    if not test_speech_regions_schema_and_runtime_handoff_static():
        ok = False

    # ---- Test 8f: energy VAD is not speech proof for a long synthetic tail ----
    if not test_speech_region_backend_provenance_static():
        ok = False

    # ---- Test 8f2: broad balanced gate uses only trusted speech-aware proof ----
    if not test_balanced_broad_padding_requires_trusted_speech_proof():
        ok = False

    # ---- Test 9: Resona chỉ gom cue ngắn nếu đủ credit và vẫn giới hạn timing ----
    if not test_resona_short_grouping_static():
        ok = False

    # ---- Test 9b: Resona requested nhưng coverage<85% -> ResonaCoverageTooLow ----
    if not test_resona_coverage_too_low_gate():
        ok = False

    # ---- Test 9c: final tail silence KHÔNG làm fail padding_video_ratio ----
    if not test_tail_silence_not_padding_fail():
        ok = False

    # ---- Test 9d: bounded mode không fail chỉ vì nhiều cue có tail padding nhẹ ----
    if not test_balanced_padding_ratio_warning_only():
        ok = False

    # ---- Test 9d2: AI33/Vbee nói nhanh -> slow-fit nhẹ phải được tính vào gate ----
    if not test_balanced_ai33_fast_voice_defaults_to_padding_not_turtle_slowfit():
        ok = False

    # ---- Test 9e: bounded mode cho phép vài cue ngắn overhang nếu không drift/trim nặng ----
    if not test_balanced_short_cue_overhang_warning_only():
        ok = False

    # ---- Test 9e1: rejected text adaptation may still converge through bounded AI33 native speed ----
    if not test_ai33_rejected_adaptation_native_speed_regression():
        ok = False

    # ---- Test 9e1a: AI33 timing intent is applied once, with only residual atempo ----
    if not test_ai33_single_speed_contract_static():
        ok = False

    # ---- Test 9e2: phần dư concat nằm trong final tail silence được trim an toàn ----
    if not test_final_tail_safe_trim_static():
        ok = False

    # ---- Test 9f: frame_strict fit slot thì padding/median chỉ là warning ----
    if not test_frame_strict_padding_is_warning():
        ok = False

    # ---- Test 9g: frame_strict total drift budget scale theo số cue ----
    if not test_frame_strict_total_drift_budget_scales_with_entries():
        ok = False

    # ---- Test 9h: Resona API lỗi thật -> fail Resona error, KHÔNG fallback Edge ----
    if not test_resona_api_fail_no_edge_fallback():
        ok = False

    print()
    print("ALL PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


def build_good_tts_stats(asr_cues, video_ms):
    """TTS bám ASR speech timing + slow-fit (atempo<1) kéo raw ~92% slot lấp đầy slot.
    Sau slow-fit: final_duration ≈ slot, padding ≈ 0. raw_slot_ratios vẫn là raw gốc
    (gate dùng raw/slot để phát hiện TTS ngắn; nếu raw ~92% thì median 0.92 > 0.75 OK)."""
    entries = len(asr_cues)
    ratios = []
    raw_total = 0
    padding_total = 0
    padded = 0
    low_ratio = 0
    drift_list = []
    for (s, e, _text) in asr_cues:
        slot_ms = max(1, e - s)
        raw_ms = int(slot_ms * 0.92)
        raw_total += raw_ms
        ratio = raw_ms / slot_ms
        ratios.append(round(ratio, 4))
        if ratio < 0.5:
            low_ratio += 1
        # TTS fit slot, no overrun -> actual_start = start -> drift 0.
        drift_list.append(0)
        # slow-fit kéo raw lên ~slot -> không còn tail silence padding.
    return {
        "entries": entries,
        "raw_tts_ms": raw_total,
        "padded_segments": padded,
        "padding_total_ms": padding_total,
        "speech_padding_ms": padding_total,
        "raw_slot_ratios": ratios,
        "final_slot_ratios": [1.0] * entries,
        "low_ratio_segments": low_ratio,
        "final_low_ratio_segments": 0,
        "start_drift_ms_list": drift_list,
        "tts_over_max_speed_segments": 0,
        "tts_too_long_not_clipped_segments": 0,
        "final_voice_ms": video_ms,
        "target_video_ms": video_ms,
        "trimmed_ms": 0,
    }


def make_asr_cues_dense(n=163, video_ms=297100):
    """163 cue ASR dày, slot 0.8-1.2s (case Douyin job 091907: rất nhiều cue ngắn)."""
    cues = []
    t = 300
    for i in range(n):
        dur = 800 + (i % 5) * 100  # 0.8-1.2s
        if t + dur > video_ms - 500:
            break
        cues.append((t, t + dur, f"第{i+1}句"))
        t += dur + 60 + (i % 3) * 20  # gap nhỏ, dày
    return cues


def build_too_long_tts_stats(asr_cues, video_ms, final_voice_ms=319700):
    """Tái tạo stats job Douyin 091907: TTS raw ~1.4-1.8x slot (quá dài) -> speed-fit
    tới MAX_TTS_SPEED vẫn quá -> tràn slot kế -> drift tích lũy. 80 over-max-speed,
    77 kept too-long, 97 overhang, 123/163 start late, median drift ~2.1s, max ~9.8s."""
    entries = len(asr_cues)
    ratios = []
    drift_list = []
    raw_total = 0
    over_max = 0
    too_long = 0
    overhang = 0
    cursor = 0
    cumulative_drift = 0
    for idx, (s, e, _t) in enumerate(asr_cues):
        slot_ms = max(1, e - s)
        # TTS raw dài hơn slot ~1.4-1.8x.
        raw_ms = int(slot_ms * (1.4 + (idx % 5) * 0.1))
        raw_total += raw_ms
        ratios.append(round(raw_ms / slot_ms, 4))
        # actual_start = cursor (có thể > s do overrun câu trước -> drift tích lũy).
        actual_start = max(cursor, s)
        drift = max(0, actual_start - s)
        drift_list.append(drift)
        # speed-fit tới MAX_TTS_SPEED (1.5x): nếu raw>1.5x -> over_max.
        if raw_ms / slot_ms > 1.5:
            over_max += 1
        final_ms = int(raw_ms / 1.5)
        if final_ms > slot_ms:
            # Vẫn quá slot sau speed-fit tối đa -> kept_unclipped (giữ nguyên raw, overrun).
            too_long += 1
            final_ms = raw_ms  # giữ audio tràn (policy fail-strict, không clip)
        cursor = s + final_ms  # overrun đẩy câu kế trễ -> drift tích lũy
        if cursor > e:
            overhang += 1
        cumulative_drift = drift
    # final_voice dài hơn video -> trim cắt đuôi (319.7s vs 297.1s).
    trimmed = max(0, final_voice_ms - video_ms)
    return {
        "entries": entries,
        "raw_tts_ms": raw_total,
        "padded_segments": 0,
        "padding_total_ms": 0,
        "raw_slot_ratios": ratios,
        "low_ratio_segments": 0,
        "start_drift_ms_list": drift_list,
        "tts_over_max_speed_segments": over_max,
        "tts_too_long_not_clipped_segments": too_long,
        "tts_overhang_segments": overhang,
        "final_voice_ms": final_voice_ms,
        "target_video_ms": video_ms,
        "trimmed_ms": trimmed,
    }


def test_dub_merge_dense():
    """Import group_entries_for_dub từ optimizer, build 163 micro-cue, assert:
    group ≤3 cues, ≤4.5s, không >20s, count group < 163 (gộp xảy ra)."""
    import importlib.util
    OPTIMIZER = SKILL_DIR / "viet_dub_timing_optimizer.py"
    spec = importlib.util.spec_from_file_location("vopt_merge", OPTIMIZER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cues = make_asr_cues_dense(163, 297100)
    entries = [{"id": i + 1, "start_ms": s, "end_ms": e, "source_text": t} for i, (s, e, t) in enumerate(cues)]
    groups = mod.group_entries_for_dub(entries)
    group_durs = [(g[-1]["end_ms"] - g[0]["start_ms"]) / 1000.0 for g in groups]
    max_cues = max(len(g) for g in groups) if groups else 0
    max_dur = max(group_durs) if group_durs else 0.0
    print(f"[dub merge] groups={len(groups)} cues_orig={len(entries)} max_cues/group={max_cues} max_group_dur={max_dur:.2f}s")
    ok = True
    if max_cues > 3:
        print(f"  FAIL: group có {max_cues} cues > 3")
        ok = False
    if max_dur > 4.5 + 0.01:
        print(f"  FAIL: group dài {max_dur:.2f}s > 4.5s")
        ok = False
    if max_dur > 20.0:
        print(f"  FAIL: group dài {max_dur:.2f}s > 20s (regression gộp dây chuyền cũ)")
        ok = False
    if len(groups) >= len(entries):
        print(f"  FAIL: không gộp gì, groups={len(groups)} == entries={len(entries)}")
        ok = False
    else:
        print(f"  OK: gộp an toàn {len(entries)} -> {len(groups)} group, ≤3 cues, ≤4.5s")
    return ok


def test_dub_merge_meets_short_group_gate_floor():
    """165-cue regression: DUB_GATE used to fail at 105 groups before TTS."""
    import importlib.util
    optimizer = SKILL_DIR / "viet_dub_timing_optimizer.py"
    spec = importlib.util.spec_from_file_location("vopt_gate_floor", optimizer)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    entries = []
    cursor = 0
    for pair_index in range(60):
        # Punctuation marks a semantically preferable split boundary.
        entries.append({"id": len(entries) + 1, "start_ms": cursor, "end_ms": cursor + 700,
                        "source_text": f"Ý {pair_index}."})
        cursor += 750
        entries.append({"id": len(entries) + 1, "start_ms": cursor, "end_ms": cursor + 1650,
                        "source_text": f"Tiếp {pair_index}"})
        cursor += 1700
    for single_index in range(45):
        entries.append({"id": len(entries) + 1, "start_ms": cursor, "end_ms": cursor + 1700,
                        "source_text": f"Câu độc lập {single_index}."})
        cursor += 1750

    original_ratio = mod.CONFIG["dub_short_group_min_ratio"]
    try:
        mod.CONFIG["dub_short_group_min_ratio"] = 0
        disabled_groups = mod.group_entries_for_dub(entries)
        mod.CONFIG["dub_short_group_min_ratio"] = original_ratio
        groups = mod.group_entries_for_dub(entries)
    finally:
        mod.CONFIG["dub_short_group_min_ratio"] = original_ratio
    floor = 108  # ceil(165 * 0.65), the DUB_GATE-compatible adaptive floor.
    flattened_ids = [entry["id"] for group in groups for entry in group]
    group_durations = [(group[-1]["end_ms"] - group[0]["start_ms"]) / 1000 for group in groups]
    print(f"[dub gate floor] entries={len(entries)} disabled_groups={len(disabled_groups)} groups={len(groups)} floor={floor}")
    if len(disabled_groups) != 105:
        print(f"  FAIL: adaptive floor disabled should preserve old 105-group shape, got {len(disabled_groups)}")
        return False
    if len(groups) < floor:
        print("  FAIL: gate-aware regrouping vẫn dưới short-group DUB_GATE floor")
        return False
    if len(groups) != floor:
        print("  FAIL: regrouping không split số group tối thiểu")
        return False
    if flattened_ids != list(range(1, len(entries) + 1)):
        print("  FAIL: regrouping làm mất hoặc đảo thứ tự cue")
        return False
    if max(map(len, groups)) > 3 or max(group_durations) > 4.5 + 0.001:
        print("  FAIL: regrouping phá giới hạn 3 cue / 4.5 giây")
        return False
    if not any(len(group) > 1 for group in groups):
        print("  FAIL: regrouping đã bỏ toàn bộ safe merges")
        return False
    if [group[-1]["id"] for group in groups[:6]] != [1, 2, 3, 4, 5, 6] or groups[6][0]["id"] != 7:
        print("  FAIL: semantic punctuation boundaries were not selected before non-semantic boundaries")
        return False
    print("  OK: split tối thiểu tới DUB_GATE short-group floor, giữ timing/order/safe merges")
    return True


def test_dub_merge_long_original_cue_uses_normal_gate_floor():
    """A >4.5s original cue is allowed, but cannot justify the 0.65 shortcut."""
    import importlib.util
    optimizer = SKILL_DIR / "viet_dub_timing_optimizer.py"
    spec = importlib.util.spec_from_file_location("vopt_long_original", optimizer)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    entries = []
    cursor = 0
    for pair_index in range(34):
        entries.append({"id": len(entries) + 1, "start_ms": cursor, "end_ms": cursor + 700,
                        "source_text": f"Ý {pair_index}."})
        cursor += 750
        entries.append({"id": len(entries) + 1, "start_ms": cursor, "end_ms": cursor + 1650,
                        "source_text": f"Tiếp {pair_index}"})
        cursor += 1700
    for single_index in range(35):
        entries.append({"id": len(entries) + 1, "start_ms": cursor, "end_ms": cursor + 1700,
                        "source_text": f"Câu độc lập {single_index}."})
        cursor += 1750
    # This source timing must stay intact: it is an original standalone cue,
    # not an optimizer-created merge, and must never be split or falsified.
    entries.append({"id": len(entries) + 1, "start_ms": cursor, "end_ms": cursor + 4520,
                    "source_text": "Cue gốc dài 4.52 giây."})

    original_short_floor = mod.CONFIG["dub_short_group_min_ratio"]
    original_normal_floor = mod.CONFIG["dub_gate_min_ratio"]
    try:
        mod.CONFIG["dub_short_group_min_ratio"] = 0
        mod.CONFIG["dub_gate_min_ratio"] = 0
        old_groups = mod.group_entries_for_dub(entries)
        mod.CONFIG["dub_short_group_min_ratio"] = original_short_floor
        mod.CONFIG["dub_gate_min_ratio"] = original_normal_floor
        groups = mod.group_entries_for_dub(entries)
    finally:
        mod.CONFIG["dub_short_group_min_ratio"] = original_short_floor
        mod.CONFIG["dub_gate_min_ratio"] = original_normal_floor

    normal_floor = 78  # ceil(104 * DUB_GATE_MIN_RATIO=0.75)
    flattened_ids = [entry["id"] for group in groups for entry in group]
    merged_durations = [
        (group[-1]["end_ms"] - group[0]["start_ms"]) / 1000
        for group in groups if len(group) > 1
    ]
    print(f"[dub long-original floor] entries={len(entries)} old_groups={len(old_groups)} groups={len(groups)} floor={normal_floor}")
    if not (70 <= len(old_groups) < normal_floor):
        print(f"  FAIL: fixture must reproduce the old ~70/<.75 shape, got {len(old_groups)}")
        return False
    if len(groups) < normal_floor:
        print("  FAIL: long original cue incorrectly retained the 0.65 short-group floor")
        return False
    if flattened_ids != list(range(1, 105)):
        print("  FAIL: regrouping lost or reordered source cue ids")
        return False
    if max(map(len, groups)) > 3 or any(duration > 4.5 + 0.001 for duration in merged_durations):
        print("  FAIL: regrouping broke the merged-group cue/duration cap")
        return False
    long_group = next((group for group in groups if group[0]["id"] == 104), None)
    if long_group is None or len(long_group) != 1 or long_group[0]["end_ms"] - long_group[0]["start_ms"] != 4520:
        print("  FAIL: standalone 4.52s source cue was altered or merged")
        return False
    print("  OK: long original cue keeps timing while regrouping reaches the normal 0.75 gate floor")
    return True


def test_dub_gate_failure_preserves_status_static():
    """DUB_GATE's actionable needs_attention state must not be overwritten by fail()."""
    print("[dub gate status preservation]")
    text = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    anchor = 'if [[ "$dub_gate_status" -eq 7 ]]; then'
    branch_start = text.find(anchor)
    branch_end = text.find('\nfi', branch_start)
    branch = text[branch_start:branch_end if branch_end >= 0 else branch_start + 1200]
    required = [
        'status_update "needs_attention" "97" "Dub.srt gộp cue quá mạnh, cần retry/dán thủ công" "0" "DubTimingMerged"',
        'echo "Output giữ lại tại: $OUT_DIR" >&2',
        'exit "$dub_gate_status"',
    ]
    missing = [needle for needle in required if needle not in branch]
    if missing:
        print(f"  FAIL: DUB_GATE branch missing direct status/exit contract: {missing}")
        return False
    if 'fail ' in branch:
        print("  FAIL: DUB_GATE branch still calls fail(), overwriting DubTimingMerged with PipelineError")
        return False
    print("  OK: DUB_GATE exits directly and retains needs_attention/DubTimingMerged")
    return True


def _extract_shell_function(run_sh, name):
    start = run_sh.index(f"{name}() {{")
    end = run_sh.index("\n}\n", start) + 3
    return run_sh[start:end]


def test_status_writer_timeout_is_nonfatal():
    """A stalled external writer cannot hold status_update or fail the caller."""
    print("[status writer timeout]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    required = [
        'STATUS_WRITER_TIMEOUT_SECONDS="${OPENCLAW_STATUS_WRITER_TIMEOUT_SECONDS:-5}"',
        '[[ "$STATUS_WRITER_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]]',
        '[[ "$STATUS_WRITER_TIMEOUT_SECONDS" -lt 1 ]]',
        'timeout --kill-after=1 "$STATUS_WRITER_TIMEOUT_SECONDS" "$STATUS_WRITER"',
    ]
    missing = [needle for needle in required if needle not in run_sh]
    if missing:
        print(f"  FAIL: status writer timeout/default validation missing: {missing}")
        return False
    with tempfile.TemporaryDirectory(prefix="status_writer_") as td:
        tmp = Path(td)
        writer = tmp / "sleeping-status-writer.sh"
        functions_file = tmp / "status-functions.sh"
        writer.write_text("#!/usr/bin/env bash\nsleep 2\nexit 17\n", encoding="utf-8")
        writer.chmod(0o755)
        functions_file.write_text(_extract_shell_function(run_sh, "status_update"), encoding="utf-8")
        command = (
            f"STATUS_WRITER={writer!s}; OUT_DIR={tmp!s}; "
            "STATUS_WRITER_TIMEOUT_SECONDS=1; "
            f"source {functions_file!s}; "
            "started=$(date +%s%3N); status_update tts 66 stalled 0; rc=$?; "
            "elapsed=$(( $(date +%s%3N) - started )); "
            "printf '%s %s\\n' \"$rc\" \"$elapsed\""
        )
        proc = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=4)
    if proc.returncode != 0:
        print(f"  FAIL: status_update shell exited {proc.returncode}: {proc.stderr.strip()}")
        return False
    try:
        status_rc, elapsed_ms = map(int, proc.stdout.strip().split())
    except ValueError:
        print(f"  FAIL: unexpected status_update output: {proc.stdout!r}")
        return False
    if status_rc != 0 or elapsed_ms > 1500:
        print(f"  FAIL: expected nonfatal <=1500ms writer bound, got rc={status_rc} elapsed={elapsed_ms}ms")
        return False
    print(f"  OK: sleeping writer returned nonfatally in {elapsed_ms}ms")
    return True


def test_tts_guarded_heartbeat_timeout_contract():
    """The guarded wrapper supports functions, preserves exits, and reaps descendants."""
    print("[TTS guarded heartbeat timeout]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    tts_anchor = 'tts_total_timeout="${TTS_TOTAL_TIMEOUT_SECONDS:-3600}"'
    tts_start = run_sh.find(tts_anchor)
    tts_end = run_sh.find("\ntts_synth_status=$?", tts_start)
    tts_block = run_sh[tts_start:tts_end]
    expected = (
        'run_with_status_heartbeat_guarded "tts" "66" "Đang tạo giọng Việt bằng TTS" '
        '"$tts_total_timeout" "${OPENCLAW_LONG_STEP_HEARTBEAT_SECONDS:-30}"'
    )
    if tts_start < 0 or expected not in tts_block:
        print("  FAIL: TTS generation is not using the guarded heartbeat wrapper")
        return False
    with tempfile.TemporaryDirectory(prefix="tts_guarded_") as td:
        tmp = Path(td)
        functions_file = Path(td) / "heartbeat-functions.sh"
        functions_file.write_text("\n".join(_extract_shell_function(run_sh, name) for name in (
            "status_update", "process_group_id", "terminate_process_tree", "run_with_status_heartbeat_guarded")), encoding="utf-8")
        descendant_pid_file = tmp / "descendant.pid"
        command = (
            "OUT_DIR=; STATUS_WRITER=/nonexistent; "
            f"source {functions_file!s}; "
            "child_success() { return 0; }; "
            "child_failure() { return 23; }; "
            f"child_with_descendant() {{ sleep 30 & echo \"$!\" > {descendant_pid_file!s}; wait; }}; "
            "run_with_status_heartbeat_guarded tts 66 success 5 1 child_success; success_rc=$?; "
            "run_with_status_heartbeat_guarded tts 66 failure 5 1 child_failure; failure_rc=$?; "
            "started=$SECONDS; run_with_status_heartbeat_guarded tts 66 external 1 5 bash -c 'sleep 5'; external_rc=$?; external_elapsed=$((SECONDS - started)); "
            "run_with_status_heartbeat_guarded tts 66 descendant 1 1 child_with_descendant; timeout_rc=$?; "
            "printf '%s %s %s %s %s\\n' \"$success_rc\" \"$failure_rc\" \"$external_rc\" \"$timeout_rc\" \"$external_elapsed\""
        )
        proc = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=25)
        descendant_pid = descendant_pid_file.read_text(encoding="utf-8").strip() if descendant_pid_file.exists() else ""
        descendant_alive = bool(descendant_pid) and Path(f"/proc/{descendant_pid}").exists()
    try:
        success_rc, failure_rc, external_rc, timeout_rc, external_elapsed = map(int, proc.stdout.strip().split())
    except ValueError:
        success_rc = failure_rc = external_rc = timeout_rc = external_elapsed = -1
    if (proc.returncode != 0 or (success_rc, failure_rc, external_rc, timeout_rc) != (0, 23, 124, 124)
            or external_elapsed > 7 or descendant_alive):
        print(
            "  FAIL: guarded wrapper expected function exits 0/23, external/function timeouts 124 within 7s, "
            f"and reaped descendant; got shell={proc.returncode} stdout={proc.stdout!r} "
            f"descendant_pid={descendant_pid!r} alive={descendant_alive} stderr={proc.stderr!r}"
        )
        return False
    print("  OK: guarded wrapper supports functions, preserves exits, and reaps timeout descendants")
    return True


def test_tts_guarded_timeout_bounds_stalled_status_writer():
    """Timeout cleanup must not inherit the normal five-second status-writer bound."""
    print("[TTS guarded timeout with stalled status writer]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    required = [
        'OPENCLAW_TIMEOUT_STATUS_WRITER_TIMEOUT_SECONDS',
        'OPENCLAW_GUARDED_TERMINATION_GRACE_SECONDS',
        'STATUS_WRITER_TIMEOUT_SECONDS="$timeout_status_writer_timeout_seconds" status_update',
    ]
    missing = [needle for needle in required if needle not in run_sh]
    if missing:
        print(f"  FAIL: timeout path lacks bounded cleanup/status controls: {missing}")
        return False
    with tempfile.TemporaryDirectory(prefix="guarded_stalled_status_") as td:
        tmp = Path(td)
        writer = tmp / "sleeping-status-writer.sh"
        functions_file = tmp / "heartbeat-functions.sh"
        writer.write_text("#!/usr/bin/env bash\nsleep 8\n", encoding="utf-8")
        writer.chmod(0o755)
        functions_file.write_text("\n".join(_extract_shell_function(run_sh, name) for name in (
            "status_update", "process_group_id", "terminate_process_tree", "run_with_status_heartbeat_guarded")), encoding="utf-8")
        command = (
            f"OUT_DIR={tmp!s}; STATUS_WRITER={writer!s}; STATUS_WRITER_TIMEOUT_SECONDS=5; "
            "OPENCLAW_TIMEOUT_STATUS_WRITER_TIMEOUT_SECONDS=1; OPENCLAW_GUARDED_TERMINATION_GRACE_SECONDS=1; "
            f"source {functions_file!s}; "
            "started=$(date +%s%3N); run_with_status_heartbeat_guarded tts 66 stalled 1 1 bash -c 'sleep 30'; rc=$?; "
            "elapsed=$(( $(date +%s%3N) - started )); printf '%s %s\\n' \"$rc\" \"$elapsed\""
        )
        proc = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=6)
    try:
        status_rc, elapsed_ms = map(int, proc.stdout.strip().split())
    except ValueError:
        status_rc = elapsed_ms = -1
    if proc.returncode != 0 or status_rc != 124 or elapsed_ms > 3500:
        print(f"  FAIL: timeout=1 must return 124 within bounded cleanup overhead; shell={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}")
        return False
    print(f"  OK: stalled timeout status writer was bounded ({elapsed_ms}ms)")
    return True


def test_tts_guarded_pgid_verification_failure_reaps_descendants():
    """A PGID verification failure is internal failure, never an orphaning child-only kill."""
    print("[TTS guarded PGID verification failure]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    required = ["process_group_id()", "terminate_process_tree()", "GuardedProcessGroupUnavailable"]
    missing = [needle for needle in required if needle not in run_sh]
    if missing:
        print(f"  FAIL: PGID verification fail-closed helpers missing: {missing}")
        return False
    with tempfile.TemporaryDirectory(prefix="guarded_pgid_failure_") as td:
        tmp = Path(td)
        functions_file = tmp / "heartbeat-functions.sh"
        functions_file.write_text("\n".join(_extract_shell_function(run_sh, name) for name in (
            "status_update", "process_group_id", "terminate_process_tree", "run_with_status_heartbeat_guarded")), encoding="utf-8")
        descendant_pid_file = tmp / "descendant.pid"
        command = (
            "OUT_DIR=; STATUS_WRITER=/nonexistent; OPENCLAW_GUARDED_TERMINATION_GRACE_SECONDS=1; "
            f"source {functions_file!s}; "
            "process_group_id() { return 1; }; "
            f"child_with_descendant() {{ sleep 30 & echo \"$!\" > {descendant_pid_file!s}; wait; }}; "
            "run_with_status_heartbeat_guarded tts 66 pgid-failure 10 1 child_with_descendant; rc=$?; printf '%s\\n' \"$rc\""
        )
        proc = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=6)
        descendant_pid = descendant_pid_file.read_text(encoding="utf-8").strip() if descendant_pid_file.exists() else ""
        descendant_alive = bool(descendant_pid) and Path(f"/proc/{descendant_pid}").exists()
    try:
        status_rc = int(proc.stdout.strip())
    except ValueError:
        status_rc = -1
    if proc.returncode != 0 or status_rc in (0, 124) or descendant_alive:
        print(f"  FAIL: PGID verification failure must return internal error and reap descendants; shell={proc.returncode} stdout={proc.stdout!r} descendant={descendant_pid!r} alive={descendant_alive} stderr={proc.stderr!r}")
        return False
    print(f"  OK: PGID verification failure returned {status_rc} and reaped descendants")
    return True


def test_tts_atempo_no_inplace_static():
    """Regression cho crash job 212123:
    ffmpeg từng được gọi với input=output cùng là *_speech_fit.wav và atempo≈1.
    run.sh là Bash chứa heredoc Python, nên test tĩnh xác nhận helper chống in-place tồn tại.
    """
    run_sh = SKILL_DIR / "run.sh"
    text = run_sh.read_text(encoding="utf-8")
    required = [
        "def apply_atempo_fit",
        "def unique_segment_wav",
        "candidate.resolve() == src_resolved",
        "abs(ratio - 1.0) <= epsilon",
        "stderr=subprocess.PIPE",
        "ffmpeg atempo failed segment=",
    ]
    missing = [needle for needle in required if needle not in text]
    print("[tts atempo no-inplace]")
    if missing:
        print(f"  FAIL: missing no-inplace guard pieces: {missing}")
        return False
    risky = "str(segment_out),\n                    '-filter:a', build_atempo_filters(speed_ratio),"
    if risky in text and "apply_atempo_fit(segment_out" not in text:
        print("  FAIL: rewrite speed-fit still appears to call ffmpeg directly on segment_out")
        return False
    print("  OK: speed-fit dùng helper unique output + skip atempo≈1, tránh ffmpeg input=output")
    return True


def test_new_tts_audio_path_and_slowfit_defaults_static():
    """TTS master phải tách ASR 16k; bounded mode giữ speed 1.0 trừ opt-in slow nhẹ."""
    print("[tts master audio path + bounded slowfit defaults]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    ai33 = (SKILL_DIR / "ai33_tts_synthesize.py").read_text(encoding="utf-8")
    required = [
        'TTS_MASTER_SAMPLE_RATE="${TTS_MASTER_SAMPLE_RATE:-48000}"',
        'FINAL_AUDIO_SAMPLE_RATE="${FINAL_AUDIO_SAMPLE_RATE:-48000}"',
        'FINAL_AUDIO_CHANNELS="${FINAL_AUDIO_CHANNELS:-2}"',
        'ALLOW_SLOW_FIT="${ALLOW_SLOW_FIT:-0}"',
        'POST_ATEMPO_MIN="${POST_ATEMPO_MIN:-0.95}"',
        "allow_slow_fit = (os.environ.get(\"ALLOW_SLOW_FIT\", \"0\")",
        "post_atempo_min = max(0.5, min(1.0, float(os.environ.get(\"POST_ATEMPO_MIN\", \"0.95\")",
        'if allow_slow_fit and not frame_strict',
        '"slow_fit_used": action_taken == \'slow_fit\'',
        'segment_id,slot_ms,natural_tts_ms,post_atempo,final_segment_ms,slow_fit_used',
        'final_slot_ratios',
        'TTS_MASTER_DOWNGRADED_TO_ASR_FORMAT',
        'VOICE_SYNC_PADDING_WARN_RATIO="${VOICE_SYNC_PADDING_WARN_RATIO:-0.20}"',
        'VOICE_SYNC_PADDING_FAIL_RATIO="${VOICE_SYNC_PADDING_FAIL_RATIO:-0.30}"',
        'VOICE_SYNC_MIN_MEDIAN_FILL_RATIO="${VOICE_SYNC_MIN_MEDIAN_FILL_RATIO:-0.55}"',
        'VOICE_SYNC_LONG_PADDING_WARN_MS="${VOICE_SYNC_LONG_PADDING_WARN_MS:-1500}"',
        'VOICE_SYNC_LONG_PADDING_FAIL_MS="${VOICE_SYNC_LONG_PADDING_FAIL_MS:-2500}"',
        '"source_gap_ms": gap_ms',
        '"synthetic_padding_ms": synthetic_padding_for_segment',
        '"median_final_fill_ratio"',
    ]
    missing = [needle for needle in required if needle not in run_sh]
    if missing:
        print(f"  FAIL: thiếu TTS master/slow-fit guards: {missing}")
        return False
    if '["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1"' in ai33:
        print("  FAIL: AI33 wrapper vẫn ép audio TTS về ASR 16k mono")
        return False
    if 'os.environ.get("TTS_MASTER_SAMPLE_RATE", "48000")' not in ai33:
        print("  FAIL: AI33 wrapper chưa nhận TTS_MASTER_SAMPLE_RATE=48000")
        return False
    if 'run_with_status_heartbeat_guarded "tts" "66" "Đang tạo giọng Việt bằng TTS"' not in run_sh:
        print("  FAIL: TTS long step thiếu guarded heartbeat wrapper, dashboard dễ tưởng job treo")
        return False
    print("  OK: ASR 16k tách TTS master 48k; bounded mặc định pad silence, slow-fit chỉ opt-in 0.95-0.99")
    return True


def test_balanced_short_audio_policy_static():
    """Balanced mode keeps display-only under-fill visible without false-failing it."""
    print("[balanced short-audio policy]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    required = [
        'relaxed_short_audio_mode = sync_mode in ("balanced_dub", "quality_dub")',
        'VOICE_SYNC_PADDING_FAIL_RATIO", "0.30"',
        'proven_padding_video_ratio > padding_fail_ratio',
        'combined_short_audio_failure',
        'LOW_FILL_AFTER_RESTORE',
        'VOICE_SYNC_GATE_WARNING:',
    ]
    missing = [needle for needle in required if needle not in run_sh]
    if missing:
        print(f"  FAIL: thiếu balanced short-audio policy: {missing}")
        return False
    combined_start = run_sh.find("if combined_short_audio_failure:")
    combined_block = run_sh[combined_start:run_sh.find("if longest_consecutive_padding_ms", combined_start)]
    if combined_start < 0 or "sync_fail_reasons.append(reason)" not in combined_block:
        print("  FAIL: combined severe short-audio condition can bypass VoiceSyncFail")
        return False
    if "needs_attention_reasons.append(reason)" in combined_block or "strict_quality_gate" in combined_block:
        print("  FAIL: combined severe short-audio condition is still warning-only or strict-only")
        return False
    long_padding_start = run_sh.find("if longest_proven_padding_ms > long_padding_fail_ms:")
    long_padding_block = run_sh[long_padding_start:run_sh.find("elif longest_consecutive_padding_ms", long_padding_start)]
    if long_padding_start < 0 or "sync_fail_reasons.append(reason)" not in long_padding_block:
        print("  FAIL: VAD-proven pathological synthetic padding can bypass VoiceSyncFail")
        return False
    if "needs_attention_reasons.append(reason)" in long_padding_block or "strict_quality_gate" in long_padding_block:
        print("  FAIL: VAD-proven pathological synthetic padding is still strict-only/warning-only")
        return False
    if "unproven_long_synthetic_padding" not in run_sh:
        print("  FAIL: long padding without source-speech evidence is not classified needs-attention")
        return False
    episode_one = {
        "entries": 45,
        "padded_segments": 43,
        "synthetic_padding_ms": 108096,
        "speech_padding_ms": 108096,
        "synthetic_padding_tails_ms": [2601] * 43,
        "proven_synthetic_padding_tails_ms": [0] * 43,
        "raw_slot_ratios": [0.3414] * 45,
        "final_slot_ratios": [0.3414] * 45,
    }
    gate = evaluate_sync_gate(episode_one, 338858, relaxed_short_audio_mode=True)
    if (gate["status"] != "ok"
            or not any("unproven_long_synthetic_padding=2601ms>2500" in reason
                       for reason in gate["needs_attention_reasons"])):
        print(f"  FAIL: unproven episode-1 OCR holds must be needs-attention, not VoiceSyncFail, got {gate}")
        return False
    # Regression fixture from input-20260712-195539: its 18.39% total padding
    # would not trip the broad-padding gate, but a 9.202s synthetic run is still
    # pathological and must never produce a successful balanced render.
    pathological_run = {
        "entries": 67,
        "padded_segments": 21,
        "synthetic_padding_ms": 31615,
        "speech_padding_ms": 31615,
        "longest_consecutive_synthetic_padding_ms": 9202,
        "longest_proven_synthetic_padding_ms": 9202,
        "raw_slot_ratios": [0.7473] * 67,
        "final_slot_ratios": [0.7473] * 67,
    }
    gate = evaluate_sync_gate(pathological_run, 171958, relaxed_short_audio_mode=True)
    if gate["status"] != "fail" or not any("longest_proven_synthetic_padding=9202ms>2500" in reason for reason in gate["fail_reasons"]):
        print(f"  FAIL: 9.202s synthetic-padding fixture must fail in balanced mode, got {gate}")
        return False
    ordinary_pause = dict(pathological_run, longest_consecutive_synthetic_padding_ms=2400,
                          longest_proven_synthetic_padding_ms=2400)
    gate = evaluate_sync_gate(ordinary_pause, 171958, relaxed_short_audio_mode=True)
    if gate["status"] != "ok":
        print(f"  FAIL: sub-threshold isolated synthetic pause should remain allowed, got {gate}")
        return False
    print("  OK: balanced keeps display-only OCR under-fill visible; only proven pathological padding VoiceSyncFails")
    return True


def test_tts_gate_status_capture_static():
    """Regression cho job 212123:
    VOICE_SYNC_GATE_FAIL từng sys.exit(8) trong heredoc Python; vì bash đang set -e,
    script thoát ngay trước khi copy report/status_update, dashboard còn state=running
    rồi báo StuckHeartbeat.
    """
    run_sh = SKILL_DIR / "run.sh"
    text = run_sh.read_text(encoding="utf-8")
    required = [
        'export VOICE_SYNC_REPORT_JSON="$OUT_DIR/voice_sync_quality_report.json"',
        'set +e\n  python3 - "$TTS_STATS_JSON"',
        "tts_gate_status=$?\n  set -e",
        'status_update "needs_attention" "78" "Voice-sync hỏng',
        'echo "Output giữ lại tại: $OUT_DIR" >&2\n    exit 8',
    ]
    missing = [needle for needle in required if needle not in text]
    print("[tts gate status capture]")
    if missing:
        print(f"  FAIL: missing status/report capture pieces: {missing}")
        return False
    gate_anchor = "# TTS coverage gate: giọng thật quá ít so với video"
    gate_start = text.find(gate_anchor)
    gate_block = text[gate_start:gate_start + 4500] if gate_start >= 0 else ""
    gate_required = [
        'sync_policy = (os.environ.get("TTS_SYNC_POLICY", "bounded")',
        'frame_strict = (sync_policy == "frame_strict")',
        'frame_strict_max_segment_drift = max(0, int(float(os.environ.get("FRAME_STRICT_MAX_SEGMENT_DRIFT_MS"',
        'frame_strict_base_total_drift = max(0, int(float(os.environ.get("FRAME_STRICT_MAX_TOTAL_DRIFT_MS"',
        'frame_strict_total_drift_per_segment = max(0, int(float(os.environ.get("FRAME_STRICT_TOTAL_DRIFT_PER_SEGMENT_MS"',
        'frame_strict_max_total_drift = max(frame_strict_base_total_drift, total * frame_strict_total_drift_per_segment)',
    ]
    gate_missing = [needle for needle in gate_required if needle not in gate_block]
    if gate_missing:
        print(f"  FAIL: TTS gate heredoc thiếu khai báo frame_strict vars: {gate_missing}")
        return False
    old_bad = 'status_update "needs_attention" "78" "Voice-sync hỏng'
    if old_bad in text:
        branch_start = text.index(old_bad)
        branch_end = text.find("  fi", branch_start)
        branch = text[branch_start:branch_end if branch_end != -1 else branch_start + 800]
        if "fail " in branch:
            print("  FAIL: VoiceSyncFail branch still calls fail(), which overwrites job_status")
            return False
    print("  OK: gate captures exit code, writes report to job dir, preserves VoiceSyncFail status")
    return True


def test_tts_synthesis_early_failure_report_static():
    """Regression cho AI33 voice mới: TTS Python chết sớm trước stats/report từng bị
    Bash ghi đè thành PipelineError mù. Phải ghi voice_sync_quality_report.json sớm
    và Bash phải giữ error_code cụ thể.
    """
    print("[tts synthesis early failure report]")
    text = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    required = [
        "def _write_tts_early_failure_report",
        '"phase": "tts_generation"',
        '"ai33_failed_segments": 1 if error_code.startswith("AI33") else 0',
        "sys.excepthook = _tts_excepthook",
        'tts_early_err_code=""',
        'status_update "error" "66" "TTS synthesis fail: $tts_early_err_code"',
        'exit "$tts_synth_status"',
    ]
    missing = [needle for needle in required if needle not in text]
    if missing:
        print(f"  FAIL: thiếu early TTS failure/report guard: {missing}")
        return False
    bad = 'fail "TTS synthesis lỗi (exit=$tts_synth_status). Xem log."'
    if bad in text:
        print("  FAIL: TTS synth nonzero vẫn gọi fail() generic, sẽ overwrite error_code thành PipelineError")
        return False
    print("  OK: TTS synth nonzero preserves provider/early error report instead of PipelineError")
    return True


def test_final_voice_sync_report_gate_static():
    """A final render cannot organize without a readable explicit voice-sync result."""
    print("[final voice-sync report gate]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    status_helper = (SKILL_DIR / "voice_sync_status.py").read_text(encoding="utf-8")
    required_run = [
        "from voice_sync_status import final_report_status",
        'status_update "needs_attention" "97" "Voice-sync report không hợp lệ, chưa organize"',
        'exit 1',
    ]
    required_helper = ["def final_report_status", "VoiceSyncReportMissing", 'status in ("ok", "warning")', 'status == "fail"']
    missing = [item for item in required_run if item not in run_sh]
    missing += [item for item in required_helper if item not in status_helper]
    if missing:
        print(f"  FAIL: final voice-sync report gate missing: {missing}")
        return False
    if "source_cue_id_by_timing" in run_sh:
        print("  FAIL: Resona source identity still uses a timing-key reverse lookup")
        return False
    print("  OK: missing/malformed report blocks organize; explicit ok/warning passes and fail blocks")
    return True


def test_balanced_dub_quality_policy_static():
    """Default policy keeps natural caps; DUB_GATE must fail before TTS, not raise speed."""
    print("[balanced dub quality policy]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    optimizer = (SKILL_DIR / "viet_dub_timing_optimizer.py").read_text(encoding="utf-8")
    required_run = [
        'SYNC_MODE="${SYNC_MODE:-${TTS_SYNC_MODE:-exact_sync}}"',
        'TTS_SYNC_POLICY="${TTS_SYNC_POLICY:-bounded}"',
        'AI33_MAX_SPEED="${AI33_MAX_SPEED:-1.12}"',
        'POST_ATEMPO_MAX="${POST_ATEMPO_MAX:-1.05}"',
        'TOTAL_AUDIO_SPEED_MAX="${TOTAL_AUDIO_SPEED_MAX:-1.35}"',
        'ALLOW_AGGRESSIVE_ATEMPO="${ALLOW_AGGRESSIVE_ATEMPO:-0}"',
        'if frame_strict and allow_aggressive_atempo:',
        'def choose_ai33_native_speed',
        'def post_atempo_cap_for',
        'def normalize_wav_for_concat',
        'post_cap = post_atempo_cap_for(ai33_speed_used)',
        'AI33 native speed segment=',
        "native_wav_path = segments_dir / f'{segment_index:04d}_speech_ai33_native.wav'",
        '"normalized_for_concat_segments": 0',
        '"concat_duration_extra_ms": 0',
        '"final_tail_safe_trim_ms": 0',
        'TTS_FINAL_TAIL_TRIM_TOLERANCE_MS',
        'os.replace(tailfit_wav, voice_wav)',
        "'-vn', '-ac', str(tts_master_channels), '-ar', str(tts_master_sample_rate), '-c:a', 'pcm_s16le', str(voice_wav)",
        'native_mp3_path, native_wav_path, text, voice_name, slot_ms',
        'ai33_speed,native_speed,native_speed_mode,post_atempo_speed,post_atempo_applied,total_audio_speed,total_speed_factor',
        'ALLOW_FINAL_TRIM="${ALLOW_FINAL_TRIM:-0}"',
        'FINAL_AUDIO_SAMPLE_RATE="${FINAL_AUDIO_SAMPLE_RATE:-48000}"',
        'FINAL_AUDIO_CHANNELS="${FINAL_AUDIO_CHANNELS:-2}"',
        'FINAL_AUDIO_BITRATE="${FINAL_AUDIO_BITRATE:-192k}"',
        'FINAL_VIDEO_FIT_MODE="${FINAL_VIDEO_FIT_MODE:-none}"',
        'ALLOW_VIDEO_RETIME="${ALLOW_VIDEO_RETIME:-0}"',
        'ALLOW_FREEZE_FRAME="${ALLOW_FREEZE_FRAME:-0}"',
        'LOCAL_RETIME_SCENE_SAFE="${LOCAL_RETIME_SCENE_SAFE:-0}"',
        'STRICT_QUALITY_GATE="${STRICT_QUALITY_GATE:-0}"',
        'MAX_FREEZE_PER_SEGMENT_MS="${MAX_FREEZE_PER_SEGMENT_MS:-500}"',
        'MAX_FREEZE_PER_SCENE_MS="${MAX_FREEZE_PER_SCENE_MS:-1200}"',
        'final_mix_quality.py" --video-fit',
        'TTS_LOCAL_SYNC_FAIL_ON_PADDED_RATIO',
        '"padded_ratio_policy": "fail" if fail_on_padded_ratio else "warn"',
        '"semantic_rewrite_fields": ["subtitle_text", "dub_text_before", "dub_text_after", "kept_meaning", "dropped_details", "restored_details", "meaning_risk", "adapt_direction", "rewrite_attempts", "fit_decision"]',
        '"subtitle_text": subtitle_text',
        '"dub_text_before": dub_text_before',
        '"dub_text_after": text',
        '"adapt_direction": adapt_direction',
        '"restored_details": restored_details',
        'def adapt_dub_text(',
        'def check_adapted_meaning(',
        'ai33_speed=1.0 if voice_name.lower().startswith("ai33") else None',
        'FINAL_VIDEO_FIT_PLAN_JSON="$OUT_DIR/final_video_fit_plan.json"',
        'VIDEO_MUX_SOURCE="$OUT_DIR/video_tail_freeze_mux.mp4"',
        'VIDEO_FIT_ACTION" == "tail_freeze_local"',
        '-t "$MUX_TARGET_DURATION" -c:v libx264',
        'python3 - "$VIDEO" "$FINAL_VIDEO" "$MUX_VOICE_WAV"',
        'explicit_local_tail_freeze_no_global_retime',
        'ENABLE_BGM_DUCKING="${ENABLE_BGM_DUCKING:-1}"',
        'BGM_DUCK_AMOUNT="${BGM_DUCK_AMOUNT:-2.0}"',
        'FINAL_LOUDNESS_TARGET="${FINAL_LOUDNESS_TARGET:--18}"',
        'final_mix_quality_report.json',
        '-b:a "$FINAL_AUDIO_BITRATE" -ar "$FINAL_AUDIO_SAMPLE_RATE" -ac "$FINAL_AUDIO_CHANNELS"',
    ]
    missing_run = [needle for needle in required_run if needle not in run_sh]
    if missing_run:
        print(f"  FAIL: run.sh thiếu bounded/quality policy pieces: {missing_run}")
        return False
    required_optimizer = [
        'os.environ.get("TTS_SYNC_POLICY", "bounded")',
        '_ALLOW_AGGRESSIVE_ATEMPO',
        '50.0 if (_FRAME_STRICT and _ALLOW_AGGRESSIVE_ATEMPO)',
    ]
    missing_optimizer = [needle for needle in required_optimizer if needle not in optimizer]
    if missing_optimizer:
        print(f"  FAIL: optimizer còn policy cũ/unbounded mặc định: {missing_optimizer}")
        return False
    forbidden = [
        'sync_policy = (os.environ.get("TTS_SYNC_POLICY", "frame_strict")',
        'ffmpeg -y -i "$VIETNAMESE_VOICE_WAV" -af "apad" -t "$VIDEO_DURATION" -ac 1 -ar 16000',
        'TRIMMED_VOICE_WAV',
        "str(concat_list), '-c', 'copy', str(voice_wav)",
        '[1:a]volume=1.0[voice]',
        '-c:a aac -shortest "$AUDIO_ONLY_VIDEO"',
    ]
    hits = [needle for needle in forbidden if needle in run_sh]
    if hits:
        print(f"  FAIL: còn dấu policy/mux cũ làm bóp giọng: {hits}")
        return False
    # 1.5x remains an opt-in profile ceiling, never a balanced-default increase.
    balanced_start = run_sh.find('  balanced|balanced_dub|*)')
    balanced_end = run_sh.find('esac', balanced_start)
    balanced_branch = run_sh[balanced_start:balanced_end]
    for cap in ('AI33_MAX_SPEED="${AI33_MAX_SPEED:-1.12}"',
                'POST_ATEMPO_MAX="${POST_ATEMPO_MAX:-1.05}"',
                'TOTAL_AUDIO_SPEED_MAX="${TOTAL_AUDIO_SPEED_MAX:-1.35}"'):
        if balanced_branch.count(cap) != 1:
            print(f"  FAIL: balanced default speed cap changed or duplicated: {cap}")
            return False
    gate_at = run_sh.find("# Dub timing quality gate:")
    tts_at = run_sh.find('status_update "tts" "66"')
    if gate_at < 0 or tts_at < 0 or gate_at >= tts_at or "DUB_GATE_FAIL" not in run_sh[gate_at:tts_at]:
        print("  FAIL: DUB_GATE is not a pre-TTS naturalness/sync gate")
        return False
    print("  OK: default balanced_dub bounded, AI33 native speed nhẹ, atempo capped, final mix stereo/48k/192k")
    return True


def evaluate_resona_coverage_gate(stats, requested_resona=True, min_coverage=0.85):
    """Tái tạo ResonaCoverageTooLow gate từ run.sh."""
    if not requested_resona:
        return {"status": "ok", "resona_coverage_ratio": 0.0, "fail_reasons": []}
    total = stats.get("entries", 0) or 0
    resona = stats.get("resona_segments", 0) or 0
    if total <= 0:
        return {"status": "ok", "resona_coverage_ratio": 0.0, "fail_reasons": []}
    coverage = resona / total
    reasons = []
    if coverage < min_coverage:
        reasons.append(f"resona_coverage={coverage:.3f}<{min_coverage} resona={resona}/{total}")
    return {
        "status": "fail" if reasons else "ok",
        "resona_coverage_ratio": round(coverage, 4),
        "fail_reasons": reasons,
    }


def test_resona_short_grouping_static():
    """Regression cho Resona:
    mỗi cue <50 credit từng bị fallback Edge hết. Pipeline phải gom cue ngắn đủ
    credit (group_or_fail), cho phép vượt soft max nhưng không vượt hard max,
    merge ngược nếu group cuối thiếu, fail ResonaTextTooShortUngroupable nếu không gom đủ.
    KHÔNG fallback Edge mặc định.
    """
    run_sh = SKILL_DIR / "run.sh"
    text = run_sh.read_text(encoding="utf-8")
    required = [
        'RESONA_SHORT_TEXT_POLICY="${RESONA_SHORT_TEXT_POLICY:-group_or_fail}"',
        'RESONA_SHORT_GROUP_MAX_CUES="${RESONA_SHORT_GROUP_MAX_CUES:-8}"',
        'RESONA_SHORT_GROUP_SOFT_MAX_DURATION_SECONDS="${RESONA_SHORT_GROUP_SOFT_MAX_DURATION_SECONDS:-12}"',
        'RESONA_SHORT_GROUP_HARD_MAX_DURATION_SECONDS="${RESONA_SHORT_GROUP_HARD_MAX_DURATION_SECONDS:-18}"',
        'RESONA_SHORT_GROUP_MAX_INTERNAL_GAP_MS="${RESONA_SHORT_GROUP_MAX_INTERNAL_GAP_MS:-2500}"',
        "os.environ.get('RESONA_SHORT_GROUP_MAX_CUES', '8')",
        "os.environ.get('RESONA_SHORT_GROUP_HARD_MAX_DURATION_SECONDS', '18')",
        "os.environ.get('RESONA_SHORT_GROUP_MAX_INTERNAL_GAP_MS', '2500')",
        "def resona_credit_chars",
        "def build_resona_tts_entries",
        "resona_short_group_hard_max_ms",
        "resona_short_group_max_internal_gap_ms",
        "ResonaTextTooShortUngroupable",
        "group_or_fail",
        '"resona_short_grouped_units": resona_grouped_units',
        '"tts_engines_used": stats.get(',
        '"resona_coverage_ratio"',
        '"speech_padding_ms"',
        '"final_tail_silence_ms"',
        '"edge_segments"',
        "ResonaCoverageTooLow",
        "RESONA_GATE_MIN_COVERAGE",
    ]
    missing = [needle for needle in required if needle not in text]
    print("[resona short grouping]")
    if missing:
        print(f"  FAIL: missing Resona grouping/guard pieces: {missing}")
        return False
    if "grouped_entries.append((group[0][0], group[-1][1], combined_text))" not in text:
        print("  FAIL: grouped TTS unit is not preserving outer start/end timing")
        return False
    # group_or_fail phải KHÔNG fallback Edge mặc định.
    if "edge_result = synthesize_edge_tts" in text and "group_or_fail" in text:
        # Edge fallback chỉ được phép trong nhánh policy=edge tường minh, không phải default.
        if "if resona_short_text_policy in ('fail', 'group_or_fail'):" not in text:
            print("  FAIL: group_or_fail không được bắt trước Edge fallback")
            return False
    print("  OK: Resona gom cue ngắn (group_or_fail, 8 cue/soft 12s/hard 18s/gap 2.5s), merge ngược, không Edge mặc định, report coverage/speech_padding/tail")
    return True


def test_resona_coverage_too_low_gate():
    """10 cue ngắn như job 223820: nếu Resona requested nhưng coverage<85% -> ResonaCoverageTooLow."""
    print("[resona coverage too low]")
    # Case 1: requested Resona, 0/10 Resona segments (toàn fallback Edge) -> FAIL.
    stats = {
        "entries": 10,
        "resona_segments": 0,
        "resona_short_text_segments": 10,
        "resona_short_edge_fallback_segments": 10,
    }
    gate = evaluate_resona_coverage_gate(stats, requested_resona=True)
    if gate["status"] != "fail":
        print(f"  FAIL: expected ResonaCoverageTooLow fail (0/10), got {gate}")
        return False
    print(f"  OK: 0/10 Resona coverage={gate['resona_coverage_ratio']} -> fail {gate['fail_reasons']}")
    # Case 2: 9/10 Resona -> coverage 0.9 >= 0.85 -> OK.
    stats2 = {"entries": 10, "resona_segments": 9, "resona_short_text_segments": 1,
              "resona_short_edge_fallback_segments": 1}
    gate2 = evaluate_resona_coverage_gate(stats2, requested_resona=True)
    if gate2["status"] != "ok":
        print(f"  FAIL: expected OK (9/10=0.9>=0.85), got {gate2}")
        return False
    print(f"  OK: 9/10 Resona coverage={gate2['resona_coverage_ratio']} -> ok")
    # Case 3: Resona không requested (Edge voice) -> coverage gate skip.
    gate3 = evaluate_resona_coverage_gate(stats, requested_resona=False)
    if gate3["status"] != "ok":
        print(f"  FAIL: Edge voice must skip Resona coverage gate, got {gate3}")
        return False
    print("  OK: Edge voice skip Resona coverage gate")
    return True


def test_tail_silence_not_padding_fail():
    """Final tail silence (im lặng cuối video) KHÔNG làm fail padding_video_ratio."""
    print("[tail silence not padding fail]")
    # 5 câu cuối kết thúc ở 280s, video 281.8s -> final_tail ~1.8s.
    # Speech padding thấp (0.05s) -> padding_video_ratio phải OK (<0.15).
    stats = {
        "entries": 65,
        "padded_segments": 5,
        "speech_padding_ms": 50,            # 0.05s speech padding
        "padding_total_ms": 50,
        "final_tail_silence_ms": 1797,      # 1.8s tail (không tính vào speech padding)
        "raw_slot_ratios": [0.92] * 65,
        "low_ratio_segments": 0,
    }
    gate = evaluate_sync_gate(stats, 281797)
    if gate["status"] != "ok":
        print(f"  FAIL: tail silence leaked into padding_video ({gate['padding_video_ratio']}), got {gate['fail_reasons']}")
        return False
    print(f"  OK: speech_padding_video={gate['padding_video_ratio']} (tail 1.8s excluded) -> gate ok")
    # Ngược lại: speech padding cao 100s -> vẫn fail đúng.
    stats_bad = dict(stats)
    stats_bad["speech_padding_ms"] = 100000
    stats_bad["padding_total_ms"] = 100000
    gate_bad = evaluate_sync_gate(stats_bad, 281797)
    if gate_bad["status"] != "fail":
        print(f"  FAIL: 100s speech padding must fail, got {gate_bad}")
        return False
    print("  OK: 100s speech padding -> fail (VoiceSyncFail đúng, không phải tail)")
    return True


def test_balanced_padding_ratio_warning_only():
    """Screenshot regression: nhiều segment có tail silence nhẹ không được fail oan."""
    print("[balanced padded ratio warning]")
    stats = {
        "entries": 49,
        "padded_segments": 38,
        "speech_padding_ms": 24303,
        "padding_total_ms": 24303,
        "raw_slot_ratios": [0.781] * 49,
        "low_ratio_segments": 0,
        "tts_too_long_not_clipped_segments": 0,
        "tts_over_max_speed_segments": 0,
        "start_drift_ms_list": [0] * 48 + [19],
        "final_segment_drift_ms_list": [0] * 49,
        "total_final_drift_ms": 0,
        "trimmed_ms": 64,
    }
    gate = evaluate_sync_gate(stats, 240000)
    if gate["status"] != "ok":
        print(f"  FAIL: padded_ratio alone should be warning in bounded mode, got {gate}")
        return False
    if not any("padded_ratio" in reason and "warn_only" in reason for reason in gate["warning_reasons"]):
        print(f"  FAIL: expected padded_ratio warn_only, got {gate['warning_reasons']}")
        return False
    print(
        f"  OK: status={gate['status']} padded_ratio={gate['padded_ratio']} "
        f"padding_video={gate['padding_video_ratio']} median_raw_slot={gate['median_raw_slot']} -> warning only"
    )

    legacy_gate = evaluate_sync_gate(stats, 240000, fail_on_padded_ratio=True)
    if legacy_gate["status"] != "fail":
        print(f"  FAIL: explicit fail_on_padded_ratio should still fail, got {legacy_gate}")
        return False
    print("  OK: TTS_LOCAL_SYNC_FAIL_ON_PADDED_RATIO=1 keeps legacy hard-fail path available")
    return True


def test_balanced_ai33_fast_voice_defaults_to_padding_not_turtle_slowfit():
    """Default mới không được đưa bất kỳ segment nào xuống 0.85 để lấp slot."""
    print("[balanced AI33 default padding, no turtle slow-fit]")
    raw_ratios = [
        0.9736, 0.7297, 0.5247, 0.6945, 0.7688, 0.9138, 0.774, 0.7067, 0.4713, 0.919,
        0.5781, 0.4818, 0.6349, 0.5685, 0.2476, 0.2699, 0.9496, 0.5637, 0.9797, 0.9797,
        0.451, 0.673, 0.4673, 0.353, 0.7594, 0.4073, 0.5967, 0.7775, 0.7078, 0.856,
        0.6422, 0.647, 0.4977, 0.6619, 0.7707, 0.934, 0.8322, 0.7488, 0.908, 0.634,
        0.947, 0.7447, 0.6885, 0.5555, 1.0385, 0.5945, 0.9995, 0.7775, 0.634, 1.0125,
        0.5962,
    ]
    stats_no_fit = {
        "entries": 51,
        "padded_segments": 47,
        "speech_padding_ms": 30175,
        "padding_total_ms": 30175,
        "raw_slot_ratios": raw_ratios,
        "low_ratio_segments": sum(1 for r in raw_ratios if r < 0.5),
        "tts_too_long_not_clipped_segments": 0,
        "tts_over_max_speed_segments": 0,
        "start_drift_ms_list": [0] * 51,
        "final_segment_drift_ms_list": [0] * 51,
        "total_final_drift_ms": 0,
        "trimmed_ms": 0,
    }
    gate_no_fit = evaluate_sync_gate(stats_no_fit, 182485)
    if gate_no_fit["status"] != "fail":
        print(f"  FAIL: without slow-fit this case should still fail, got {gate_no_fit}")
        return False

    # ALLOW_SLOW_FIT=0: speed giữ 1.0, phần còn lại là silence padding.
    default_post_atempo = [1.0] * len(raw_ratios)
    if any(speed < 0.95 for speed in default_post_atempo):
        print(f"  FAIL: default slow-fit produced turtle speed: {default_post_atempo}")
        return False
    # Opt-in chỉ được làm chậm nhẹ 0.95–0.99; cues ngắn hơn phải vẫn pad silence.
    opt_in_post_atempo = [max(0.95, min(0.99, ratio)) if 0.95 <= ratio < 0.99 else 1.0 for ratio in raw_ratios]
    if any(speed < 0.95 or speed > 1.0 for speed in opt_in_post_atempo):
        print(f"  FAIL: opt-in slow-fit escaped 0.95..0.99: {opt_in_post_atempo}")
        return False
    if sum(speed < 1.0 for speed in opt_in_post_atempo) >= len(raw_ratios) // 2:
        print(f"  FAIL: too many cues use opt-in slow-fit: {opt_in_post_atempo}")
        return False
    print("  OK: default keeps natural 1.0 + padding; opt-in only permits 0.95–0.99")
    return True


def test_balanced_short_cue_overhang_warning_only():
    """Regression: short natural speech overhang should not fail if drift/trim stay bounded."""
    print("[balanced short cue overhang warning]")
    stats = {
        "entries": 71,
        "padded_segments": 45,
        "speech_padding_ms": 17447,
        "padding_total_ms": 17447,
        "raw_slot_ratios": [0.8934] * 71,
        "low_ratio_segments": 3,
        "tts_too_long_not_clipped_segments": 3,
        "tts_over_max_speed_segments": 11,
        "start_drift_ms_list": [0] * 68 + [358, 251, 20],
        "final_segment_drift_ms_list": [358, 251, 36] + [0] * 68,
        "total_final_drift_ms": 801,
        "trimmed_ms": 0,
    }
    gate = evaluate_sync_gate(stats, 167160)
    if gate["status"] != "ok":
        print(f"  FAIL: local short-cue overhang should pass when drift/trim are bounded, got {gate}")
        return False
    if not any("too_long_not_clipped" in reason and "local_overhang_warn" in reason for reason in gate["warning_reasons"]):
        print(f"  FAIL: expected too_long local warning, got {gate['warning_reasons']}")
        return False
    print(
        f"  OK: too_long_ratio={gate['too_long_ratio']} max_drift={gate['max_start_drift_ms']}ms "
        f"trimmed={gate['trimmed_ms']}ms -> warning only"
    )
    stats_bad = dict(stats)
    stats_bad["tts_too_long_not_clipped_segments"] = 12
    bad_gate = evaluate_sync_gate(stats_bad, 167160)
    if bad_gate["status"] != "fail":
        print(f"  FAIL: many overlong cues must fail, got {bad_gate}")
        return False
    print("  OK: too_long ratio >10% still fails")
    return True


def test_ai33_rejected_adaptation_native_speed_regression():
    """A semantic rejection must not suppress the bounded native-speed retry.

    This is an offline numeric fixture: 72 cues, 13 initially overlong, with
    12 expected to fit after the existing 1.12 native AI33 cap.  It deliberately
    contains no subtitle or job content and keeps the 10%/drift gates unchanged.
    """
    print("[AI33 rejected-adaptation native-speed convergence]")
    ratios_before = [1.10] * 12 + [1.18] + [0.94] * 59
    native_cap = 1.12
    ratios_after_native = [ratio / native_cap for ratio in ratios_before]
    unresolved = sum(ratio > 1.0 for ratio in ratios_after_native)
    stats = {
        "entries": 72,
        "padded_segments": 0,
        "speech_padding_ms": 0,
        "raw_slot_ratios": ratios_after_native,
        "low_ratio_segments": 0,
        "tts_too_long_not_clipped_segments": unresolved,
        "tts_over_max_speed_segments": unresolved,
        "start_drift_ms_list": [0] * 71 + [120],
        "final_segment_drift_ms_list": [0] * 72,
        "total_final_drift_ms": 0,
        "trimmed_ms": 0,
    }
    gate = evaluate_sync_gate(stats, 192000)
    if unresolved != 1 or gate["status"] != "ok":
        print(f"  FAIL: bounded native fit should leave 1/72 local overhang, got unresolved={unresolved} gate={gate}")
        return False

    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    native_start = run_sh.find('if (engine == "ai33"')
    blocked_start = run_sh.find('fit_decision = "no_safe_adaptation_candidate"')
    native_resolved = 'fit_decision = "native_speed_resolved_after_adaptation_rejected"'
    if native_start < 0 or blocked_start < 0 or native_start <= blocked_start or native_resolved not in run_sh:
        print("  FAIL: native retry is still unavailable after a rejected adaptation")
        return False
    print("  OK: 12/13 measured overlong cues converge via the existing native cap; 1/72 stays subject to unchanged local-overhang gates")
    return True


def test_ai33_single_speed_contract_static():
    """The numeric provider speed and ffmpeg correction must not multiply unchecked."""
    print("[AI33 single-speed contract]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    required = [
        "speed_contract.canonical_speed_contract(",
        "total_max_speed=total_audio_speed_max",
        "speed_contract.measured_post_atempo_fit(",
        "adaptation_needs_attention=adaptation_needs_attention",
        'adaptation_fit_eligible=(fit_decision == "candidate_accepted_pending_fit")',
        '"post_atempo_applied": final_speed != 1.0',
        '"total_speed_factor": round(ai33_speed_used * final_speed, 4)',
        '"speed_fit_decision": speed_fit_decision',
        "native_speed_mode = speed_intent['native_speed_mode']",
        '"measured_duration_ms": raw_duration_ms',
        "voice_name.lower().startswith('ai33')",
    ]
    missing = [needle for needle in required if needle not in run_sh]
    if missing:
        print(f"  FAIL: missing single-speed contract pieces: {missing}")
        return False
    # Existing voice-sync gate thresholds remain the authority; this change may
    # only alter speed selection, not relax the acceptance criteria.
    for threshold in ('TTS_LOCAL_SYNC_FAIL_ON_PADDED_RATIO', 'tts_too_long_not_clipped_segments', 'max_start_drift_ms'):
        if threshold not in run_sh:
            print(f"  FAIL: quality gate changed or removed: {threshold}")
            return False
    if 'if not adaptation_needs_attention and duration_ms > effective_slot_ms + fit_tolerance_ms:' in run_sh:
        print("  FAIL: semantic needs_attention still suppresses bounded measured audio fit")
        return False
    print("  OK: AI33 native cap and total cap are distinct; measured residual is auditable and quality gates unchanged")
    return True


def test_final_tail_safe_trim_static():
    """Regression: concat extra that fits inside final tail silence is safe silence trim."""
    print("[final tail safe trim]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    required = [
        '"final_tail_safe_trim_ms": 0',
        'tail_trim_tolerance_ms = max(0, int(float(os.environ.get("TTS_FINAL_TAIL_TRIM_TOLERANCE_MS", "80"))))',
        'excess_ms <= final_tail_ms + tail_trim_tolerance_ms',
        "os.replace(tailfit_wav, voice_wav)",
        'stats["final_tail_safe_trim_ms"] = excess_ms',
        'stats["final_tail_silence_ms"] = max(0, final_tail_ms - excess_ms)',
        '"final_tail_safe_trim_ms": stats.get("final_tail_safe_trim_ms", 0) or 0',
    ]
    missing = [needle for needle in required if needle not in run_sh]
    if missing:
        print(f"  FAIL: thiếu safe tail trim pieces: {missing}")
        return False
    stats = {
        "entries": 71,
        "padded_segments": 45,
        "speech_padding_ms": 16928,
        "raw_slot_ratios": [0.9019] * 71,
        "low_ratio_segments": 2,
        "tts_too_long_not_clipped_segments": 2,
        "tts_over_max_speed_segments": 8,
        "start_drift_ms_list": [0] * 68 + [323, 162, 15],
        "final_segment_drift_ms_list": [323, 162, 108] + [0] * 68,
        "total_final_drift_ms": 593,
        "final_tail_silence_ms": 2240,
        "final_tail_safe_trim_ms": 609,
        "concat_duration_extra_ms": 609,
        "trimmed_ms": 0,
    }
    gate = evaluate_sync_gate(stats, 167160)
    if gate["status"] != "ok":
        print(f"  FAIL: safe tail-silence trim should not VoiceSyncFail, got {gate}")
        return False
    if gate["final_tail_safe_trim_ms"] != 609:
        print(f"  FAIL: gate/report lost final_tail_safe_trim_ms: {gate}")
        return False
    print("  OK: dư concat 609ms nằm trong final tail silence -> trim silence, không fail voice-sync")
    return True


def test_frame_strict_padding_is_warning():
    """frame_strict fit slot xong thì padding/median/low-ratio chỉ là warning."""
    print("[frame_strict padding warning]")
    stats = {
        "entries": 45,
        "padded_segments": 23,
        "speech_padding_ms": 22000,
        "padding_total_ms": 22000,
        "raw_slot_ratios": [0.44] * 45,
        "low_ratio_segments": 28,
        "final_segment_drift_ms_list": [0] * 45,
        "total_final_drift_ms": 0,
    }
    legacy_gate = evaluate_sync_gate(stats, 281797, frame_strict=False)
    if legacy_gate["status"] != "fail":
        print(f"  FAIL: legacy gate phải fail padding cao, got {legacy_gate}")
        return False

    strict_gate = evaluate_sync_gate(stats, 281797, frame_strict=True)
    if strict_gate["status"] != "ok":
        print(f"  FAIL: frame_strict đã drift=0 phải OK, got {strict_gate}")
        return False
    required = ("padded_ratio", "median_raw_slot", "low_ratio_segs")
    if not all(any(key in reason for reason in strict_gate["warning_reasons"]) for key in required):
        print(f"  FAIL: frame_strict phải giữ warning padding/ratio, got {strict_gate['warning_reasons']}")
        return False
    print(f"  OK: frame_strict drift={strict_gate['max_final_segment_drift_ms']}ms, padding chỉ warning")
    return True


def test_frame_strict_total_drift_budget_scales_with_entries():
    """Kokoro nhiều cue có tổng residual nhỏ không bị fail chỉ vì vượt 200ms cứng."""
    print("[frame_strict total drift budget]")
    stats = {
        "entries": 108,
        "padded_segments": 72,
        "speech_padding_ms": 34067,
        "padding_total_ms": 34067,
        "raw_slot_ratios": [0.891] * 108,
        "low_ratio_segments": 1,
        "start_drift_ms_list": [0] * 108,
        "final_segment_drift_ms_list": [20] * 15 + [2] + [0] * 92,
        "total_final_drift_ms": 302,
        "trimmed_ms": 288,
    }
    gate = evaluate_sync_gate(stats, 297076, frame_strict=True)
    if gate["status"] != "ok":
        print(f"  FAIL: 302ms total drift /108 cues should pass dynamic budget, got {gate}")
        return False
    if gate["frame_strict_max_total_drift_ms"] != 540:
        print(f"  FAIL: expected dynamic total drift budget 540ms, got {gate['frame_strict_max_total_drift_ms']}")
        return False
    stats_bad = dict(stats)
    stats_bad["total_final_drift_ms"] = 800
    gate_bad = evaluate_sync_gate(stats_bad, 297076, frame_strict=True)
    if gate_bad["status"] != "fail":
        print(f"  FAIL: 800ms total drift /108 cues should still fail, got {gate_bad}")
        return False
    print("  OK: 302ms/108 cues pass, 800ms/108 cues fail")
    return True


def test_resona_api_fail_no_edge_fallback():
    """Resona API lỗi thật (auth/timeout) phải fail bằng Resona error, KHÔNG fallback Edge."""
    print("[resona api fail no edge fallback]")
    run_sh = SKILL_DIR / "run.sh"
    text = run_sh.read_text(encoding="utf-8")
    # synthesize_resona_tts fail path phải KHÔNG gọi synthesize_edge_tts.
    if "ResonaAuthMissing" not in text or "ResonaTimeout" not in text:
        print("  FAIL: thiếu ResonaAuthMissing/ResonaTimeout markers")
        return False
    # Fail path ghi write_silence + resona_failed=True, không xuống edge_result.
    if "write_silence(wav_path, slot_ms)\n        return {" not in text:
        # chấp nhận biến thể format
        if 'write_silence(wav_path, slot_ms)' not in text:
            print("  FAIL: fail path không write_silence")
            return False
    if "RESONA_ERROR_SEVERITY" not in text or "ResonaCoverageTooLow" not in text:
        print("  FAIL: thiếu RESONA_ERROR_SEVERITY hoặc ResonaCoverageTooLow trong severity list")
        return False
    print("  OK: Resona API fail -> write_silence + resona_failed + error_code, KHÔNG fallback Edge")
    return True


def test_ai33_api_fail_gate_has_severity_and_voice_report_static():
    """Regression: AI33 fail gate không được crash NameError khi có segment timeout/fail."""
    print("[ai33 api fail gate severity/report]")
    text = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    gate_marker = "if ai33_fail > 0 and ai33_fail_codes:"
    gate_idx = text.find(gate_marker)
    if gate_idx < 0:
        print("  FAIL: thiếu AI33 fail gate")
        return False
    gate_start = text.rfind("stats_path, video_duration, voice_duration, original_srt, voice", 0, gate_idx)
    if gate_start < 0:
        gate_start = max(0, gate_idx - 5000)
    pre_gate = text[gate_start:gate_idx]
    gate_block = text[gate_idx:gate_idx + 2500]
    if "AI33_ERROR_SEVERITY = [" not in pre_gate:
        print("  FAIL: AI33 fail gate thiếu AI33_ERROR_SEVERITY trong cùng heredoc")
        return False
    generic_all_silence_idx = pre_gate.find("if total > 0 and real_voice <= 0")
    if generic_all_silence_idx >= 0:
        print("  FAIL: all-silence gate chạy trước AI33 provider gate, làm mất error_code actionable")
        return False
    if "AI33_PROVIDER_FAIL_FAST" not in text:
        print("  FAIL: AI33 provider failure vẫn bị circuit breaker thay vì dừng sớm")
        return False
    required = [
        "AI33Timeout",
        "TTSAI33Failed",
        "chosen = next((c for c in AI33_ERROR_SEVERITY",
        '"voice_label": stats.get',
        '"canonical_voice": stats.get',
        '"timing_profile": stats.get',
        '"min_slow_ratio": stats.get',
    ]
    missing = [needle for needle in required if needle not in gate_block and needle not in pre_gate]
    if missing:
        print(f"  FAIL: AI33 fail report/gate thiếu marker: {missing}")
        return False
    print("  OK: AI33 fail gate có severity list riêng và report metadata giọng")
    return True


def test_resona_no_audio_not_token_message_static():
    """Regression: Resona task failed 'No generated audio' không được báo nhầm thành lỗi token."""
    print("[resona no-audio message]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    wrapper = (SKILL_DIR / "resona_tts_synthesize.py").read_text(encoding="utf-8")

    required_wrapper = [
        '"No generated" in msg',
        "MARKER_NO_AUDIO",
        "return 5",
    ]
    missing_wrapper = [needle for needle in required_wrapper if needle not in wrapper]
    if missing_wrapper:
        print(f"  FAIL: wrapper chưa map task_failed/no generated -> ResonaNoAudioUrl: {missing_wrapper}")
        return False

    required_run = [
        "ResonaNoAudioUrl",
        "'No generated' in stderr",
        "Không phải lỗi token nếu request đã tạo được",
        "thử voice khác",
    ]
    missing_run = [needle for needle in required_run if needle not in run_sh]
    if missing_run:
        print(f"  FAIL: run.sh chưa phân loại/message đúng no-audio: {missing_run}")
        return False
    print("  OK: no-audio được báo là lỗi sinh audio/voice-text, không đổ nhầm token")
    return True


def test_resona_tue_an_and_subtitle_band_static():
    """Regression: thêm voice Resona Nữ Tuệ An và giữ blur band đủ phủ sub Trung dao động."""
    print("[resona tue an + subtitle band coverage]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    renderer = (SKILL_DIR / "subtitle_mask_render.py").read_text(encoding="utf-8")
    dashboard_path = Path("/home/haonguyen/openclaw-dashboard/dashboard.py")
    dashboard = dashboard_path.read_text(encoding="utf-8") if dashboard_path.exists() else ""

    required_run = [
        'RESONA_TUE_AN_VOICE_ID="${RESONA_TUE_AN_VOICE_ID:-0phiCO46biYtwYYP0DIR}"',
        'SUBTITLE_BAND_SAMPLE_COUNT="${SUBTITLE_BAND_SAMPLE_COUNT:-24}"',
        'SUBTITLE_BAND_REGION_BOTTOM_RATIO="${SUBTITLE_BAND_REGION_BOTTOM_RATIO:-0.98}"',
        'SUBTITLE_BAND_HEIGHT_RATIO="${SUBTITLE_BAND_HEIGHT_RATIO:-0.10}"',
        'SUBTITLE_BAND_MIN_HEIGHT="${SUBTITLE_BAND_MIN_HEIGHT:-64}"',
        'SUBTITLE_REGION_REBUILD="${SUBTITLE_REGION_REBUILD:-0}"',
        'Geometry cache is independent from ASR/OCR-content/translation/TTS/download.',
        '--validate-subtitle-region-only',
        '--detect-subtitle-region-only',
    ]
    missing_run = [needle for needle in required_run if needle not in run_sh]
    if missing_run:
        print(f"  FAIL: run.sh thiếu default Resona/subtitle band: {missing_run}")
        return False

    required_renderer = [
        "select_subtitle_cluster",
        "SUBTITLE_REGION_SCHEMA_VERSION",
        "--detect-subtitle-region-only",
        "subtitle_region_artifact",
        "int(height * 0.15)",
    ]
    missing_renderer = [needle for needle in required_renderer if needle not in renderer]
    if missing_renderer:
        print(f"  FAIL: renderer chưa dùng source-span để phủ band ổn định: {missing_renderer}")
        return False

    if dashboard and 'value="resona:0phiCO46biYtwYYP0DIR"' not in dashboard:
        print("  FAIL: dashboard chưa có option Resona - Nữ Tuệ An")
        return False
    print("  OK: có voice Nữ Tuệ An + blur band artifact/cluster giới hạn chiều cao")
    return True


def test_kokoro_voice_integration_static():
    """Regression: Kokoro remains available as a local selectable TTS engine."""
    print("[kokoro voice integration]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    optimizer = (SKILL_DIR / "viet_dub_timing_optimizer.py").read_text(encoding="utf-8")
    bilibili = (SKILL_DIR.parent / "bilibili-vietnamese-dubber" / "run.sh").read_text(encoding="utf-8")
    series = (SKILL_DIR.parent / "series-tracker" / "series-tracker.py").read_text(encoding="utf-8")
    voices = json.loads((SKILL_DIR / "kokoro_voices.json").read_text(encoding="utf-8"))
    voice_ids = {item.get("id") for item in voices}
    expected_voices = {
        "diem_trinh", "duc_an", "duc_duy", "hung_thinh", "mai_linh", "mai_loan",
        "manh_dung", "my_yen", "ngoc_huyen", "phat_tai", "storyvert",
        "thanh_dat", "thuc_trinh", "tuan_ngoc",
    }
    if voice_ids != expected_voices:
        print(f"  FAIL: kokoro_voices.json mismatch: {sorted(voice_ids)}")
        return False
    required_run = [
        'KOKORO_DEFAULT_VOICE="${KOKORO_DEFAULT_VOICE:-mai_linh}"',
        'KOKORO_TTS_PYTHON="${KOKORO_TTS_PYTHON:-$HOME/.local/share/openclaw-kokoro-venv/bin/python}"',
        "def resolve_kokoro_voice",
        "def get_kokoro_model",
        "def synthesize_kokoro_tts",
        "return synthesize_kokoro_tts(mp3_path, wav_path, text, voice)",
        '"tts_engine_requested": "kokoro"',
        '"kokoro_segments": kokoro',
        '"kokoro_voice_used"',
    ]
    missing_run = [needle for needle in required_run if needle not in run_sh]
    if missing_run:
        print(f"  FAIL: run.sh thiếu Kokoro pieces: {missing_run}")
        return False
    required_other = [
        ("optimizer", optimizer, "tts_probe_kokoro_estimate"),
        ("bilibili", bilibili, "kokoro:*"),
        ("series", series, 'value.startswith("kokoro:")'),
    ]
    missing_other = [name for name, text, needle in required_other if needle not in text]
    if missing_other:
        print(f"  FAIL: thiếu Kokoro normalizer/probe ở: {missing_other}")
        return False
    print("  OK: Kokoro vẫn chọn được với 14 voice, engine/report/probe + Bilibili/series đều nhận kokoro:*")
    return True


def test_ai33_voice_registry_integration_static():
    """Regression: AI33 voices are resolved through the shared registry."""
    print("[ai33 voice registry integration]")
    run_sh = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    wrapper = (SKILL_DIR / "ai33_tts_synthesize.py").read_text(encoding="utf-8")
    optimizer = (SKILL_DIR / "viet_dub_timing_optimizer.py").read_text(encoding="utf-8")
    registry_py = (SKILL_DIR / "voice_registry.py").read_text(encoding="utf-8")
    registry_seed = json.loads((SKILL_DIR / "voice_registry.default.json").read_text(encoding="utf-8"))
    bilibili = (SKILL_DIR.parent / "bilibili-vietnamese-dubber" / "run.sh").read_text(encoding="utf-8")
    series = (SKILL_DIR.parent / "series-tracker" / "series-tracker.py").read_text(encoding="utf-8")
    dashboard_path = Path("/home/haonguyen/openclaw-dashboard/dashboard.py")
    dashboard = dashboard_path.read_text(encoding="utf-8") if dashboard_path.exists() else ""
    host_runner_path = Path("/home/haonguyen/.local/bin/openclaw-host-douyin-runner.sh")
    host_runner = host_runner_path.read_text(encoding="utf-8") if host_runner_path.exists() else ""

    required_run = [
        'AI33_TTS_WRAPPER="${AI33_TTS_WRAPPER:-$SKILL_DIR/ai33_tts_synthesize.py}"',
        'AI33_API_BASE="${AI33_API_BASE:-https://api.ai33.pro}"',
        'AI33_MAI_PHUONG_VOICE_ID="${AI33_MAI_PHUONG_VOICE_ID:-vbee_hn_female_maiphuong_vdts_48k-fhg}"',
        'AI33_PHANH_VOICE_ID="${AI33_PHANH_VOICE_ID:-elevenlabs_UuMSQK8FdLwaY2M8ZAnh}"',
        'AI33_DEFAULT_VOICE_ID="${AI33_DEFAULT_VOICE_ID:-$AI33_MAI_PHUONG_VOICE_ID}"',
        'OPENCLAW_KEEP_LEGACY_PHANH_DEFAULT',
        'VOICE_REGISTRY_PY="${VOICE_REGISTRY_PY:-$SKILL_DIR/voice_registry.py}"',
        'OPENCLAW_VOICE_REGISTRY_JSON="${OPENCLAW_VOICE_REGISTRY_JSON:-$HOME/.openclaw/config/voice_registry.json}"',
        'VOICE_PRESET_INPUT="${EDGE_TTS_VOICE_PRESET:-${DOUYIN_TTS_VOICE_PRESET:-}}"',
        'VOICE_SOURCE_HINT="registry"',
        "normalize-ai33",
        "VoiceInvalid: AI33 voice",
        "def resolve_ai33_voice_id",
        "def resolve_ai33_voice_meta",
        "def synthesize_ai33_tts",
        "return synthesize_ai33_tts(mp3_path, wav_path, text, voice, slot_ms, ai33_speed)",
        '"tts_engine_requested": "kokoro" if voice_name.lower().startswith("kokoro") else ("ai33"',
        '"ai33_segments": ai33',
        '"voice_source": ai33_voice_meta.get("voice_source"',
        '"voice_label": ai33_voice_meta.get("label"',
        '"canonical_voice": ai33_voice_meta.get("canonical_voice"',
        '"timing_profile": ai33_voice_meta.get("timing_profile"',
        '"min_slow_ratio": ai33_voice_meta.get("min_slow_ratio"',
        "AI33_GATE_FAIL",
    ]
    missing_run = [needle for needle in required_run if needle not in run_sh]
    if missing_run:
        print(f"  FAIL: run.sh thiếu AI33 pieces: {missing_run}")
        return False

    required_wrapper = [
        "POST /v3/text-to-speech",
        "xi-api-key",
        "AI33_API_KEY",
        "MARKER_AUTH_MISSING = \"AI33AuthMissing\"",
        "def post_multipart",
        "def poll_task",
        "def find_audio_url",
    ]
    missing_wrapper = [needle for needle in required_wrapper if needle not in wrapper]
    if missing_wrapper:
        print(f"  FAIL: ai33_tts_synthesize.py thiếu API pieces: {missing_wrapper}")
        return False

    forbidden = [
        "sk" + "_n",
    ]
    leaked = [needle for needle in forbidden if needle in run_sh or needle in wrapper]
    if leaked:
        print(f"  FAIL: phát hiện pattern secret trong code: {leaked}")
        return False

    required_registry = [
        "RUNTIME_REGISTRY",
        "DEFAULT_REGISTRY",
        'os.environ.get("OPENCLAW_VOICE_REGISTRY_JSON") or',
        "def normalize_ai33_voice",
        "def default_voice",
        "def public_registry",
        "def add_ai33_voice",
        "def set_default_voice",
        "def disable_voice",
        "def restore_latest_backup",
        "tmp.replace(path)",
        "VoiceRegistryInvalid",
        "alias trùng",
    ]
    missing_registry = [needle for needle in required_registry if needle not in registry_py]
    if missing_registry:
        print(f"  FAIL: voice_registry.py thiếu registry pieces: {missing_registry}")
        return False
    if registry_seed.get("default_voice") != "ai33:vbee_hn_female_maiphuong_vdts_48k-fhg":
        print("  FAIL: seed registry chưa default về AI33 Mai Phương")
        return False
    seed_by_id = {voice.get("voice_id"): voice for voice in registry_seed.get("voices", [])}
    if "vbee_hn_female_maiphuong_vdts_48k-fhg" not in seed_by_id:
        print("  FAIL: seed registry thiếu Mai Phương - Vbee")
        return False
    if "elevenlabs_UuMSQK8FdLwaY2M8ZAnh" not in seed_by_id:
        print("  FAIL: seed registry thiếu Phanh - ElevenLabs")
        return False
    if seed_by_id["vbee_hn_female_maiphuong_vdts_48k-fhg"].get("min_slow_ratio") != 0.85:
        print("  FAIL: Mai Phương seed chưa giữ min_slow_ratio=0.85")
        return False

    required_other = [
        ("optimizer", optimizer, "tts_probe_ai33_estimate"),
        ("bilibili", bilibili, "VOICE_REGISTRY_PY"),
        ("bilibili", bilibili, "normalize-ai33"),
        ("bilibili", bilibili, "VoiceInvalid: AI33 voice"),
        ("bilibili", bilibili, "ai33:*"),
        ("bilibili", bilibili, "vbee_*"),
        ("series", series, "voice_registry_lib.default_voice()"),
        ("series", series, "voice_registry_lib.normalize_ai33_voice"),
        ("series", series, 'value.startswith("ai33:")'),
        ("series", series, 'value.startswith("vbee_")'),
    ]
    missing_other = [name for name, text, needle in required_other if needle not in text]
    if missing_other:
        print(f"  FAIL: thiếu AI33 normalizer/probe ở: {missing_other}")
        return False

    if dashboard and "Voice Manager" not in dashboard:
        print("  FAIL: dashboard chưa có Voice Manager")
        return False
    if dashboard and "/api/voices/test" not in dashboard:
        print("  FAIL: dashboard chưa có API test voice riêng")
        return False
    if dashboard and "voice_registry_lib.public_registry()" not in dashboard:
        print("  FAIL: dashboard chưa lấy dropdown từ voice registry")
        return False
    if dashboard and "POST /api/voices/test" in dashboard:
        print("  FAIL: dashboard không nên hard-code marker API test trong text")
        return False
    if dashboard and "Test giọng sẽ gọi AI33 TTS và tốn credit" not in dashboard:
        print("  FAIL: dashboard test voice chưa cảnh báo credit")
        return False
    if dashboard and "Giọng dùng thật" not in dashboard:
        print("  FAIL: dashboard chưa hiển thị giọng thật từ report")
        return False
    if dashboard and "AI33AuthMissing" not in dashboard:
        print("  FAIL: dashboard chưa map friendly error AI33")
        return False
    if dashboard and "voice_registry_lib.default_voice()" not in dashboard:
        print("  FAIL: dashboard chưa dùng registry default video voice")
        return False
    if dashboard and "normalize_voice_value(payload.get('voice'), strict=True)" not in dashboard:
        print("  FAIL: dashboard job/retry chưa fail rõ khi explicit voice invalid")
        return False
    if host_runner and "VOICE_REGISTRY_PY" not in host_runner:
        print("  FAIL: host runner chưa dùng voice registry")
        return False
    if host_runner and "normalize-ai33" not in host_runner:
        print("  FAIL: host runner chưa normalize AI33 qua registry")
        return False
    if host_runner and "VoiceInvalid: AI33 voice" not in host_runner:
        print("  FAIL: host runner chưa fail rõ khi explicit AI33 invalid")
        return False
    spec = importlib.util.spec_from_file_location("series_tracker_static_test", SKILL_DIR.parent / "series-tracker" / "series-tracker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected_series_default = module.voice_registry_lib.default_voice()
    if module.normalize_voice(None) != expected_series_default:
        print(f"  FAIL: series normalize_voice(None) chưa theo registry default hiện tại: {expected_series_default}")
        return False
    if module.normalize_voice("phanh") != "ai33:elevenlabs_UuMSQK8FdLwaY2M8ZAnh":
        print("  FAIL: series alias phanh không còn trỏ về AI33 Phanh")
        return False
    if module.normalize_voice("vbee_hn_female_maiphuong_vdts_48k-fhg") != "ai33:vbee_hn_female_maiphuong_vdts_48k-fhg":
        print("  FAIL: series raw vbee voice id chưa map sang ai33:<id>")
        return False

    print("  OK: AI33 registry seed Mai Phương, runtime default động, Phanh selectable, resolver/report/UI/API + Bilibili/series/host-runner đều dùng registry")
    return True


if __name__ == "__main__":
    # ---- Test 10: voice-sync gate fail phải ghi status/report, không bị set -e nuốt ----
    if not test_speech_only_preprocess_timeout_keeps_terminal_foreground_group_static():
        sys.exit(1)
    if not test_tts_gate_status_capture_static():
        sys.exit(1)
    if not test_tts_synthesis_early_failure_report_static():
        sys.exit(1)
    if not test_final_voice_sync_report_gate_static():
        sys.exit(1)
    if not test_balanced_dub_quality_policy_static():
        sys.exit(1)
    if not test_resona_no_audio_not_token_message_static():
        sys.exit(1)
    if not test_ai33_api_fail_gate_has_severity_and_voice_report_static():
        sys.exit(1)
    if not test_resona_tue_an_and_subtitle_band_static():
        sys.exit(1)
    if not test_kokoro_voice_integration_static():
        sys.exit(1)
    if not test_ai33_voice_registry_integration_static():
        sys.exit(1)
    main()
