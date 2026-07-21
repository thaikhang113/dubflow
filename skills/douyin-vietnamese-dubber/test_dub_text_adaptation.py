#!/usr/bin/env python3
"""Deterministic policy tests for the post-probe dub-text adaptation decision."""
import importlib.util
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("dub_text_adaptation", SKILL_DIR / "dub_text_adaptation.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    long = module.decide_adaptation(
        natural_tts_ms=2350, slot_ms=1800, tolerance_ms=20,
        subtitle_text="Anh phải mang thanh kiếm này về cho trưởng lão.",
        dub_text="Anh phải mang thanh kiếm này về cho trưởng lão.",
    )
    check(long["adapt_direction"] == "shorten", long)

    short_cut = module.decide_adaptation(
        natural_tts_ms=650, slot_ms=1800, tolerance_ms=20,
        subtitle_text="Cô hãy lập tức mang bản đồ và chiếc chìa khóa cổ đến gặp ta.",
        dub_text="Mang bản đồ đến đây.",
    )
    check(short_cut["adapt_direction"] == "restore_safe_detail", short_cut)

    # A voice profile may ask for restoration sooner, but only when the dub text
    # is demonstrably shorter than the full subtitle.
    voice_profile_short = module.decide_adaptation(
        natural_tts_ms=1400, slot_ms=1800, tolerance_ms=20,
        subtitle_text="Cô hãy lập tức mang bản đồ và chiếc chìa khóa cổ đến gặp ta.",
        dub_text="Mang bản đồ đến đây.", restore_ratio=0.82,
    )
    check(voice_profile_short["adapt_direction"] == "restore_safe_detail", voice_profile_short)

    short_complete = module.decide_adaptation(
        natural_tts_ms=650, slot_ms=1800, tolerance_ms=20,
        subtitle_text="Đi mau.", dub_text="Đi mau.",
    )
    check(short_complete["adapt_direction"] == "keep_natural", short_complete)

    rejected = module.normalize_adaptation_response(
        {"dub_text": "Một chuyện mới chưa từng có", "meaning_risk": "high"},
        direction="shorten", before_text="Câu gốc", natural_tts_ms=2200, slot_ms=1800,
    )
    check(rejected["accepted"] is False and rejected["adapt_direction"] == "needs_attention", rejected)

    # AI33's optimizer probe is only an estimate; it must not choose a rewrite,
    # speed, or subtitle-only result before run.sh measures the natural 1.0 WAV.
    optimizer = (SKILL_DIR / "viet_dub_timing_optimizer.py").read_text(encoding="utf-8")
    runtime = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    check("ai33_post_probe_adaptation" in optimizer, "AI33 deferred probe guard missing")
    check("not ai33_post_probe_adaptation and ratio >" in optimizer, "estimated AI33 rewrite still enabled")
    check('ai33_speed=1.0 if voice_name.lower().startswith("ai33") else None' in runtime, "natural AI33 probe is not fixed at 1.0")
    check("def check_adapted_meaning(" in runtime, "independent meaning gate missing")
    check('"adapt_direction": adapt_direction' in runtime, "segment adaptation report missing")
    print("ALL PASS")


if __name__ == "__main__":
    main()
