#!/usr/bin/env python3
"""Focused regression coverage for CJK text leaking into Vietnamese TTS."""
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
OPTIMIZER = SKILL_DIR / "viet_dub_timing_optimizer.py"
RUN_SH = SKILL_DIR / "run.sh"


def load_optimizer():
    spec = importlib.util.spec_from_file_location("cjk_optimizer", OPTIMIZER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def run_srt_gate(vietnamese_text, source_text):
    source = RUN_SH.read_text(encoding="utf-8")
    function = source.split("srt_looks_vietnamese() {", 1)[1].split("\nPY\n}", 1)[0]
    script = function.split("<<'PY'\n", 1)[1]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vi_srt = root / "vietnamese.srt"
        src_srt = root / "original.srt"
        template = "1\n00:00:00,000 --> 00:00:01,000\n{}\n"
        vi_srt.write_text(template.format(vietnamese_text), encoding="utf-8")
        src_srt.write_text(template.format(source_text), encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-c", script, str(vi_srt), str(src_srt)],
            capture_output=True,
            text=True,
        )


def five_cjk_group():
    return [
        {"id": index, "start_ms": (index - 1) * 1000, "end_ms": index * 1000,
         "source_text": f"第{index}句中文"}
        for index in range(1, 6)
    ]


def test_optimizer_rejects_five_cjk_cues_without_source_fallback():
    """A CJK response is retried once, then fails instead of becoming TTS text."""
    optimizer = load_optimizer()
    calls = []

    def cjk_chat(*args, **kwargs):
        calls.append(args[3][-1]["content"])
        return json.dumps({
            "subtitle_segments": [{"id": cue["id"], "text": cue["source_text"]}
                                  for cue in five_cjk_group()],
            "dub_text": "第一句中文 第二句中文 第三句中文 第四句中文 第五句中文",
        }, ensure_ascii=False)

    optimizer.chat = cjk_chat
    try:
        optimizer.translate_group(five_cjk_group(), "http://fake", "fake", "fake")
    except RuntimeError as exc:
        if "translation_contains_cjk" not in str(exc):
            print(f"FAIL: wrong CJK rejection: {exc}")
            return False
    else:
        print("FAIL: five CJK cues were accepted for TTS")
        return False
    if len(calls) != 2 or "CHỈ tiếng Việt" not in calls[-1]:
        print(f"FAIL: expected one strict Vietnamese retry, got {len(calls)} calls")
        return False
    print("OK: five CJK cues rejected; no TTS text returned")
    return True


def test_valid_vietnamese_translation_passes():
    optimizer = load_optimizer()

    def vietnamese_chat(*args, **kwargs):
        return json.dumps({
            "subtitle_segments": [{"id": cue["id"], "text": f"Câu tiếng Việt {cue['id']}"}
                                  for cue in five_cjk_group()],
            "dub_text": "Năm câu tiếng Việt tự nhiên để lồng tiếng",
        }, ensure_ascii=False)

    optimizer.chat = vietnamese_chat
    subtitle, dub = optimizer.translate_group(five_cjk_group(), "http://fake", "fake", "fake")
    if len(subtitle) != 5 or re.search(r"[\u3400-\u9fff\uf900-\ufaff]", dub):
        print(f"FAIL: valid Vietnamese translation was rejected or altered: {subtitle!r} / {dub!r}")
        return False
    print("OK: valid Vietnamese translation passes")
    return True

def test_non_cjk_name_identical_to_source_passes_srt_gate():
    result = run_srt_gate("AI33", "AI33")
    if result.returncode != 0:
        print(f"FAIL: non-CJK name was rejected: {result.stdout.strip()}")
        return False
    cjk_result = run_srt_gate("中文", "中文")
    if cjk_result.returncode == 0:
        print("FAIL: CJK cue passed Vietnamese SRT gate")
        return False
    print("OK: non-CJK name passes while CJK remains rejected")
    return True

def test_repeated_tts_syllable_is_rejected():
    optimizer = load_optimizer()
    try:
        optimizer.validate_vietnamese_translation(
            [{"subtitle_text": "Nhân vật quay trở lại."}],
            "mo mo mo mo",
        )
    except RuntimeError as exc:
        if "translation_repeated_short_token" not in str(exc):
            print(f"FAIL: repeated syllable rejected for wrong reason: {exc}")
            return False
    else:
        print("FAIL: repeated TTS syllable was accepted")
        return False
    print("OK: repeated TTS syllable rejected")
    return True

def test_review_film_style_is_explicit_in_translation_prompt():
    source = OPTIMIZER.read_text(encoding="utf-8")
    required = ("văn phong review phim", "giữ tên riêng", "đại từ nhất quán")
    missing = [value for value in required if value not in source]
    if missing:
        print(f"FAIL: review-film prompt rules missing: {len(missing)}")
        return False
    print("OK: review-film prompt rules present")
    return True


def test_translategemma_prompt_locks_language_and_json_contract():
    optimizer = load_optimizer()
    rules = optimizer.translation_model_rules("translategemma:4b")
    required = ("zh-Hans", "vi", "JSON", "không thêm")
    missing = [value for value in required if value not in rules]
    if missing:
        print(f"FAIL: TranslateGemma prompt rules missing: {missing}")
        return False
    if optimizer.translation_model_rules("qwen3:4b"):
        print("FAIL: generic models received TranslateGemma-only prompt rules")
        return False
    print("OK: TranslateGemma receives explicit zh-Hans to vi JSON rules")
    return True


def test_batch_and_adaptive_paths_reject_cjk():
    """Batch validation must fail before adaptive routing can hand CJK to TTS."""
    optimizer = load_optimizer()
    group = five_cjk_group()
    payload = {
        "group_id": 1, "group": group, "source_text": " ".join(cue["source_text"] for cue in group),
        "duration": 5.0, "segments": optimizer._group_segments_payload(group),
    }

    def cjk_batch_chat(*args, **kwargs):
        return json.dumps({"items": [{
            "group_id": 1,
            "subtitle_segments": [{"id": cue["id"], "text": cue["source_text"]} for cue in group],
            "dub_text": "第一句中文 第二句中文 第三句中文 第四句中文 第五句中文",
        }]}, ensure_ascii=False)

    optimizer.chat = cjk_batch_chat
    for name, translate in (
        ("batch", lambda: optimizer.translate_groups_batch([payload], "http://fake", "fake", "fake")),
        ("adaptive", lambda: optimizer.translate_groups_adaptive([payload], "http://fake", "fake", "fake", min_batch_size=1)),
    ):
        try:
            translate()
        except RuntimeError as exc:
            if "translation_contains_cjk" not in str(exc):
                print(f"FAIL: {name} rejected for the wrong reason: {exc}")
                return False
        else:
            print(f"FAIL: {name} accepted CJK batch output")
            return False
    print("OK: batch and adaptive paths reject CJK before fallback")
    return True


def test_pre_tts_gate_audits_actual_tts_source_before_voice_generation():
    run_sh = RUN_SH.read_text(encoding="utf-8")
    expected = 'srt_looks_vietnamese "$TTS_SOURCE_SRT" "$ORIGINAL_SRT"'
    gate_at = run_sh.find(expected)
    tts_at = run_sh.find('generate_vietnamese_voice "$TTS_SOURCE_SRT"')
    if gate_at < 0 or tts_at < 0 or gate_at >= tts_at:
        print("FAIL: actual TTS source is not CJK-gated before voice generation")
        return False
    if 'create_translate_pending "pre-TTS/' not in run_sh:
        print("FAIL: pre-TTS CJK rejection does not create manual-translate handoff")
        return False
    quality_at = run_sh.find('python3 "$TTS_VOICE_QUALITY_SCRIPT" text-gate')
    if quality_at < 0 or quality_at >= tts_at:
        print("FAIL: detailed Vietnamese text quality gate is not before TTS")
        return False
    print("OK: actual TTS source is gated before TTS")
    return True


def main():
    ok = test_optimizer_rejects_five_cjk_cues_without_source_fallback()
    ok = test_valid_vietnamese_translation_passes() and ok
    ok = test_non_cjk_name_identical_to_source_passes_srt_gate() and ok
    ok = test_repeated_tts_syllable_is_rejected() and ok
    ok = test_review_film_style_is_explicit_in_translation_prompt() and ok
    ok = test_translategemma_prompt_locks_language_and_json_contract() and ok
    ok = test_batch_and_adaptive_paths_reject_cjk() and ok
    ok = test_pre_tts_gate_audits_actual_tts_source_before_voice_generation() and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
