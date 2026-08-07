#!/usr/bin/env python3
import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
MOJIBAKE_RE = re.compile(r"(?:Ã.|Ä.|Æ.|áº|á»)")
TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ỹĐđ]+", re.UNICODE)


def normalize_spoken_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    text = text.translate(str.maketrans({"，": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";"}))
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", normalize_spoken_text(text).lower())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return TOKEN_RE.findall(folded)


def _has_repeated_short_token(tokens: list[str]) -> bool:
    if len(tokens) < 3:
        return False
    counts = Counter(token for token in tokens if len(token) <= 3)
    return any(count >= 3 and count / len(tokens) >= 0.5 for count in counts.values())


def text_quality_issues(text: str) -> list[str]:
    normalized = normalize_spoken_text(text)
    issues = []
    if not normalized:
        issues.append("empty")
    if CJK_RE.search(normalized):
        issues.append("contains_cjk")
    if MOJIBAKE_RE.search(normalized):
        issues.append("mojibake")
    if _has_repeated_short_token(_tokens(normalized)):
        issues.append("repeated_short_token")
    return issues


def _srt_seconds(value: str) -> float:
    hh, mm, rest = value.strip().split(":")
    ss, ms = rest.replace(".", ",").split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms[:3].ljust(3, "0")) / 1000.0


def parse_srt(path: str | Path) -> list[dict]:
    blocks = re.split(r"\n\s*\n", Path(path).read_text(encoding="utf-8", errors="replace").strip())
    events = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->", 1)]
        events.append({
            "index": len(events) + 1,
            "start": _srt_seconds(start_raw),
            "end": _srt_seconds(end_raw),
            "start_raw": start_raw,
            "end_raw": end_raw,
            "text": normalize_spoken_text(" ".join(lines[2:])),
        })
    return events


def token_similarity(expected: str, observed: str) -> float:
    left, right = Counter(_tokens(expected)), Counter(_tokens(observed))
    if not left:
        return 1.0 if not right else 0.0
    overlap = sum((left & right).values())
    precision = overlap / max(1, sum(right.values()))
    recall = overlap / sum(left.values())
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def compare_transcripts(expected: list[dict], observed: list[dict], cue_ids=None) -> dict:
    selected = set(int(value) for value in cue_ids) if cue_ids else None
    cue_reports = []
    critical = []
    warnings = []
    for cue in expected:
        cue_id = int(cue.get("index") or len(cue_reports) + 1)
        if selected is not None and cue_id not in selected:
            continue
        matches = [
            item for item in observed
            if min(float(cue["end"]), float(item["end"])) > max(float(cue["start"]), float(item["start"]))
        ]
        heard = normalize_spoken_text(" ".join(str(item.get("text") or "") for item in matches))
        similarity = token_similarity(str(cue.get("text") or ""), heard)
        expected_tokens = _tokens(str(cue.get("text") or ""))
        heard_tokens = _tokens(heard)
        reasons = []
        level = "ok"
        if _has_repeated_short_token(heard_tokens):
            reasons.append("repeated_short_token")
            level = "critical"
        if expected_tokens and len(heard_tokens) <= max(0, int(len(expected_tokens) * 0.25)):
            reasons.append("transcript_missing")
            level = "critical"
        elif similarity < 0.45 and level != "critical":
            reasons.append("low_similarity")
            level = "warning"
        if level == "critical":
            critical.append(cue_id)
        elif level == "warning":
            warnings.append(cue_id)
        cue_reports.append({
            "cue_id": cue_id,
            "expected": normalize_spoken_text(str(cue.get("text") or "")),
            "observed": heard,
            "similarity": round(similarity, 4),
            "level": level,
            "reasons": reasons,
        })
    status = "fail" if critical else ("warning" if warnings else "ok")
    return {
        "status": status,
        "critical_cue_ids": critical,
        "warning_cue_ids": warnings,
        "cues": cue_reports,
    }


def build_retry_overrides(report: dict) -> dict[str, str]:
    critical = {int(value) for value in report.get("critical_cue_ids") or []}
    overrides = {}
    for cue in report.get("cues") or []:
        cue_id = int(cue.get("cue_id") or 0)
        if cue_id not in critical:
            continue
        text = normalize_spoken_text(cue.get("expected"))
        if text and text[-1] not in ".!?":
            text += "."
        if text:
            overrides[str(cue_id)] = text
    return overrides


def write_text_gate_report(srt_path: str | Path, report_path: str | Path) -> dict:
    cues = []
    failed = []
    for event in parse_srt(srt_path):
        issues = text_quality_issues(event["text"])
        cues.append({"cue_id": event["index"], "text": event["text"], "issues": issues})
        if issues:
            failed.append(event["index"])
    report = {"status": "fail" if failed else "ok", "failed_cue_ids": failed, "cues": cues}
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    text_gate = sub.add_parser("text-gate")
    text_gate.add_argument("--srt", required=True)
    text_gate.add_argument("--report", required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("--expected-srt", required=True)
    compare.add_argument("--observed-srt", required=True)
    compare.add_argument("--report", required=True)
    compare.add_argument("--cue-ids", default="")
    retry = sub.add_parser("retry-overrides")
    retry.add_argument("--report", required=True)
    retry.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "text-gate":
        return 8 if write_text_gate_report(args.srt, args.report)["status"] == "fail" else 0
    if args.command == "compare":
        cue_ids = [int(value) for value in args.cue_ids.split(",") if value.strip()] if args.cue_ids else None
        report = compare_transcripts(parse_srt(args.expected_srt), parse_srt(args.observed_srt), cue_ids=cue_ids)
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 8 if report["status"] == "fail" else 0
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    Path(args.output).write_text(json.dumps(build_retry_overrides(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
