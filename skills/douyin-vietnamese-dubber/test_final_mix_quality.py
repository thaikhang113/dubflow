#!/usr/bin/env python3
"""Deterministic tests for final stereo mix, trim, and local-retime policy."""
import importlib.util
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("final_mix_quality", SKILL_DIR / "final_mix_quality.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def check(value, message):
    if not value:
        raise AssertionError(message)


def main():
    canonical_stage_aliases = (
        "tts_normalized",
        "voice_master",
        "final_mp4",
    )
    for stage in canonical_stage_aliases:
        mismatch = module.canonical_sample_rate_error(stage, 44100)
        check(mismatch == f"TTS_CANONICAL_SAMPLE_RATE_MISMATCH stage={stage} expected=48000 actual=44100", mismatch)
        check(module.canonical_sample_rate_error(stage, 48000) is None, stage)
    check(module.canonical_sample_rate_error("ai33_response", 16000) is None, "provider input remains diagnostic-only")
    run_script = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    check("final_mix_quality.canonical_sample_rate_error" in run_script, "TTS stage gate must use canonical helper")
    check("raise RuntimeError(sample_rate_error)" in run_script, "TTS stage mismatch must fail closed")
    check("raise SystemExit(sample_rate_error)" in run_script, "final stage mismatch must fail closed")

    for mode in ("aggressive_legacy", "balanced_dub", "quality_dub"):
        policy = module.build_final_mix_policy({"SYNC_MODE": mode})
        check(policy["final_sample_rate"] == 48000, (mode, policy))
        check(policy["final_channels"] == 2, (mode, policy))
        check(policy["allow_video_retime"] is False, (mode, policy))
        check(policy["allow_freeze_frame"] is False, (mode, policy))
        check(policy["allow_final_trim"] is False, (mode, policy))

    no_freeze = module.decide_video_fit(
        video_seconds=60.0, voice_seconds=60.4,
        allow_video_retime=False, allow_freeze_frame=False,
        max_freeze_per_segment_ms=500, max_freeze_per_scene_ms=1200,
        max_output_duration_increase=10.0,
    )
    check(no_freeze["action"] == "needs_attention_no_trim", no_freeze)

    unsafe_scene = module.decide_video_fit(
        video_seconds=60.0, voice_seconds=60.4,
        allow_video_retime=True, allow_freeze_frame=True, scene_safe=False,
        max_freeze_per_segment_ms=500, max_freeze_per_scene_ms=1200,
        max_output_duration_increase=10.0,
    )
    check(unsafe_scene["action"] == "needs_attention_no_trim", unsafe_scene)

    safe_freeze = module.decide_video_fit(
        video_seconds=60.0, voice_seconds=60.4,
        allow_video_retime=True, allow_freeze_frame=True,
        scene_safe=True,
        max_freeze_per_segment_ms=500, max_freeze_per_scene_ms=1200,
        max_output_duration_increase=10.0,
    )
    check(safe_freeze["action"] == "tail_freeze_local", safe_freeze)
    check(safe_freeze["freeze_ms"] == 400, safe_freeze)

    too_long = module.decide_video_fit(
        video_seconds=60.0, voice_seconds=60.8,
        allow_video_retime=True, allow_freeze_frame=True,
        max_freeze_per_segment_ms=500, max_freeze_per_scene_ms=1200,
        max_output_duration_increase=10.0,
    )
    check(too_long["action"] == "needs_attention_no_trim", too_long)

    graph = module.stereo_mix_filter(voice_volume=1.25, music_volume=0.12, ducking=True, duck_amount=2.0)
    check("pan=stereo" in graph and "aformat=sample_rates=48000:channel_layouts=stereo" in graph, graph)
    check("sidechaincompress" in graph and "amix=inputs=2" in graph, graph)
    print("ALL PASS")


if __name__ == "__main__":
    main()
