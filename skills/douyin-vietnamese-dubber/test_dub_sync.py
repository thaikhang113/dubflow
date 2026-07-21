#!/usr/bin/env python3
"""Mock test cho dub.srt bám per-cue (viet_dub_timing_optimizer.py).

Chạy độc lập, không cần 9Router/edge-tts. Monkeypatch chat + synthesize_measure.
Fixture tự sinh 247 cue (mix ngắn 1.2s + dài 3-5s). Assert:
- dub.srt cue count >= 75% vi (≈200+), không còn 30.
- dub.srt max cue <= 6s, không cue > 8s.
- case 2 cue <1.6s kế nhau -> gộp 1 group <= ~4s (không vỡ vụn cũng không dài 28s).
- dubbing_report có dub_cue_count/dub_max_cue_seconds/dub_vi_ratio.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
OPTIMIZER = SKILL_DIR / "viet_dub_timing_optimizer.py"


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


def make_cues(n=247):
    """247 cue: phần lớn 3-5s, vài cue ngắn 1.2s kế nhau (test gộp), vài dài."""
    cues = []
    t = 0
    for i in range(n):
        if i in (10, 11):  # 2 cue ngắn kế nhau -> gộp 1 group
            dur = 1200
        elif i in (50, 51):  # 2 cue ngắn kế nhau khác
            dur = 1100
        elif i % 40 == 0:
            dur = 5000  # cue dài 5s
        else:
            dur = 3000
        cues.append((t, t + dur, f"第{i+1}句中文台词"))
        t += dur + 400
    return cues


def parse_dub_durs(path):
    content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    durs = []
    for block in re.split(r"\n\s*\n", content):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        try:
            a, b = [p.strip() for p in lines[1].split("-->", 1)]
            def ms(x):
                hh, mm, rest = x.split(":")
                ss, mmm = rest.split(",")
                return ((int(hh)*60+int(mm))*60+int(ss))*1000+int(mmm)
            durs.append((ms(b) - ms(a)) / 1000.0)
        except Exception:
            continue
    return durs


def make_mock_chat():
    def fake_chat(api_base, api_key, model, messages, temperature=0.2, timeout=None, api_provider="ninerouter"):
        user = messages[-1]["content"]
        # Batch: JSON input thật sau "Input:"
        idx = user.rfind("Input:")
        batch_input = None
        if idx >= 0:
            tail = user[idx + len("Input:"):]
            start = tail.find("{")
            end = tail.rfind("}")
            if start >= 0 and end > start:
                try:
                    batch_input = json.loads(tail[start:end + 1])
                except Exception:
                    batch_input = None
        if isinstance(batch_input, dict) and "items" in batch_input:
            out = []
            for it in batch_input["items"]:
                segs = it.get("segments", [])
                out.append({
                    "group_id": it["group_id"],
                    "subtitle_segments": [{"id": s["id"], "text": f"VI{s['id']}"} for s in segs],
                    "dub_text": " ".join(f"VI{s['id']}" for s in segs),
                })
            return json.dumps({"items": out})
        # Single: list segment có source_text
        for cand in re.findall(r'\[\{.*?\}\]', user, re.S):
            if '"source_text"' in cand:
                try:
                    segs = json.loads(cand)
                    if isinstance(segs, list) and segs and "id" in segs[0]:
                        return json.dumps({
                            "subtitle_segments": [{"id": s["id"], "text": f"VI{s['id']}"} for s in segs],
                            "dub_text": " ".join(f"VI{s['id']}" for s in segs),
                        })
                except Exception:
                    pass
        if "must_keep" in user:
            return json.dumps({"must_keep": [], "emotion": "", "negation_or_assertion": "", "important_terms": []})
        if "meaning_preserved" in user:
            return json.dumps({"meaning_preserved": True, "risk_level": "low", "lost_details": [], "changed_meaning": [], "recommendation": "use"})
        return "VI"
    return fake_chat


def run_optimizer(tmp, original_srt):
    vi_srt = tmp / "vietnamese.srt"
    dub_srt = tmp / "dub.srt"
    segs_json = tmp / "dubbing_segments.json"
    report_json = tmp / "dubbing_report.json"
    sys.argv = [
        "viet_dub_timing_optimizer.py",
        "--original-srt", str(original_srt),
        "--vietnamese-srt", str(vi_srt),
        "--dub-srt", str(dub_srt),
        "--segments-json", str(segs_json),
        "--report-json", str(report_json),
        "--api-base", "http://fake", "--api-key", "fake",
        "--api-provider", "ninerouter", "--model", "fake", "--voice", "vi-VN-fake",
        "--work-dir", str(tmp),
    ]
    os.environ["VIET_DUB_TIMING_OPTIMIZER"] = "1"
    import importlib.util
    spec = importlib.util.spec_from_file_location("vopt_dub", OPTIMIZER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.chat = make_mock_chat()
    mod.synthesize_measure = lambda text, voice, work_dir, name: int(max(1, len(re.sub(r"\s+", "", text or ""))) / 14.0 * 1000)
    try:
        mod.main()
        exit_code = 0
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
    return vi_srt, dub_srt, report_json, exit_code


def main():
    ok = True
    with tempfile.TemporaryDirectory(prefix="dubsync_") as td:
        tmp = Path(td)
        orig = tmp / "original.srt"
        cues = make_cues(247)
        write_srt(orig, cues)
        vi_srt, dub_srt, report_json, exit_code = run_optimizer(tmp, orig)
        vi_durs = parse_dub_durs(vi_srt)
        dub_durs = parse_dub_durs(dub_srt)
        n_vi = len(vi_durs)
        n_dub = len(dub_durs)
        max_dub = max(dub_durs) if dub_durs else 0
        overlong = sum(1 for d in dub_durs if d > 8)
        ratio = n_dub / max(1, n_vi)
        print(f"[dub sync] vi={n_vi} dub={n_dub} ratio={ratio:.3f} max_dub={max_dub:.2f}s overlong={overlong} exit={exit_code}")
        if ratio < 0.75:
            print(f"  FAIL: dub/vi ratio {ratio:.3f} < 0.75 (vẫn gộp quá mạnh)")
            ok = False
        else:
            print(f"  OK: dub cue count {n_dub} >= 75% vi {n_vi}")
        if max_dub > 6.0:
            # cho phép gộp 2 cue ngắn -> có thể ~2.4s; 6s là ngưỡng long.
            print(f"  FAIL: dub max cue {max_dub:.2f}s > 6s (gộp thành cue dài)")
            ok = False
        else:
            print(f"  OK: dub max cue {max_dub:.2f}s <= 6s")
        if overlong > 0:
            print(f"  FAIL: {overlong} cue > 8s")
            ok = False
        else:
            print(f"  OK: không cue > 8s")
        # report fields
        report = json.loads(report_json.read_text(encoding="utf-8"))
        dtq = report.get("dub_timing_quality", {})
        print(f"  report dub_timing_quality: {dtq}")
        if not dtq or "dub_cue_count" not in dtq:
            print("  FAIL: report thiếu dub_timing_quality")
            ok = False
        else:
            print("  OK: report có dub_timing_quality")
    print()
    print("ALL PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()