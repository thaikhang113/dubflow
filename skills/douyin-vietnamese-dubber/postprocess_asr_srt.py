#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
from pathlib import Path

MEANINGFUL_RE = re.compile(r"[\w\u4e00-\u9fff]", re.UNICODE)


def parse_ms(ts):
    hh, mm, rest = ts.split(":")
    ss, ms = rest.split(",")
    return ((int(hh)*60 + int(mm))*60 + int(ss))*1000 + int(ms)


def fmt_ms(ms):
    ms = max(0, int(ms))
    hh, rem = divmod(ms, 3600000)
    mm, rem = divmod(rem, 60000)
    ss, mmm = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{mmm:03d}"


def parse_srt(path):
    content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    entries = []
    if not content:
        return entries
    for block in re.split(r"\n\s*\n", content):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->", 1)]
        entries.append({"start_ms": parse_ms(start_raw), "end_ms": parse_ms(end_raw), "text": " ".join(lines[2:]).strip()})
    return entries


def write_srt(path, entries):
    out = []
    for idx, entry in enumerate(entries, 1):
        out.append(str(idx))
        out.append(f"{fmt_ms(entry['start_ms'])} --> {fmt_ms(entry['end_ms'])}")
        out.append(entry["text"])
        out.append("")
    Path(path).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def overlap_ratio(entry, regions):
    start = entry["start_ms"] / 1000
    end = entry["end_ms"] / 1000
    dur = max(0.001, end - start)
    overlap = 0.0
    for region in regions:
        overlap += max(0.0, min(end, region["end"]) - max(start, region["start"]))
    return overlap / dur


def repeated_text(text):
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 6 and re.search(r"(.)\1{5,}", compact):
        return True
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text, re.UNICODE)
    if len(tokens) >= 6:
        most = max(tokens.count(tok) for tok in set(tokens))
        if most / len(tokens) >= 0.65:
            return True
    return False

def compact_text(text):
    return re.sub(r"\s+", "", text or "")

def detect_repeated_bursts(entries, window_sec, min_count, short_max_chars, pair_min_count):
    flagged = set()
    bursts = []
    normalized = [compact_text(entry["text"]) for entry in entries]
    for idx, entry in enumerate(entries):
        text = normalized[idx]
        if not text or len(text) > short_max_chars:
            continue
        window_end = entry["start_ms"] + int(window_sec * 1000)
        indexes = [j for j in range(idx, len(entries)) if entries[j]["start_ms"] <= window_end and normalized[j] == text]
        if len(indexes) >= min_count:
            flagged.update(indexes)
            bursts.append({"type": "single_text", "text": text, "count": len(indexes), "start_ms": entry["start_ms"], "end_ms": entries[indexes[-1]]["end_ms"]})
    for idx in range(len(entries) - 1):
        a = normalized[idx]
        b = normalized[idx + 1]
        if not a or not b or len(a) > short_max_chars or len(b) > short_max_chars:
            continue
        window_end = entries[idx]["start_ms"] + int(window_sec * 1000)
        pair_indexes = []
        j = idx
        while j < len(entries) - 1 and entries[j]["start_ms"] <= window_end:
            if normalized[j] == a and normalized[j + 1] == b:
                pair_indexes.extend([j, j + 1])
                j += 2
            else:
                j += 1
        if len(pair_indexes) // 2 >= pair_min_count:
            flagged.update(pair_indexes)
            bursts.append({"type": "pair_text", "text": f"{a}|{b}", "count": len(pair_indexes) // 2, "start_ms": entries[idx]["start_ms"], "end_ms": entries[pair_indexes[-1]]["end_ms"]})
    top = {}
    for text in normalized:
        if text and len(text) <= short_max_chars:
            top[text] = top.get(text, 0) + 1
    return flagged, bursts, sorted(top.items(), key=lambda item: item[1], reverse=True)[:20]


def too_short_meaningless(entry):
    text = entry["text"].strip()
    dur = (entry["end_ms"] - entry["start_ms"]) / 1000
    if dur <= 0.35 and len(text) <= 2:
        return True
    if not MEANINGFUL_RE.search(text):
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--srt", required=True)
    parser.add_argument("--speech-regions-json", required=True)
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--hallucination-report-json", default="")
    parser.add_argument("--min-overlap", type=float, default=0.20)
    parser.add_argument("--repeat-burst-window-sec", type=float, default=float(os.environ.get("ASR_REPEAT_BURST_WINDOW_SEC", "90")))
    parser.add_argument("--repeat-text-min-count", type=int, default=int(os.environ.get("ASR_REPEAT_TEXT_MIN_COUNT", "8")))
    parser.add_argument("--repeat-short-text-max-chars", type=int, default=int(os.environ.get("ASR_REPEAT_SHORT_TEXT_MAX_CHARS", "8")))
    parser.add_argument("--repeat-pair-min-count", type=int, default=int(os.environ.get("ASR_REPEAT_PAIR_MIN_COUNT", "4")))
    args = parser.parse_args()

    srt_path = Path(args.srt)
    backup = srt_path.with_suffix(".raw.srt")
    if not backup.exists():
        shutil.copy2(srt_path, backup)
    entries = parse_srt(srt_path)
    try:
        regions = json.load(open(args.speech_regions_json, encoding="utf-8"))
    except Exception:
        regions = []
    kept = []
    dropped = []
    burst_indexes, bursts, top_repeated_texts = detect_repeated_bursts(
        entries,
        args.repeat_burst_window_sec,
        args.repeat_text_min_count,
        args.repeat_short_text_max_chars,
        args.repeat_pair_min_count,
    )
    for index, entry in enumerate(entries):
        reasons = []
        if regions and overlap_ratio(entry, regions) < args.min_overlap:
            reasons.append("outside_speech_region")
        if repeated_text(entry["text"]):
            reasons.append("repeated_text")
        if index in burst_indexes:
            reasons.append("repeated_burst")
        if too_short_meaningless(entry):
            reasons.append("too_short_or_meaningless")
        if reasons:
            dropped.append({**entry, "reasons": reasons})
        else:
            kept.append(entry)
    write_srt(srt_path, kept)
    hallucination = {
        "repeated_burst_count": len(bursts),
        "dropped_burst_segments": sum(1 for item in dropped if "repeated_burst" in item.get("reasons", [])),
        "top_repeated_texts": top_repeated_texts,
        "bursts": bursts[:100],
        "severe": len(bursts) > 0 and sum(1 for item in dropped if "repeated_burst" in item.get("reasons", [])) >= args.repeat_text_min_count,
        "config": {
            "window_sec": args.repeat_burst_window_sec,
            "text_min_count": args.repeat_text_min_count,
            "short_text_max_chars": args.repeat_short_text_max_chars,
            "pair_min_count": args.repeat_pair_min_count,
        },
    }
    report = {
        "input_segments": len(entries),
        "kept_segments": len(kept),
        "dropped_segments": len(dropped),
        "dropped": dropped,
        "hallucination": hallucination,
        "quality_fields": {
            "no_speech_prob": "unavailable_with_whisper_cpp",
            "avg_logprob": "unavailable_with_whisper_cpp",
            "confidence": "unavailable_with_whisper_cpp",
            "note": "If faster-whisper is used later, enable vad_filter=True and condition_on_previous_text=False and persist these fields per segment.",
        },
    }
    Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.hallucination_report_json:
        Path(args.hallucination_report_json).write_text(json.dumps(hallucination, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ASR postprocess OK: kept={len(kept)} dropped={len(dropped)}", flush=True)


if __name__ == "__main__":
    main()
