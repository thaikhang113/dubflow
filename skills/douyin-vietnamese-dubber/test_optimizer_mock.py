#!/usr/bin/env python3
"""Mock test cho viet_dub_timing_optimizer.py: verify subtitle per-cue, dub grouped.

Chạy độc lập, không cần 9Router/edge-tts/ffmpeg. Monkeypatch:
- chat(): trả JSON canned theo contract mới (subtitle_segments per-cue + dub_text gộp).
- synthesize_measure(): trả duration giả (không gọi TTS thật).

Fixture: /mnt/hdd500/video douyin vietsub/Bilibili/input-20260627-224745/original.srt
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
OPTIMIZER = SKILL_DIR / "viet_dub_timing_optimizer.py"
FIXTURE = Path("/mnt/hdd500/video douyin vietsub/Bilibili/input-20260627-224745/original.srt")


def parse_srt_cues(path):
    """Trả list (index, start_ms, end_ms) theo ordinal trong file."""
    content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    out = []
    for block in re.split(r"\n\s*\n", content):
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        try:
            a, b = [p.strip() for p in lines[1].split("-->", 1)]
            def ms(t):
                hh, mm, rest = t.split(":")
                ss, mmm = rest.split(",")
                return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000 + int(mmm)
            out.append((ms(a), ms(b)))
        except Exception:
            continue
    return out


def make_mock_chat():
    """chat() giả: parse prompt JSON, trả subtitle_segments + dub_text.

    Behavior giả: mỗi segment id -> "VI<id>". dub_text = gộp "VI<id> ..." cho group.
    Có toggle rơi vào path single translate_group (prompt 1 group) vs batch.
    """
    calls = {"n": 0}

    def fake_chat(api_base, api_key, model, messages, temperature=0.2, timeout=None, api_provider="ninerouter"):
        calls["n"] += 1
        user = messages[-1]["content"]
        # Batch: JSON input thật nằm SAU "Input:\n" (instruction có JSON ví dụ trước đó).
        batch_input = None
        idx = user.rfind("Input:")
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
            items = batch_input["items"]
            out_items = []
            for it in items:
                segs = it.get("segments", [])
                sub_segs = [{"id": s["id"], "text": f"VI{s['id']}"} for s in segs]
                dub = " ".join(f"VI{s['id']}" for s in segs)
                out_items.append({
                    "group_id": it["group_id"],
                    "subtitle_segments": sub_segs,
                    "dub_text": dub,
                })
            return json.dumps({"items": out_items})
        # Single translate_group: prompt chứa JSON segments (list của group).
        # Tìm list JSON có "source_text" để chắc là segment thật, không phải ví dụ.
        seg_list = None
        for cand in re.findall(r'\[\{.*?\}\]', user, re.S):
            if '"source_text"' in cand:
                try:
                    parsed = json.loads(cand)
                    if isinstance(parsed, list) and parsed and "id" in parsed[0]:
                        seg_list = parsed
                        break
                except Exception:
                    pass
        if seg_list:
            sub_segs = [{"id": s["id"], "text": f"VI{s['id']}"} for s in seg_list]
            dub = " ".join(f"VI{s['id']}" for s in seg_list)
            return json.dumps({"subtitle_segments": sub_segs, "dub_text": dub})
        # rewrite/meaning helpers: trả JSON/str an toàn để không phá flow.
        if "must_keep" in user:
            return json.dumps({"must_keep": [], "emotion": "", "negation_or_assertion": "", "important_terms": []})
        if "meaning_preserved" in user:
            return json.dumps({"meaning_preserved": True, "risk_level": "low", "lost_details": [], "changed_meaning": [], "recommendation": "use"})
        return "VI"

    return fake_chat, calls


def make_mock_synthesize():
    """Trả duration giả ~ dựa char count, không gọi TTS/ffmpeg."""
    def fake_measure(text, voice, work_dir, name):
        chars = max(1, len(re.sub(r"\s+", "", text or "")))
        return int(chars / 14.0 * 1000)
    return fake_measure


def run_optimizer(tmp, original_srt, monkey_missing_subsegments=False):
    """Import optimizer, patch, gọi main() qua sys.argv. Trả (vi_srt, dub_srt, report)."""
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
        "--api-base", "http://fake",
        "--api-key", "fake",
        "--api-provider", "ninerouter",
        "--model", "fake-model",
        "--voice", "vi-VN-fake",
        "--work-dir", str(tmp),
    ]
    os.environ["VIET_DUB_TIMING_OPTIMIZER"] = "1"

    import importlib.util
    spec = importlib.util.spec_from_file_location("vopt", OPTIMIZER)
    mod = importlib.util.module_from_spec(spec)
    # exec_module sẽ rebind chat/synthesize_measure từ source, nên patch SAU khi exec.
    spec.loader.exec_module(mod)

    fake_chat, calls = make_mock_chat()
    if monkey_missing_subsegments:
        # Biến fake_chat thành trả thiếu subtitle_segments để test fallback distribute.
        orig_chat = fake_chat
        def chat_no_sub(api_base, api_key, model, messages, temperature=0.2, timeout=None, api_provider="ninerouter"):
            content = orig_chat(api_base, api_key, model, messages, temperature, timeout, api_provider)
            try:
                data = json.loads(content)
                if isinstance(data, dict) and "items" in data:
                    for it in data["items"]:
                        it.pop("subtitle_segments", None)
                    return json.dumps(data)
                if isinstance(data, dict) and "subtitle_segments" in data:
                    data.pop("subtitle_segments")
                    return json.dumps(data)
            except Exception:
                pass
            return content
        fake_chat = chat_no_sub
    mod.chat = fake_chat
    mod.synthesize_measure = make_mock_synthesize()

    try:
        mod.main()
        exit_code = 0
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1

    report = {}
    if report_json.exists():
        report = json.loads(report_json.read_text(encoding="utf-8"))
    return vi_srt, dub_srt, report, exit_code, calls


def assert_main_case():
    if not FIXTURE.exists():
        print(f"SKIP: fixture không tồn tại: {FIXTURE}")
        return False
    with tempfile.TemporaryDirectory(prefix="optmock_") as td:
        tmp = Path(td)
        vi_srt, dub_srt, report, exit_code, calls = run_optimizer(tmp, FIXTURE)
        orig_cues = parse_srt_cues(FIXTURE)
        vi_cues = parse_srt_cues(vi_srt)
        dub_cues = parse_srt_cues(dub_srt)

        n_orig = len(orig_cues)
        n_vi = len(vi_cues)
        ratio = n_vi / n_orig if n_orig else 0

        print(f"[main] orig={n_orig} vi={n_vi} dub={len(dub_cues)} ratio={ratio:.3f} exit={exit_code} chat_calls={calls['n']}")
        ok = True
        # 1. vi cue count >= 80% orig (sửa bug 45/253).
        if ratio < 0.80:
            print(f"  FAIL: vi ratio {ratio:.3f} < 0.80 (standing-still bug vẫn còn)")
            ok = False
        else:
            print(f"  OK: vi cue count {n_vi} >= 80% orig {n_orig}")
        # 2. cue đầu vi bám cue đầu orig (end_ms ~ orig[0] end), không kéo tới 51600.
        if vi_cues:
            vi_first_end = vi_cues[0][1]
            orig_first_end = orig_cues[0][1]
            if vi_first_end > orig_first_end + 2000:  # cho phép trượt nhỏ
                print(f"  FAIL: vi cue đầu end={vi_first_end}ms >> orig {orig_first_end}ms (gộp khối dài)")
                ok = False
            else:
                print(f"  OK: vi cue đầu end={vi_first_end}ms bám orig {orig_first_end}ms")
        # 3. dub vẫn group dài (ít cue hơn vi).
        if len(dub_cues) >= n_vi:
            print(f"  FAIL: dub cue count {len(dub_cues)} >= vi {n_vi} (dub không gộp group)")
            ok = False
        else:
            print(f"  OK: dub cue count {len(dub_cues)} < vi {n_vi} (group dài cho TTS)")
        # 4. report có subtitle_cue_count/original_cue_count.
        if "subtitle_cue_count" not in report or "original_cue_count" not in report:
            print("  FAIL: report thiếu subtitle_cue_count/original_cue_count")
            ok = False
        else:
            print(f"  OK: report subtitle_cue_count={report.get('subtitle_cue_count')} original_cue_count={report.get('original_cue_count')}")
        return ok


def assert_fallback_case():
    """subtitle_segments thiếu -> fallback distribute + warning trong report."""
    if not FIXTURE.exists():
        print(f"SKIP: fixture không tồn tại: {FIXTURE}")
        return False
    with tempfile.TemporaryDirectory(prefix="optmock_fb_") as td:
        tmp = Path(td)
        vi_srt, dub_srt, report, exit_code, calls = run_optimizer(tmp, FIXTURE, monkey_missing_subsegments=True)
        vi_cues = parse_srt_cues(vi_srt)
        print(f"[fallback] vi={len(vi_cues)} exit={exit_code}")
        warn_reasons = [w.get("reason") for w in report.get("warnings", [])]
        has_fb = any("subtitle_segments_missing_fallback_distribute" in (r or "") for r in warn_reasons)
        if not has_fb:
            print(f"  FAIL: không có warning fallback distribute (reasons={set(warn_reasons)})")
            return False
        print(f"  OK: có warning fallback distribute; vi cue count={len(vi_cues)}")
        return len(vi_cues) > 0


def main():
    ok = True
    print("== main case: per-cue subtitle, grouped dub ==")
    ok = assert_main_case() and ok
    print("== fallback case: missing subtitle_segments -> distribute ==")
    ok = assert_fallback_case() and ok
    print()
    if ok:
        print("ALL PASS")
        sys.exit(0)
    print("FAIL")
    sys.exit(1)


if __name__ == "__main__":
    main()